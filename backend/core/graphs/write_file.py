"""``write_file`` writer graph — one node per output format, one Markdown parser.

Why a graph
-----------
Writing is the mirror image of reading: the reader has one branch per *input*
family (text, image, pdf, word/excel, archive), so the writer has one node per
*output* format (text, docx, pdf, html). Each node owns its format completely,
which is what lets a format be improved — or tested — without touching the
others.

Why it exists at all
--------------------
The writers it replaces split the content on blank lines and emitted only
``h1`` / ``h2`` / ``h3`` / ``p``. Measured on a Markdown source with a bold run, a
link, bullets, a table and a code fence, that produced:

    .html   no <table>, no <ul>, no <strong>, no <a href>, no <code>
    .docx   no <w:tbl>, no list numbering, no bold runs
    .pdf    the table as pipe text, bullets as literal "- item"

Every format flattened the same way, so the loss was invisible to whoever chose
"export as HTML to keep the table". The fix is a single Markdown parser
(:func:`parse_markdown`) whose blocks and inline spans each emitter maps onto the
constructs its own format has: a real Word table, an fpdf2 ``table()``, real
``<table>`` / ``<ul>`` / ``<strong>`` / ``<a>`` elements.

Routing
-------
    classify ─┬─ text/md ─→ write_text ──┐
              ├─ docx ────→ write_docx ──┤
              ├─ pdf ─────→ write_pdf ───┼─→ verify ─→ END
              ├─ html ────→ write_html ──┘
              └─ other ───→ unsupported ───────────→ END

``verify`` is the reduce of this graph: one small node that every branch passes
through, which is where "did the renderer actually produce a file, and how big is
it" is answered once instead of in five places.

Where a file goes is **not** this graph's business: the caller resolves the path
inside the workspace (see ``tools/native_impl._write_target``) and this module
only renders into the path it is given, so the workspace rules and the formats
stay independently testable.

The Markdown subset
-------------------
Deliberately a subset, because it is parsed here rather than by a library
(``markdown`` / ``mistune`` are not dependencies): ATX headings, paragraphs,
bullet and ordered lists, GFM tables, fenced code, blockquotes, horizontal rules,
and inline bold / italic / code / links. Anything else is written through as
text, which is the safe direction for a subset to fail in.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

# The reader and the writer agree on what "plain text" means; one list, imported
# rather than copied, so a format cannot be text to one and binary to the other.
from core.graphs.read_file import TEXT_EXTS

logger = logging.getLogger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────────
MAX_CONTENT_CHARS = int(os.getenv("LANGCONFIG_WRITE_MAX_CHARS", "1000000"))
MAX_TABLE_COLUMNS = int(os.getenv("LANGCONFIG_WRITE_MAX_TABLE_COLUMNS", "12"))
CODE_FONT = os.getenv("LANGCONFIG_WRITE_CODE_FONT", "Menlo")

# Formats this graph renders. ``text`` is the verbatim branch.
RENDERED_FORMATS = (".html", ".pdf", ".docx")

# Binary formats that would be *silently corrupted* by writing text into them —
# refused with a pointer at the tool that can actually produce them.
UNWRITABLE_FORMATS = {
    ".pptx": "a PowerPoint deck — use gen_pptx / doc_to_deck (slides JSON + a template)",
    ".ppt": "a legacy PowerPoint deck — save/convert it and use gen_pptx",
    ".xlsx": "a spreadsheet — write .csv instead (the reader reads .xlsx, nothing writes it)",
    ".xls": "a legacy spreadsheet — write .csv instead",
    ".doc": "a legacy Word document — write .docx instead",
}

FORMAT_LABELS = {
    ".docx": "Word document rendered from your markdown",
    ".pdf": "PDF rendered from your markdown",
    ".html": "HTML page rendered from your markdown",
}


class WriteState(TypedDict, total=False):
    """Graph state. ``result`` is what the caller reports; the rest is detail."""

    # ── input ──
    target_path: str
    content: str
    display_path: str
    # ── classification ──
    kind: str                       # text | docx | pdf | html | unsupported
    ext: str
    # ── outcome ──
    written_bytes: int
    format_label: str
    result: str
    error: str
    # per-node durations
    classify_ms: int
    write_ms: int
    verify_ms: int


# ── Markdown: blocks ─────────────────────────────────────────────────────────
FENCE_RE = re.compile(r"^```\s*([\w+-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*([-*+])\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
RULE_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _split_table_row(line: str) -> List[str]:
    """``| a | b |`` → ``["a", "b"]`` (the outer pipes are optional)."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def parse_markdown(content: str) -> List[Dict[str, Any]]:
    """Parse the supported Markdown subset into typed blocks, in order.

    Block kinds: ``heading`` (``level``, ``text``), ``paragraph`` (``spans``),
    ``list`` (``ordered``, ``items`` where each item is a span list), ``table``
    (``header``, ``rows``), ``code`` (``lang``, ``text``), ``quote`` (``spans``),
    ``rule``.
    """
    lines = (content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append({"kind": "paragraph", "spans": parse_inline(" ".join(paragraph).strip())})
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]

        fence = FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            language, body, index = fence.group(1), [], index + 1
            while index < len(lines) and not FENCE_RE.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1                                  # consume the closing fence
            blocks.append({"kind": "code", "lang": language, "text": "\n".join(body)})
            continue

        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            blocks.append({"kind": "heading", "level": len(heading.group(1)),
                           "text": heading.group(2).strip()})
            index += 1
            continue

        if RULE_RE.match(line):
            flush_paragraph()
            blocks.append({"kind": "rule"})
            index += 1
            continue

        # A table is a header row followed by a divider row; without the divider
        # the pipes are just text, which is how GFM behaves too.
        if "|" in line and index + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[index + 1]):
            flush_paragraph()
            header = _split_table_row(line)[:MAX_TABLE_COLUMNS]
            index += 2
            rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_table_row(lines[index])[:MAX_TABLE_COLUMNS])
                index += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue

        bullet = BULLET_RE.match(line)
        ordered = ORDERED_RE.match(line)
        if bullet or ordered:
            flush_paragraph()
            is_ordered = ordered is not None
            items: List[List[Dict[str, Any]]] = []
            while index < len(lines):
                match = (ORDERED_RE if is_ordered else BULLET_RE).match(lines[index])
                if not match:
                    break
                items.append(parse_inline(match.group(2).strip()))
                index += 1
            blocks.append({"kind": "list", "ordered": is_ordered, "items": items})
            continue

        quote = QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            quoted = []
            while index < len(lines):
                match = QUOTE_RE.match(lines[index])
                if not match:
                    break
                quoted.append(match.group(1).strip())
                index += 1
            blocks.append({"kind": "quote", "spans": parse_inline(" ".join(quoted).strip())})
            continue

        paragraph.append(line.strip())
        index += 1

    flush_paragraph()
    return blocks


# ── Markdown: inline ─────────────────────────────────────────────────────────
INLINE_RE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<bold>\*\*[^*]+\*\*|__[^_]+__)"
    r"|(?P<italic>\*[^*\n]+\*|_[^_\n]+_)"
    r"|(?P<link>\[[^\]]+\]\([^)\s]+\))"
)


def parse_inline(text: str) -> List[Dict[str, Any]]:
    """Split a line into spans: ``{text, bold, italic, code, url}``.

    Emitters map these onto what their format has — a bold ``run`` in Word,
    ``<strong>`` in HTML, a font switch in the PDF.
    """
    spans: List[Dict[str, Any]] = []
    position = 0
    for match in INLINE_RE.finditer(text or ""):
        if match.start() > position:
            spans.append({"text": text[position:match.start()]})
        raw = match.group(0)
        if match.group("code"):
            spans.append({"text": raw[1:-1], "code": True})
        elif match.group("bold"):
            spans.append({"text": raw[2:-2], "bold": True})
        elif match.group("italic"):
            spans.append({"text": raw[1:-1], "italic": True})
        else:
            label, url = raw[1:-1].split("](", 1)
            spans.append({"text": label, "url": url})
        position = match.end()
    if position < len(text or ""):
        spans.append({"text": text[position:]})
    return spans or [{"text": text or ""}]


def spans_to_text(spans: List[Dict[str, Any]]) -> str:
    """Plain text of a span list — for formats that cannot carry the styling."""
    return "".join(span.get("text", "") for span in spans)


# ── emitters ─────────────────────────────────────────────────────────────────
def render_text(path: Path, content: str) -> None:
    """The verbatim branch: bytes in, bytes out (UTF-8, no BOM, newlines as given)."""
    path.write_text(content, encoding="utf-8")


def render_html(content: str, title: str = "Document") -> str:
    """Markdown → one self-contained HTML page, with real elements."""
    import html as _html

    def esc(text: str) -> str:
        return _html.escape(text, quote=False)

    def inline(spans: List[Dict[str, Any]]) -> str:
        out = []
        for span in spans:
            text = esc(span.get("text", ""))
            if span.get("code"):
                out.append(f"<code>{text}</code>")
            elif span.get("bold"):
                out.append(f"<strong>{text}</strong>")
            elif span.get("italic"):
                out.append(f"<em>{text}</em>")
            elif span.get("url"):
                out.append(f'<a href="{_html.escape(span["url"], quote=True)}">{text}</a>')
            else:
                out.append(text)
        return "".join(out)

    parts: List[str] = []
    for block in parse_markdown(content):
        kind = block["kind"]
        if kind == "heading":
            level = min(block["level"], 6)
            parts.append(f"<h{level}>{esc(block['text'])}</h{level}>")
        elif kind == "paragraph":
            parts.append(f"<p>{inline(block['spans'])}</p>")
        elif kind == "list":
            tag = "ol" if block["ordered"] else "ul"
            items = "".join(f"<li>{inline(item)}</li>" for item in block["items"])
            parts.append(f"<{tag}>{items}</{tag}>")
        elif kind == "table":
            head = "".join(f"<th>{esc(cell)}</th>" for cell in block["header"])
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(parse_inline(cell))}</td>" for cell in row) + "</tr>"
                for row in block["rows"]
            )
            parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif kind == "code":
            language = f' class="language-{esc(block["lang"])}"' if block.get("lang") else ""
            parts.append(f"<pre><code{language}>{esc(block['text'])}</code></pre>")
        elif kind == "quote":
            parts.append(f"<blockquote>{inline(block['spans'])}</blockquote>")
        elif kind == "rule":
            parts.append("<hr>")

    safe_title = esc(title or "Document")
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 820px; margin: 40px auto; padding: 0 24px; color: #1f2328; line-height: 1.7; }}
  h1, h2, h3, h4, h5, h6 {{ line-height: 1.3; margin: 1.6em 0 0.6em; }}
  h1 {{ font-size: 1.9em; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.3em; }}
  h2 {{ font-size: 1.45em; }}
  h3 {{ font-size: 1.2em; }}
  p, li, blockquote {{ font-size: 16px; }}
  ul, ol {{ padding-left: 1.5em; }}
  li {{ margin: 0.25em 0; }}
  code {{ background: #f3f4f6; padding: 0.15em 0.35em; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, {CODE_FONT}, Consolas, monospace; font-size: 0.92em; }}
  pre {{ background: #f6f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 14px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 15px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f6f8fa; font-weight: 600; }}
  blockquote {{ border-left: 4px solid #d0d7de; margin: 1em 0; padding: 0.2em 1em; color: #57606a; }}
  a {{ color: #0969da; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 2em 0; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_docx(path: Path, content: str) -> None:
    """Markdown → .docx with real Word constructs (headings, lists, tables, runs)."""
    from docx import Document
    from docx.shared import Pt

    document = Document()

    def add_runs(paragraph, spans: List[Dict[str, Any]]) -> None:
        for span in spans:
            run = paragraph.add_run(span.get("text", ""))
            if span.get("bold"):
                run.bold = True
            if span.get("italic"):
                run.italic = True
            if span.get("code"):
                run.font.name = CODE_FONT
                run.font.size = Pt(10)
            if span.get("url") and span["url"] != span.get("text"):
                paragraph.add_run(f" ({span['url']})")

    for block in parse_markdown(content):
        kind = block["kind"]
        if kind == "heading":
            document.add_heading(block["text"], level=min(block["level"], 9))
        elif kind == "paragraph":
            add_runs(document.add_paragraph(), block["spans"])
        elif kind == "list":
            style = "List Number" if block["ordered"] else "List Bullet"
            for item in block["items"]:
                add_runs(document.add_paragraph(style=style), item)
        elif kind == "code":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(block["text"])
            run.font.name = CODE_FONT
            run.font.size = Pt(9)
        elif kind == "quote":
            add_runs(document.add_paragraph(style="Quote"), block["spans"])
        elif kind == "table":
            columns = max(len(block["header"]), 1)
            table = document.add_table(rows=1 + len(block["rows"]), cols=columns)
            try:
                table.style = "Table Grid"
            except Exception:                      # a template without that style
                logger.debug("docx template has no 'Table Grid' style")
            for column, cell in enumerate(block["header"][:columns]):
                table.rows[0].cells[column].text = cell
            for row_number, row in enumerate(block["rows"], start=1):
                for column, cell in enumerate(row[:columns]):
                    table.rows[row_number].cells[column].text = cell
        elif kind == "rule":
            document.add_paragraph("—" * 20)

    document.save(str(path))


def render_pdf(path: Path, content: str) -> None:
    """Markdown → PDF via fpdf2, with a real table and inline bold."""
    from fpdf import FPDF

    from tools.native_impl import _add_pdf_font      # unicode/CJK-capable font

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    family = _add_pdf_font(pdf)

    def write_spans(spans: List[Dict[str, Any]], size: int) -> None:
        for span in spans:
            style = "B" if span.get("bold") else ("I" if span.get("italic") else "")
            pdf.set_font(family, style, size)
            text = span.get("text", "")
            if span.get("url") and span["url"] != text:
                text = f"{text} ({span['url']})"
            pdf.write(6, text)
        pdf.ln(8)

    for block in parse_markdown(content):
        kind = block["kind"]
        if kind == "heading":
            pdf.set_font(family, "B", {1: 16, 2: 14, 3: 12}.get(block["level"], 11))
            pdf.multi_cell(0, 8, block["text"])
            pdf.ln(2)
        elif kind == "paragraph":
            write_spans(block["spans"], 11)
        elif kind == "list":
            for number, item in enumerate(block["items"], start=1):
                marker = f"{number}." if block["ordered"] else "•"
                pdf.set_font(family, "", 11)
                pdf.write(6, f"{marker} ")
                write_spans(item, 11)
        elif kind == "code":
            pdf.set_font(family, "", 9)
            pdf.multi_cell(0, 5, block["text"])
            pdf.ln(3)
        elif kind == "quote":
            pdf.set_font(family, "I", 11)
            pdf.multi_cell(0, 6, spans_to_text(block["spans"]))
            pdf.ln(2)
        elif kind == "table":
            with pdf.table() as table:
                header = table.row()
                for cell in block["header"]:
                    header.cell(cell)
                for row in block["rows"]:
                    cells = table.row()
                    for cell in row:
                        cells.cell(spans_to_text(parse_inline(cell)))
            pdf.ln(3)
        elif kind == "rule":
            pdf.set_font(family, "", 11)
            pdf.multi_cell(0, 4, "-" * 40)

    pdf.output(str(path))


# ── nodes ────────────────────────────────────────────────────────────────────
def classify_output_node(state: WriteState) -> WriteState:
    """Decide the branch from the target's extension."""
    started = time.time()
    target = state["target_path"]
    ext = Path(target).suffix.lower()
    if ext == ".docx":
        kind = "docx"
    elif ext == ".pdf":
        kind = "pdf"
    elif ext in (".html", ".htm"):
        kind = "html"
    elif ext in UNWRITABLE_FORMATS:
        kind = "unsupported"
    else:
        # Everything else is text: the plain-text list the reader uses, plus the
        # leniency this tool has always had for unknown extensions (.rst, .log…).
        kind = "text"
    return {"kind": kind, "ext": ext, "display_path": state.get("display_path") or Path(target).name,
            "classify_ms": int((time.time() - started) * 1000)}


def route_by_kind(state: WriteState) -> str:
    """Conditional-edge router: ``text`` | ``docx`` | ``pdf`` | ``html`` | ``unsupported``."""
    return state.get("kind") or "text"


def _write_node(state: WriteState, kind: str, writer) -> WriteState:
    """Run one emitter and report what it produced (shared by all four branches)."""
    started = time.time()
    path = Path(state["target_path"])
    content = state.get("content") or ""
    if len(content) > MAX_CONTENT_CHARS:
        msg = (f"Error: content is {len(content)} characters, over the "
               f"{MAX_CONTENT_CHARS} character write limit.")
        return {"result": msg, "error": msg, "kind": kind,
                "write_ms": int((time.time() - started) * 1000)}
    try:
        writer(path, content)
    except Exception as e:
        msg = f"Error: could not write '{path.name}' as {kind}: {type(e).__name__}: {e}"
        logger.warning(msg)
        return {"result": msg, "error": msg, "kind": kind,
                "write_ms": int((time.time() - started) * 1000)}
    return {"kind": kind, "format_label": FORMAT_LABELS.get(state.get("ext") or "",
                                                           "written verbatim"),
            "write_ms": int((time.time() - started) * 1000)}


def write_text_node(state: WriteState) -> WriteState:
    """Verbatim branch: markdown, csv, json, code, logs — bytes as given."""
    return _write_node(state, "text", render_text)


def write_docx_node(state: WriteState) -> WriteState:
    """Word branch: headings, lists, tables and inline runs are real Word objects."""
    return _write_node(state, "docx", lambda path, content: render_docx(path, content))


def write_pdf_node(state: WriteState) -> WriteState:
    """PDF branch: headings, lists, a real table and inline bold."""
    return _write_node(state, "pdf", lambda path, content: render_pdf(path, content))


def write_html_node(state: WriteState) -> WriteState:
    """HTML branch: elements, not escaped paragraphs."""
    def write(path: Path, content: str) -> None:
        path.write_text(render_html(content, title=path.name), encoding="utf-8")

    return _write_node(state, "html", write)


def unsupported_node(state: WriteState) -> WriteState:
    """A format that would be corrupted rather than rendered: say what to use."""
    ext = state.get("ext") or ""
    advice = UNWRITABLE_FORMATS.get(ext, "not a writable format")
    msg = (f"Error: cannot write '{state.get('display_path')}' — {advice}. "
           f"This writer produces .md/.txt/.csv/.json (verbatim), .docx, .pdf and .html.")
    return {"result": msg, "error": msg, "kind": "unsupported", "format_label": ""}


def verify_node(state: WriteState) -> WriteState:
    """Reduce: did the branch actually produce a file, and how big is it.

    One place for the answer, so a renderer that silently writes nothing is
    caught here rather than reaching the user as "successfully wrote".
    """
    started = time.time()
    if state.get("error"):
        return {}                                   # the branch already answered
    path = Path(state["target_path"])
    try:
        size = path.stat().st_size
    except OSError as e:
        msg = f"Error: '{path.name}' was not written ({type(e).__name__}: {e})"
        return {"result": msg, "error": msg, "verify_ms": int((time.time() - started) * 1000)}
    if size == 0 and (state.get("content") or "").strip():
        msg = f"Error: '{path.name}' came out empty although content was given"
        return {"result": msg, "error": msg, "verify_ms": int((time.time() - started) * 1000)}
    return {"written_bytes": size,
            "result": f"wrote {state.get('display_path')} ({size} bytes, "
                      f"{state.get('format_label') or 'written verbatim'})",
            "verify_ms": int((time.time() - started) * 1000)}


# ── graph ────────────────────────────────────────────────────────────────────
def build_file_writer_graph():
    """Compile the writer graph (utility graph: no checkpointer, no state kept)."""
    builder = StateGraph(WriteState)
    builder.add_node("classify", classify_output_node)
    builder.add_node("write_text", write_text_node)
    builder.add_node("write_docx", write_docx_node)
    builder.add_node("write_pdf", write_pdf_node)
    builder.add_node("write_html", write_html_node)
    builder.add_node("unsupported", unsupported_node)
    builder.add_node("verify", verify_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_by_kind, {
        "text": "write_text",
        "docx": "write_docx",
        "pdf": "write_pdf",
        "html": "write_html",
        "unsupported": "unsupported",
    })
    # Every branch that produced a file passes through the same check.
    for branch in ("write_text", "write_docx", "write_pdf", "write_html"):
        builder.add_edge(branch, "verify")
    builder.add_edge("verify", END)
    builder.add_edge("unsupported", END)
    return builder.compile()


_GRAPH = None


def get_file_writer_graph():
    """Process-wide compiled graph (built lazily)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_file_writer_graph()
    return _GRAPH


def write_document(target_path: str, content: str, display_path: Optional[str] = None) -> WriteState:
    """Run the graph for one file. Returns the state (``result`` is the message).

    Synchronous on purpose: writing a file has nothing to await, and the tools
    that call this are synchronous, so the graph runs with ``invoke``.
    """
    return get_file_writer_graph().invoke(
        {"target_path": str(target_path), "content": content,
         "display_path": display_path or ""},
        config={"recursion_limit": 8},
    )


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli(argv: Optional[list] = None) -> int:
    """Render one file from the command line — same code path the tool uses.

        python -m core.graphs.write_file out.docx --content notes.md
        python -m core.graphs.write_file out.html --text "# Hi"
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="write_file",
        description="Run the write_file writer graph on a target path and report what it wrote.")
    parser.add_argument("path", help="target file, e.g. report.docx (extension picks the format)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--content", help="file to read the markdown content from")
    source.add_argument("--text", help="markdown content given inline")
    parser.add_argument("--json", action="store_true", help="print the whole state")
    args = parser.parse_args(argv)

    content = args.text if args.text is not None else Path(args.content).read_text(encoding="utf-8")
    state = write_document(args.path, content)
    if args.json:
        print(json.dumps(state, indent=2, default=str))
    else:
        print(state.get("result") or "writer produced no output")
    return 1 if state.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
