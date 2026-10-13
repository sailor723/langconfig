"""``read_file`` reader graph — one text result for any file type.

Why a graph and why text
------------------------
A tool result crosses the model wire as **text** (an OpenAI-compatible tool
message cannot carry an image content part), so a reader tool may never hand
back raw image bytes. deepagents' filesystem middleware returns images as
``[{"type": "image", "base64": …}]``; inside a tool message that base64 is
tokenised per character, so a 1.5 MB PNG became 2,113,084 chars →
1,465,119 tokens → HTTP 400 against the 1,048,576-token window. This graph
turns any file into a small **text** payload instead.

Routing
-------
Five branches, one per family of file, plus the path that refuses:

    classify ─┬─ text/data ────→ read_text ──────────────────────────────→ END
              ├─ image ─────────→ read_image ─┬─ ocr ──────┐
              │                               └─ describe ─┴→ merge ─→ END
              ├─ pdf ──────────→ read_pdf ─┬─ (one Send per image-only page) ─┐
              │                            └─ (nothing to render) ───────────┤
              ├─ word/ppt/xls ─→ read_document ─┬─ (one Send per picture) ────┤
              │                                 └─ (no pictures) ─────────────┤
              ├─ zip/tar ──────→ read_archive ─┬─ (Send per readable member) ─┤
              │                                └─ (no readable members) ─────┤
              │                                                             ↓
              │        pdf_page / doc_picture / archive_member ─→ *┬─ pdf_compose ─┐
              │                                                    ├─ doc_compose ─┤
              │                                                    └─ archive_compose ─→ END
              └─ other ────────→ unsupported ──────────────────────────────────→ END

``read_text`` / ``read_image`` / ``read_pdf`` / ``read_document`` /
``read_archive`` are the five branch entry points and the only nodes the router
chooses between; everything else is a node inside one of those branches, because
a format is not always one step: an image is normalised *and* OCR'd *and*
described, a PDF is a per-page map plus a reduce, a Word/PowerPoint/Excel file is
a structure pass plus a map over the pictures embedded in it, and an archive is a
manifest plus a map over its readable members.

An archive is the one branch that **recurses**: a member is read by
:func:`read_file_as_text` again, so a .csv member is read by the text branch, a
.docx member by the document branch, and a .png member by the image branch —
there is no second implementation of any format. ``depth`` counts the expansion,
so an archive inside an archive is listed but not expanded again; the member is
staged on disk under a name this code chooses (index + extension), never the
member's own path, so nothing in a hostile archive has anywhere to traverse to.

Word, PowerPoint and Excel are **not** on the text branch even though text comes
out of them: a .docx is ZIP+XML, a .pptx is slides and a .xlsx is a grid, so
reading any of them needs the format's own library (python-docx / python-pptx /
openpyxl, in ``tools/native_impl``) — and the pictures inside them need OCR and
vision, which is what ``doc_picture`` is for. A document whose content *is* a
screenshot is that branch's whole reason to exist. Spreadsheets ride the same
branch, being the same family — an Office file whose structure needs a library —
and bring their own caps (``XLSX_MAX_SHEETS`` / ``XLSX_MAX_ROWS`` /
``XLSX_MAX_COLS`` in ``tools/native_impl``), because a sheet is unbounded where a
page is not.

``ocr`` and ``describe`` are two edges out of ``read_image``, so LangGraph runs
them in the same superstep (wall time ≈ the slower one, not the sum). They
write different state keys, so no reducer is needed; ``merge`` composes them.

PDFs
----
A PDF is not one format but two: pages that carry a text layer, and pages that
are just a scan. Reading only the text layer means a scanned contract returns
`no extractable text found in PDF` — a whole, common file class the reader used
to fail on. So ``read_pdf`` walks the document (PyMuPDF, already a dependency)
and sorts the pages: a page whose extracted text reaches ``PDF_MIN_PAGE_CHARS``
is text and is kept as is; every other page is image-only and becomes a **map
task** — ``route_pdf_pages`` returns one ``Send("pdf_page", {page: n, …})`` per
such page, so ``pdf_page`` runs them in one superstep and reads each page the
same way ``read_image``/``ocr``/``describe`` read a loose image. ``pdf_compose``
is the reduce: it sorts the blocks by page number (map results arrive in
completion order, not page order), reports what was read and what was skipped,
and applies the character cap.

Budgets keep a 300-page scan from becoming a 300-page API bill: ``PDF_MAX_PAGES``
bounds the probe's walk, ``PDF_MAX_OCR_PAGES`` the number of pages rendered and
OCR'd (local tesseract: free but serial), ``PDF_MAX_VISION_PAGES`` the paid
vision calls, which go to the first image-only pages. The router decides vision
per page *before* fanning out, so no shared counter is needed and the split is
deterministic. Every omitted page is named in the payload, so a partial read is
never silently partial.

Output is page-structured rather than line-numbered: for a PDF the page is the
unit a model can cite (and cannot edit), and six characters of line number per
line is pure token overhead on a long document.

OCR
---
tesseract is asked for ``LANGCONFIG_OCR_LANGS``; unset, the languages are
resolved from the packs actually installed (English, plus Chinese when present),
and the payload names the ones used. This matters more than it sounds: a
Han-character page read with ``eng`` returns Latin nonsense, which is worse than
an empty result because it looks like content.

The compiled graph is a utility graph: **no checkpointer** (it would accumulate
image state per thread — the very failure this module removes) and an in-process
node cache for the vision call, keyed by file content hash.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import mimetypes
import operator
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

logger = logging.getLogger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────────
VISION_MODEL = os.getenv("LANGCONFIG_VISION_MODEL", "deepseek-flash")
OCR_MAX_CHARS = int(os.getenv("LANGCONFIG_OCR_MAX_CHARS", "4000"))
# tesseract languages. Empty = resolve from what is installed (English plus any
# Chinese pack), because the default `eng` renders CJK pages as mojibake.
OCR_LANGS_ENV = os.getenv("LANGCONFIG_OCR_LANGS", "").strip()
DESCRIBE_MAX_TOKENS = int(os.getenv("LANGCONFIG_DESCRIBE_MAX_TOKENS", "400"))
MAX_IMAGE_EDGE = int(os.getenv("LANGCONFIG_MAX_IMAGE_EDGE", "1600"))
PDF_MIN_PAGE_CHARS = int(os.getenv("LANGCONFIG_PDF_MIN_PAGE_CHARS", "12"))
PDF_RENDER_DPI = int(os.getenv("LANGCONFIG_PDF_RENDER_DPI", "150"))
PDF_MAX_PAGES = int(os.getenv("LANGCONFIG_PDF_MAX_PAGES", "200"))
PDF_MAX_OCR_PAGES = int(os.getenv("LANGCONFIG_PDF_MAX_OCR_PAGES", "20"))
PDF_MAX_VISION_PAGES = int(os.getenv("LANGCONFIG_PDF_MAX_VISION_PAGES", "3"))
DOC_MAX_PICTURES = int(os.getenv("LANGCONFIG_DOC_MAX_PICTURES", "10"))
DOC_MAX_VISION_PICTURES = int(os.getenv("LANGCONFIG_DOC_MAX_VISION_PICTURES", "3"))
ARCHIVE_MAX_ENTRIES = int(os.getenv("LANGCONFIG_ARCHIVE_MAX_ENTRIES", "200"))
ARCHIVE_MAX_MEMBERS = int(os.getenv("LANGCONFIG_ARCHIVE_MAX_MEMBERS", "15"))
ARCHIVE_MAX_MEMBER_BYTES = int(os.getenv("LANGCONFIG_ARCHIVE_MAX_MEMBER_BYTES", str(256 * 1024)))
ARCHIVE_MAX_TOTAL_BYTES = int(os.getenv("LANGCONFIG_ARCHIVE_MAX_TOTAL_BYTES", str(2 * 1024 * 1024)))
ARCHIVE_MAX_DEPTH = int(os.getenv("LANGCONFIG_ARCHIVE_MAX_DEPTH", "1"))
TEXT_MAX_CHARS = 500_000          # matches the legacy read_file cap
TEXT_MAX_READ_BYTES = 2 * 1024 * 1024
DESCRIBE_CACHE_SIZE = 128

DESCRIBE_PROMPT = (
    "Describe this image precisely and briefly: what kind of image it is, its "
    "layout, and its main message. Mention any text you can read."
)

# Formats the DeepSeek image API accepts natively, plus ones we convert first.
NATIVE_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
CONVERTIBLE_IMAGE_EXTS = frozenset({".bmp", ".tif", ".tiff"})
IMAGE_EXTS = NATIVE_IMAGE_EXTS | CONVERTIBLE_IMAGE_EXTS

# Binary documents. PDFs are pages; Office documents are ZIP+XML that needs the
# format's own library (python-docx / python-pptx) — which is why they are not
# on the text branch even though what comes out of them is text.
PDF_EXTS = frozenset({".pdf"})
OFFICE_EXTS = frozenset({".docx", ".pptx"})
SHEET_EXTS = frozenset({".xlsx", ".xlsm"})       # read by openpyxl, same branch
DOCUMENT_EXTS = PDF_EXTS | OFFICE_EXTS | SHEET_EXTS

# Containers: an archive has no text of its own, only members.
ARCHIVE_EXTS = frozenset({".zip", ".tar", ".tgz", ".gz", ".tbz2", ".txz"})

# Office formats whose structure needs a library we do not read: they get a
# conversion instruction instead of a generic "binary file" refusal.
LEGACY_OFFICE_EXTS = frozenset({".doc", ".ppt", ".xls", ".odt", ".odp", ".ods"})
OFFICE_ADVICE = {
    ".doc": "legacy Word .doc — save it as .docx and read that",
    ".ppt": "legacy PowerPoint .ppt — save it as .pptx and read that",
    ".xls": "legacy Excel .xls — save it as .xlsx and read that",
    ".ods": "OpenDocument .ods — export the sheet to .csv and read that",
    ".odt": "OpenDocument .odt — save it as .docx and read that",
    ".odp": "OpenDocument .odp — save it as .pptx and read that",
}

# Plain-text formats. Mirrors the extension lists the chat upload path and the
# legacy read_file tool treat as text, so behaviour does not drift between them.
TEXT_EXTS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".csv", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".css", ".scss", ".sql", ".sh", ".bash", ".rb", ".go",
    ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".rtf", ".tex", ".toml",
    ".ini", ".cfg", ".conf", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
})

UNSUPPORTED_HINT = (
    "Text: .txt/.md/.json/.csv/.yaml/.py. "
    "Images: .png/.jpg/.jpeg/.webp/.gif/.bmp/.tiff. "
    "Documents: .pdf/.docx/.pptx/.xlsx. "
    "Archives: .zip/.tar/.tar.gz/.tgz."
)


class FileReadState(TypedDict, total=False):
    """Graph state. Only ``result`` is handed back to the caller/agent."""

    # ── input ──
    file_path: str
    # What to call the file in the payload: a member of an archive is staged
    # under a generated name, and the model should see the member's real one.
    display_name: str
    question: Optional[str]
    vision_enabled: bool
    vision_model: str
    # ── classification ──
    kind: Literal["text", "document", "image", "archive", "binary"]
    branch: str
    ext: str
    mime: str
    name: str
    # ── image path internals ──
    image_b64: str
    image_bytes: int
    image_format: str
    image_dimensions: str
    image_tmp_path: str
    ocr_text: str
    ocr_chars: int
    ocr_available: bool
    description: str
    vision_disabled: bool
    describe_error: str
    describe_tokens: int
    describe_cached: bool
    # ── pdf path internals ──
    # ``read_pdf`` fills the counts and the text blocks; the per-page map tasks
    # (``Send`` → ``pdf_page``) append their own block through ``pdf_page_blocks``,
    # whose reducer is ``operator.add`` because several run in one superstep.
    pdf_pages: int
    pdf_text_pages: int
    pdf_image_pages: int
    pdf_render_pages: List[int]
    pdf_text_blocks: List[Dict[str, Any]]
    pdf_skipped_blocks: List[Dict[str, Any]]
    pdf_page_blocks: Annotated[List[Dict[str, Any]], operator.add]
    pdf_ocr_pages: int
    pdf_vision_pages: int
    pdf_vision_tokens: int
    pdf_vision_budget: int
    # ── document branch internals (Word / PowerPoint) ──
    doc_format: str
    doc_text: str
    doc_pictures: int
    doc_sheets: int
    doc_rows: int
    doc_picture_items: List[Dict[str, Any]]
    doc_skipped_pictures: List[Dict[str, Any]]
    doc_picture_blocks: Annotated[List[Dict[str, Any]], operator.add]
    doc_ocr_pictures: int
    doc_vision_pictures: int
    doc_vision_tokens: int
    doc_vision_budget: int
    read_document_ms: int
    doc_ms: int
    # ── archive branch internals (zip / tar containers) ──
    archive_kind: str
    archive_entries: int
    archive_manifest: List[Dict[str, Any]]
    archive_members: List[Dict[str, Any]]
    archive_skipped: List[Dict[str, Any]]
    archive_run_dir: str
    archive_blocks: Annotated[List[Dict[str, Any]], operator.add]
    archive_read_members: int
    read_archive_ms: int
    archive_ms: int
    member_index: int
    member_arch_index: int
    member_name: str
    member_ext: str
    member_bytes: int
    depth: int
    # ── one map task's payload (``pdf_page`` / ``doc_picture``; never the whole state) ──
    page: int
    item_index: int
    item_label: str
    item_anchor: str
    vision: bool
    vision_reason: str
    # ── output ──
    result: str
    truncated: bool
    error: str
    # per-node durations (distinct keys: the parallel nodes write in one superstep)
    classify_ms: int
    read_ms: int
    read_image_ms: int
    ocr_ms: int
    describe_ms: int
    merge_ms: int
    pdf_ms: int
    read_pdf_ms: int


# ── helpers ──────────────────────────────────────────────────────────────────
_DESCRIBE_CACHE: Dict[str, tuple[str, int]] = {}


def classify(file_name_or_path: str) -> tuple[str, str]:
    """Return ``(kind, ext)`` for a filename — the router's decision only.

    ``kind`` is one of ``text`` / ``document`` / ``image`` / ``binary``.
    """
    ext = Path(file_name_or_path).suffix.lower() or Path(file_name_or_path).name.lower()
    if ext in IMAGE_EXTS:
        return "image", ext
    if ext in DOCUMENT_EXTS or ext in LEGACY_OFFICE_EXTS:
        return "document", ext
    if ext in ARCHIVE_EXTS:
        return "archive", ext
    if ext in TEXT_EXTS:
        return "text", ext
    return "binary", ext


def route_by_kind(state: FileReadState) -> str:
    """Conditional-edge router: ``text`` | ``pdf`` | ``image`` | ``other``."""
    if state.get("error"):
        return "other"
    kind = state.get("kind")
    if kind == "document":
        ext = state.get("ext")
        if ext in PDF_EXTS:
            return "pdf"
        if ext in OFFICE_EXTS or ext in SHEET_EXTS or ext in LEGACY_OFFICE_EXTS:
            return "document"
    if kind in ("text", "document"):
        return "text"
    if kind == "image":
        return "image"
    if kind == "archive":
        return "archive"
    return "other"


def _resolve_path(path_str: str) -> tuple[Optional[Path], Optional[str]]:
    """Resolve *path_str* inside the app sandbox (same policy as other FS tools).

    Imported lazily so the graph can be unit-tested without the app's heavier
    import graph (and so a caller that has already sandboxed the path can pass
    an absolute one).
    """
    try:
        from tools.native_impl import _resolve_sandbox_path

        return _resolve_sandbox_path(path_str)
    except Exception as e:  # pragma: no cover - fallback for standalone use
        logger.warning(f"sandbox resolver unavailable ({e}); using the raw path")
        p = Path(path_str).expanduser()
        return (p.resolve(), None) if p.exists() else (None, f"Error: file '{path_str}' not found")


def _line_number(text: str) -> str:
    """Number lines exactly like the legacy read_file tool.

    ``split("\n")`` (not ``splitlines()``) so a trailing newline still yields a
    final numbered blank line — the two readers must stay byte-identical.
    """
    lines = text.split("\n")
    return "\n".join(f"{i + 1:4d}| {line}" for i, line in enumerate(lines))


# Languages tesseract is asked for, and the packs worth adding by default: a
# Han-character page read with `eng` comes back as Latin nonsense, which is
# worse than an empty result because it looks like content.
_PREFERRED_OCR_LANGS = ("eng", "chi_sim", "chi_tra")
_SPECIAL_TESSDATA = frozenset({"osd", "snum", "equ"})
_OCR_LANGS_CACHE: Optional[str] = None


def _installed_tessdata_langs() -> List[str]:
    """Language packs tesseract can actually load right now."""
    try:
        proc = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                              # tesseract's stderr is not always UTF-8 (leptonica
                              # prints raw bytes), and text=True would raise on it
                              text=True, errors="replace", timeout=20)
    except Exception as e:                                   # pragma: no cover
        logger.warning(f"could not list tesseract languages: {e}")
        return []
    # The first line is the tessdata path, not a language.
    lines = (proc.stdout or "").splitlines()[1:]
    return [l.strip() for l in lines if l.strip() and l.strip() not in _SPECIAL_TESSDATA]


def _resolve_ocr_langs(configured: str, installed: List[str]) -> str:
    """Pick the ``-l`` argument: explicit config wins, else the sane default."""
    if configured:
        return configured
    available = set(installed)
    chosen = [lang for lang in _PREFERRED_OCR_LANGS if lang in available]
    if not chosen:
        chosen = sorted(available)[:1]
    return "+".join(chosen) or "eng"


def ocr_langs() -> str:
    """The language argument for tesseract (resolved once per process)."""
    global _OCR_LANGS_CACHE
    if _OCR_LANGS_CACHE is None:
        _OCR_LANGS_CACHE = _resolve_ocr_langs(OCR_LANGS_ENV, _installed_tessdata_langs())
        logger.info(f"OCR languages: {_OCR_LANGS_CACHE}")
    return _OCR_LANGS_CACHE


def clear_ocr_langs_cache() -> None:
    """Re-resolve on the next call (a pack may have been installed since)."""
    global _OCR_LANGS_CACHE
    _OCR_LANGS_CACHE = None


def _fit_image_bytes(raw: bytes, ext: Optional[str] = None) -> Tuple[bytes, str, str, str]:
    """Decode *raw*; downscale if too large; return ``(raw, mime, format, dims)``.

    Shared by the image branch (which reads a path) and the PDF branch (which
    renders a page), so the size cap and the re-encode rule exist once. Formats
    the image API accepts are passed through untouched unless they need
    shrinking; everything else is converted to PNG.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        fmt = img.format or "PNG"
        dims = f"{img.width}x{img.height}"
        needs_resize = max(img.width, img.height) > MAX_IMAGE_EDGE
        passthrough = fmt in ("PNG", "JPEG", "WEBP", "GIF") and (ext or "").lower() not in CONVERTIBLE_IMAGE_EXTS
        if passthrough and not needs_resize:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg",
                    "WEBP": "image/webp", "GIF": "image/gif"}.get(fmt, "image/png")
            return raw, mime, fmt, dims

        work = img
        if needs_resize:
            scale = MAX_IMAGE_EDGE / max(img.width, img.height)
            work = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        if work.mode not in ("RGB", "L"):
            work = work.convert("RGB")
        buf = io.BytesIO()
        work.save(buf, format="PNG", optimize=True)
        out = buf.getvalue()

    with Image.open(io.BytesIO(out)) as scaled:
        return out, "image/png", "PNG", f"{scaled.width}x{scaled.height}"


def _ocr_file(path: os.PathLike | str) -> Tuple[str, int, bool]:
    """Run tesseract on *path*; return ``(text, chars_full_length, available)``.

    ``chars_full_length`` is the untrimmed length, so a caller can say it only
    showed the first N characters. Local, free, and deterministic — which is why
    the PDF branch spends it on every image-only page it can.
    """
    if shutil.which("tesseract") is None:
        return "", 0, False
    try:
        proc = subprocess.run(["tesseract", str(path), "stdout", "-l", ocr_langs()],
                              capture_output=True, text=True, errors="replace", timeout=60)
        text = (proc.stdout or "").strip()
    except Exception as e:
        logger.warning(f"OCR failed for {path}: {e}")
        text = ""
    return text[:OCR_MAX_CHARS], len(text), True


def _describe_cached(
    image_b64: str, mime: str, question: Optional[str], model: Optional[str]
) -> FileReadState:
    """Cache-aware vision call. Returns the ``describe_*`` state keys."""
    resolved_model = (model or "").strip() or VISION_MODEL
    if not image_b64:
        return {"describe_tokens": 0, "describe_cached": False,
                "describe_error": "no image payload"}
    cache_key = hashlib.sha256(
        f"{resolved_model}|{question or ''}|{image_b64}".encode()
    ).hexdigest()
    hit = _DESCRIBE_CACHE.get(cache_key)
    if hit is not None:
        return {"description": hit[0], "describe_tokens": hit[1], "describe_cached": True}
    try:
        description, tokens = _describe_with_vision(image_b64, mime, question, resolved_model)
    except Exception as e:
        logger.warning(f"vision describe failed: {type(e).__name__}: {e}")
        return {"describe_tokens": 0, "describe_cached": False,
                "describe_error": f"{type(e).__name__}: {e}"}
    if len(_DESCRIBE_CACHE) >= DESCRIBE_CACHE_SIZE:
        _DESCRIBE_CACHE.clear()
    _DESCRIBE_CACHE[cache_key] = (description, tokens)
    return {"description": description, "describe_tokens": tokens, "describe_cached": False}


def _image_block(
    raw: bytes,
    *,
    tag: Any,
    title: str,
    question: Optional[str],
    vision: bool,
    vision_model: Optional[str],
    vision_reason: str,
    vision_budget: int,
    budget_unit: str,
    ocr_empty_note: str = "(no OCR text found in the image)",
) -> Dict[str, Any]:
    """Read one image as text: OCR always, vision when the router granted it.

    Shared by the PDF page task and the document picture task, because a scanned
    PDF page and a screenshot inside a .docx are the same problem — pixels that
    must become text — and two copies of this would drift apart. ``title`` is a
    template carrying ``{dims}``.
    """
    out: Dict[str, Any] = {"ocr": False, "vision": False, "tokens": 0}
    try:
        raw, mime, _, dims = _fit_image_bytes(raw, ".png")
    except Exception as e:
        out["body"] = f"{title.format(dims='?')} — could not be decoded: {type(e).__name__}: {e}"
        return out

    lines = [title.format(dims=dims)]
    used_model = (vision_model or "").strip() or VISION_MODEL

    # vision first: it is the slow half, and the OCR section reads better under it
    if vision:
        described = _describe_cached(base64.b64encode(raw).decode(), mime, question, vision_model)
        out["tokens"] = int(described.get("describe_tokens") or 0)
        if described.get("describe_error"):
            lines.append(f"== Description (vision: {used_model}) ==\n"
                         f"(vision description unavailable: {described['describe_error']})")
        else:
            note = " (cached)" if described.get("describe_cached") else ""
            body = described.get("description") or "(no description returned)"
            lines.append(f"== Description (vision: {used_model}) ==\n{body}{note}")
            out["vision"] = True
    elif vision_reason == "disabled":
        lines.append("== Description ==\n(vision not requested — OCR text only)")
    else:
        lines.append("== Description ==\n(vision skipped — the vision budget covers the "
                     f"first {vision_budget} {budget_unit})")

    ocr_text, ocr_chars, ocr_available = _ocr_bytes(raw, tag)
    if not ocr_available:
        lines.append("== Text in the image (OCR: tesseract) ==\n"
                     "(no OCR available — tesseract binary not installed)")
    elif ocr_text:
        section = ocr_text
        if ocr_chars > len(ocr_text):
            section += (f"\n...(OCR truncated: showing {len(ocr_text)} "
                        f"of {ocr_chars} chars)")
        lines.append(f"== Text in the image (OCR: tesseract, {ocr_langs()}) ==\n{section}")
        out["ocr"] = True
    else:
        lines.append(f"== Text in the image (OCR: tesseract, {ocr_langs()}) ==\n{ocr_empty_note}")

    out["body"] = "\n\n".join(lines)
    return out


def _describe_with_vision(
    image_b64: str, mime: str, question: Optional[str], model: str = VISION_MODEL
) -> tuple[str, int]:
    """Vision node body: image as an image_url block on a USER message.

    Returns ``(description, completion_tokens)``. Raises on failure; the node
    converts that into ``describe_error`` so the graph still returns text.
    """
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    from config import get_api_key_from_db

    api_key = get_api_key_from_db("deepseek_api_key")
    if not api_key:
        raise RuntimeError("no DeepSeek API key configured")

    llm = init_chat_model(
        model=model or VISION_MODEL, model_provider="deepseek", api_key=api_key,
        max_tokens=DESCRIBE_MAX_TOKENS, streaming=False,
        # deepseek-flash defaults to thinking; for a caption the reasoning only
        # eats the answer budget.
        reasoning_effort="none",
    )
    reply = llm.invoke([HumanMessage(content=[
        {"type": "text", "text": question or DESCRIBE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ])])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    usage = (reply.response_metadata or {}).get("token_usage") or {}
    return text.strip(), int(usage.get("completion_tokens") or 0)


# ── nodes ────────────────────────────────────────────────────────────────────
def classify_node(state: FileReadState) -> FileReadState:
    started = time.time()
    path_str = state["file_path"]
    kind, ext = classify(path_str)
    name = state.get("display_name") or Path(path_str).name
    out: FileReadState = {
        "kind": kind,
        "ext": ext,
        "branch": kind,
        "name": name,
        "mime": mimetypes.guess_type(path_str)[0] or "application/octet-stream",
        "classify_ms": int((time.time() - started) * 1000),
    }
    if kind == "binary":
        out["result"] = f"Error: '{name}' is a binary file with no readable text. {UNSUPPORTED_HINT}"
        out["branch"] = "unsupported"
        out["error"] = f"unsupported extension {ext or '(none)'}"
    return out


def read_text_node(state: FileReadState) -> FileReadState:
    """Text / document branch — line-numbered text, same shape as before."""
    started = time.time()
    path_str = state["file_path"]
    path, err = _resolve_path(path_str)
    if err:
        return {"result": err, "error": err, "read_ms": int((time.time() - started) * 1000)}
    if not path.is_file():
        msg = f"Error: File not found: {path_str}"
        return {"result": msg, "error": msg, "read_ms": int((time.time() - started) * 1000)}

    try:
        if state.get("kind") == "document":
            from tools.native_impl import (
                _extract_docx_text, _extract_pdf_text, _extract_pptx_text,
            )

            # ``.pdf`` normally routes to the pdf branch; this stays as the
            # fallback for a direct call to this node.
            ext = state.get("ext")
            if ext == ".pdf":
                content = _extract_pdf_text(path)
            elif ext == ".docx":
                content = _extract_docx_text(path)
            else:
                content = _extract_pptx_text(path)
            truncated = len(content) > TEXT_MAX_CHARS
            if truncated:
                content = content[:TEXT_MAX_CHARS]
        else:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(TEXT_MAX_READ_BYTES + 1)
            truncated = len(content) > TEXT_MAX_READ_BYTES
            if truncated:
                content = content[:TEXT_MAX_READ_BYTES]
            if len(content) > TEXT_MAX_CHARS:
                content = content[:TEXT_MAX_CHARS]
                truncated = True
        body = _line_number(content)
        if len(body) > TEXT_MAX_CHARS:
            body = body[:TEXT_MAX_CHARS] + (
                f"\n\n[Truncated - content exceeds {TEXT_MAX_CHARS} characters]"
            )
            truncated = True
        return {"result": body, "truncated": truncated,
                "read_ms": int((time.time() - started) * 1000)}
    except Exception as e:
        msg = f"Error: could not read '{path_str}': {type(e).__name__}: {e}"
        logger.warning(msg)
        return {"result": msg, "error": msg, "read_ms": int((time.time() - started) * 1000)}


# ── pdf branch ───────────────────────────────────────────────────────────────
def _pdf_error(msg: str, started: float) -> FileReadState:
    """Every PDF failure returns text, never an exception (the tool contract)."""
    logger.warning(msg)
    return {"result": msg, "error": msg, "branch": "pdf",
            "pdf_ms": int((time.time() - started) * 1000)}


def _document_error(msg: str, started: float) -> FileReadState:
    """Every document failure returns text, never an exception."""
    logger.warning(msg)
    return {"result": msg, "error": msg, "branch": "document",
            "read_document_ms": int((time.time() - started) * 1000)}


def _ocr_bytes(raw: bytes, tag: str) -> Tuple[str, int, bool]:
    """OCR an in-memory image: tesseract needs a path, so hand it a temp file."""
    tmpdir = tempfile.mkdtemp(prefix="langconfig-pdf-")
    try:
        tmp = Path(tmpdir) / f"page-{tag}.png"
        tmp.write_bytes(raw)
        return _ocr_file(tmp)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def read_pdf_node(state: FileReadState) -> FileReadState:
    """Walk the PDF once: keep the text layer, name the pages that need rendering.

    This is the map half's planner. It does not render anything — that is the
    per-page task's job — so a 200-page scan costs one cheap text pass here and
    nothing more until the router decides how many pages to read.
    """
    started = time.time()
    path_str = state["file_path"]
    name = state.get("name") or Path(path_str).name
    path, err = _resolve_path(path_str)
    if err:
        return _pdf_error(err, started)
    if not path.is_file():
        return _pdf_error(f"Error: File not found: {path_str}", started)

    try:
        import fitz  # PyMuPDF
    except ImportError:
        # No PyMuPDF: fall back to the legacy text-only extractor rather than
        # refusing the read outright. No page rendering is possible this way.
        from tools.native_impl import _extract_pdf_text

        text = _extract_pdf_text(path)
        if text.startswith("Error:"):
            return _pdf_error(text, started)
        return {"branch": "pdf", "result": _line_number(text),
                "pdf_pages": 0, "pdf_text_pages": 0, "pdf_image_pages": 0,
                "pdf_render_pages": [], "pdf_text_blocks": [], "pdf_skipped_blocks": [],
                "pdf_vision_budget": 0,
                "read_pdf_ms": int((time.time() - started) * 1000)}

    try:
        doc = fitz.open(path)
    except Exception as e:
        return _pdf_error(f"Error: could not open '{name}' as a PDF: "
                          f"{type(e).__name__}: {e}", started)

    try:
        if doc.needs_pass:
            return _pdf_error(f"Error: '{name}' is password-protected — it cannot be "
                              f"read without the password", started)
        total = doc.page_count
        walk = min(total, PDF_MAX_PAGES)
        text_blocks: List[Dict[str, Any]] = []
        render_pages: List[int] = []
        skipped: List[Dict[str, Any]] = []
        for i in range(walk):
            text = (doc.load_page(i).get_text() or "").strip()
            if len(text) >= PDF_MIN_PAGE_CHARS:
                text_blocks.append({"page": i + 1, "body": f"[Page {i + 1}]\n{text}"})
            elif len(render_pages) < PDF_MAX_OCR_PAGES:
                render_pages.append(i + 1)
            else:
                skipped.append({"page": i + 1, "body": (
                    f"[Page {i + 1}] (image-only — not read: OCR is limited to "
                    f"{PDF_MAX_OCR_PAGES} image-only pages per document)")})
    except Exception as e:
        return _pdf_error(f"Error: could not read '{name}': {type(e).__name__}: {e}", started)
    finally:
        doc.close()

    vision_enabled = state.get("vision_enabled", True)
    return {
        "branch": "pdf",
        "pdf_pages": total,
        "pdf_text_pages": len(text_blocks),
        "pdf_image_pages": len(render_pages) + len(skipped),
        "pdf_render_pages": render_pages,
        "pdf_text_blocks": text_blocks,
        "pdf_skipped_blocks": skipped,
        "pdf_vision_budget": PDF_MAX_VISION_PAGES if vision_enabled else 0,
        "read_pdf_ms": int((time.time() - started) * 1000),
    }


def route_pdf_pages(state: FileReadState):
    """Map the image-only pages: one ``Send`` each, or straight to the reduce.

    Vision is granted per page *here* rather than counted inside the tasks, so
    the split is deterministic and the tasks stay pure.
    """
    if state.get("error") or state.get("result"):
        return "pdf_compose"                      # the probe already answered
    pages = state.get("pdf_render_pages") or []
    if not pages:
        return "pdf_compose"

    budget = int(state.get("pdf_vision_budget") or 0)
    sends = []
    for index, page_no in enumerate(pages):
        if index < budget:
            wants_vision, reason = True, "requested"
        elif budget:
            wants_vision, reason = False, "budget"
        else:
            wants_vision, reason = False, "disabled"
        sends.append(Send("pdf_page", {
            "file_path": state["file_path"],
            "name": state.get("name"),
            "question": state.get("question"),
            "vision_enabled": state.get("vision_enabled", True),
            "vision_model": state.get("vision_model"),
            "page": page_no,
            "vision": wants_vision,
            "vision_reason": reason,
        }))
    return sends


def pdf_page_node(state: FileReadState) -> FileReadState:
    """One image-only page: render → OCR → (if granted) vision.

    Runs as a map task, so it receives its ``Send`` payload — not the graph's
    whole state — and returns only its block for the reducer to append.
    """
    started = time.time()
    page_no = int(state["page"])
    out: Dict[str, Any] = {"page": page_no}
    blocked = None
    png = b""

    path, err = _resolve_path(state["file_path"])
    if err or not path.is_file():
        blocked = err or f"Error: File not found: {state['file_path']}"
    else:
        try:
            import fitz

            with fitz.open(path) as doc:
                png = doc.load_page(page_no - 1).get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")
        except Exception as e:
            blocked = f"{type(e).__name__}: {e}"

    if blocked:
        out.update({"ocr": False, "vision": False, "tokens": 0, "ms": int((time.time() - started) * 1000),
                    "body": f"[Page {page_no}] (image-only — could not be read: {blocked})"})
        return {"pdf_page_blocks": [out]}

    out.update(_image_block(
        png,
        tag=page_no,
        title=f"[Page {page_no}] (image-only — rendered at {PDF_RENDER_DPI} dpi, {{dims}})",
        question=state.get("question"),
        vision=bool(state.get("vision")),
        vision_model=state.get("vision_model"),
        vision_reason=state.get("vision_reason") or "",
        vision_budget=PDF_MAX_VISION_PAGES,
        budget_unit="image-only page(s)",
        ocr_empty_note="(no OCR text found in the page)",
    ))
    out["ms"] = int((time.time() - started) * 1000)
    return {"pdf_page_blocks": [out]}


def pdf_compose_node(state: FileReadState) -> FileReadState:
    """Reduce: page order, the header, the counts, and the character cap."""
    started = time.time()
    if state.get("error") or state.get("result"):
        return {}                                  # the probe already answered

    text_blocks = list(state.get("pdf_text_blocks") or [])
    page_blocks = list(state.get("pdf_page_blocks") or [])
    skipped = list(state.get("pdf_skipped_blocks") or [])
    # Map tasks finish in completion order; a reader must see page order.
    blocks = sorted(text_blocks + page_blocks + skipped, key=lambda b: b.get("page") or 0)

    total = int(state.get("pdf_pages") or 0)
    text_pages = int(state.get("pdf_text_pages") or 0)
    image_pages = int(state.get("pdf_image_pages") or 0)
    read_pages = len(page_blocks)
    ocr_pages = sum(1 for b in page_blocks if b.get("ocr"))
    vision_pages = sum(1 for b in page_blocks if b.get("vision"))
    tokens = sum(int(b.get("tokens") or 0) for b in page_blocks)
    budget = int(state.get("pdf_vision_budget") or 0)
    vision_enabled = state.get("vision_enabled", True)
    used_model = (state.get("vision_model") or "").strip() or VISION_MODEL

    if text_pages == 0 and ocr_pages == 0 and vision_pages == 0:
        # Nothing at all came back from the document: say so as an error rather
        # than hand the model a payload of empty sections. (A blank page that
        # vision *did* describe is content — "an empty scan" — so not this case.)
        has_tesseract = shutil.which("tesseract") is not None
        msg = (f"Error: no readable text in '{state.get('name')}' — {total} page(s), "
               f"{image_pages} of them image-only with no OCR text"
               + ("" if has_tesseract else " (tesseract is not installed)")
               + ("" if vision_enabled else " (vision was not requested)"))
        return {"result": msg, "error": msg, "branch": "pdf",
                "pdf_ms": int((time.time() - started) * 1000)}

    header = [
        "== PDF ==",
        f"name: {state.get('name')}  pages: {total}  "
        f"text pages: {text_pages}  image-only pages: {image_pages}",
        f"read: {text_pages} text + {read_pages} image-only "
        f"(OCR {ocr_pages}, vision {vision_pages})",
        f"mode: {'ocr-only' if not vision_enabled else f'vision+ocr ({used_model})'}  "
        f"render: {PDF_RENDER_DPI} dpi",
    ]
    question = (state.get("question") or "").strip()
    if question:
        header.append(f"question: {question}")
    if total > PDF_MAX_PAGES:
        header.append(f"note: only the first {PDF_MAX_PAGES} of {total} pages were examined")
    if image_pages > PDF_MAX_OCR_PAGES:
        header.append(f"note: OCR is limited to {PDF_MAX_OCR_PAGES} image-only pages "
                      f"per document")
    if vision_enabled and image_pages > budget:
        header.append(f"note: vision is limited to the first {budget or PDF_MAX_VISION_PAGES} "
                      f"image-only page(s); the rest are OCR only")

    body = "\n".join(header) + "\n\n" + "\n\n".join(b.get("body") or "" for b in blocks)
    truncated = False
    if len(body) > TEXT_MAX_CHARS:
        body = body[:TEXT_MAX_CHARS] + (
            f"\n\n[Truncated - content exceeds {TEXT_MAX_CHARS} characters]")
        truncated = True

    # The map tasks run in one superstep, so the branch's wall time is the
    # probe plus the slowest page plus this reduce — not the sum of the pages.
    page_ms = max((int(b.get("ms") or 0) for b in page_blocks), default=0)
    return {"result": body, "branch": "pdf", "truncated": truncated,
            "pdf_ocr_pages": ocr_pages, "pdf_vision_pages": vision_pages,
            "pdf_vision_tokens": tokens,
            "pdf_ms": int(state.get("read_pdf_ms") or 0) + page_ms
                      + int((time.time() - started) * 1000)}


def read_document_node(state: FileReadState) -> FileReadState:
    """Word/PowerPoint: their own library for structure, an inventory of pictures.

    A .docx is ZIP+XML and a .pptx is slides — neither is text, so neither is
    read as text. The structure comes from python-docx / python-pptx (headings,
    lists, tables, slide notes) and the pictures, which have no text at all, are
    listed here and read by the map task.
    """
    started = time.time()
    path_str = state["file_path"]
    name = state.get("name") or Path(path_str).name
    ext = state.get("ext") or ""
    path, err = _resolve_path(path_str)
    if err:
        return _document_error(err, started)
    if not path.is_file():
        return _document_error(f"Error: File not found: {path_str}", started)
    if ext not in OFFICE_EXTS and ext not in SHEET_EXTS:
        advice = OFFICE_ADVICE.get(ext)
        msg = (f"Error: cannot read '{name}'. {advice}" if advice else
               f"Error: '{name}' is not a Word (.docx), PowerPoint (.pptx) or Excel "
               f"(.xlsx) file")
        return _document_error(msg, started)

    from tools.native_impl import _extract_docx, _extract_pptx, _extract_xlsx

    try:
        if ext in SHEET_EXTS:
            text, pictures = _extract_xlsx(path)
        elif ext == ".docx":
            text, pictures = _extract_docx(path)
        else:
            text, pictures = _extract_pptx(path)
    except ImportError as e:
        package = {"xlsx": "openpyxl", "docx": "python-docx"}.get(ext.lstrip("."), "python-pptx")
        return _document_error(f"Error: {package} is not installed ({e})", started)
    except Exception as e:
        return _document_error(f"Error: could not read '{name}': {type(e).__name__}: {e}",
                               started)

    items = [{"index": p["index"], "label": p["label"], "anchor": p["anchor"],
              "ext": p.get("ext"), "bytes": p.get("bytes")} for p in pictures[:DOC_MAX_PICTURES]]
    skipped = [p for p in pictures[DOC_MAX_PICTURES:]]
    vision_enabled = state.get("vision_enabled", True)
    rows = sum(1 for line in text.splitlines() if "|" in line) if ext in SHEET_EXTS else 0
    sheets = text.count("[Sheet: ") if ext in SHEET_EXTS else 0
    return {
        "branch": "document",
        "doc_format": ext.lstrip(".").upper(),
        "doc_sheets": sheets,
        "doc_rows": rows,
        "doc_text": text,
        "doc_picture_items": items,
        "doc_skipped_pictures": [{"label": p["label"], "anchor": p["anchor"]} for p in skipped],
        "doc_pictures": len(pictures),
        "doc_vision_budget": DOC_MAX_VISION_PICTURES if vision_enabled else 0,
        "read_document_ms": int((time.time() - started) * 1000),
    }


def route_document_pictures(state: FileReadState):
    """Map the embedded pictures: one ``Send`` each, or straight to the reduce."""
    if state.get("error") or state.get("result"):
        return "doc_compose"
    items = state.get("doc_picture_items") or []
    if not items:
        return "doc_compose"

    budget = int(state.get("doc_vision_budget") or 0)
    sends = []
    for position, item in enumerate(items):
        if position < budget:
            wants_vision, reason = True, "requested"
        elif budget:
            wants_vision, reason = False, "budget"
        else:
            wants_vision, reason = False, "disabled"
        sends.append(Send("doc_picture", {
            "file_path": state["file_path"],
            "ext": state.get("ext"),
            "question": state.get("question"),
            "vision_enabled": state.get("vision_enabled", True),
            "vision_model": state.get("vision_model"),
            "item_index": item["index"],
            "item_label": item["label"],
            "item_anchor": item.get("anchor") or "",
            "vision": wants_vision,
            "vision_reason": reason,
        }))
    return sends


def doc_picture_node(state: FileReadState) -> FileReadState:
    """One embedded picture: extract its bytes → OCR → (if granted) vision.

    A map task too, so it takes its ``Send`` payload and returns only its block.
    The bytes are re-extracted by index from the document (the probe kept only
    labels, so no picture bytes ever sit in the graph state).
    """
    started = time.time()
    index = int(state["item_index"])
    label = state.get("item_label") or f"[Picture {index + 1}]"
    anchor = state.get("item_anchor") or ""
    where = f" — {anchor}" if anchor else ""
    out: Dict[str, Any] = {"index": index}

    blob = None
    blocked = None
    path, err = _resolve_path(state["file_path"])
    if err or not path.is_file():
        blocked = err or f"Error: File not found: {state['file_path']}"
    else:
        try:
            from tools.native_impl import _docx_pictures, _pptx_pictures

            pictures = (_docx_pictures(path) if state.get("ext") == ".docx"
                        else _pptx_pictures(path))
            blob = pictures[index].get("blob") if index < len(pictures) else None
            if not blob:
                blocked = f"picture {index + 1} is no longer in the document"
        except Exception as e:
            blocked = f"{type(e).__name__}: {e}"

    if blocked or not blob:
        out.update({"ocr": False, "vision": False, "tokens": 0, "ms": int((time.time() - started) * 1000),
                    "body": f"{label}{where} — could not be read: {blocked or 'no bytes'}"})
        return {"doc_picture_blocks": [out]}

    out.update(_image_block(
        blob,
        tag=index,
        title=f"{label}{where} (embedded picture, {{dims}})",
        question=state.get("question"),
        vision=bool(state.get("vision")),
        vision_model=state.get("vision_model"),
        vision_reason=state.get("vision_reason") or "",
        vision_budget=DOC_MAX_VISION_PICTURES,
        budget_unit="embedded picture(s)",
        ocr_empty_note="(no OCR text found in the picture)",
    ))
    out["ms"] = int((time.time() - started) * 1000)
    return {"doc_picture_blocks": [out]}


def doc_compose_node(state: FileReadState) -> FileReadState:
    """Reduce: the header, the structure, the picture blocks, and the cap."""
    started = time.time()
    if state.get("error") or state.get("result"):
        return {}                                  # the probe already answered

    text = (state.get("doc_text") or "").strip()
    picture_blocks = list(state.get("doc_picture_blocks") or [])
    skipped = list(state.get("doc_skipped_pictures") or [])
    name = state.get("name")
    total_pictures = int(state.get("doc_pictures") or 0)
    budget = int(state.get("doc_vision_budget") or 0)
    vision_enabled = state.get("vision_enabled", True)
    used_model = (state.get("vision_model") or "").strip() or VISION_MODEL

    read_pictures = len(picture_blocks)
    ocr_pictures = sum(1 for b in picture_blocks if b.get("ocr"))
    vision_pictures = sum(1 for b in picture_blocks if b.get("vision"))
    tokens = sum(int(b.get("tokens") or 0) for b in picture_blocks)

    if not text and read_pictures == 0:
        msg = (f"Error: no readable content in '{name}' — no text and "
               f"{total_pictures} picture(s) could not be read")
        return {"result": msg, "error": msg, "branch": "document",
                "doc_ms": int((time.time() - started) * 1000)}

    spreadsheet = str(state.get("doc_format") or "").lower() in ("xlsx", "xlsm")
    if spreadsheet:
        header = [
            "== Spreadsheet ==",
            f"name: {name}  format: {state.get('doc_format')}  "
            f"sheets: {state.get('doc_sheets')}  rows: {state.get('doc_rows')}",
            "read: cell values sheet by sheet (a formula shows as its result when the "
            "file carries one, else as the formula)",
        ]
    else:
        header = [
            "== Document ==",
            f"name: {name}  format: {state.get('doc_format')}  "
            f"pictures: {total_pictures}",
            f"read: {len(text.splitlines())} line(s) of text + {read_pictures} picture(s) "
            f"(OCR {ocr_pictures}, vision {vision_pictures})",
            f"mode: {'ocr-only' if not vision_enabled else f'vision+ocr ({used_model})'}",
        ]
    question = (state.get("question") or "").strip()
    if question:
        header.append(f"question: {question}")
    if total_pictures > DOC_MAX_PICTURES:
        header.append(f"note: only the first {DOC_MAX_PICTURES} of {total_pictures} "
                      f"picture(s) were read")
    if vision_enabled and total_pictures > budget:
        header.append(f"note: vision is limited to the first "
                      f"{budget or DOC_MAX_VISION_PICTURES} picture(s); the rest are OCR only")

    parts = ["\n".join(header)]
    if text:
        parts.append(text)
    parts.extend(b.get("body") or "" for b in sorted(picture_blocks, key=lambda b: b.get("index") or 0))
    for picture in skipped:
        parts.append(f"{picture.get('label')} — {picture.get('anchor')} "
                     f"(not read: pictures are limited to {DOC_MAX_PICTURES} per document)")

    body = "\n\n".join(p for p in parts if p)
    truncated = False
    if len(body) > TEXT_MAX_CHARS:
        body = body[:TEXT_MAX_CHARS] + (
            f"\n\n[Truncated - content exceeds {TEXT_MAX_CHARS} characters]")
        truncated = True

    return {"result": body, "branch": "document", "truncated": truncated,
            "doc_ocr_pictures": ocr_pictures, "doc_vision_pictures": vision_pictures,
            "doc_vision_tokens": tokens,
            "doc_ms": int((time.time() - started) * 1000)}


# ── archive branch ───────────────────────────────────────────────────────────
def _human_size(size: int) -> str:
    """A size a reader can act on: ``19 B``, ``35.8 KiB``, ``1.4 MiB``."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _decode_archive_name(name: str) -> str:
    """Repair a member name that arrived as CP437 mojibake.

    zipfile decodes names as CP437 unless the archive sets the UTF-8 flag, and
    many tools (macOS ``zip`` among them) do not — so ``价格表.csv`` arrives as
    ``Σ╗╖µá╝Φí¿.csv``. Re-encoding through CP437 and decoding as UTF-8/GBK/Big5
    recovers it; anything that does not decode is left exactly as zipfile gave it.
    """
    if name.isascii():
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for codec in ("utf-8", "gbk", "big5"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return name


def _archive_open(path: Path):
    """``(kind, entries, reader)`` for a zip or tar container.

    ``entries`` are plain dicts — name, size, compressed, date, dir — so the zip
    and tar paths share everything downstream. Member bytes are never read here.
    """
    import tarfile
    import zipfile

    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        entries = [{
            "name": _decode_archive_name(info.filename),
            "raw": info.filename,          # the archive's own key; may be mojibake
            "size": info.file_size,
            "compressed": info.compress_size,
            "date": "-".join(str(part).zfill(2) for part in info.date_time[:3]),
            "dir": info.is_dir(),
            "encrypted": bool(info.flag_bits & 0x1),
        } for info in archive.infolist()]
        return "zip", entries, archive

    try:
        archive = tarfile.open(path, "r:*")       # .tar, .tar.gz, .tgz, .tar.bz2, .tar.xz
    except tarfile.ReadError:
        # Only a bare .gz can be a non-tar: for any other extension this means
        # "not a zip and not a tar", which the caller reports as unreadable.
        if path.suffix.lower() != ".gz":
            raise
        # A bare .gz is one compressed file rather than a container; it still has
        # a member — the file itself — so treat it as a one-entry archive.
        return "gz", [{"name": path.name[:-3] or path.name, "raw": path.name,
                       "size": 0, "compressed": 0,
                       "date": "-".join(str(part).zfill(2)
                                        for part in time.gmtime(path.stat().st_mtime)[:3]),
                       "dir": False, "encrypted": False}], None
    entries = [{
        "name": _decode_archive_name(member.name),
        "raw": member.name,
        "size": member.size,
        "compressed": member.size,
        "date": "-".join(str(part).zfill(2) for part in
                         (time.gmtime(member.mtime)[:3] if member.mtime else (0, 0, 0))),
        "dir": member.isdir(),
        "encrypted": False,
    } for member in archive.getmembers()]
    return "tar", entries, archive


def _archive_read_member(archive, kind: str, name: str, limit: int) -> bytes:
    """Read one member's bytes into memory, refusing to exceed *limit*.

    Nothing is ever written for this call, so a hostile member name (``../``)
    has nothing to escape into: the name is only ever a lookup key.
    """
    if kind == "gz":
        import gzip

        with gzip.open(archive or name, "rb") as handle:      # ``name`` is the path here
            return handle.read(limit + 1)[:limit]
    if kind == "zip":
        with archive.open(name) as handle:
            data = handle.read(limit + 1)
    else:
        handle = archive.extractfile(name)
        if handle is None:
            return b""
        with handle:
            data = handle.read(limit + 1)
    return data[:limit]


def _archive_error(msg: str, started: float) -> FileReadState:
    """Every archive failure returns text, never an exception."""
    logger.warning(msg)
    return {"result": msg, "error": msg, "branch": "archive",
            "read_archive_ms": int((time.time() - started) * 1000)}


def read_archive_node(state: FileReadState) -> FileReadState:
    """List the container, then choose which members are worth reading.

    A .zip or .tar has no text of its own — it is a container — so the branch
    answers two questions: what is in here, and what of it can be read. Members
    whose own extension the reader understands (text, image, PDF, Word,
    PowerPoint, Excel) become map tasks and go back through this same reader, so
    there is no second implementation of any format.
    """
    started = time.time()
    path_str = state["file_path"]
    name = state.get("name") or Path(path_str).name
    depth = int(state.get("depth") or 0)
    path, err = _resolve_path(path_str)
    if err:
        return _archive_error(err, started)
    if not path.is_file():
        return _archive_error(f"Error: File not found: {path_str}", started)

    try:
        kind, entries, archive = _archive_open(path)
    except Exception as e:
        return _archive_error(f"Error: could not open '{name}' as an archive: "
                              f"{type(e).__name__}: {e}", started)

    try:
        if kind == "zip" and entries and all(entry["encrypted"] for entry in entries):
            return _archive_error(f"Error: '{name}' is encrypted — it cannot be read "
                                  f"without the password", started)

        files = [entry for entry in entries if not entry["dir"]]
        members, skipped = [], []
        budget = ARCHIVE_MAX_TOTAL_BYTES
        expanded = depth < ARCHIVE_MAX_DEPTH
        for entry in files:
            reason = None
            member_kind, member_ext = classify(entry["name"])
            if len(members) >= ARCHIVE_MAX_MEMBERS:
                reason = f"only the first {ARCHIVE_MAX_MEMBERS} members are read"
            elif entry["encrypted"]:
                reason = "encrypted — needs a password"
            elif member_kind == "binary":
                reason = "no readable format for this extension"
            elif member_kind == "archive" and not expanded:
                reason = ("nested archive — listed only, an archive inside an archive "
                          "is not expanded")
            elif entry["size"] > ARCHIVE_MAX_MEMBER_BYTES:
                reason = (f"declared size {_human_size(entry['size'])} exceeds the "
                          f"{_human_size(ARCHIVE_MAX_MEMBER_BYTES)} per-member cap")
            elif entry["size"] > budget:
                reason = (f"the remaining {_human_size(budget)} of the "
                          f"{_human_size(ARCHIVE_MAX_TOTAL_BYTES)} total cap is too small")
            if reason:
                skipped.append({"name": entry["name"], "reason": reason})
                continue
            budget -= entry["size"]
            members.append({"index": len(members), "name": entry["name"],
                            "arch_index": entries.index(entry),
                            "ext": member_ext, "size": entry["size"]})
    finally:
        if archive is not None:
            archive.close()

    run_dir = ""
    if members:
        # Members are staged under a name of OUR choosing, never the archive's:
        # index + sanitised extension, so no member name can traverse anywhere.
        run_dir = str(path.parent / f".archive_{uuid.uuid4().hex[:8]}")
        Path(run_dir).mkdir(parents=True, exist_ok=True)

    return {
        "branch": "archive",
        "archive_kind": kind.upper(),
        "archive_entries": len(entries),
        "archive_manifest": entries[:ARCHIVE_MAX_ENTRIES],
        "archive_members": members,
        "archive_skipped": skipped,
        "archive_run_dir": run_dir,
        "depth": depth,
        "read_archive_ms": int((time.time() - started) * 1000),
    }


def route_archive_members(state: FileReadState):
    """Map the readable members: one ``Send`` each, or straight to the reduce."""
    if state.get("error") or state.get("result"):
        return "archive_compose"
    members = state.get("archive_members") or []
    if not members:
        return "archive_compose"
    return [Send("archive_member", {
        "file_path": state["file_path"],
        "name": state.get("name"),
        "question": state.get("question"),
        "vision_enabled": state.get("vision_enabled", True),
        "vision_model": state.get("vision_model"),
        "member_index": member["index"],
        "member_arch_index": member["arch_index"],
        "member_name": member["name"],
        "member_ext": member["ext"],
        "member_bytes": member["size"],
        "archive_run_dir": state.get("archive_run_dir") or "",
        "depth": int(state.get("depth") or 0) + 1,
    }) for member in members]


async def archive_member_node(state: FileReadState) -> FileReadState:
    """One member: read its bytes, stage it, and read it with this same reader.

    The staging file is named after the member's *index*, not its path, so the
    classic archive traversal (``../../etc/passwd``) has nothing to traverse; and
    the staged file is read by the ordinary branches — a .csv member through the
    text branch, a .docx member through the document branch — which is why an
    archive needs no format code of its own.
    """
    started = time.time()
    index = int(state["member_index"])
    member_name = state.get("member_name") or f"member {index}"
    out: Dict[str, Any] = {"index": index, "name": member_name, "chars": 0}
    run_dir = state.get("archive_run_dir") or ""

    path, err = _resolve_path(state["file_path"])
    if err or not path.is_file():
        out["body"] = f"--- {member_name} ---\n(could not be read: {err or 'archive not found'})"
        return {"archive_blocks": [out]}

    try:
        kind, entries, archive = _archive_open(path)
        try:
            position = int(state.get("member_arch_index") or 0)
            raw_name = entries[position]["raw"] if position < len(entries) else state["member_name"]
            data = _archive_read_member(archive if kind != "gz" else str(path),
                                       kind, raw_name, ARCHIVE_MAX_MEMBER_BYTES)
        finally:
            if archive is not None:
                archive.close()
    except Exception as e:
        out["body"] = (f"--- {member_name} ---\n"
                       f"(could not be read: {type(e).__name__}: {e})")
        return {"archive_blocks": [out]}

    # The member's real name is in the archive; on disk it is index + extension.
    safe_ext = "".join(ch for ch in (state.get("member_ext") or "") if ch.isalnum())[:8]
    staged = Path(run_dir) / f"member_{index:03d}.{safe_ext or 'bin'}"
    try:
        staged.write_bytes(data)
        body = await read_file_as_text(
            str(staged),
            question=state.get("question"),
            vision_enabled=state.get("vision_enabled", True),
            vision_model=state.get("vision_model"),
            depth=int(state.get("depth") or 1),
            display_name=member_name,
        )
    except Exception as e:
        body = f"(could not be read: {type(e).__name__}: {e})"
    finally:
        staged.unlink(missing_ok=True)

    out["body"] = f"--- {member_name} ---\n{body}"
    out["chars"] = len(body)
    out["ms"] = int((time.time() - started) * 1000)
    return {"archive_blocks": [out]}


def archive_compose_node(state: FileReadState) -> FileReadState:
    """Reduce: the manifest, the members read, what was skipped, and the cap."""
    started = time.time()
    run_dir = state.get("archive_run_dir") or ""
    try:
        if state.get("error") or state.get("result"):
            return {}
        blocks = sorted(state.get("archive_blocks") or [], key=lambda b: b.get("index") or 0)
        members = state.get("archive_members") or []
        skipped = state.get("archive_skipped") or []
        entries = state.get("archive_manifest") or []
        total = int(state.get("archive_entries") or 0)
        name = state.get("name")

        manifest = [f"  {entry['name']}"
                    f"{'/' if entry['dir'] and not entry['name'].endswith('/') else ''}  "
                    f"{_human_size(entry['size'])}  {entry['date']}"
                    + ("  [encrypted]" if entry.get("encrypted") else "")
                    for entry in entries]
        if total > len(entries):
            manifest.append(f"  ... ({total - len(entries)} more entries not listed)")

        header = [
            "== Archive ==",
            f"name: {name}  kind: {state.get('archive_kind')}  entries: {total}  "
            f"read: {len(blocks)} member(s)",
        ]
        question = (state.get("question") or "").strip()
        if question:
            header.append(f"question: {question}")
        parts = ["\n".join(header), "manifest:\n" + "\n".join(manifest) if manifest else "manifest: (empty)"]
        parts.extend(block.get("body") or "" for block in blocks)
        if skipped:
            parts.append("not read:\n" + "\n".join(
                f"  {item['name']} — {item['reason']}" for item in skipped))

        if not blocks:
            if not any(not entry["dir"] for entry in entries):
                msg = f"Error: '{name}' is empty — {total} entr(y/ies), no files to read"
                return {"result": msg, "error": msg, "branch": "archive",
                        "archive_ms": int((time.time() - started) * 1000)}
            # Entries exist but none could be read: the manifest is still the most
            # useful answer, so keep it and name the reason for each member.
            parts.append(f"nothing above could be read — {len(skipped)} member(s) skipped, "
                         f"each with its reason")

        body = "\n\n".join(parts)
        truncated = False
        if len(body) > TEXT_MAX_CHARS:
            body = body[:TEXT_MAX_CHARS] + (
                f"\n\n[Truncated - content exceeds {TEXT_MAX_CHARS} characters]")
            truncated = True
        return {"result": body, "branch": "archive", "truncated": truncated,
                "archive_read_members": len(blocks),
                "archive_ms": int((time.time() - started) * 1000)}
    finally:
        if run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)      # nothing staged survives a read


def read_image_node(state: FileReadState) -> FileReadState:
    """Decode → (convert BMP/TIFF → PNG) → cap the longest edge → re-encode."""
    started = time.time()
    path_str = state["file_path"]
    path, err = _resolve_path(path_str)
    if err:
        return {"result": err, "error": err, "read_ms": int((time.time() - started) * 1000)}
    if not path.is_file():
        msg = f"Error: File not found: {path_str}"
        return {"result": msg, "error": msg, "read_ms": int((time.time() - started) * 1000)}

    try:
        raw, mime, fmt, dims = _fit_image_bytes(path.read_bytes(), state.get("ext"))
    except Exception as e:
        msg = f"Error: '{path_str}' is not a readable image: {e}"
        logger.warning(msg)
        return {"result": msg, "error": msg, "read_image_ms": int((time.time() - started) * 1000)}

    return {
        "read_image_ms": int((time.time() - started) * 1000),
        "image_b64": base64.b64encode(raw).decode(),
        "image_bytes": len(raw),
        "image_format": fmt,
        "image_dimensions": dims,
        "mime": mime,
        "image_tmp_path": str(path),
    }


def ocr_node(state: FileReadState) -> FileReadState:
    """Local tesseract pass — free, exact characters, no API call."""
    started = time.time()
    if state.get("image_tmp_path") is None and state.get("error"):
        return state
    tmp_path = state.get("image_tmp_path") or state["file_path"]
    text, chars, available = _ocr_file(tmp_path)
    return {"ocr_text": text, "ocr_chars": chars, "ocr_available": available,
            "ocr_ms": int((time.time() - started) * 1000)}


def describe_node(state: FileReadState) -> FileReadState:
    """Vision pass — the image rides a USER message (the only wire that works)."""
    started = time.time()
    if not state.get("vision_enabled", True):
        # Caller asked for OCR only — not a failure, so it is reported as such.
        return {"describe_tokens": 0, "describe_cached": False,
                "vision_disabled": True, "describe_ms": int((time.time() - started) * 1000)}
    out = _describe_cached(state.get("image_b64") or "", state.get("mime") or "image/png",
                           state.get("question"), state.get("vision_model"))
    out["describe_ms"] = int((time.time() - started) * 1000)
    return out


def merge_node(state: FileReadState) -> FileReadState:
    """Compose the text payload handed back to the agent."""
    started = time.time()
    if state.get("error"):
        return {}

    question = (state.get("question") or "").strip()
    asked = f"question: {question}\n" if question else ""
    used_model = (state.get("vision_model") or "").strip() or VISION_MODEL
    mode = "ocr-only" if state.get("vision_disabled") else f"vision+ocr ({used_model})"
    header = (
        f"== Image ==\n"
        f"name: {state.get('name')}\n"
        f"mode: {mode}\n"
        f"{asked}"
        f"format: {state.get('image_format')}  dimensions: {state.get('image_dimensions')}  "
        f"size: {(state.get('image_bytes') or 0) / 1024:.0f} KiB"
    )
    if state.get("vision_disabled"):
        vision = "(vision not requested — OCR text only)"
    elif state.get("describe_error"):
        vision = f"(vision description unavailable: {state['describe_error']})"
    else:
        note = " (cached)" if state.get("describe_cached") else ""
        vision = state.get("description") or "(no description returned)"
        vision = f"{vision}{note}" if note else vision

    ocr_text = state.get("ocr_text") or ""
    if not ocr_text and state.get("ocr_available") is False:
        ocr_section = "(no OCR available — tesseract binary not installed)"
    elif ocr_text:
        ocr_section = ocr_text
        if (state.get("ocr_chars") or 0) > len(ocr_text):
            ocr_section += f"\n...(OCR truncated: showing {len(ocr_text)} of {state['ocr_chars']} chars)"
    else:
        ocr_section = "(no OCR text found in image)"

    payload = (
        f"{header}\n\n"
        # ``used_model``, not the module default: an agent that pinned its own
        # vision model must not see two different model names in one payload.
        f"== Description (vision: {used_model}) ==\n{vision}\n\n"
        f"== Text in the image (OCR: tesseract, {ocr_langs()}) ==\n{ocr_section}"
    )
    return {"result": payload, "branch": "image",
            "merge_ms": int((time.time() - started) * 1000)}


def unsupported_node(state: FileReadState) -> FileReadState:
    if not state.get("result"):
        name = state.get("name") or Path(state.get("file_path", "")).name
        return {"result": f"Error: cannot read '{name}'. {UNSUPPORTED_HINT}",
                "branch": "unsupported"}
    return {}


# ── graph ────────────────────────────────────────────────────────────────────
def build_file_reader_graph():
    """Compile the reader graph (utility graph: no checkpointer)."""
    builder = StateGraph(FileReadState)
    builder.add_node("classify", classify_node)
    builder.add_node("read_text", read_text_node)
    builder.add_node("read_pdf", read_pdf_node)
    builder.add_node("pdf_page", pdf_page_node)
    builder.add_node("pdf_compose", pdf_compose_node)
    builder.add_node("read_document", read_document_node)
    builder.add_node("doc_picture", doc_picture_node)
    builder.add_node("doc_compose", doc_compose_node)
    builder.add_node("read_archive", read_archive_node)
    builder.add_node("archive_member", archive_member_node)
    builder.add_node("archive_compose", archive_compose_node)
    builder.add_node("read_image", read_image_node)
    builder.add_node("ocr", ocr_node)
    builder.add_node("describe", describe_node)
    builder.add_node("merge", merge_node)
    builder.add_node("unsupported", unsupported_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_by_kind, {
        "text": "read_text",
        "pdf": "read_pdf",
        "document": "read_document",
        "archive": "read_archive",
        "image": "read_image",
        "other": "unsupported",
    })
    # PDF: the probe's router maps one task per image-only page (``Send``), and
    # ``pdf_compose`` reduces once every task in the superstep has landed.
    builder.add_conditional_edges("read_pdf", route_pdf_pages, {
        "pdf_page": "pdf_page",
        "pdf_compose": "pdf_compose",
    })
    builder.add_edge("pdf_page", "pdf_compose")
    builder.add_edge("pdf_compose", END)
    # Documents: same shape as PDF — probe, one task per embedded picture, reduce.
    builder.add_conditional_edges("read_document", route_document_pictures, {
        "doc_picture": "doc_picture",
        "doc_compose": "doc_compose",
    })
    builder.add_edge("doc_picture", "doc_compose")
    builder.add_edge("doc_compose", END)
    # Archives: list the container, then read its readable members by recursing
    # into this same reader — no format code of its own.
    builder.add_conditional_edges("read_archive", route_archive_members, {
        "archive_member": "archive_member",
        "archive_compose": "archive_compose",
    })
    builder.add_edge("archive_member", "archive_compose")
    builder.add_edge("archive_compose", END)
    # Fan-out: both nodes run in one superstep; they write different keys.
    builder.add_edge("read_image", "ocr")
    builder.add_edge("read_image", "describe")
    builder.add_edge("ocr", "merge")
    builder.add_edge("describe", "merge")
    builder.add_edge("read_text", END)
    builder.add_edge("merge", END)
    builder.add_edge("unsupported", END)

    try:
        from langgraph.cache.memory import InMemoryCache

        return builder.compile(cache=InMemoryCache())
    except Exception:  # pragma: no cover - cache backend optional
        return builder.compile()


_GRAPH = None


def get_file_reader_graph():
    """Process-wide compiled graph (built lazily)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_file_reader_graph()
    return _GRAPH


async def read_file_as_text(
    file_path: str,
    question: Optional[str] = None,
    vision_enabled: bool = True,
    vision_model: Optional[str] = None,
    depth: int = 0,
    display_name: Optional[str] = None,
) -> str:
    """Run the graph and return only the text result (the tool contract).

    ``vision_model`` overrides ``LANGCONFIG_VISION_MODEL`` for this call, so an
    agent can pin the model its reader uses (``tool_params``). ``depth`` counts
    archive expansions: a member is read by this same function with ``depth+1``,
    so an archive nested in an archive is listed but not expanded again.
    """
    state = await get_file_reader_graph().ainvoke(
        {"file_path": file_path, "display_name": display_name or "", "question": question,
         "vision_enabled": vision_enabled, "vision_model": vision_model or "", "depth": depth},
        config={"recursion_limit": 16},
    )
    return state.get("result") or "Error: reader produced no output"


def clear_describe_cache() -> None:
    _DESCRIBE_CACHE.clear()


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli(argv: Optional[list] = None) -> int:
    """Run the graph on one path and print the TEXT result.

    Mostly a testing/debugging entry point: same code path the tool will use.
    """
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser(
        prog="read_file",
        description="Run the read_file reader graph on a file and print its text result.",
    )
    parser.add_argument("path", help="file to read (must be inside the app sandbox roots)")
    parser.add_argument("--question", help="question to ask the vision node about an image")
    parser.add_argument("--no-vision", action="store_true",
                        help="skip the vision call (OCR only; no API cost)")
    parser.add_argument("--state", action="store_true",
                        help="print the whole graph state as JSON instead of just the result")
    parser.add_argument("--vision-model", dest="vision_model",
                        help=f"override the vision model (default {VISION_MODEL})")
    args = parser.parse_args(argv)

    state = asyncio.run(get_file_reader_graph().ainvoke({
        "file_path": args.path,
        "question": args.question,
        "vision_enabled": not args.no_vision,
        "vision_model": args.vision_model or "",
    }, config={"recursion_limit": 12}))

    if args.state:
        print(json.dumps(state, indent=2, default=str))
    else:
        print(state.get("result") or "Error: reader produced no output")
        if state.get("branch") == "pdf":
            # A PDF's useful telemetry is per page, not per describe call.
            detail = (f"pages={state.get('pdf_pages')} text={state.get('pdf_text_pages')} "
                      f"image_only={state.get('pdf_image_pages')} "
                      f"ocr={state.get('pdf_ocr_pages')} vision={state.get('pdf_vision_pages')} "
                      f"vision_tokens={state.get('pdf_vision_tokens')} "
                      f"probe={state.get('read_pdf_ms')}ms")
        elif state.get("branch") == "document":
            detail = (f"format={state.get('doc_format')} text_lines="
                      f"{len((state.get('doc_text') or '').splitlines())} "
                      f"sheets={state.get('doc_sheets')} rows={state.get('doc_rows')} "
                      f"pictures={state.get('doc_pictures')} "
                      f"ocr={state.get('doc_ocr_pictures')} vision={state.get('doc_vision_pictures')} "
                      f"vision_tokens={state.get('doc_vision_tokens')}")
        elif state.get("branch") == "archive":
            detail = (f"format={state.get('archive_kind')} entries={state.get('archive_entries')} "
                      f"read_members={state.get('archive_read_members')}")
        else:
            detail = (f"describe_tokens={state.get('describe_tokens')} "
                      f"ocr_chars={state.get('ocr_chars')} ocr={state.get('ocr_ms')}ms "
                      f"describe={state.get('describe_ms')}ms "
                      f"cached={state.get('describe_cached')}")
        print(
            f"\n[branch={state.get('branch')} kind={state.get('kind')} {detail} "
            f"total={state.get('pdf_ms') or state.get('doc_ms') or state.get('archive_ms') or state.get('read_ms') or state.get('merge_ms')}ms]",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        # Direct script execution: make the backend package importable
        # (``python -m core.graphs.read_file`` does not need this).
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(_cli())
