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
    classify ─┬─ text/document ─→ read_text ─────────────────────────→ END
              ├─ image ─────────→ normalise ─┬─ ocr ──────┐
              │                              └─ describe ─┴→ merge ─→ END
              ├─ pdf ──────────→ pdf_probe ─┬─ (one Send per image-only page) ─┐
              │                             └─ (nothing to render) ───────────┤
              │                                                               ↓
              │                                                          pdf_page ─→ pdf_compose ─→ END
              └─ other ────────→ unsupported ───────────────────────────────────────→ END

``ocr`` and ``describe`` are two edges out of ``normalise``, so LangGraph runs
them in the same superstep (wall time ≈ the slower one, not the sum). They
write different state keys, so no reducer is needed; ``merge`` composes them.

PDFs
----
A PDF is not one format but two: pages that carry a text layer, and pages that
are just a scan. Reading only the text layer means a scanned contract returns
`no extractable text found in PDF` — a whole, common file class the reader used
to fail on. So ``pdf_probe`` walks the document (PyMuPDF, already a dependency)
and sorts the pages: a page whose extracted text reaches ``PDF_MIN_PAGE_CHARS``
is text and is kept as is; every other page is image-only and becomes a **map
task** — ``route_pdf_pages`` returns one ``Send("pdf_page", {page: n, …})`` per
such page, so ``pdf_page`` runs them in one superstep and reads each page the
same way ``normalise``/``ocr``/``describe`` read a loose image. ``pdf_compose``
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

# Binary documents converted to text by _extract_* helpers in tools.native_impl.
DOCUMENT_EXTS = frozenset({".pdf", ".docx", ".pptx"})

# Documents that get the page-aware branch (text layer + rendered image pages).
PDF_EXTS = frozenset({".pdf"})

# Plain-text formats. Mirrors the extension lists the chat upload path and the
# legacy read_file tool treat as text, so behaviour does not drift between them.
TEXT_EXTS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".csv", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".css", ".scss", ".sql", ".sh", ".bash", ".rb", ".go",
    ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".rtf", ".tex", ".toml",
    ".ini", ".cfg", ".conf", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
})

UNSUPPORTED_HINT = (
    "Images: .png/.jpg/.jpeg/.webp/.gif. "
    "Documents: .pdf/.docx/.pptx. "
    "Text: .txt/.md/.json/.csv/.yaml/.py/..."
)


class FileReadState(TypedDict, total=False):
    """Graph state. Only ``result`` is handed back to the caller/agent."""

    # ── input ──
    file_path: str
    question: Optional[str]
    vision_enabled: bool
    vision_model: str
    # ── classification ──
    kind: Literal["text", "document", "image", "binary"]
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
    # ``pdf_probe`` fills the counts and the text blocks; the per-page map tasks
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
    # ── one ``pdf_page`` map task (never the whole graph state) ──
    page: int
    vision: bool
    vision_reason: str
    # ── output ──
    result: str
    truncated: bool
    error: str
    # per-node durations (distinct keys: the parallel nodes write in one superstep)
    classify_ms: int
    read_ms: int
    normalise_ms: int
    ocr_ms: int
    describe_ms: int
    merge_ms: int
    pdf_ms: int
    pdf_probe_ms: int


# ── helpers ──────────────────────────────────────────────────────────────────
_DESCRIBE_CACHE: Dict[str, tuple[str, int]] = {}


def classify(file_name_or_path: str) -> tuple[str, str]:
    """Return ``(kind, ext)`` for a filename — the router's decision only.

    ``kind`` is one of ``text`` / ``document`` / ``image`` / ``binary``.
    """
    ext = Path(file_name_or_path).suffix.lower() or Path(file_name_or_path).name.lower()
    if ext in IMAGE_EXTS:
        return "image", ext
    if ext in DOCUMENT_EXTS:
        return "document", ext
    if ext in TEXT_EXTS:
        return "text", ext
    return "binary", ext


def route_by_kind(state: FileReadState) -> str:
    """Conditional-edge router: ``text`` | ``pdf`` | ``image`` | ``other``."""
    if state.get("error"):
        return "other"
    kind = state.get("kind")
    if kind == "document" and state.get("ext") in PDF_EXTS:
        return "pdf"
    if kind in ("text", "document"):
        return "text"
    if kind == "image":
        return "image"
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
        proc = subprocess.run(["tesseract", "--list-langs"],
                              capture_output=True, text=True, timeout=20)
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
                              capture_output=True, text=True, timeout=60)
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
    name = Path(path_str).name
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


def _ocr_bytes(raw: bytes, tag: str) -> Tuple[str, int, bool]:
    """OCR an in-memory image: tesseract needs a path, so hand it a temp file."""
    tmpdir = tempfile.mkdtemp(prefix="langconfig-pdf-")
    try:
        tmp = Path(tmpdir) / f"page-{tag}.png"
        tmp.write_bytes(raw)
        return _ocr_file(tmp)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def pdf_probe_node(state: FileReadState) -> FileReadState:
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
                "pdf_probe_ms": int((time.time() - started) * 1000)}

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
        "pdf_probe_ms": int((time.time() - started) * 1000),
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
    vision = bool(state.get("vision"))
    out: Dict[str, Any] = {"page": page_no, "ocr": False, "vision": False, "tokens": 0}
    blocked = None

    path, err = _resolve_path(state["file_path"])
    if err or not path.is_file():
        blocked = err or f"Error: File not found: {state['file_path']}"
    else:
        try:
            import fitz

            with fitz.open(path) as doc:
                png = doc.load_page(page_no - 1).get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")
            raw, mime, _, dims = _fit_image_bytes(png, ".png")
        except Exception as e:
            blocked = f"{type(e).__name__}: {e}"

    if blocked:
        out["body"] = f"[Page {page_no}] (image-only — could not be read: {blocked})"
        out["ms"] = int((time.time() - started) * 1000)
        return {"pdf_page_blocks": [out]}

    lines = [f"[Page {page_no}] (image-only — rendered at {PDF_RENDER_DPI} dpi, {dims})"]

    # vision first: it is the slow half, and the OCR section reads better under it
    used_model = (state.get("vision_model") or "").strip() or VISION_MODEL
    if vision:
        described = _describe_cached(base64.b64encode(raw).decode(), mime,
                                    state.get("question"), state.get("vision_model"))
        tokens = int(described.get("describe_tokens") or 0)
        out["tokens"] = tokens
        if described.get("describe_error"):
            lines.append(f"== Description (vision: {used_model}) ==\n"
                         f"(vision description unavailable: {described['describe_error']})")
        else:
            note = " (cached)" if described.get("describe_cached") else ""
            body = described.get("description") or "(no description returned)"
            lines.append(f"== Description (vision: {used_model}) ==\n{body}{note}")
            out["vision"] = True
    elif state.get("vision_reason") == "disabled":
        lines.append("== Description ==\n(vision not requested — OCR text only)")
    else:
        lines.append("== Description ==\n(vision skipped — the vision budget covers the "
                     f"first {PDF_MAX_VISION_PAGES} image-only page(s))")

    ocr_text, ocr_chars, ocr_available = _ocr_bytes(raw, page_no)
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
        lines.append(f"== Text in the image (OCR: tesseract, {ocr_langs()}) ==\n"
                     "(no OCR text found in the page)")

    out["body"] = "\n\n".join(lines)
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
            "pdf_ms": int(state.get("pdf_probe_ms") or 0) + page_ms
                      + int((time.time() - started) * 1000)}


def normalise_image_node(state: FileReadState) -> FileReadState:
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
        return {"result": msg, "error": msg, "normalise_ms": int((time.time() - started) * 1000)}

    return {
        "normalise_ms": int((time.time() - started) * 1000),
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
    builder.add_node("pdf_probe", pdf_probe_node)
    builder.add_node("pdf_page", pdf_page_node)
    builder.add_node("pdf_compose", pdf_compose_node)
    builder.add_node("normalise", normalise_image_node)
    builder.add_node("ocr", ocr_node)
    builder.add_node("describe", describe_node)
    builder.add_node("merge", merge_node)
    builder.add_node("unsupported", unsupported_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_by_kind, {
        "text": "read_text",
        "pdf": "pdf_probe",
        "image": "normalise",
        "other": "unsupported",
    })
    # PDF: the probe's router maps one task per image-only page (``Send``), and
    # ``pdf_compose`` reduces once every task in the superstep has landed.
    builder.add_conditional_edges("pdf_probe", route_pdf_pages, {
        "pdf_page": "pdf_page",
        "pdf_compose": "pdf_compose",
    })
    builder.add_edge("pdf_page", "pdf_compose")
    builder.add_edge("pdf_compose", END)
    # Fan-out: both nodes run in one superstep; they write different keys.
    builder.add_edge("normalise", "ocr")
    builder.add_edge("normalise", "describe")
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
) -> str:
    """Run the graph and return only the text result (the tool contract).

    ``vision_model`` overrides ``LANGCONFIG_VISION_MODEL`` for this call, so an
    agent can pin the model its reader uses (``tool_params``).
    """
    state = await get_file_reader_graph().ainvoke(
        {"file_path": file_path, "question": question, "vision_enabled": vision_enabled,
         "vision_model": vision_model or ""},
        config={"recursion_limit": 12},
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
                      f"probe={state.get('pdf_probe_ms')}ms")
        else:
            detail = (f"describe_tokens={state.get('describe_tokens')} "
                      f"ocr_chars={state.get('ocr_chars')} ocr={state.get('ocr_ms')}ms "
                      f"describe={state.get('describe_ms')}ms "
                      f"cached={state.get('describe_cached')}")
        print(
            f"\n[branch={state.get('branch')} kind={state.get('kind')} {detail} "
            f"total={state.get('pdf_ms') or state.get('read_ms') or state.get('merge_ms')}ms]",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        # Direct script execution: make the backend package importable
        # (``python -m core.graphs.read_file`` does not need this).
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(_cli())
