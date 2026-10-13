"""Documents must be titled after the file the caller asked for.

The bug this pins: ``FormatAwareBackend`` renders .docx/.pdf to a *temporary* path
and then copies the bytes to the real one. The renderers derived the document
title from that path, so every agent-written Word/PDF file arrived headed
``Langconfig-Doc-4f2a`` instead of its own filename — visible in the user's own
reports before the fix.
"""
from __future__ import annotations

import re
import zipfile

import pytest

from services.format_backend import FormatAwareBackend
from tools.native_impl import _write_docx_file, _write_pdf_file


class _MemoryBackend:
    """A BackendProtocol stand-in that keeps writes in a dict."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def write(self, path, content):
        self.files[str(path)] = content if isinstance(content, bytes) else str(content).encode()
        return {"path": str(path)}

    def __getattr__(self, name):           # everything else is unused here
        def _missing(*_a, **_k):
            raise NotImplementedError(name)

        return _missing


@pytest.fixture
def backend(tmp_path):
    """A FormatAwareBackend over a real directory (so temp rendering works)."""
    from deepagents.backends.filesystem import FilesystemBackend

    return FormatAwareBackend(FilesystemBackend(root_dir=str(tmp_path))), tmp_path


def _docx_text(path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode()
    return [t for t in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml) if t.strip()]


def _pdf_text(path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def test_docx_is_titled_after_the_requested_filename(backend):
    adapter, root = backend
    adapter.write("generated/quarterly-report.docx", "Body text only, no heading.\n")

    written = next(root.rglob("quarterly-report.docx"))
    runs = _docx_text(written)

    assert runs[0] == "Quarterly Report"          # the file the caller asked for
    assert not any("Langconfig-Doc" in run for run in runs)


def test_pdf_is_titled_after_the_requested_filename(backend):
    adapter, root = backend
    adapter.write("generated/quarterly-report.pdf", "Body text only, no heading.\n")

    written = next(root.rglob("quarterly-report.pdf"))
    text = _pdf_text(written)

    assert text.splitlines()[0].strip() == "Quarterly Report"
    assert "Langconfig-Doc" not in text


def test_a_heading_in_the_content_is_not_duplicated(backend):
    """The content's own H1 wins; no filename heading is prepended."""
    adapter, root = backend
    adapter.write("generated/quarterly-report.docx", "# Q3 Analysis\n\nBody.\n")

    runs = _docx_text(next(root.rglob("quarterly-report.docx")))

    assert runs[0] == "Q3 Analysis"
    assert "Quarterly Report" not in runs


def test_pdf_does_not_duplicate_a_content_heading(backend):
    adapter, root = backend
    adapter.write("generated/quarterly-report.pdf", "# Q3 Analysis\n\nBody.\n")

    text = _pdf_text(next(root.rglob("quarterly-report.pdf")))

    assert text.splitlines()[0].strip() == "Q3 Analysis"
    assert "Quarterly Report" not in text


def test_renderers_still_derive_a_title_from_the_real_path(tmp_path):
    """Callers that render straight to the final file keep working unchanged."""
    docx, pdf = tmp_path / "site-review.docx", tmp_path / "site-review.pdf"
    content = "Body only.\n"

    _write_docx_file(docx, content)
    _write_pdf_file(pdf, content)

    assert _docx_text(docx)[0] == "Site Review"
    assert _pdf_text(pdf).splitlines()[0].strip() == "Site Review"


def test_an_explicit_title_still_wins():
    """The html renderer already took a title; docx/pdf now match its contract."""
    from tools.native_impl import _render_html_document

    html = _render_html_document("Body only.\n", title="Custom Name")
    assert "<h1>Custom Name</h1>" in html
