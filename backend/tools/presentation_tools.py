"""
Presentation generation native tool: gen_pptx (theme-aware).

Generates a styled PowerPoint (.pptx) deck with python-pptx. The layout
language is shared with the platform's Deep Presentation Generator (agent
165): full-bleed light content slides with an accent top strip, navy/dark
title blocks, white rounded bullet cards with accent dot markers, big-number
highlights, page footers + watermark, and dark cover/closing slides.

Theme parameter selects a named palette (business, fashion, tech, health,
education, minimal). Default "business" keeps the classic navy/gold look.

Slides JSON schema:
{
  "title": "Deck title",
  "slides": [
    {"type": "title", "title": "...", "subtitle": "..."},
    {"type": "section", "title": "...", "subtitle": "..."},
    {"type": "content", "title": "...", "bullets": ["..."], "speaker_notes": "...", "highlight": ["61,704"]},
    {"type": "data",    "title": "...", "bullets": ["..."]},
    {"type": "conclusion", "title": "...", "bullets": ["..."]},
    {"type": "closing", "title": "...", "subtitle": "..."}
  ]
}

Supported slide types: title, section, content, data, conclusion, closing,
image. `highlight` (optional list of bullet substrings) renders those bullets
in the accent color at a larger size (best for key numbers/percentages).
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
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

_OUTPUT_DIR = Path(os.getenv("PRESENTATION_OUTPUT_DIR", "/tmp/langconfig-tools/presentations"))

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


# ── Named palettes (theme → colors) ─────────────────────────────────────
THEMES: dict = {
    "business": {
        "label": "Business / Corporate (navy + gold)",
        "primary": "#1A2A4A", "accent": "#C8A24A", "accent_light": "#D8BD77", "accent_dark": "#A8842F",
        "bg": "#EEF0F5", "card": "#FFFFFF", "card_line": "#E6E9F0", "body": "#4A5570", "muted": "#7A8398",
        "dark_bg": "#1A2A4A", "dark_text": "#DBE2EF", "font": "Calibri",
    },
    "fashion": {
        "label": "Fashion / Editorial (black + gold, serif)",
        "primary": "#0B0B0F", "accent": "#BFA05A", "accent_light": "#D6BC7E", "accent_dark": "#8F7738",
        "bg": "#F7F4EE", "card": "#FFFFFF", "card_line": "#E8E1D2", "body": "#2B2B2B", "muted": "#8A8A8A",
        "dark_bg": "#0B0B0F", "dark_text": "#F2EEE4", "font": "Georgia",
    },
    "tech": {
        "label": "Technology (slate + cyan)",
        "primary": "#0F172A", "accent": "#22D3EE", "accent_light": "#67E8F9", "accent_dark": "#0891B2",
        "bg": "#F1F5F9", "card": "#FFFFFF", "card_line": "#E2E8F0", "body": "#334155", "muted": "#64748B",
        "dark_bg": "#0F172A", "dark_text": "#E2E8F0", "font": "Segoe UI",
    },
    "health": {
        "label": "Healthcare (teal + white)",
        "primary": "#134E4A", "accent": "#14B8A6", "accent_light": "#5EEAD4", "accent_dark": "#0F766E",
        "bg": "#F0FDFA", "card": "#FFFFFF", "card_line": "#CCFBF1", "body": "#115E59", "muted": "#5F7A76",
        "dark_bg": "#134E4A", "dark_text": "#E6FFFA", "font": "Calibri",
    },
    "education": {
        "label": "Education (indigo + amber)",
        "primary": "#3730A3", "accent": "#F59E0B", "accent_light": "#FCD34D", "accent_dark": "#B45309",
        "bg": "#F8FAFC", "card": "#FFFFFF", "card_line": "#E2E8F0", "body": "#1E293B", "muted": "#64748B",
        "dark_bg": "#3730A3", "dark_text": "#EEF2FF", "font": "Calibri",
    },
    "minimal": {
        "label": "Minimal (monochrome)",
        "primary": "#111111", "accent": "#8A8A8A", "accent_light": "#B0B0B0", "accent_dark": "#555555",
        "bg": "#FFFFFF", "card": "#F5F5F5", "card_line": "#E0E0E0", "body": "#333333", "muted": "#999999",
        "dark_bg": "#111111", "dark_text": "#F5F5F5", "font": "Arial",
    },
}


def _theme(name: str) -> dict:
    key = (name or "business").strip().lower()
    if key not in THEMES:
        raise ValueError(
            f"Unknown theme '{name}'. Choose one of: {', '.join(sorted(THEMES))}"
        )
    return THEMES[key]


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


# ── Low-level shape helpers (theme-aware) ───────────────────────────────

def _set_font(run, size: int, bold: bool, color, font_name: str, text: str = ""):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font_name
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", "Microsoft YaHei" if _CJK_RE.search(text or "") else font_name)


def _add_text(slide, x, y, w, h, text, size, bold, color, font_name,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    _set_font(r, size, bold, color, font_name, text)
    return tb


def _add_rect(slide, x, y, w, h, fill, line=None, rounded=False, radius=0.08):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    if rounded:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def _accent_top_bar(slide, sw, t: dict):
    """Three-segment accent gradient strip at the top of a light slide."""
    third = sw / 3
    for i, cname in enumerate(("accent_light", "accent", "accent_dark")):
        _add_rect(slide, int(i * third), 0, int(third), 0.07, _rgb(t[cname]))


def _footer(slide, page, total, deck_title, t: dict):
    tb = slide.shapes.add_textbox(Inches(11.4), Inches(7.02), Inches(1.7), Inches(0.35))
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    r = p.add_run()
    r.text = f"{page} / {total}"
    _set_font(r, 10, False, _rgb(t["muted"]), t["font"])
    wb = slide.shapes.add_textbox(Inches(0.6), Inches(7.02), Inches(10.5), Inches(0.35))
    wp = wb.text_frame.paragraphs[0]
    wp.alignment = PP_ALIGN.LEFT
    wr = wp.add_run()
    wr.text = deck_title
    _set_font(wr, 9, False, _rgb(t["muted"]), t["font"])


def _render_pptx(data: dict, output_dir: Path, theme_name: str, filename: str | None = None) -> Path:
    t = _theme(theme_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    sw = int(prs.slide_width)
    blank = prs.slide_layouts[6]
    deck_title = data.get("title", "Presentation")
    total = len(data["slides"])
    dark_types = {"title", "closing"}

    for i, slide_data in enumerate(data["slides"], start=1):
        stype = str(slide_data.get("type", "content")).lower()
        title = str(slide_data.get("title", ""))
        subtitle = str(slide_data.get("subtitle", ""))
        bullets = [str(b) for b in (slide_data.get("bullets") or [])]
        notes = str(slide_data.get("speaker_notes") or slide_data.get("notes") or "")
        highlight = [str(h) for h in (slide_data.get("highlight") or [])]

        s = prs.slides.add_slide(blank)
        dark = stype in dark_types
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = _rgb(t["dark_bg"] if dark else t["bg"])

        if dark:
            # ── dark cover / closing ──
            _add_rect(s, int(sw / 2 - 1.2 * 914400), int(3.30 * 914400), int(2.4 * 914400), int(0.04 * 914400), _rgb(t["accent"]))
            _add_text(s, 0.5, 1.4, 12.33, 1.6, title, 54, True, _rgb(t["accent"]),
                      t["font"], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            if subtitle:
                _add_text(s, 0.5, 3.6, 12.33, 1.2, subtitle, 22, False, _rgb(t["dark_text"]),
                          t["font"], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            kicker = deck_title if stype == "closing" else t["label"].upper()
            _add_text(s, 0.5, 5.1, 12.33, 0.6, kicker, 14, False, _rgb(t["muted"]),
                      t["font"], align=PP_ALIGN.CENTER)
        else:
            # ── light content / section / data / conclusion ──
            _accent_top_bar(s, sw, t)
            _add_text(s, 0.9, 0.45, 11.5, 1.0, title, 30, True, _rgb(t["primary"]), t["font"])
            if subtitle:
                _add_text(s, 0.9, 1.25, 11.5, 0.5, subtitle, 16, False, _rgb(t["muted"]), t["font"])

            if stype == "section":
                _add_text(s, 0.9, 2.9, 11.5, 1.2, title, 40, True, _rgb(t["primary"]), t["font"],
                          align=PP_ALIGN.CENTER)
                if subtitle:
                    _add_text(s, 0.9, 4.3, 11.5, 0.7, subtitle, 18, False, _rgb(t["muted"]), t["font"],
                              align=PP_ALIGN.CENTER)
            elif bullets:
                # responsive bullet cards: 3/4/5 per row; highlight key numbers
                n = len(bullets)
                col_w = {5: 2.14, 4: 2.78, 3: 3.7, 2: 5.75, 1: 11.6}.get(n, 3.7)
                gap = 0.22 if n >= 4 else 0.3
                x0 = (13.333 - (n * col_w + (n - 1) * gap)) / 2
                y_card, card_h = 2.15, 2.3
                if n <= 2:
                    y_card, card_h = 2.3, 3.4
                for idx, b in enumerate(bullets):
                    cx = x0 + idx * (col_w + gap)
                    big = any(h in b for h in highlight) or bool(re.fullmatch(
                        r"[\d.,%+\-\u2192\u2190\s/'\"]{2,}", b))
                    card = _add_rect(s, cx, y_card, col_w, card_h, _rgb(t["card"]),
                                     line=_rgb(t["card_line"]), rounded=True, radius=0.08)
                    _add_text(s, cx + 0.35, y_card + 0.28, col_w - 0.7, card_h - 0.5, b,
                              26 if big else 18, True, _rgb(t["accent"] if big else t["primary"]),
                              t["font"], anchor=MSO_ANCHOR.MIDDLE)
                    _add_rect(s, cx + 0.35, y_card + 0.22, 0.13, 0.13, _rgb(t["accent"]),
                              rounded=True, radius=0.5)

        _footer(s, i, total, deck_title, t)
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
    """Return a non-colliding filename by appending _2, _3, ... when needed."""
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
def gen_pptx(title: str, slides_json: str, output_dir: str = "", theme: str = "business") -> str:
    """Generate a styled PowerPoint (.pptx) deck from a slides JSON outline.

    Args:
        title: Deck title shown in the filename and slide footers.
        slides_json: JSON object with "title" and "slides". Each slide has
            "type" (title|section|content|data|conclusion|closing|image),
            "title", optional "subtitle", optional "bullets" (list of
            strings), optional "highlight" (list of substrings rendered as
            big accent numbers), and optional "speaker_notes".
        output_dir: Optional directory (inside the presentation output folder)
            to write the file. Created if it does not exist. Defaults to
            PRESENTATION_OUTPUT_DIR.
        theme: Named color palette — one of business (navy/gold),
            fashion (black/gold serif), tech (slate/cyan), health (teal),
            education (indigo/amber), minimal (monochrome). Default business.

    Returns:
        Absolute path to the generated .pptx file.
    """
    try:
        data = _parse_slides(slides_json)
        theme_key = _theme(theme)["label"]  # validate theme early
        target = _resolve_pptx_output(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        base_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.pptx"
        filename = _unique_pptx_path(target, base_name)
        path = _render_pptx(data, target, theme, filename=filename.name)
        return f"Created {path} with {len(data['slides'])} slides (theme={theme})"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating presentation: {e}"


# =============================================================================
# HTML deck (single-file, JS paging) + PDF deck (fpdf, one page per slide)
# =============================================================================

def _html_escape(text) -> str:
    import html as _html
    return _html.escape(str(text or ""), quote=True)


def _theme_css(t: dict) -> str:
    """Inline CSS for a theme (colors pulled from THEMES)."""
    return f"""
:root {{
  --primary: {t['primary']}; --accent: {t['accent']}; --accent-l: {t['accent_light']};
  --accent-d: {t['accent_dark']}; --bg: {t['bg']}; --card: {t['card']};
  --card-line: {t['card_line']}; --body: {t['body']}; --muted: {t['muted']};
  --dark-bg: {t['dark_bg']}; --dark-text: {t['dark_text']};
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: {t['font']}, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: var(--bg); color: var(--primary); }}
.slide {{ display: none; width: 100vw; height: 100vh; padding: 5vh 6vw; position: relative;
         overflow: hidden; }}
.slide.active {{ display: flex; flex-direction: column; }}
.slide.dark {{ background: var(--dark-bg); color: var(--dark-text); }}
.topbar {{ position: absolute; top: 0; left: 0; right: 0; height: 6px; display: flex; }}
.topbar i {{ flex: 1; }} .topbar i:nth-child(1) {{ background: var(--accent-l); }}
.topbar i:nth-child(2) {{ background: var(--accent); }}
.topbar i:nth-child(3) {{ background: var(--accent-d); }}
h2 {{ font-size: 30px; margin-bottom: 8px; }}
.sub {{ color: var(--muted); font-size: 17px; margin-bottom: 18px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 18px; flex: 1; align-content: flex-start; }}
.card {{ background: var(--card); border: 1px solid var(--card-line); border-radius: 16px;
         box-shadow: 0 6px 18px rgba(0,0,0,.08); padding: 22px; min-width: 240px; flex: 1;
         display: flex; align-items: center; gap: 12px; }}
.card .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--accent); flex: 0 0 auto; }}
.card span {{ font-size: 18px; font-weight: 600; }}
.card.big span {{ font-size: 30px; font-weight: 800; color: var(--accent); }}
.cover {{ text-align: center; }}
.cover .title {{ font-size: 52px; color: var(--accent); letter-spacing: .04em; }}
.cover .sub {{ font-size: 20px; margin-top: 14px; }}
.cover .kicker {{ font-size: 13px; letter-spacing: .22em; color: var(--muted); margin-bottom: 18px; }}
.goldline {{ width: 120px; height: 3px; background: linear-gradient(90deg, var(--accent-l), var(--accent), var(--accent-d)); margin: 22px auto; }}
.nav {{ display: flex; justify-content: space-between; align-items: center; margin-top: 14px; }}
.navbtn {{ padding: 10px 22px; border-radius: 999px; background: var(--primary); color: #fff;
          text-decoration: none; font-weight: 600; cursor: pointer; border: none; }}
.navbtn:hover {{ background: var(--accent); }}
.pageind {{ color: var(--muted); font-size: 14px; }}
.notes {{ margin-top: 12px; background: rgba(0,0,0,.04); border-left: 4px solid var(--accent);
         border-radius: 10px; padding: 10px 14px; color: var(--muted); font-size: 13px; }}
.dark .notes {{ background: rgba(255,255,255,.06); color: var(--dark-text); }}
"""


def _render_html_deck(data: dict, theme_name: str) -> str:
    """Render a single-file HTML deck (JS paging) from the slides JSON."""
    t = _theme(theme_name)
    deck_title = data.get("title", "Presentation")
    slides = data["slides"]
    total = len(slides)
    dark_types = {"title", "closing"}
    parts = []
    for i, s in enumerate(slides, start=1):
        stype = str(s.get("type", "content")).lower()
        dark = stype in dark_types
        title = _html_escape(s.get("title", ""))
        subtitle = _html_escape(s.get("subtitle", ""))
        bullets = [str(b) for b in (s.get("bullets") or [])]
        highlight = [str(h) for h in (s.get("highlight") or [])]
        notes = _html_escape(s.get("speaker_notes") or s.get("notes") or "")

        cls = "slide active" if i == 1 else "slide"
        if dark:
            cls += " dark"
        parts.append(f'<section class="{cls}">')
        if dark:
            kicker = _html_escape(deck_title if stype == "closing" else t["label"].upper())
            parts.append(f'<div class="cover"><div class="kicker">{kicker}</div>'
                         f'<div class="title">{title}</div>')
            if subtitle:
                parts.append(f'<div class="sub">{subtitle}</div>')
            parts.append('<div class="goldline"></div></div>')
        else:
            parts.append('<div class="topbar"><i></i><i></i><i></i></div>')
            parts.append(f'<h2>{title}</h2>')
            if subtitle:
                parts.append(f'<div class="sub">{subtitle}</div>')
            if bullets:
                parts.append('<div class="cards">')
                for b in bullets:
                    big = any(h in b for h in highlight) or bool(re.fullmatch(
                        r"[\d.,%+\-\u2192\u2190\s/'\"]{2,}", b))
                    parts.append(f'<div class="card{" big" if big else ""}><div class="dot"></div>'
                                 f'<span>{_html_escape(b)}</span></div>')
                parts.append('</div>')
        parts.append('<div class="nav">'
                     f'<button class="navbtn" onclick="go(-1)">← Prev</button>'
                     f'<span class="pageind">{i} / {total}</span>'
                     f'<button class="navbtn" onclick="go(1)">Next →</button>'
                     '</div>')
        if notes:
            parts.append(f'<div class="notes"><strong>Notes:</strong> {notes}</div>')
        parts.append('</section>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html_escape(deck_title)}</title>
<style>{_theme_css(t)}</style></head>
<body>
{''.join(parts)}
<script>
var slides = document.querySelectorAll('.slide'); var i = 0;
function show(n) {{ slides.forEach(function(s, k) {{ s.classList.toggle('active', k === n); }}); }}
function go(d) {{ i = Math.min(Math.max(i + d, 0), slides.length - 1); show(i); }}
document.addEventListener('keydown', function(e) {{ if (e.key === 'ArrowRight') go(1); if (e.key === 'ArrowLeft') go(-1); }});
show(0);
</script>
</body></html>"""


def _find_unicode_font(pdf) -> str:
    """Register a Unicode TTF on the fpdf instance; return the family name.

    Mirrors tools/native_impl._add_pdf_font: try common CJK-capable fonts,
    fall back to a built-in Latin font if none can be registered.
    """
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdf.add_font("DocFont", "", path)
            pdf.add_font("DocFont", "B", path)
            return "DocFont"
        except Exception:
            continue
    return "Helvetica"


def _render_pdf_deck(data: dict, output_dir: Path, theme_name: str, filename: str | None = None) -> Path:
    """Render a landscape PDF deck (one page per slide) using fpdf."""
    from fpdf import FPDF

    t = _theme(theme_name)
    deck_title = data.get("title", "Presentation")
    slides = data["slides"]
    total = len(slides)
    dark_types = {"title", "closing"}

    pdf = FPDF(orientation="L", unit="pt", format="A4")  # 842 x 595 pt
    pdf.set_auto_page_break(False)
    font_family = _find_unicode_font(pdf)

    def hexc(hx):
        hx = hx.lstrip("#")
        return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))

    def set_fill(hx):
        pdf.set_fill_color(*hexc(hx))

    for i, s in enumerate(slides, start=1):
        stype = str(s.get("type", "content")).lower()
        dark = stype in dark_types
        bullets = [str(b) for b in (s.get("bullets") or [])]
        highlight = [str(h) for h in (s.get("highlight") or [])]
        pdf.add_page()
        set_fill(t["dark_bg"] if dark else t["bg"])
        pdf.rect(0, 0, 842, 595, "F")

        if dark:
            pdf.set_text_color(*hexc(t["accent"]))
            pdf.set_font(font_family, "B", 40)
            pdf.multi_cell(0, 50, str(s.get("title", "")), align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(10)
            if s.get("subtitle"):
                pdf.set_text_color(*hexc(t["dark_text"]))
                pdf.set_font(font_family, "", 18)
                pdf.multi_cell(0, 26, str(s["subtitle"]), align="C")
        else:
            set_fill(t["accent_light"])
            pdf.rect(0, 0, 281, 5, "F")
            set_fill(t["accent"])
            pdf.rect(281, 0, 281, 5, "F")
            set_fill(t["accent_dark"])
            pdf.rect(562, 0, 280, 5, "F")
            pdf.set_text_color(*hexc(t["primary"]))
            pdf.set_font(font_family, "B", 24)
            pdf.multi_cell(0, 30, str(s.get("title", "")), new_x="LMARGIN", new_y="NEXT")
            if s.get("subtitle"):
                pdf.set_text_color(*hexc(t["muted"]))
                pdf.set_font(font_family, "", 13)
                pdf.multi_cell(0, 18, str(s["subtitle"]), new_x="LMARGIN", new_y="NEXT")
            n = len(bullets)
            if n:
                y = 110
                gap = 12
                card_h = 60 if n <= 2 else 90
                for b in bullets:
                    big = any(h in b for h in highlight) or bool(re.fullmatch(
                        r"[\d.,%+\-\u2192\u2190\s/'\"]{2,}", b))
                    set_fill(t["card"])
                    pdf.set_draw_color(*hexc(t["card_line"]))
                    pdf.rect(48, y, 746, card_h, "DF")
                    set_fill(t["accent"])
                    pdf.ellipse(66, y + (card_h - 10) / 2, 10, 10, "F")
                    pdf.set_text_color(*hexc(t["accent"] if big else t["primary"]))
                    pdf.set_font(font_family, "B", 22 if big else 15)
                    pdf.set_xy(88, y + (card_h - 14) / 2)
                    pdf.cell(690, 14, str(b)[:90])
                    y += card_h + gap
                    if y > 560:
                        break
        pdf.set_font(font_family, "", 10)
        pdf.set_text_color(*hexc(t["muted"]))
        pdf.set_xy(60, 570)
        pdf.cell(0, 10, f"{deck_title}", align="L")
        pdf.set_xy(700, 570)
        pdf.cell(90, 10, f"{i} / {total}", align="R")
        notes = s.get("speaker_notes") or s.get("notes") or ""
        if notes:
            pdf.set_font(font_family, "", 9)
            pdf.set_xy(60, 555)
            pdf.multi_cell(720, 11, str(notes)[:220], align="L")

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(deck_title)}.pdf"
    path = output_dir / filename
    pdf.output(str(path))
    return path


@tool
def gen_html_deck(title: str, slides_json: str, output_dir: str = "", theme: str = "business",
                  filename: str = "") -> str:
    """Generate a single-file themed HTML slide deck from a slides JSON outline.

    Args:
        title: Deck title (used in the HTML <title> and fallback filename).
        slides_json: JSON object with "title" and "slides" (same schema as
            gen_pptx: types title|section|content|data|conclusion|closing|image,
            optional bullets / highlight / speaker_notes).
        output_dir: Optional directory (inside the presentation output folder).
        theme: Named color palette (business|fashion|tech|health|education|minimal).
        filename: Optional explicit filename (must end .html).

    Returns:
        Absolute path to the generated .html file.
    """
    try:
        data = _parse_slides(slides_json)
        _theme(theme)
        target = _resolve_pptx_output(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        name = filename if filename and filename.endswith(".html") else \
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.html"
        path = _unique_pptx_path(target, name)
        path.write_text(_render_html_deck(data, theme), encoding="utf-8")
        return f"Created {path} with {len(data['slides'])} slides (theme={theme})"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating HTML deck: {e}"


@tool
def gen_pdf_deck(title: str, slides_json: str, output_dir: str = "", theme: str = "business",
                 filename: str = "") -> str:
    """Generate a themed PDF slide deck (one landscape page per slide) via fpdf.

    Args:
        title: Deck title (used in the fallback filename).
        slides_json: JSON object with "title" and "slides" (same schema as
            gen_pptx). CJK text is supported via a Unicode font.
        output_dir: Optional directory (inside the presentation output folder).
        theme: Named color palette (business|fashion|tech|health|education|minimal).
        filename: Optional explicit filename (must end .pdf).

    Returns:
        Absolute path to the generated .pdf file.
    """
    try:
        data = _parse_slides(slides_json)
        _theme(theme)
        target = _resolve_pptx_output(output_dir)
        name = filename if filename and filename.endswith(".pdf") else \
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.pdf"
        path = _render_pdf_deck(data, target, theme, filename=_unique_pptx_path(target, name).name)
        return f"Created {path} with {len(data['slides'])} slides (theme={theme})"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating PDF deck: {e}"
