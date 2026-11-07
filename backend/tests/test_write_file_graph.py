"""The writer graph (core/graphs/write_file.py): one node per output format.

The graph exists because the writers it replaced flattened every format the same
way — a Markdown table arrived in Word as pipe text, bullets as literal "- item",
bold and links as their own syntax. These tests pin the fidelity per format, so a
future renderer cannot quietly go back to emitting paragraphs only.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from core.graphs import write_file as wf

MARKDOWN = """# Market Report

Intro with **bold**, *italic*, `code` and a [link](https://example.com).

## Findings

- first bullet
- second bullet

1. ordered one
2. ordered two

| Region | Revenue |
|--------|---------|
| HK     | 1200    |

> A quoted line.

```python
print("code block")
```

---

Done.
"""


@pytest.fixture
def target(tmp_path):
    def _make(name: str) -> Path:
        return tmp_path / name

    return _make


def _write(target, name, content=MARKDOWN):
    path = target(name)
    state = wf.write_document(str(path), content)
    return path, state


# ── the markdown parser ──────────────────────────────────────────────────────
def test_parser_classifies_every_supported_block():
    kinds = [block["kind"] for block in wf.parse_markdown(MARKDOWN)]

    assert kinds == ["heading", "paragraph", "heading", "list", "list", "table",
                     "quote", "code", "rule", "paragraph"]


def test_parser_reads_headings_lists_and_tables():
    blocks = {b["kind"]: b for b in wf.parse_markdown(MARKDOWN)}
    headings = [b for b in wf.parse_markdown(MARKDOWN) if b["kind"] == "heading"]
    lists = [b for b in wf.parse_markdown(MARKDOWN) if b["kind"] == "list"]

    assert [h["level"] for h in headings] == [1, 2]
    assert headings[0]["text"] == "Market Report"
    assert lists[0]["ordered"] is False and len(lists[0]["items"]) == 2
    assert lists[1]["ordered"] is True
    assert blocks["table"]["header"] == ["Region", "Revenue"]
    assert blocks["table"]["rows"] == [["HK", "1200"]]
    assert blocks["code"]["lang"] == "python"


def test_pipes_without_a_divider_row_stay_text():
    blocks = wf.parse_markdown("a | b | c\n")

    assert blocks[0]["kind"] == "paragraph"


def test_inline_spans_are_typed():
    spans = wf.parse_inline("plain **bold** *italic* `code` [link](https://x.dev)")
    by_text = {s["text"].strip(): s for s in spans if s["text"].strip()}

    assert by_text["bold"]["bold"] is True
    assert by_text["italic"]["italic"] is True
    assert by_text["code"]["code"] is True
    assert by_text["link"]["url"] == "https://x.dev"
    assert by_text["plain"].get("bold") is None
    assert by_text[""].get("code") is None if "" in by_text else True


# ── classification ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,kind", [
    ("a.md", "text"), ("a.markdown", "text"), ("a.txt", "text"), ("a.csv", "text"),
    ("a.json", "text"), ("a.py", "text"), ("a.rst", "text"), ("a", "text"),
    ("a.docx", "docx"), ("a.pdf", "pdf"), ("a.html", "html"), ("a.htm", "html"),
    ("a.pptx", "unsupported"), ("a.xlsx", "unsupported"), ("a.doc", "unsupported"),
])
def test_classify_picks_the_branch_by_extension(name, kind):
    assert wf.classify_output_node({"target_path": name})["kind"] == kind


def test_unwritable_formats_point_at_the_tool_that_can_do_it(target):
    deck = wf.write_document(str(target("deck.pptx")), "# x")
    sheet = wf.write_document(str(target("data.xlsx")), "# x")

    assert deck["error"] and "gen_pptx" in deck["result"]
    assert sheet["error"] and ".csv" in sheet["result"]
    assert not (target("deck.pptx")).exists()


# ── the text branch ──────────────────────────────────────────────────────────
def test_text_is_stored_verbatim(target):
    source = "# 报告\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**bold**\r\n"
    path, state = _write(target, "notes.md", source)

    assert not state.get("error")
    assert path.read_bytes() == source.encode("utf-8")
    assert "written verbatim" in state["format_label"]


# ── the docx branch ──────────────────────────────────────────────────────────
def test_docx_keeps_tables_lists_and_runs(target):
    path, state = _write(target, "report.docx")

    assert not state.get("error")
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode()
        parts = archive.namelist()

    assert "<w:tbl>" in xml                                   # a real Word table
    assert "ListBullet" in xml and "ListNumber" in xml         # real lists
    assert "word/numbering.xml" in parts                       # with numbering definitions
    assert "<w:b/>" in xml and "<w:i/>" in xml                 # bold and italic runs
    assert 'w:val="Heading1"' in xml                           # heading style
    assert "1200" in xml and "HK" in xml                       # table cells reached the file


# ── the pdf branch ───────────────────────────────────────────────────────────
def test_pdf_keeps_content_and_structure(target):
    path, state = _write(target, "report.pdf")

    assert not state.get("error")
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    assert all(value in text for value in ("Region", "Revenue", "HK", "1200"))
    assert "•" in text                                         # bullets
    assert "example.com" in text                               # the link target survives
    assert 'print("code block")' in text                       # the code block survives


# ── the html branch ──────────────────────────────────────────────────────────
def test_html_uses_real_elements(target):
    path, state = _write(target, "report.html")

    assert not state.get("error")
    html = path.read_text(encoding="utf-8")
    for marker in ("<table", "<thead>", "<ul>", "<ol>", "<li>", "<strong>", "<em>",
                   "<code>", "<pre>", "<blockquote", "<hr>", '<a href="https://example.com"'):
        assert marker in html, marker
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>report.html</title>" in html


def test_html_escapes_content_instead_of_executing_it(target):
    path, _ = _write(target, "evil.html", "# <script>alert(1)</script>\n\n<b>not bold</b>\n")

    html = path.read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>not bold</b>" not in html


# ── verify, caps and failures ────────────────────────────────────────────────
def test_verify_reports_the_size(target):
    path, state = _write(target, "notes.md", "hello\n")

    assert state["written_bytes"] == path.stat().st_size
    assert str(path.stat().st_size) in state["result"]


def test_verify_rejects_an_empty_render(target):
    state = wf.verify_node({"target_path": str(target("missing.docx")), "content": "x"})

    assert state["error"] and "not written" in state["result"]


def test_content_over_the_cap_is_refused(target):
    big = "x" * (wf.MAX_CONTENT_CHARS + 1)
    path, state = _write(target, "big.md", big)

    assert state["error"] and "write limit" in state["result"]
    assert not path.exists()


def test_writing_to_a_directory_reports_an_error(target):
    directory = target("adir")
    directory.mkdir()

    state = wf.write_document(str(directory), "content")

    assert state["error"]


def test_cli_writes_a_file_and_reports_it(tmp_path, capsys):
    out = tmp_path / "cli.md"

    assert wf._cli([str(out), "--text", "# Hi\n"]) == 0
    assert out.read_text() == "# Hi\n"
    assert "written verbatim" in capsys.readouterr().out
