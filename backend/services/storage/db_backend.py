# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DbBackend — deepagents ``BackendProtocol`` backed by the storage seam.

Phase 3 of docs/system-architecture.md §15: skills become 100% DB-managed in
``STORAGE_MODE=db`` by presenting the ``storage_objects`` keys as a virtual
POSIX filesystem to deepagents. ``SkillsMiddleware`` only ever calls
``backend.ls()`` + ``backend.download_files()``, and the agent's ``read_file``
tool calls ``backend.read()`` — all three work against ``get_storage()`` with
no disk involvement.

Key mapping: a virtual path ``/skills/builtin/web-search/SKILL.md`` maps to the
storage key ``skills/builtin/web-search/SKILL.md`` (leading ``/`` is the only
difference). ``local`` mode is fully supported too — this class is agnostic to
which ``StorageBackend`` implementation backs it — but the assembly wiring only
activates it when ``STORAGE_MODE=db``.

Not to be confused with ``DbStorageBackend`` (the ``StorageBackend`` impl that
persists BYTEA rows); ``DbBackend`` is the deepagents-facing adapter on top.
"""
import logging
import mimetypes
from typing import List, Optional

from deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    check_empty_content,
    compile_grep_include_glob,
    compile_recursive_glob,
    perform_string_replacement,
    slice_read_response,
)

from .base import StorageBackend

logger = logging.getLogger(__name__)


class DbBackend(BackendProtocol):
    """A deepagents backend that reads/writes the storage seam by virtual path.

    Directories are virtual: they exist implicitly wherever a key sits below
    them (``skills/builtin/hello/SKILL.md`` implies the ``/skills``,
    ``/skills/builtin`` and ``/skills/builtin/hello`` directories).
    """

    def __init__(self, backend: Optional[StorageBackend] = None, storage_prefix: str = ""):
        self._backend = backend if backend is not None else self._default_backend()
        # When this backend is routed behind a CompositeBackend (e.g.
        # ``routes={"/skills/": DbBackend(storage_prefix="skills")}``), the
        # composite strips the route prefix before delegating, so this backend
        # must re-attach the matching storage namespace. Empty (standalone)
        # means virtual paths map 1:1 to keys.
        self._storage_prefix = storage_prefix.strip("/")

    @staticmethod
    def _default_backend() -> StorageBackend:
        # Lazy import: the factory needs config + a live DB in db mode, and we
        # don't want that to run at module import time.
        from services.storage import get_storage
        return get_storage()

    # ------------------------------------------------------------------
    # Path mapping
    # ------------------------------------------------------------------

    def _to_key(self, path: str) -> str:
        """Normalize a virtual POSIX path to a storage key ('' for root).

        Raises ValueError on traversal attempts (``..`` / ``~``) so callers
        can surface a structured error instead of writing outside the tree.
        """
        parts = path.replace("\\", "/").split("/")
        cleaned = [p for p in parts if p and p != "."]
        if any(p in ("..", "~") for p in cleaned):
            raise ValueError(f"Path traversal not allowed: {path!r}")
        rel = "/".join(cleaned)
        if self._storage_prefix:
            return f"{self._storage_prefix}/{rel}" if rel else self._storage_prefix
        return rel

    def _to_virtual(self, key: str) -> str:
        """Map a storage key back to the absolute virtual path the agent sees."""
        if self._storage_prefix and key.startswith(self._storage_prefix + "/"):
            key = key[len(self._storage_prefix):].lstrip("/")
        return "/" + key

    # ------------------------------------------------------------------
    # Listing / stat
    # ------------------------------------------------------------------

    def ls(self, path: str) -> LsResult:  # noqa: C901 - small dispatch helper, keep flat
        """List the immediate children (files + dirs) under a virtual path."""
        try:
            prefix = self._to_key(path)
        except ValueError as e:
            return LsResult(error=str(e), entries=None)

        try:
            keys = self._backend.list(prefix)
        except Exception as e:  # noqa: BLE001 - surface any backend failure to the agent
            msg = f"Cannot list '{path}': {e}"
            logger.warning("%s", msg)
            return LsResult(error=msg, entries=None)

        entries: List[FileInfo] = []
        seen: set[str] = set()
        for key in keys:
            rest = key[len(prefix):].lstrip("/") if prefix else key
            if not rest:
                continue
            first, sep, _tail = rest.partition("/")
            child = f"{prefix}/{first}" if prefix else first
            if child in seen:
                continue
            seen.add(child)
            if sep:
                # Anything nested under `first` makes it a directory.
                entries.append({"path": self._to_virtual(child) + "/", "is_dir": True, "size": 0})
            else:
                stat = self._backend.stat(child)
                entries.append({
                    "path": self._to_virtual(child),
                    "is_dir": False,
                    "size": stat.size_bytes if stat else 0,
                })

        entries.sort(key=lambda e: e["path"])
        return LsResult(error=None, entries=entries)

    # ------------------------------------------------------------------
    # Read / write / edit / delete
    # ------------------------------------------------------------------

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Read text content for a line window (SkillsMiddleware / read_file)."""
        try:
            key = self._to_key(file_path)
        except ValueError as e:
            return ReadResult(error=f"Error reading file '{file_path}': {e}")

        try:
            content = self._backend.read(key).decode("utf-8")
        except KeyError:
            return ReadResult(error=f"File '{file_path}' not found")
        except Exception as e:  # noqa: BLE001 - decode errors surface to the agent
            return ReadResult(error=f"Error reading file '{file_path}': {e}")

        empty_msg = check_empty_content(content)
        if empty_msg:
            return ReadResult(file_data={"content": empty_msg, "encoding": "utf-8"})
        # Reuse the library slicer so pagination / trailing-newline semantics
        # match FilesystemBackend exactly.
        return slice_read_response({"content": content, "encoding": "utf-8"}, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Upsert a file's content under its virtual path."""
        try:
            key = self._to_key(file_path)
        except ValueError as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")
        mime, _ = mimetypes.guess_type(key)
        try:
            self._backend.save(key, content.encode("utf-8"), mime)
        except Exception as e:  # noqa: BLE001
            return WriteResult(error=f"Error writing file '{file_path}': {e}")
        return WriteResult(path=file_path)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Exact string replacement, mirroring FilesystemBackend.edit()."""
        try:
            key = self._to_key(file_path)
        except ValueError as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")

        try:
            content = self._backend.read(key).decode("utf-8")
        except KeyError:
            return EditResult(error=f"Error: File '{file_path}' not found")
        except Exception as e:  # noqa: BLE001 - decode errors surface to the agent
            return EditResult(error=f"Error editing file '{file_path}': {e}")

        # Normalize CRLF like FilesystemBackend so model-provided strings match.
        old_string = old_string.replace("\r\n", "\n").replace("\r", "\n")
        new_string = new_string.replace("\r\n", "\n").replace("\r", "\n")

        result = perform_string_replacement(content, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)
        new_content, occurrences = result
        try:
            self._backend.save(key, new_content.encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return EditResult(error=f"Error editing file '{file_path}': {e}")
        return EditResult(path=file_path, occurrences=int(occurrences))

    def delete(self, file_path: str) -> DeleteResult:
        """Delete a key, or every key under a virtual directory (recursive)."""
        try:
            key = self._to_key(file_path)
        except ValueError as e:
            return DeleteResult(error=f"Error deleting '{file_path}': {e}")

        try:
            targets = [key] if self._backend.exists(key) else []
            if not targets:
                targets = self._backend.list(key if key else "") if key else self._backend.list()
            deleted_any = False
            for k in targets:
                if self._backend.delete(k):
                    deleted_any = True
            if not deleted_any:
                return DeleteResult(error=f"Error: '{file_path}' not found")
            return DeleteResult(path=file_path)
        except Exception as e:  # noqa: BLE001
            return DeleteResult(error=f"Error deleting '{file_path}': {e}")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Match storage keys against a glob pattern (supports ``**``)."""
        try:
            base = self._to_key(path) if path else ""
            matcher = compile_recursive_glob(pattern.lstrip("/"))
        except ValueError as e:
            return GlobResult(error=f"Error globbing path '{path}': {e}", matches=[])

        try:
            keys = self._backend.list(base)
        except Exception as e:  # noqa: BLE001
            return GlobResult(error=f"Error globbing path '{path}': {e}", matches=[])

        matches: List[FileInfo] = []
        for key in keys:
            rel = key[len(base):].lstrip("/") if base else key
            if not matcher(rel):
                continue
            stat = self._backend.stat(key)
            matches.append({
                "path": self._to_virtual(key),
                "is_dir": False,
                "size": stat.size_bytes if stat else 0,
            })
        matches.sort(key=lambda m: m["path"])
        return GlobResult(matches=matches)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        """Literal substring search over stored text keys (Python fallback)."""
        try:
            base = self._to_key(path) if path else ""
            glob_matcher = compile_grep_include_glob(glob) if glob else None
        except ValueError as e:
            return GrepResult(error=f"Error searching path '{path}': {e}", matches=[])

        try:
            keys = self._backend.list(base)
        except Exception as e:  # noqa: BLE001
            return GrepResult(error=f"Error searching path '{path}': {e}", matches=[])

        matches: List[GrepMatch] = []
        truncated = False
        for key in keys:
            rel = key[len(base):].lstrip("/") if base else key
            if glob_matcher is not None and not glob_matcher(rel):
                continue
            try:
                text = self._backend.read(key).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - unreadable keys are skipped
                continue
            for line_num, raw_line in enumerate(text.splitlines(), 1):
                if pattern in raw_line:
                    matches.append({
                        "path": self._to_virtual(key),
                        "line": line_num,
                        "text": raw_line,
                    })
                    if max_count is not None and len(matches) >= max_count:
                        truncated = True
                        break
            if truncated:
                break
        return GrepResult(matches=matches, truncated=truncated)

    # ------------------------------------------------------------------
    # Batch upload / download
    # ------------------------------------------------------------------

    def upload_files(self, files: List[tuple[str, bytes]]) -> List[FileUploadResponse]:
        """Upload multiple files to the storage seam."""
        responses: List[FileUploadResponse] = []
        for path, content in files:
            try:
                key = self._to_key(path)
                mime, _ = mimetypes.guess_type(key)
                self._backend.save(key, content, mime)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:  # noqa: BLE001
                responses.append(FileUploadResponse(path=path, error=str(e)))
        return responses

    def download_files(self, paths: List[str]) -> List[FileDownloadResponse]:
        """Download multiple files (SkillsMiddleware reads SKILL.md bodies)."""
        responses: List[FileDownloadResponse] = []
        for path in paths:
            try:
                key = self._to_key(path)
                content = self._backend.read(key)
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except KeyError:
                responses.append(FileDownloadResponse(path=path, content=None, error=FILE_NOT_FOUND))
            except Exception as e:  # noqa: BLE001
                responses.append(FileDownloadResponse(path=path, content=None, error=str(e)))
        return responses
