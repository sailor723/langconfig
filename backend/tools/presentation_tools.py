"""
Presentation generation native tools: gen_pptx and gen_html.

Both tools accept the same slides JSON schema:
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
import html
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
_ACCENT = RGBColor(0x4F, 0x46, 0xE5)
_DARK = RGBColor(0x1A, 0x1A, 0x1A)
_CONTENT_TYPES = {"content", "data", "conclusion"}


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


def _add_text(slide, left, top, width, height, text, size, bold=False, align=PP_ALIGN.LEFT, color=_DARK):
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


def _add_bullets(slide, bullets):
    box = slide.shapes.add_textbox(Inches(0.75), Inches(1.7), Inches(11.8), Inches(5.2))
    tf = box.text_frame
    tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {b}"
        p.font.size = Pt(18)
        p.space_before = Pt(10)
        p.font.color.rgb = _DARK


def _render_pptx(data: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    for slide_data in data["slides"]:
        stype = str(slide_data.get("type", "content")).lower()
        title = str(slide_data.get("title", ""))
        subtitle = str(slide_data.get("subtitle", ""))
        bullets = [str(b) for b in (slide_data.get("bullets") or [])]
        notes = str(slide_data.get("speaker_notes") or slide_data.get("notes") or "")

        slide = prs.slides.add_slide(blank)
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.12), Inches(7.5)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = _ACCENT
        bar.line.fill.background()

        if stype == "title":
            _add_text(slide, 0.8, 2.3, 11.7, 1.4, title, 42, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                _add_text(slide, 0.8, 3.9, 11.7, 0.8, subtitle, 22, align=PP_ALIGN.CENTER)
        elif stype == "section":
            _add_text(slide, 0.8, 2.8, 11.7, 1.2, title, 36, bold=True, align=PP_ALIGN.CENTER)
            if subtitle:
                _add_text(slide, 0.8, 4.2, 11.7, 0.8, subtitle, 18, align=PP_ALIGN.CENTER)
        elif stype == "image":
            _add_text(slide, 0.5, 0.45, 12.3, 1.0, title, 30, bold=True)
            _add_bullets(slide, [subtitle] if subtitle else ["Image slide — visual suggestion: " + str(slide_data.get("visual_suggestion", ""))])
        else:
            _add_text(slide, 0.5, 0.45, 12.3, 1.0, title, 30, bold=True)
            _add_bullets(slide, bullets)

        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data['title'])}.pptx"
    path = output_dir / filename
    prs.save(str(path))
    return path


def _slide_html(slide_data: dict, index: int) -> str:
    stype = str(slide_data.get("type", "content")).lower()
    title = html.escape(str(slide_data.get("title", "")))
    subtitle = html.escape(str(slide_data.get("subtitle", "")))
    bullets = [html.escape(str(b)) for b in (slide_data.get("bullets") or [])]
    notes = html.escape(str(slide_data.get("speaker_notes") or slide_data.get("notes") or ""))

    parts = [f'<section class="slide" data-index="{index}">']
    if stype == "title":
        parts.append(f'<h1>{title or "Presentation"}</h1>')
        if subtitle:
            parts.append(f'<p class="subtitle">{subtitle}</p>')
    elif stype == "section":
        parts.append(f'<h2 class="section-title">{title}</h2>')
        if subtitle:
            parts.append(f'<p class="subtitle">{subtitle}</p>')
    else:
        parts.append(f'<h2>{title}</h2>')
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
    if notes:
        parts.append(f'<aside class="notes">{notes}</aside>')
    parts.append("</section>")
    return "".join(parts)


def _render_html(data: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    slides_html = "".join(_slide_html(s, i) for i, s in enumerate(data["slides"]))
    title = html.escape(data["title"])

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --accent: #4f46e5;
    --bg: #f5f6fa;
    --fg: #1a1a1a;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
         font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  .deck {{ position: relative; width: 100vw; height: 100vh; overflow: hidden; }}
  .slide {{ position: absolute; inset: 0; display: none; flex-direction: column;
           justify-content: center; align-items: center; padding: 8vh 12vw;
           border-left: 10px solid var(--accent); text-align: center; }}
  .slide.active {{ display: flex; }}
  h1 {{ font-size: 3.4rem; margin: 0 0 1rem; }}
  h2 {{ font-size: 2.6rem; margin: 0 0 1.2rem; }}
  .section-title {{ font-size: 3rem; }}
  .subtitle {{ font-size: 1.3rem; opacity: 0.75; margin: 0; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ font-size: 1.35rem; line-height: 1.9; }}
  .nav {{ position: fixed; bottom: 20px; right: 24px; display: flex; gap: 8px; }}
  .nav button {{ padding: 8px 16px; border: 1px solid #d0d3e0; border-radius: 6px;
                 background: #fff; color: var(--fg); font-size: 0.95rem; cursor: pointer; }}
  .dots {{ position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
           display: flex; gap: 6px; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #c9ccdb; }}
  .dot.active {{ background: var(--accent); }}
  .notes {{ display: none; }}
</style>
</head>
<body>
  <div class="deck">{slides_html}</div>
  <div class="dots">{"".join('<span class="dot"></span>' for _ in data["slides"])}</div>
  <div class="nav">
    <button data-dir="-1">Prev</button>
    <button data-dir="1">Next</button>
  </div>
  <script>
    const slides = document.querySelectorAll('.slide');
    const dots = document.querySelectorAll('.dot');
    let cur = 0;
    function show(i) {{
      cur = Math.max(0, Math.min(slides.length - 1, i));
      slides.forEach((s, j) => s.classList.toggle('active', j === cur));
      dots.forEach((d, j) => d.classList.toggle('active', j === cur));
    }}
    document.querySelectorAll('.nav button').forEach(b => {{
      b.addEventListener('click', () => show(cur + Number(b.dataset.dir)));
    }});
    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === ' ') show(cur + 1);
      if (e.key === 'ArrowLeft') show(cur - 1);
    }});
    show(0);
  </script>
</body>
</html>"""

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data['title'])}.html"
    path = output_dir / filename
    path.write_text(doc, encoding="utf-8")
    return path


@tool
def gen_pptx(title: str, slides_json: str, output_dir: str = "") -> str:
    """Generate a PowerPoint (.pptx) deck from a slides JSON outline.

    Args:
        title: Deck title shown in the filename.
        slides_json: JSON object with "title" and "slides". Each slide has
            "type" (title|section|content|data|conclusion|image), "title",
            optional "subtitle", optional "bullets" (list of strings), and
            optional "speaker_notes".
        output_dir: Optional absolute directory to write the file. Created if
            it does not exist. Defaults to PRESENTATION_OUTPUT_DIR.

    Returns:
        Absolute path to the generated .pptx file.
    """
    data = _parse_slides(slides_json)
    target = Path(output_dir.strip()) if output_dir and output_dir.strip() else _OUTPUT_DIR
    path = _render_pptx(data, target)
    return f"Created {path} with {len(data['slides'])} slides"


@tool
def gen_html(title: str, slides_json: str, output_dir: str = "") -> str:
    """Generate a standalone HTML presentation deck from a slides JSON outline.

    Args:
        title: Deck title shown in the browser tab and filename.
        slides_json: JSON object with "title" and "slides". Each slide has
            "type" (title|section|content|data|conclusion|image), "title",
            optional "subtitle", optional "bullets" (list of strings), and
            optional "speaker_notes".
        output_dir: Optional absolute directory to write the file. Created if
            it does not exist. Defaults to PRESENTATION_OUTPUT_DIR.

    Returns:
        Absolute path to the generated .html file.
    """
    data = _parse_slides(slides_json)
    target = Path(output_dir.strip()) if output_dir and output_dir.strip() else _OUTPUT_DIR
    path = _render_html(data, target)
    return f"Created {path} with {len(data['slides'])} slides"
