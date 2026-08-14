"""
Presentation generation native tool: gen_pptx.

Generates a business-professional PowerPoint (.pptx) deck in the classic
navy/gold corporate style used by the hand-crafted Tesla deck: full-bleed
light background, gold top strip, navy titles, white content cards with
light borders and page footers.

Slides JSON schema:
{
  "title": "Deck title",
  "slides": [
    {"type": "title", "title": "...", "subtitle": "..."},
    {"type": "section", "title": "...", "subtitle": "..."},
    {"type": "content", "title": "...", "bullets": ["..."], "speaker_notes": "..."}
  ]
}

Supported slide types: title, section, content, data, conclusion, image.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

_OUTPUT_DIR = Path(os.getenv("PRESENTATION_OUTPUT_DIR", "/tmp/langconfig-tools/presentations"))

# ── Navy/gold corporate palette (matches make_pptx.py in the sandbox) ──
NAVY = RGBColor(0x1A, 0x2A, 0x4A)       # titles / primary text
GOLD = RGBColor(0xC8, 0xA2, 0x4A)       # top strip + kicker
WHITE = RGBColor(0xFF, 0xFF, 0xFF)      # card fill
GRAY = RGBColor(0x7A, 0x83, 0x98)       # subtitle / footer
LIGHT = RGBColor(0xEE, 0xF0, 0xF5)      # slide background
BODY = RGBColor(0x4A, 0x55, 0x70)       # bullet text
CARD_LINE = RGBColor(0xEF, 0xEA, 0xE0)  # card border


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return slug[:60] or "presentation"


def _parse_slides(slides_json: str) -> dict:
    if isinstance(slides_json, str):
        slides_json = slides_json.strip()
        start, end = slides_json.find("{"), slides_json.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("slides_json must be a JSON object with title and slides")
        slides_json = slides_json[start:end + 1]
    data = json.loads(slides_json) if isinstance(slides_json, str) else slides_json
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        raise ValueError("slides_json must contain a 'slides' list")
    data.setdefault("title", "Presentation")
    return data


def _add_text(slide, left, top, width, height, text, size, bold=False,
              align=PP_ALIGN.LEFT, color=NAVY):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.alignment = align
    return box


def _new_slide(prs, blank, tag, title, subtitle):
    """Full-bleed light slide with gold top strip + navy title block."""
    s = prs.slides.add_slide(blank)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = LIGHT
    bg.line.fill.background()
    strip = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.09))
    strip.fill.solid()
    strip.fill.fore_color.rgb = GOLD
    strip.line.fill.background()
    if tag:
        _add_text(s, 0.6, 0.2, 12, 0.35, tag.upper(), 12, bold=True, color=GOLD)
    _add_text(s, 0.6, 0.45, 12, 0.7, title or "Presentation", 28, bold=True, color=NAVY)
    if subtitle:
        _add_text(s, 0.6, 1.15, 12, 0.4, subtitle, 13, color=GRAY)
    return s


def _card(slide, x, y, w, h, head, lines):
    """White card with navy head + bullet lines (like make_pptx.box())."""
    c = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    c.fill.solid()
    c.fill.fore_color.rgb = WHITE
    c.line.color.rgb = CARD_LINE
    c.line.width = Pt(0.75)
    c.shadow.inherit = False
    tf = c.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.15)
    tf.margin_right = Inches(0.15)
    p = tf.paragraphs[0]
    if head:
        r = p.add_run()
        r.text = head
        r.font.size = Pt(13)
        r.font.bold = True
        r.font.color.rgb = NAVY
    for ln in lines:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = "• " + ln
        r.font.size = Pt(11)
        r.font.color.rgb = BODY
        p.space_before = Pt(2)


def _footer(slide, page, total, deck_title):
    # centered page counter, deck title right-aligned (make_pptx style)
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(7.02), Inches(12), Inches(0.35))
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = f"{page} / {total}"
    r.font.size = Pt(10)
    r.font.color.rgb = GRAY
    wb = slide.shapes.add_textbox(Inches(8.4), Inches(7.02), Inches(4.3), Inches(0.35))
    wp = wb.text_frame.paragraphs[0]
    wp.alignment = PP_ALIGN.RIGHT
    wr = wp.add_run()
    wr.text = deck_title
    wr.font.size = Pt(9)
    wr.font.color.rgb = GRAY


def _render_pptx(data: dict, output_dir: Path, filename: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    deck_title = data.get("title", "Presentation")
    total = len(data["slides"])

    for i, slide_data in enumerate(data["slides"], start=1):
        stype = str(slide_data.get("type", "content")).lower()
        title = str(slide_data.get("title", ""))
        subtitle = str(slide_data.get("subtitle", ""))
        bullets = [str(b) for b in (slide_data.get("bullets") or [])]
        notes = str(slide_data.get("speaker_notes") or slide_data.get("notes") or "")

        if stype == "title":
            # centered cover on the navy/gold scaffold
            s = _new_slide(prs, blank, "Presentation", "", "")
            _add_text(s, 0.8, 2.6, 11.7, 1.6, title, 42, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                _add_text(s, 0.8, 4.3, 11.7, 0.7, subtitle, 18, align=PP_ALIGN.CENTER, color=GRAY)
        elif stype == "section":
            s = _new_slide(prs, blank, "Section", "", "")
            _add_text(s, 0.8, 2.9, 11.7, 1.2, title, 36, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                _add_text(s, 0.8, 4.3, 11.7, 0.7, subtitle, 18, align=PP_ALIGN.CENTER, color=GRAY)
        else:
            # content / data / conclusion / image: header + white bullet cards
            s = _new_slide(prs, blank, stype, title, subtitle)
            if bullets:
                if len(bullets) <= 6:
                    _card(s, 0.6, 1.7, 12.1, 4.9, None, bullets)
                else:
                    mid = (len(bullets) + 1) // 2
                    _card(s, 0.6, 1.7, 5.95, 4.9, None, bullets[:mid])
                    _card(s, 6.75, 1.7, 5.95, 4.9, None, bullets[mid:])

        _footer(s, i, total, deck_title)
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    filename = filename or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(deck_title)}.pptx"
    path = output_dir / filename
    prs.save(str(path))
    return path


def _resolve_pptx_output(output_dir: str) -> Path:
    """Resolve the output directory and enforce the tool sandbox.

    Only the default tool-owned directory (or a subdirectory of it) is
    allowed — arbitrary server paths are rejected.
    """
    if output_dir and output_dir.strip():
        target = Path(output_dir.strip()).expanduser().resolve()
        try:
            target.relative_to(_OUTPUT_DIR.resolve())
        except ValueError:
            raise ValueError(
                f"output_dir must be inside the presentation output directory "
                f"({_OUTPUT_DIR})"
            )
        return target
    return _OUTPUT_DIR


def _unique_pptx_path(output_dir: Path, base_filename: str) -> Path:
    """Return a non-colliding filename by appending _2, _3, ... when needed.

    Prevents two decks generated in the same second from silently overwriting
    each other (the timestamp-only filename used to collide).
    """
    candidate = output_dir / base_filename
    if not candidate.exists():
        return candidate
    if "." in base_filename:
        stem, suffix = base_filename.rsplit(".", 1)
        suffix = f".{suffix}"
    else:
        stem, suffix = base_filename, ""
    for i in range(2, 100):
        c = output_dir / f"{stem}_{i}{suffix}"
        if not c.exists():
            return c
    return candidate


@tool
def gen_pptx(title: str, slides_json: str, output_dir: str = "") -> str:
    """Generate a business-professional PowerPoint (.pptx) deck in navy/gold
    corporate style from a slides JSON outline.

    Args:
        title: Deck title shown in the filename and slide footers.
        slides_json: JSON object with "title" and "slides". Each slide has
            "type" (title|section|content|data|conclusion|image), "title",
            optional "subtitle", optional "bullets" (list of strings), and
            optional "speaker_notes".
        output_dir: Optional directory (inside the presentation output folder)
            to write the file. Created if it does not exist. Defaults to
            PRESENTATION_OUTPUT_DIR.

    Returns:
        Absolute path to the generated .pptx file.
    """
    try:
        data = _parse_slides(slides_json)
        target = _resolve_pptx_output(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        base_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.pptx"
        filename = _unique_pptx_path(target, base_name)
        path = _render_pptx(data, target, filename=filename.name)
        return f"Created {path} with {len(data['slides'])} slides"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating presentation: {e}"
