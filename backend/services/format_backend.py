# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
FormatAwareBackend — multi-format filesystem backend for the deepagents SDK.

The SDK's ``FilesystemMiddleware`` exposes ``write_file`` / ``read_file`` tools
that call the configured ``BackendProtocol`` (``backend.write`` /
``backend.read``) and treat every file as plain text. LangConfig's native
renderers/extractors (``tools/native_impl.py``) already handle real documents:
``.html`` / ``.pdf`` / ``.docx`` are rendered from markdown content on write,
and ``.pdf`` / ``.docx`` / ``.pptx`` / ``.xlsx`` text is extracted on read.

This wrapper sits *between* the SDK middleware and whatever backend is active
(``FilesystemBackend`` in fs mode, ``DbBackend`` in db mode), so the SDK's
``write_file`` / ``read_file`` become format-aware with zero SDK changes and
zero duplicate tool names:

- ``write(path, content)`` → render by extension (``.html``/``.pdf``/``.docx``),
  then delegate the rendered bytes to the wrapped backend.
- ``read(path, ...)`` → delegate the raw read; for binary documents
  (``.pdf``/``.docx``/``.pptx``) extract text instead of returning raw bytes.

Every other operation (``ls``/``edit``/``glob``/``grep``/``delete``/…)
delegates unchanged to the wrapped backend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from deepagents.backends.protocol import BackendProtocol

logger = logging.getLogger(__name__)

# Extensions that write_file renders as real documents (not plain text).
_RENDER_EXTENSIONS = {".html", ".pdf", ".docx"}
# Extensions read_file extracts text from (binary document formats).
_EXTRACT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm"}


class FormatAwareBackend(BackendProtocol):
    """BackendProtocol adapter that adds multi-format write/read on top of any
    deepagents backend (FilesystemBackend / DbBackend / CompositeBackend).

    Subclasses ``BackendProtocol`` so the SDK's ``FilesystemMiddleware``
    accepts it (its constructor checks ``isinstance(backend, BackendProtocol)``
    and capabilities dispatch on concrete types); every method we do not
    override delegates to the wrapped backend.
    """

    def __init__(self, backend: Any):
        self._backend = backend

    # ── format-aware read ────────────────────────────────────────────────────
    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ):
        """Read a file; extract text for .pdf/.docx/.pptx instead of raw bytes."""
        ext = Path(file_path).suffix.lower()
        # Binary document formats: read raw bytes directly (the SDK backend's
        # read() utf-8-decodes and would error before we can extract).
        if ext in _EXTRACT_EXTENSIONS:
            return self._read_extracted(file_path, ext, offset, limit)
        return self._backend.read(file_path, offset=offset, limit=limit)

    def _read_extracted(self, file_path: str, ext: str, offset: int, limit: int):
        """Extract text from a binary document (.pdf/.docx/.pptx)."""
        try:
            from tools.native_impl import (
                _extract_docx_text,
                _extract_xlsx,
                _extract_pdf_text,
                _extract_pptx_text,
            )
            from deepagents.backends.protocol import FileData, ReadResult

            fs = self._find_filesystem_backend(self._backend)
            if fs is not None:
                resolved = fs._resolve_path(file_path)
                raw_bytes = resolved.read_bytes() if resolved.exists() else None
            else:
                raw_bytes = self._read_bytes_via_backend(file_path)
            if not raw_bytes:
                return ReadResult(error=f"File '{file_path}' not found")

            tmp = _path_for_extraction(file_path, raw_bytes)
            try:
                if ext == ".pdf":
                    text = _extract_pdf_text(tmp)
                elif ext == ".docx":
                    text = _extract_docx_text(tmp)
                elif ext in (".xlsx", ".xlsm"):
                    text = _extract_xlsx(tmp)[0] or "Error: no data found in workbook"
                else:  # .pptx
                    text = _extract_pptx_text(tmp)
            finally:
                tmp.unlink(missing_ok=True)

            # Re-slice the extracted text with the requested window so the
            # middleware's pagination semantics hold. Extracted documents are
            # already fully materialized in memory, so return up to 1000 lines
            # (the SDK read_file default of 100 truncates real documents).
            lines = text.splitlines()
            total = len(lines)
            start = max(0, offset)
            eff_limit = max(limit or 0, 1000)
            end = min(start + eff_limit, total)
            window = "\n".join(lines[start:end])
            return ReadResult(
                file_data=FileData(content=window, encoding="utf-8"),
                total_lines=total,
                start_line=start + 1,
                end_line=end,
                next_offset=end,
            )
        except Exception as e:
            logger.warning("FormatAwareBackend: failed to extract %s: %s", file_path, e)
            return ReadResult(error=f"Error reading file '{file_path}': {e}")

    # ── format-aware write ───────────────────────────────────────────────────
    def write(self, file_path: str, content: str):
        """Write a file; render .html/.pdf/.docx from markdown content first.

        HTML is plain text and can go through the wrapped backend's str write.
        PDF/DOCX are binary — the SDK backend only accepts ``str`` (utf-8), so
        we render to bytes and write them directly to the resolved filesystem
        path (fs mode). In db mode (DbBackend) we fall back to the underlying
        storage seam via the backend's own machinery.
        """
        ext = Path(file_path).suffix.lower()
        if ext not in _RENDER_EXTENSIONS:
            return self._backend.write(file_path, content)
        try:
            from tools.native_impl import (
                _render_html_document,
                _write_docx_file,
                _write_pdf_file,
            )

            filename = Path(file_path).name or "document"
            if ext == ".html":
                rendered = _render_html_document(content, title=filename)
                return self._backend.write(file_path, rendered)
            # Binary formats: render to a temp path, then write bytes directly.
            tmp = _path_for_extraction(file_path, b"")
            try:
                # The temp path is an implementation detail of rendering to bytes;
                # the document must be titled after the file the caller asked for.
                if ext == ".pdf":
                    _write_pdf_file(tmp, content, title=filename)
                else:
                    _write_docx_file(tmp, content, title=filename)
                payload = tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
            return self._write_binary(file_path, payload)
        except Exception as e:
            logger.warning("FormatAwareBackend: failed to render %s: %s", file_path, e)
            return self._backend.write(file_path, content)

    def _write_binary(self, file_path: str, payload: bytes):
        """Write binary bytes to the resolved filesystem path.

        Handles FilesystemBackend directly and CompositeBackend whose default
        is a FilesystemBackend (the db-mode skills case). Falls back to the
        wrapped backend's str write for other backends (best-effort)."""
        fs = self._find_filesystem_backend(self._backend)
        if fs is not None:
            try:
                resolved = fs._resolve_path(file_path)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(payload)
                from deepagents.backends.protocol import WriteResult
                return WriteResult(path=file_path)
            except Exception as e:
                logger.warning("FormatAwareBackend: direct binary write failed (%s); falling back", e)
        return self._backend.write(file_path, payload.decode("utf-8", errors="replace"))

    @staticmethod
    def _find_filesystem_backend(backend):
        """Return the FilesystemBackend inside a backend or CompositeBackend."""
        from deepagents.backends.filesystem import FilesystemBackend
        if isinstance(backend, FilesystemBackend):
            return backend
        # CompositeBackend: its `.default` handles non-routed paths.
        default = getattr(backend, "default", None)
        if isinstance(default, FilesystemBackend):
            return default
        return None

    # ── delegation ───────────────────────────────────────────────────────────
    # BackendProtocol base methods raise NotImplementedError; since we subclass
    # it (for isinstance checks), we must delegate each one explicitly —
    # __getattr__ never fires for methods the base class defines.
    def ls(self, path: str):
        return self._backend.ls(path)

    async def als(self, path: str):
        return await self._backend.als(path)

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        return self._backend.grep(pattern, path=path, glob=glob, max_count=max_count)

    async def agrep(self, pattern, path=None, glob=None, *, max_count=None):
        return await self._backend.agrep(pattern, path=path, glob=glob, max_count=max_count)

    def glob(self, pattern, path=None):
        return self._backend.glob(pattern, path=path)

    async def aglob(self, pattern, path=None):
        return await self._backend.aglob(pattern, path=path)

    def edit(self, file_path, old_string, new_string, replace_all=False):
        return self._backend.edit(file_path, old_string, new_string, replace_all=replace_all)

    async def aedit(self, file_path, old_string, new_string, replace_all=False):
        return await self._backend.aedit(file_path, old_string, new_string, replace_all=replace_all)

    def delete(self, file_path):
        return self._backend.delete(file_path)

    async def adelete(self, file_path):
        return await self._backend.adelete(file_path)

    async def aread(self, file_path, offset=0, limit=2000):
        """Async read — format-aware like the sync read (SDK calls aread on
        the async path, bypassing the sync read otherwise)."""
        import asyncio
        return await asyncio.to_thread(self.read, file_path, offset=offset, limit=limit)

    async def awrite(self, file_path, content):
        """Async write — must be format-aware too (SDK calls awrite on the
        async path, which would otherwise bypass the .docx/.pdf rendering)."""
        import asyncio
        return await asyncio.to_thread(self.write, file_path, content)

    def download_files(self, paths):
        return self._backend.download_files(paths)

    def __getattr__(self, name: str):
        return getattr(self._backend, name)

    def _read_bytes_via_backend(self, file_path: str) -> Optional[bytes]:
        """Read raw bytes via the wrapped backend (base64 content for DbBackend)."""
        try:
            full = self._backend.read(file_path, offset=0, limit=10_000_000)
            if full.error or not full.file_data:
                return None
            raw = full.file_data.get("content", "")
            encoding = full.file_data.get("encoding", "utf-8")
            if encoding == "base64":
                import base64
                return base64.b64decode(raw)
            return raw.encode("utf-8")
        except Exception:
            return None


def _path_for_extraction(file_path: str, data: bytes) -> Path:
    """Materialize bytes to a temp file with the right extension so the native
    extractors (which dispatch on Path suffix) can read them."""
    import tempfile

    suffix = Path(file_path).suffix or ".bin"
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="langconfig-doc-")
    with open(fd, "wb") as f:
        f.write(data)
    return Path(name)
