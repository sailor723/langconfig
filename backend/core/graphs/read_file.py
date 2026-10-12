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
              └─ other ─────────→ unsupported ───────────────────────→ END

``ocr`` and ``describe`` are two edges out of ``normalise``, so LangGraph runs
them in the same superstep (wall time ≈ the slower one, not the sum). They
write different state keys, so no reducer is needed; ``merge`` composes them.

The compiled graph is a utility graph: **no checkpointer** (it would accumulate
image state per thread — the very failure this module removes) and an in-process
node cache for the vision call, keyed by file content hash.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────────
VISION_MODEL = os.getenv("LANGCONFIG_VISION_MODEL", "deepseek-flash")
OCR_MAX_CHARS = int(os.getenv("LANGCONFIG_OCR_MAX_CHARS", "4000"))
DESCRIBE_MAX_TOKENS = int(os.getenv("LANGCONFIG_DESCRIBE_MAX_TOKENS", "400"))
MAX_IMAGE_EDGE = int(os.getenv("LANGCONFIG_MAX_IMAGE_EDGE", "1600"))
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
    describe_error: str
    describe_tokens: int
    describe_cached: bool
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
    """Conditional-edge router: ``text`` | ``image`` | ``other``."""
    if state.get("error"):
        return "other"
    kind = state.get("kind")
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


def _describe_with_vision(image_b64: str, mime: str, question: Optional[str]) -> tuple[str, int]:
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
        model=VISION_MODEL, model_provider="deepseek", api_key=api_key,
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
        from PIL import Image

        with Image.open(path) as img:
            fmt = img.format or "unknown"
            dims = f"{img.width}x{img.height}"
            native = state.get("ext") in NATIVE_IMAGE_EXTS
            needs_resize = max(img.width, img.height) > MAX_IMAGE_EDGE
            if native and not needs_resize:
                raw = path.read_bytes()
                mime = state.get("mime") or "image/png"
            else:
                work = img
                if needs_resize:
                    scale = MAX_IMAGE_EDGE / max(img.width, img.height)
                    work = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
                if work.mode not in ("RGB", "L"):
                    work = work.convert("RGB")
                import io

                buf = io.BytesIO()
                work.save(buf, format="PNG", optimize=True)
                raw = buf.getvalue()
                mime = "image/png"
                fmt = "PNG"
                with Image.open(io.BytesIO(raw)) as scaled:
                    dims = f"{scaled.width}x{scaled.height}"
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
    if shutil.which("tesseract") is None:
        return {"ocr_text": "", "ocr_chars": 0, "ocr_available": False,
                "ocr_ms": int((time.time() - started) * 1000)}
    out: FileReadState = {"ocr_available": True}
    try:
        proc = subprocess.run(["tesseract", str(tmp_path), "stdout"],
                              capture_output=True, text=True, timeout=60)
        text = (proc.stdout or "").strip()
    except Exception as e:
        logger.warning(f"OCR failed for {tmp_path}: {e}")
        text = ""
    out["ocr_text"] = text[:OCR_MAX_CHARS]
    out["ocr_chars"] = len(text)
    out["ocr_ms"] = int((time.time() - started) * 1000)
    return out


def describe_node(state: FileReadState) -> FileReadState:
    """Vision pass — the image rides a USER message (the only wire that works)."""
    started = time.time()
    elapsed = lambda: int((time.time() - started) * 1000)  # noqa: E731
    if not state.get("vision_enabled", True):
        return {"describe_tokens": 0, "describe_cached": False,
                "describe_error": "vision disabled", "describe_ms": elapsed()}

    b64 = state.get("image_b64") or ""
    if not b64:
        return {"describe_tokens": 0, "describe_cached": False,
                "describe_error": "no image payload", "describe_ms": elapsed()}

    cache_key = hashlib.sha256(
        f"{VISION_MODEL}|{state.get('question') or ''}|{b64}".encode()
    ).hexdigest()
    hit = _DESCRIBE_CACHE.get(cache_key)
    if hit is not None:
        return {"description": hit[0], "describe_tokens": hit[1], "describe_cached": True,
                "describe_ms": elapsed()}

    try:
        description, tokens = _describe_with_vision(b64, state.get("mime") or "image/png",
                                                    state.get("question"))
    except Exception as e:
        logger.warning(f"vision describe failed: {type(e).__name__}: {e}")
        return {"describe_tokens": 0, "describe_cached": False,
                "describe_error": f"{type(e).__name__}: {e}", "describe_ms": elapsed()}

    if len(_DESCRIBE_CACHE) >= DESCRIBE_CACHE_SIZE:
        _DESCRIBE_CACHE.clear()
    _DESCRIBE_CACHE[cache_key] = (description, tokens)
    return {"description": description, "describe_tokens": tokens, "describe_cached": False,
            "describe_ms": elapsed()}


def merge_node(state: FileReadState) -> FileReadState:
    """Compose the text payload handed back to the agent."""
    started = time.time()
    if state.get("error"):
        return {}

    question = (state.get("question") or "").strip()
    asked = f"question: {question}\n" if question else ""
    header = (
        f"== Image ==\n"
        f"name: {state.get('name')}\n"
        f"{asked}"
        f"format: {state.get('image_format')}  dimensions: {state.get('image_dimensions')}  "
        f"size: {(state.get('image_bytes') or 0) / 1024:.0f} KiB"
    )
    if state.get("describe_error"):
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
        f"== Description (vision: {VISION_MODEL}) ==\n{vision}\n\n"
        f"== Text in the image (OCR: tesseract, eng) ==\n{ocr_section}"
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
    builder.add_node("normalise", normalise_image_node)
    builder.add_node("ocr", ocr_node)
    builder.add_node("describe", describe_node)
    builder.add_node("merge", merge_node)
    builder.add_node("unsupported", unsupported_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_by_kind, {
        "text": "read_text",
        "image": "normalise",
        "other": "unsupported",
    })
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
) -> str:
    """Run the graph and return only the text result (the tool contract)."""
    state = await get_file_reader_graph().ainvoke(
        {"file_path": file_path, "question": question, "vision_enabled": vision_enabled},
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
    parser.add_argument("--model", help=f"override the vision model (default {VISION_MODEL})")
    args = parser.parse_args(argv)

    if args.model:
        globals()["VISION_MODEL"] = args.model

    state = asyncio.run(get_file_reader_graph().ainvoke({
        "file_path": args.path,
        "question": args.question,
        "vision_enabled": not args.no_vision,
    }, config={"recursion_limit": 12}))

    if args.state:
        print(json.dumps(state, indent=2, default=str))
    else:
        print(state.get("result") or "Error: reader produced no output")
        print(
            f"\n[branch={state.get('branch')} kind={state.get('kind')} "
            f"describe_tokens={state.get('describe_tokens')} ocr_chars={state.get('ocr_chars')} "
            f"ocr={state.get('ocr_ms')}ms describe={state.get('describe_ms')}ms "
            f"cached={state.get('describe_cached')}]",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        # Direct script execution: make the backend package importable
        # (``python -m core.graphs.read_file`` does not need this).
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(_cli())
