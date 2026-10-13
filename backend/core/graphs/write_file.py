"""``write_file`` writer graph — one node per output format, staged one at a time.

Why a graph
-----------
The reader has a branch per *input* family, so the writer has a node per *output*
format. One node owns one format completely, which is what makes it safe to
change a format without touching the others — the reason this file exists instead
of a chain of ``if ext ==`` inside the tool.

Where it stands today
---------------------
Only the **markdown / text** branch is this module's own work: it stores the
content verbatim, which is the whole contract for that format (bytes in, bytes
out, UTF-8, no BOM, newlines as given).

The ``docx`` / ``pdf`` / ``html`` nodes deliberately call the renderers that
already existed (``tools/native_impl._write_docx_file`` / ``_write_pdf_file`` /
``_render_html_document``), so this step cannot change what those formats produce.
They are upgraded next, one format per step, each with its own before/after
evidence and its own tests:

* **md/text** — verbatim (done here).
* **pdf** — next: real tables, lists and inline styling.
* **docx** — then: real Word tables, list styles, bold/italic runs.
* **html** — then: real elements instead of escaped paragraphs.

The staging is measured, not stylistic: those renderers split the content on blank
lines and emit only ``h1``/``h2``/``h3``/``p``, so a Markdown table reaches Word as
pipe text and bullets as literal ``- item`` — in every format at once, which is why
the loss was invisible. Changing all three in one step would change three formats'
output together, with no way to review them separately.

Routing
-------
    classify ─┬─ text/md ─→ write_text ────┐
              ├─ docx ────→ write_docx ────┤
              ├─ pdf ─────→ write_pdf ─────┼─→ verify ─→ END
              ├─ html ────→ write_html ────┘
              └─ other ───→ unsupported ──────────────→ END

``verify`` is this graph's reduce: the single place that answers "did the branch
actually produce a file, and how big is it", rather than five places reporting
success without looking.

Where a file goes is **not** this graph's business — the caller resolves the path
inside the workspace (``tools/native_impl._write_target``) and reports it. This
module only renders into the path it is handed, so workspace rules and format
rendering stay independently testable.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────────
MAX_CONTENT_CHARS = int(os.getenv("LANGCONFIG_WRITE_MAX_CHARS", "1000000"))

# Extensions this graph renders rather than stores. Any other extension is text.
RENDERED_FORMATS = (".docx", ".pdf", ".html", ".htm")

# Binary formats that writing text into would *corrupt*: refused with a pointer at
# the tool that can produce them, rather than silently writing garbage.
UNWRITABLE_FORMATS = {
    ".pptx": "a PowerPoint deck — use gen_pptx / doc_to_deck (slides JSON + a template)",
    ".ppt": "a legacy PowerPoint deck — convert it and use gen_pptx",
    ".xlsx": "a spreadsheet — write .csv instead (this platform reads .xlsx, nothing writes it)",
    ".xls": "a legacy spreadsheet — write .csv instead",
    ".doc": "a legacy Word document — write .docx instead",
}

# How the format is described back to the caller, so the agent can tell the user
# what it actually produced rather than what it hoped to produce.
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


# ── nodes ────────────────────────────────────────────────────────────────────
def classify_output_node(state: WriteState) -> WriteState:
    """Decide the branch from the target's extension."""
    started = time.time()
    path = Path(state["target_path"])
    ext = path.suffix.lower()
    if ext == ".docx":
        kind = "docx"
    elif ext == ".pdf":
        kind = "pdf"
    elif ext in (".html", ".htm"):
        kind = "html"
    elif ext in UNWRITABLE_FORMATS:
        kind = "unsupported"
    else:
        # Everything else is text — markdown, csv, json, code, logs, and the
        # leniency this tool has always had for an unfamiliar extension.
        kind = "text"
    return {"kind": kind, "ext": ext,
            "display_path": state.get("display_path") or path.name,
            "classify_ms": int((time.time() - started) * 1000)}


def route_by_kind(state: WriteState) -> str:
    """Conditional-edge router: ``text`` | ``docx`` | ``pdf`` | ``html`` | ``unsupported``."""
    return state.get("kind") or "text"


def _guard_content(state: WriteState) -> Optional[str]:
    """Return an error message when the content cannot be written at all."""
    content = state.get("content") or ""
    if len(content) > MAX_CONTENT_CHARS:
        return (f"Error: content is {len(content)} characters, over the "
                f"{MAX_CONTENT_CHARS} character write limit.")
    return None


def write_text_node(state: WriteState) -> WriteState:
    """The markdown / text branch: verbatim, UTF-8, no BOM, newlines untouched.

    This is the whole contract for the format — there is no rendering step to get
    wrong, which is why it is the branch that landed first.
    """
    started = time.time()
    error = _guard_content(state)
    if error:
        return {"result": error, "error": error, "kind": "text",
                "write_ms": int((time.time() - started) * 1000)}
    path = Path(state["target_path"])
    try:
        path.write_text(state.get("content") or "", encoding="utf-8")
    except Exception as e:
        msg = f"Error: could not write '{path.name}': {type(e).__name__}: {e}"
        logger.warning(msg)
        return {"result": msg, "error": msg, "kind": "text",
                "write_ms": int((time.time() - started) * 1000)}
    return {"kind": "text", "format_label": "written verbatim",
            "write_ms": int((time.time() - started) * 1000)}


def _render_node(state: WriteState, kind: str, renderer) -> WriteState:
    """Shared body of the three rendered branches (their renderers are unchanged)."""
    started = time.time()
    error = _guard_content(state)
    if error:
        return {"result": error, "error": error, "kind": kind,
                "write_ms": int((time.time() - started) * 1000)}
    path = Path(state["target_path"])
    try:
        renderer(path, state.get("content") or "")
    except Exception as e:
        msg = f"Error: could not write '{path.name}' as {kind}: {type(e).__name__}: {e}"
        logger.warning(msg)
        return {"result": msg, "error": msg, "kind": kind,
                "write_ms": int((time.time() - started) * 1000)}
    return {"kind": kind,
            "format_label": FORMAT_LABELS.get(state.get("ext") or "", "written verbatim"),
            "write_ms": int((time.time() - started) * 1000)}


def write_docx_node(state: WriteState) -> WriteState:
    """Word branch — the existing renderer, until its upgrade lands."""
    from tools.native_impl import _write_docx_file

    return _render_node(state, "docx", _write_docx_file)


def write_pdf_node(state: WriteState) -> WriteState:
    """PDF branch — the existing renderer, until its upgrade lands."""
    from tools.native_impl import _write_pdf_file

    return _render_node(state, "pdf", _write_pdf_file)


def write_html_node(state: WriteState) -> WriteState:
    """HTML branch — the existing renderer, until its upgrade lands."""
    from tools.native_impl import _render_html_document

    def render(path: Path, content: str) -> None:
        path.write_text(_render_html_document(content, title=path.name), encoding="utf-8")

    return _render_node(state, "html", render)


def unsupported_node(state: WriteState) -> WriteState:
    """A format that would be corrupted rather than rendered: name the alternative."""
    advice = UNWRITABLE_FORMATS.get(state.get("ext") or "", "not a writable format")
    msg = (f"Error: cannot write '{state.get('display_path')}' — {advice}. "
           f"This writer produces .md/.txt/.csv/.json (verbatim), .docx, .pdf and .html.")
    return {"result": msg, "error": msg, "kind": "unsupported", "format_label": ""}


def verify_node(state: WriteState) -> WriteState:
    """Reduce: did the branch produce a file, and how big is it.

    A renderer that silently writes nothing is caught here rather than reaching
    the user as "successfully wrote".
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
    """Run the graph for one file; returns the state (``result`` is the message).

    Synchronous on purpose: writing a file has nothing to await, and the tool that
    calls this is synchronous, so the graph runs with ``invoke``.
    """
    return get_file_writer_graph().invoke(
        {"target_path": str(target_path), "content": content,
         "display_path": display_path or ""},
        config={"recursion_limit": 8},
    )


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli(argv: Optional[list] = None) -> int:
    """Render one file from the command line — the same code path the tool uses.

        python -m core.graphs.write_file out.docx --content notes.md
        python -m core.graphs.write_file out.md --text "# Hi"
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="write_file",
        description="Run the write_file writer graph on one target and report what it wrote.")
    parser.add_argument("path", help="target file; the extension picks the format")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--content", help="file to read the content from")
    source.add_argument("--text", help="content given inline")
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
