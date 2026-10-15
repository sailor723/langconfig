# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Doc Chat reads an HTML document as its text, not as its markup.

Why this is worth a test file of its own: `.html` is in `TEXT_EXTENSIONS`, so before this the whole
file was read verbatim and inlined into the prompt — a pandoc report's `<style>` block included.
The model was then asked to answer from "the documents", and the stylesheet was one of them.

Three things are asserted, in the order they can go wrong:

1. **The furniture goes.** `<style>`, `<script>`, `<head>`, comments and entity noise are not
   content and must not reach the prompt.
2. **The content stays, and reads as prose.** Inline markup must not split a sentence in half;
   block markup must still separate paragraphs, list items and table cells.
3. **Nothing is ever lost.** A file that yields no readable text falls back to its raw bytes, so
   this can only ever give the model more to work with than before, never less.
"""
from pathlib import Path

import pytest

from api.knowledge import doc_chat


def _html(body: str, head: str = "", title: str = "t") -> str:
    return (f"<!DOCTYPE html><html><head><title>{title}</title>{head}</head>"
            f"<body>{body}</body></html>")


# ── 1. the furniture goes ────────────────────────────────────────────

def test_css_and_scripts_never_reach_the_model():
    raw = _html(
        head='<style>body { font-kerning: normal; hyphens: auto; }</style>',
        body='<p>Revenue grew 12% in 2026.</p><script>var x = "SECRET_TOKEN";</script>',
    )
    text = doc_chat._html_to_text(raw)

    assert "Revenue grew 12% in 2026." in text
    assert "font-kerning" not in text
    assert "hyphens" not in text
    assert "SECRET_TOKEN" not in text


def test_head_metadata_is_dropped_but_a_real_title_is_kept():
    raw = ("<html><head><title>华阳医疗战略转型调研</title>"
           '<meta name="generator" content="pandoc"><link rel="stylesheet" href="x.css">'
           "</head><body><p>正文。</p></body></html>")
    text = doc_chat._html_to_text(raw, source_name="a_report.html")

    assert text.startswith("# 华阳医疗战略转型调研")
    assert "正文。" in text
    assert "pandoc" not in text
    assert "x.css" not in text


def test_a_title_that_only_repeats_the_filename_is_not_repeated():
    """The prompt already labels the document with its filename; a title that echoes it is noise."""
    text = doc_chat._html_to_text(
        _html("<p>Body.</p>", title="company_analysis_final_report"),
        source_name="company_analysis_final_report.html")
    assert text == "Body."
    assert "#" not in text


def test_the_repeated_title_check_survives_the_stored_name_prefix():
    """Real knowledge-base files are stored with an 8-hex prefix, so this is the case that counts.

    Comparing the title against the on-disk name would never match — the guard would be dead code
    on every document in an actual knowledge base.
    """
    text = doc_chat._html_to_text(
        _html("<p>Body.</p>", title="company_analysis_final_report"),
        source_name="a2d6dd95_company_analysis_final_report.html")
    assert text == "Body."
    assert "#" not in text


def test_a_title_that_says_something_new_is_kept():
    """A real page title is content and must survive — only a redundant one is dropped."""
    text = doc_chat._html_to_text(
        _html("<p>Body.</p>", title="惠州华阳医疗器械有限公司 — 战略公司分析报告"),
        source_name="a2d6dd95_report.html")
    assert text.startswith("# 惠州华阳医疗器械有限公司 — 战略公司分析报告")


def test_html_comments_are_not_content():
    text = doc_chat._html_to_text(_html("<p>Kept.</p><!-- drop me -->"))
    assert "Kept." in text
    assert "drop me" not in text


def test_entities_are_decoded():
    """A model reading `&amp;` as text cannot match it against a question asked in plain text."""
    text = doc_chat._html_to_text(_html("<p>Wound care &amp; biomaterials &lt;2026&gt;</p>"))
    assert "Wound care & biomaterials <2026>" in text
    assert "&amp;" not in text


# ── 2. the content stays, and reads as prose ─────────────────────────

def test_inline_markup_does_not_split_a_sentence():
    """Chinese reports are full of inline spans; a separator between every string shreds them."""
    text = doc_chat._html_to_text(_html(
        "<p>海外营收占比近<span>90%</span>，服务全球超<b>300</b>家客户。</p>"))
    assert "海外营收占比近90%，服务全球超300家客户。" in text


def test_blocks_keep_their_boundaries():
    text = doc_chat._html_to_text(_html(
        "<h2>风险</h2><p>集采降价。</p><ul><li>第一项</li><li>第二项</li></ul>"))
    lines = [line for line in text.splitlines() if line.strip()]

    assert "风险" in lines, "a heading must stand on its own line"
    assert "集采降价。" in lines
    assert "第一项" in lines and "第二项" in lines
    # ...and the list items are separate lines rather than one run-on line.
    assert lines.index("第一项") != lines.index("第二项")


def test_table_cells_stay_separated():
    text = doc_chat._html_to_text(_html(
        "<table><tr><th>公司</th><th>毛利率</th></tr>"
        "<tr><td>振德医疗</td><td>34.19%</td></tr></table>"))
    for cell in ("公司", "毛利率", "振德医疗", "34.19%"):
        assert cell in text
    assert "公司毛利率" not in text, "adjacent cells must not run together"


def test_whitespace_is_normalised_but_paragraphs_survive():
    text = doc_chat._html_to_text(_html(
        "<p>First.</p><p></p><p></p><p>Second.</p>"))
    assert "\n\n\n" not in text
    assert "First." in text and "Second." in text


def test_preformatted_text_keeps_its_own_line_structure():
    """`<pre>` is where a document keeps a table or a command; reflowing it would destroy it."""
    text = doc_chat._html_to_text(_html("<pre>phase1\nphase2\nphase3</pre>"))
    assert "phase1" in text and "phase3" in text
    assert text.count("\n") >= 2


# ── 3. nothing is ever lost ──────────────────────────────────────────

def test_a_page_with_no_readable_text_falls_back_to_raw():
    """An HTML file that is nothing but script must not become an empty document."""
    raw = "<html><body><script>var a = 1;</script></body></html>"
    assert doc_chat._html_to_text(raw) == raw


def test_malformed_html_does_not_raise():
    """Real exports are frequently tag soup; a parse failure must not lose the document."""
    text = doc_chat._html_to_text("<p>Unclosed <b>bold <div>and a div")
    assert "Unclosed" in text and "bold" in text


# ── wired through the reader that actually feeds the prompt ──────────

def test_extract_text_routes_html_through_the_extractor(tmp_path: Path):
    """The unit tests above only matter if `_extract_text` uses them for .html and .htm."""
    for name in ("report.html", "report.htm"):
        path = tmp_path / name
        path.write_text(_html(head="<style>.x{color:red}</style>",
                              body="<p>Net profit rose.</p>"), encoding="utf-8")
        text = doc_chat._extract_text(path)

        assert text is not None
        assert "Net profit rose." in text
        assert "color:red" not in text


def test_extract_text_still_reads_plain_text_verbatim(tmp_path: Path):
    """The HTML branch must not have changed how every other text document is read."""
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n\n<div>literal markup is fine in markdown</div>", encoding="utf-8")
    assert doc_chat._extract_text(path) == path.read_text(encoding="utf-8")


def test_missing_html_file_is_skipped_not_raised(tmp_path: Path):
    assert doc_chat._extract_text(tmp_path / "absent.html") is None


@pytest.mark.parametrize("extension", [".html", ".htm"])
def test_html_stays_a_supported_document_type(extension):
    """Chat-ability is decided by the shared extension sets in the ingest core, not here."""
    from services.kv_ingest import DOCUMENT_EXTENSIONS

    assert extension in DOCUMENT_EXTENSIONS
