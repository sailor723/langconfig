"""Smoke-test the DeepSeek image-input ("image to text") path end to end.

What it proves, in order:

1. A DeepSeek API key is resolvable the same way the app resolves it
   (``config.get_api_key_from_db`` → .env first, then the encrypted
   ``models.api_keys`` settings document set in Settings → Models).
2. The app's own message builder (``core.agents.multimodal.create_multimodal_message``)
   turns an attachment dict into the ``image_url`` content block the vision
   endpoint expects — this is the exact object a workflow node sends.
3. ``deepseek-flash`` answers a question about a real image through the same
   client class the app uses (``langchain-deepseek``'s ``ChatDeepSeek``, via
   ``init_chat_model(model_provider="deepseek")``).

Usage
-----
    cd backend

    # Generated test image (a rendered word + number), the default
    .venv/bin/python scripts/test_deepseek_vision.py

    # Your own screenshot / scan
    .venv/bin/python scripts/test_deepseek_vision.py --image ~/shot.png

    # Inspect the payload without spending tokens
    .venv/bin/python scripts/test_deepseek_vision.py --dry-run

    # A different model id (e.g. checking that a text-only model rejects it)
    .venv/bin/python scripts/test_deepseek_vision.py --model deepseek-chat

Exit codes: 0 = model read the image correctly, 1 = call/validation failed,
2 = no API key configured (nothing was called).
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_PROMPT = "Read the text in this image and reply with exactly that text, nothing else."


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="End-to-end check of the DeepSeek vision (image input) path.")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id (default: {DEFAULT_MODEL}).")
    p.add_argument("--image", help="Image file to send. Omit to generate a test image with PIL.")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="Question to ask about the image.")
    p.add_argument("--expect", help="Substring the answer must contain (defaults to the generated image's text).")
    p.add_argument("--max-tokens", type=int, default=200)
    p.add_argument("--dry-run", action="store_true", help="Build and print the payload; make no API call.")
    return p.parse_args(argv)


def _make_test_image(text: str) -> tuple[bytes, str]:
    """Render `text` into a PNG so the answer is knowable without a fixture file."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 200), "white")
    draw = ImageDraw.Draw(img)
    # Default bitmap font is small; scale it up by drawing large then resizing.
    small = Image.new("RGB", (160, 50), "white")
    ImageDraw.Draw(small).text((5, 15), text, fill="black")
    img.paste(small.resize((480, 150), Image.LANCZOS), (80, 25))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def _read_image(path: str) -> tuple[bytes, str]:
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(ext)
    if mime is None:
        sys.exit(f"✗ Unsupported image extension '.{ext}' — DeepSeek accepts JPEG, PNG, GIF, WebP.")
    with open(path, "rb") as fh:
        return fh.read(), mime


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # 1 ── API key, resolved exactly like the app resolves it
    from config import get_api_key_from_db

    api_key = get_api_key_from_db("deepseek_api_key")
    if not api_key:
        print("✗ No DeepSeek API key found.\n"
              "  Set it in the UI: Settings → Models → DeepSeek → API key, "
              "or put DEEPSEEK_API_KEY in the project-root .env.")
        return 2
    print(f"✓ DeepSeek API key resolved ({api_key[:6]}…{api_key[-4:]}, {len(api_key)} chars)")

    # 2 ── The image, as the frontend would send it (base64 attachment dict)
    expected = args.expect
    if args.image:
        raw, mime = _read_image(os.path.expanduser(args.image))
        name = os.path.basename(args.image)
        print(f"✓ Loaded {name} ({mime}, {len(raw) / 1024:.1f} KiB)")
    else:
        stamp = "DSH VISION 4821"
        raw, mime = _make_test_image(stamp)
        name = "generated-test.png"
        expected = expected or stamp
        print(f"✓ Generated test image with the text {stamp!r} ({len(raw) / 1024:.1f} KiB)")

    b64 = base64.b64encode(raw).decode("utf-8")
    attachment = {
        "type": "image",
        "name": name,
        "mime_type": mime,
        "data": b64,
    }

    # 3 ── The app's own builder (workflow nodes use this exact function)
    from core.agents.multimodal import create_multimodal_message

    message = create_multimodal_message(args.prompt, [attachment])
    blocks = message.content if isinstance(message.content, list) else []
    kinds = [b.get("type") for b in blocks if isinstance(b, dict)]
    if "image_url" not in kinds:
        print(f"✗ Message builder produced {kinds} — no image_url block. Attachment conversion failed.")
        return 1
    data_uri = blocks[-1]["image_url"]["url"]
    print(f"✓ Built multimodal HumanMessage: blocks={kinds}, "
          f"data-uri={data_uri[:32]}… ({len(data_uri) / 1024:.1f} KiB)")

    if args.dry_run:
        print(f"(dry-run) would POST to the DeepSeek chat-completions endpoint with model={args.model!r}")
        print(f"          prompt={args.prompt!r}")
        return 0

    # 4 ── The same client class the app builds (agent_utils.create_llm path)
    from langchain.chat_models import init_chat_model

    print(f"→ Calling {args.model} …")
    try:
        llm = init_chat_model(
            model=args.model,
            model_provider="deepseek",
            api_key=api_key,
            max_tokens=args.max_tokens,
            streaming=False,
        )
        answer = llm.invoke([message])
    except Exception as e:
        detail = str(e)
        print(f"✗ Call failed: {type(e).__name__}: {detail[:600]}")
        if args.model != DEFAULT_MODEL:
            print(f"  (expected if {args.model} is text-only — the image block is rejected upstream)")
        return 1

    text = answer.content if isinstance(answer.content, str) else str(answer.content)
    print(f"✓ Answer: {text.strip()[:400]!r}")

    if expected:
        flat = re.sub(r"\s+", " ", text).upper()
        needle = re.sub(r"\s+", " ", expected).upper()
        if needle in flat:
            print(f"✓ Image-to-text verified — the answer contains {expected!r}")
            return 0
        print(f"✗ Answer does not contain {expected!r} — the model may not have seen the image.")
        return 1

    print("✓ Call succeeded (no --expect given, so content was not asserted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
