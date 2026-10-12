#!/usr/bin/env python
"""Two ways to read one image, side by side.

  (a) read_image      — deterministic OCR (tesseract). Returns the text it sees.
                        No interpretation: no layout, no chart meaning, no objects.
  (b) deepseek-flash  — the vision LLM. Sees the actual picture and answers a
                        question about it.

Why the LLM call here works, while the same model failed inside chat: the image
is sent as an ``image_url`` content block on a **user** message, which is what
DeepSeek's OpenAI-compatible wire accepts. The chat failure came from the image
arriving inside a **tool** message (deepagents' FilesystemMiddleware returns
images as base64 blocks from ``read_file``); that gets serialised as text and
counted per character — 2.1 MB ≈ 1.47 M tokens → HTTP 400 over the 1 M limit.

Usage
-----
    cd backend
    .venv/bin/python scripts/vision_read_image.py --image path/to/shot.png
    .venv/bin/python scripts/vision_read_image.py --image shot.png \
        --prompt "Describe the chart: axes, trend, and any outliers."
    .venv/bin/python scripts/vision_read_image.py --image shot.png --llm-only
    .venv/bin/python scripts/vision_read_image.py --image shot.png --ocr-only

Exit codes: 0 ok, 1 the LLM call failed, 2 no DeepSeek API key configured.
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_PROMPT = (
    "Describe this image precisely: what kind of image it is, any text it "
    "contains, and anything notable. Be concise."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read one image with OCR and with the vision LLM.")
    p.add_argument("--image", required=True, help="Path to the image (PNG/JPEG/WebP/GIF).")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="Question for the vision model.")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Vision model id (default {DEFAULT_MODEL}).")
    p.add_argument("--max-tokens", type=int, default=2000,
                   help="Answer budget. deepseek-flash also spends tokens on hidden reasoning.")
    p.add_argument("--think", action="store_true",
                   help="Keep the model's thinking mode ON (default: off, so the whole budget is the answer).")
    p.add_argument("--ocr-only", action="store_true", help="Skip the LLM call.")
    p.add_argument("--llm-only", action="store_true", help="Skip the OCR call.")
    return p.parse_args(argv)


def read_image_tool(path: Path) -> str:
    """(a) The deterministic reader: the app's own read_image tool (OCR)."""
    from tools.native_impl import read_image

    out = read_image.invoke({"file_path": str(path)})
    if isinstance(out, str) and out.startswith("Error: Path") and "outside the allowed workspace" in out:
        # The tool is sandboxed to the app's workspace roots. For a file outside
        # them, fall back to the raw binary so the comparison still runs.
        import shutil
        import subprocess

        if shutil.which("tesseract") is None:
            return out + "\n(tesseract not installed — cannot OCR outside the sandbox)"
        proc = subprocess.run(["tesseract", str(path), "stdout"], capture_output=True, text=True, timeout=60)
        return f"(outside the app sandbox — ran tesseract directly)\n{(proc.stdout or '').strip()}"
    return str(out)


def read_image_llm(path: Path, prompt: str, model: str, max_tokens: int, think: bool = False) -> tuple[str, float, str]:
    """(b) The vision reader: image sent as an image_url block on a USER message."""
    from config import get_api_key_from_db
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    api_key = get_api_key_from_db("deepseek_api_key")
    if not api_key:
        raise SystemExit("No DeepSeek API key found (Settings → Models → DeepSeek, or DEEPSEEK_API_KEY).")

    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data_uri = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

    llm = init_chat_model(
        model=model, model_provider="deepseek", api_key=api_key,
        max_tokens=max_tokens, streaming=False,
        # deepseek-flash supports both modes and defaults to thinking; for
        # "read this image" the reasoning only eats the answer budget unless
        # the question genuinely needs it.
        **({} if think else {"reasoning_effort": "none"}),
    )
    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ])
    started = time.time()
    reply = llm.invoke([message])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    usage = (reply.response_metadata or {}).get("token_usage") or {}
    reasoning = (reply.additional_kwargs or {}).get("reasoning_content") or ""
    note = (f"usage: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}"
            f" reasoning={((usage.get('completion_tokens_details') or {}) or {}).get('reasoning_tokens')}"
            f" finish={(reply.response_metadata or {}).get('finish_reason')}")
    if not text.strip() and reasoning:
        # Never print a blank answer: fall back to the thinking channel.
        text = f"(empty content — showing the model's reasoning instead)\n{reasoning.strip()}"
    return text.strip(), time.time() - started, note


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.image).expanduser().resolve()
    if not path.is_file():
        print(f"✗ not a file: {path}")
        # Point at something runnable instead of leaving you guessing.
        IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")
        parent = path.parent
        if parent.is_dir():
            near = sorted(p.name for p in parent.iterdir()
                          if p.is_file() and p.suffix.lower() in IMG)[:8]
            if near:
                print(f"  images in {parent}:")
                for n in near:
                    print(f"    --image \"{parent / n}\"")
            elif not any(parent.iterdir()):
                print(f"  {parent} is empty")
        else:
            print(f"  no such directory: {parent}")
        print("  tip: ${HOME} works, and quote paths containing spaces.")
        return 1

    from PIL import Image

    with Image.open(path) as im:
        dims, fmt = f"{im.width}x{im.height}", im.format
    print(f"image: {path.name}  ({fmt}, {dims}, {path.stat().st_size / 1024:.0f} KiB)")

    if not args.llm_only:
        print("\n=== (a) read_image tool — deterministic OCR ===")
        t0 = time.time()
        try:
            print(read_image_tool(path))
        except Exception as e:
            print(f"OCR failed: {type(e).__name__}: {e}")
        print(f"[{time.time() - t0:.2f}s]")

    if not args.ocr_only:
        print(f"\n=== (b) {args.model} — vision LLM ===")
        print(f"prompt: {args.prompt}")
        try:
            text, elapsed, note = read_image_llm(
                path, args.prompt, args.model, args.max_tokens, think=args.think)
        except SystemExit as e:
            print(e)
            return 2
        except Exception as e:
            print(f"✗ call failed: {type(e).__name__}: {str(e)[:400]}")
            return 1
        print(text)
        print(f"[{elapsed:.2f}s | {note}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
