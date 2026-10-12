"""Tests for the ``read_file`` reader graph (backend/core/graphs/read_file.py).

The point of this graph is that **no image bytes ever leave it as base64**: a
tool message carries text only, so a 1.5 MB PNG returned as
``{"type": "image", "base64": …}`` cost 1,465,119 tokens and 400'd. These tests
pin that contract.

Vision is monkeypatched (no API calls, no cost); the live path is opt-in via
``LANGCONFIG_LIVE_TESTS=1``.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from core.graphs import read_file as rf

WORKSPACE = Path(__file__).resolve().parent.parent / "outputs"
PROBE_DIR = WORKSPACE / "_pytest_read_file"
LATIN_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
LIVE = os.getenv("LANGCONFIG_LIVE_TESTS") == "1"


@pytest.fixture(scope="module", autouse=True)
def probe_files():
    """Create probe files inside a sandbox root (backend/outputs)."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    text = PROBE_DIR / "sample.md"
    text.write_text("# Title\n\nrevenue = 42\n", encoding="utf-8")

    png = PROBE_DIR / "shot.png"
    img = Image.new("RGB", (900, 220), "white")
    ImageDraw.Draw(img).text((20, 60), "OCR PROBE 12345", fill="black",
                             font=ImageFont.truetype(LATIN_FONT, 44))
    img.save(png, "PNG")

    bmp = PROBE_DIR / "legacy.bmp"
    Image.new("RGB", (400, 120), "white").save(bmp, "BMP")

    binary = PROBE_DIR / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02\xff" * 64)

    rf.clear_describe_cache()
    yield {"md": text, "png": png, "bmp": bmp, "bin": binary}
    for f in PROBE_DIR.iterdir():
        f.unlink()
    PROBE_DIR.rmdir()


@pytest.fixture(autouse=True)
def _isolate_describe_cache():
    """The describe cache is process-wide; keep tests independent."""
    rf.clear_describe_cache()
    yield
    rf.clear_describe_cache()


@pytest.fixture
def fake_vision(monkeypatch):
    """Replace the vision call; record invocations."""
    calls: list[tuple[str, str]] = []

    def _fake(image_b64: str, mime: str, question: str | None, model: str = rf.VISION_MODEL):
        calls.append((mime, question or "", model))
        return "FAKE DESCRIPTION of the image.", 42

    monkeypatch.setattr(rf, "_describe_with_vision", _fake)
    return calls


# ── router ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,kind,ext", [
    ("a.png", "image", ".png"),
    ("b.JPG", "image", ".jpg"),
    ("c.jpeg", "image", ".jpeg"),
    ("d.webp", "image", ".webp"),
    ("e.gif", "image", ".gif"),
    ("f.bmp", "image", ".bmp"),
    ("g.tiff", "image", ".tiff"),
    ("h.md", "text", ".md"),
    ("i.csv", "text", ".csv"),
    ("j.pdf", "document", ".pdf"),
    ("k.docx", "document", ".docx"),
    ("l.pptx", "document", ".pptx"),
    ("m.bin", "binary", ".bin"),
    ("noext", "binary", "noext"),
])
def test_classify(name, kind, ext):
    assert rf.classify(name) == (kind, ext)


@pytest.mark.parametrize("kind,expected", [
    ("text", "text"), ("document", "text"), ("image", "image"), ("binary", "other"),
])
def test_route_by_kind(kind, expected):
    assert rf.route_by_kind({"kind": kind}) == expected


def test_route_by_kind_error_goes_to_other():
    assert rf.route_by_kind({"kind": "image", "error": "boom"}) == "other"


# ── text / document branch ───────────────────────────────────────────────────
def test_text_branch_matches_legacy_read_file(probe_files):
    """Behaviour must not drift from the tool agents already use."""
    from tools.native_impl import read_file as legacy_read_file

    path = str(probe_files["md"])
    state = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": path}))
    assert state["branch"] == "text"
    assert state["result"] == legacy_read_file.invoke({"file_path": path})
    assert state["result"].startswith("   1| # Title")
    assert state.get("describe_tokens") in (None, 0)      # no vision call for text
    assert "base64" not in state["result"]


def test_missing_file_is_an_error_string():
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(PROBE_DIR / "nope.md")}))
    assert state["result"].startswith("Error:")
    assert "not found" in state["result"]


# ── image branch ─────────────────────────────────────────────────────────────
def test_image_branch_returns_text_never_base64(probe_files, fake_vision):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"])}))

    assert state["branch"] == "image"
    result = state["result"]
    # the whole point: no image payload in the tool result
    assert "base64" not in result
    assert "iVBORw0KGgo" not in result
    assert len(result) < 5_000                      # bounded, not megabytes
    assert result.startswith("== Image ==")
    assert "== Description (vision:" in result
    assert "== Text in the image (OCR: tesseract" in result
    assert "FAKE DESCRIPTION of the image." in result
    assert "OCR PROBE 12345" in result              # real tesseract output
    assert fake_vision and fake_vision[0][0].startswith("image/")
    assert state["describe_tokens"] == 42
    assert state["ocr_available"] is True


def test_image_branch_survives_vision_failure(probe_files, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("no DeepSeek API key configured")

    monkeypatch.setattr(rf, "_describe_with_vision", _boom)
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"])}))

    assert state["branch"] == "image"
    assert "base64" not in state["result"]
    assert "(vision description unavailable:" in state["result"]
    assert "OCR PROBE 12345" in state["result"]     # OCR still delivered


def test_ocr_only_mode_skips_the_vision_call(probe_files, fake_vision):
    """OCR-only: deterministic, free, and it must not reach the vision node."""
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"]), "vision_enabled": False}))

    assert state["branch"] == "image"
    assert state.get("vision_disabled") is True
    assert state["describe_tokens"] == 0
    assert not fake_vision                       # the vision body never ran
    assert "base64" not in state["result"]
    assert "OCR PROBE 12345" in state["result"]   # OCR text is still delivered
    assert "mode: ocr-only" in state["result"]    # payload is self-describing
    assert "(vision not requested" in state["result"]
    assert "FAKE DESCRIPTION" not in state["result"]


def test_vision_mode_is_labelled_in_the_payload(probe_files, fake_vision):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"])}))
    assert "mode: vision+ocr" in state["result"]
    assert state.get("vision_disabled") in (None, False)
    assert "FAKE DESCRIPTION of the image." in state["result"]


def test_question_is_passed_to_the_vision_node(probe_files, fake_vision):
    asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"]), "question": "How many rows?"}))
    assert fake_vision[0][1] == "How many rows?"


def test_convertible_format_is_normalised_to_png(probe_files, fake_vision):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["bmp"])}))
    assert state["branch"] == "image"
    assert state["mime"] == "image/png"            # BMP converted for the API
    assert state["image_format"] == "PNG"
    assert fake_vision[0][0] == "image/png"


def test_vision_model_can_be_overridden_per_call(probe_files, fake_vision):
    """An agent can pin which model reads its images (tool_params)."""
    state = asyncio.run(rf.get_file_reader_graph().ainvoke({
        "file_path": str(probe_files["png"]), "vision_model": "some-vision-model",
    }))
    assert fake_vision[0][2] == "some-vision-model"        # override reached the client
    assert "mode: vision+ocr (some-vision-model)" in state["result"]


def test_cache_is_per_model(probe_files, fake_vision):
    """A different model must not reuse another model's description."""
    asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": str(probe_files["png"])}))
    asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"]), "vision_model": "other-model"}))
    assert len(fake_vision) == 2                            # no cross-model cache hit


def test_describe_result_is_cached(probe_files, fake_vision):
    path = str(probe_files["png"])
    first = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": path}))
    second = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": path}))
    assert first["describe_cached"] is False
    assert second["describe_cached"] is True
    assert len(fake_vision) == 1                    # vision called once


def test_oversized_image_is_downscaled(probe_files, fake_vision):
    big = PROBE_DIR / "big.png"
    Image.new("RGB", (4200, 2600), "white").save(big, "PNG")
    try:
        state = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": str(big)}))
        w, h = (int(x) for x in state["image_dimensions"].split("x"))
        assert max(w, h) == rf.MAX_IMAGE_EDGE
    finally:
        big.unlink()


def test_corrupt_image_reports_an_error(probe_files, fake_vision):
    corrupt = PROBE_DIR / "corrupt.png"
    corrupt.write_text("not really a png", encoding="utf-8")
    try:
        state = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": str(corrupt)}))
        assert state["result"].startswith("Error:")
        assert "not a readable image" in state["result"]
    finally:
        corrupt.unlink()


def test_path_outside_sandbox_is_refused(fake_vision):
    """A readable image outside the workspace roots must be refused, not read."""
    import tempfile

    outside = Path(tempfile.mkdtemp()) / "outside.png"
    Image.new("RGB", (200, 80), "white").save(outside, "PNG")
    try:
        state = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": str(outside)}))
        assert state["result"].startswith("Error:")
        assert "outside the allowed workspace" in state["result"]
        assert not fake_vision          # never reached the vision call
    finally:
        outside.unlink()
        outside.parent.rmdir()


def test_extensionless_binary_is_refused(probe_files):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke({"file_path": "/etc/hosts"}))
    assert state["result"].startswith("Error:")
    assert "binary file" in state["result"]


# ── other branch ─────────────────────────────────────────────────────────────
def test_binary_file_is_not_returned_raw(probe_files):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["bin"])}))
    assert state["branch"] == "unsupported"
    assert state["result"].startswith("Error:")
    assert "binary file" in state["result"]
    assert "\x00" not in state["result"]


# ── live path (opt-in: LANGCONFIG_LIVE_TESTS=1) ──────────────────────────────
@pytest.mark.skipif(not LIVE, reason="set LANGCONFIG_LIVE_TESTS=1 to call deepseek-flash")
def test_live_vision_describes_the_probe_image(probe_files):
    state = asyncio.run(rf.get_file_reader_graph().ainvoke(
        {"file_path": str(probe_files["png"])}))
    assert state["branch"] == "image"
    assert "base64" not in state["result"]
    assert state["describe_tokens"] > 0
    assert "OCR PROBE 12345" in state["result"]
    assert "unavailable" not in state["result"]
