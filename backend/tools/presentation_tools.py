"""
Presentation generation native tools: template-driven PPTX / HTML / PDF decks.

The deck pipeline (user's 4-step flow):
  1. ``doc_to_slides_outline`` — LLM turns a document into a 12–15 slide outline
  2. ``normalize_outline`` (services/deck_templates.py) — deterministic
     constraints: page clamp, bullet caps, auto-highlight of numbers
  3. ``gen_html_deck`` / ``doc_to_deck`` — HTML mirror of the template
  4. ``gen_pptx`` / ``doc_to_deck`` — PPTX rendered from the template file

Control model: the LLM decides *what* (content, faithfulness, emphasis); the
*template* (a real .pptx base file with themed masters/layouts, authored by
scripts/build_deck_templates.py) decides *how* (layout, colors, fonts); the
renderer is a pure function of (outline, template). That is what makes both
formats reproducible, controllable, and visually consistent.

gen_pptx / gen_html_deck / gen_pdf_deck keep their historical signatures
(slides JSON + theme name) so existing agents keep working; internally they
now render through the template system.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

from services.deck_templates import (
    DARK_KINDS,
    PALETTES,
    get_palette,
    get_template,
    list_templates as _list_templates,
    normalize_outline,
)

# Backward-compat alias (themes == template palettes).
THEMES: Dict[str, dict] = PALETTES

_OUTPUT_DIR = Path(os.getenv("PRESENTATION_OUTPUT_DIR", "/tmp/langconfig-tools/presentations"))

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")

MAX_DOC_CHARS = 150_000        # hard cap when reading a source document
MAX_LLM_INPUT_CHARS = 90_000   # what actually reaches the outline LLM


def _rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _theme(name: str) -> dict:
    """Palette for a template id (kept for backward compatibility)."""
    return get_palette(name)


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


# ── Low-level shape helpers (template-aware) ──────────────────────────────

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


# ── PPTX renderer (template layouts + placeholders) ───────────────────────

def _find_ph(slide, idx: int):
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == idx:
            return ph
    return None


def _remove_ph(slide, idx: int) -> None:
    ph = _find_ph(slide, idx)
    if ph is not None:
        ph._element.getparent().remove(ph._element)


def _fill_ph(slide, idx: int, text: str, size: int, bold: bool, color, font_name: str) -> None:
    ph = _find_ph(slide, idx)
    if ph is None or not text:
        return
    tf = ph.text_frame
    tf.word_wrap = True
    tf.text = text
    for para in tf.paragraphs:
        for run in para.runs:
            _set_font(run, size, bold, color, font_name, text)


def _fill_body_ph(slide, bullets: List[str], highlight: List[str], t: dict) -> None:
    """Fill the body placeholder with bullets (inherits the layout's bullets)."""
    ph = _find_ph(slide, 1)
    if ph is None:
        return
    tf = ph.text_frame
    tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(10)
        r = p.add_run()
        r.text = b
        big = any(h in b for h in highlight) or bool(re.fullmatch(
            r"[\d.,%+\-\u2192\u2190\s/'\"]{2,}", b))
        _set_font(r, 20 if big else 17, big, _rgb(t["accent"] if big else t["primary"]), t["font"], b)


def _draw_card_grid(slide, bullets: List[str], highlight: List[str], t: dict, data: bool) -> None:
    """Responsive card grid (used when bullets exceed the body placeholder, or
    for data slides). Big-number / highlight bullets become accent cards."""
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
        card = _add_rect(slide, cx, y_card, col_w, card_h, _rgb(t["card"]),
                         line=_rgb(t["card_line"]), rounded=True, radius=0.08)
        _add_text(slide, cx + 0.35, y_card + 0.28, col_w - 0.7, card_h - 0.5, b,
                  26 if big else 18, True, _rgb(t["accent"] if big else t["primary"]),
                  t["font"], anchor=MSO_ANCHOR.MIDDLE)
        _add_rect(slide, cx + 0.35, y_card + 0.22, 0.13, 0.13, _rgb(t["accent"]),
                  rounded=True, radius=0.5)


def _render_pptx(data: dict, template_spec: dict, output_dir: Path,
                 filename: str | None = None) -> Path:
    """Render the outline into the template's layouts (library-native themes)."""
    t = template_spec["palette"]
    fonts = template_spec["fonts"]
    layout_map = template_spec["layout_map"]
    cons = template_spec["constraints"]

    prs = Presentation(template_spec["template_file"])
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    sw = int(prs.slide_width)
    master = prs.slide_masters[0]

    deck_title = data.get("title", "Presentation")
    slides = data["slides"]
    total = len(slides)

    for i, s in enumerate(slides, start=1):
        kind = str(s.get("type", "content")).lower()
        title = str(s.get("title", ""))
        subtitle = str(s.get("subtitle", ""))
        bullets = [str(b) for b in (s.get("bullets") or [])]
        highlight = [str(h) for h in (s.get("highlight") or [])]
        notes = str(s.get("speaker_notes") or s.get("notes") or "")
        dark = kind in DARK_KINDS

        layout_idx = layout_map.get(kind, layout_map["content"])
        slide = prs.slides.add_slide(master.slide_layouts[layout_idx])

        # Title / subtitle placeholders (positions come from the template).
        if dark:
            _fill_ph(slide, 0, title, 40, True, _rgb(t["accent"]), fonts["latin"])
            if subtitle:
                _fill_ph(slide, 1, subtitle, 18, False, _rgb(t["dark_text"]), fonts["latin"])
        else:
            _fill_ph(slide, 0, title, 30, True, _rgb(t["primary"]), fonts["latin"])
            if subtitle and kind in {"section", "agenda"}:
                _fill_ph(slide, 1, subtitle, 16, False, _rgb(t["muted"]), fonts["latin"])

        # Body: placeholder when the content fits, card grid otherwise.
        if bullets and kind in {"content", "conclusion", "data", "timeline"}:
            use_grid = kind == "data" or len(bullets) > cons["bullets_max"]
            if use_grid:
                _remove_ph(slide, 1)
                _draw_card_grid(slide, bullets[: cons["max_cards"]], highlight, t, data=(kind == "data"))
            else:
                _fill_body_ph(slide, bullets, highlight, t)

        _footer(slide, i, total, deck_title, t)
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(deck_title)}.pptx"
    path = output_dir / filename
    prs.save(str(path))
    return path


def _agent_workspace_root(path: str) -> Optional[str]:
    """If ``path`` lives under an agent workspace, return that workspace root.

    Matches both layouts:
      - ``<base>/agents/<agent_id>/...``
      - ``<base>/projects/<x>/agents/<agent_id>/...``
    Returns None when the path is not inside an agent workspace.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part == "agents" and i + 1 < len(parts):
            return str(Path(*parts[: i + 2]))
    return None


def _resolve_pptx_output(output_dir: str, workspace_root: Optional[str] = None) -> Path:
    """Resolve the output directory and enforce the tool sandbox.

    Allowed roots:
      - the default tool-owned presentation directory (PRESENTATION_OUTPUT_DIR),
      - any agent workspace under the workspace base (e.g. an agent's
        ``generated/`` folder) — so decks land where the Files panel shows them.

    Relative names (e.g. ``generated`` or ``decks``) are treated as
    subdirectories: when ``workspace_root`` is known (the agent workspace the
    source document came from), they resolve against it — so a bare
    ``output_dir="generated"`` lands in that agent's ``generated/``. Without a
    workspace root they resolve under the default presentation directory.
    Arbitrary absolute server paths are rejected.
    """
    if output_dir and output_dir.strip():
        raw = output_dir.strip()
        p = Path(raw)
        if not p.is_absolute():
            if workspace_root:
                p = Path(workspace_root) / p
            else:
                p = _OUTPUT_DIR / p
        target = p.expanduser().resolve()
        allowed = [_OUTPUT_DIR.resolve()]
        try:
            from services.workspace_manager import get_workspace_manager
            allowed.append(Path(get_workspace_manager().base_dir).resolve())
        except Exception:  # noqa: BLE001 — fall back to the default dir only
            pass
        for root in allowed:
            try:
                target.relative_to(root)
                return target
            except ValueError:
                continue
        raise ValueError(
            f"output_dir must be inside the presentation output directory "
            f"({_OUTPUT_DIR}) or an agent workspace (generated/)"
        )
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
        theme: Named template palette — one of business (navy/gold),
            fashion (black/gold serif), tech (slate/cyan), health (teal),
            education (indigo/amber), minimal (monochrome). Default business.

    Returns:
        Absolute path to the generated .pptx file.
    """
    try:
        data = _parse_slides(slides_json)
        spec = get_template(theme)  # validate template early
        data, _warnings = normalize_outline(data, spec, clamp_pages=False)
        target = _resolve_pptx_output(output_dir)
        base_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.pptx"
        filename = _unique_pptx_path(target, base_name)
        path = _render_pptx(data, spec, target, filename=filename.name)
        return f"Created {path} with {len(data['slides'])} slides (template={theme})"
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
    """Inline CSS for a template palette (colors + fonts)."""
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


def _render_html_deck(data: dict, template_spec: dict) -> str:
    """Render a single-file HTML deck (JS paging) from the outline + template."""
    t = template_spec["palette"]
    deck_title = data.get("title", "Presentation")
    slides = data["slides"]
    total = len(slides)
    parts = []
    for i, s in enumerate(slides, start=1):
        stype = str(s.get("type", "content")).lower()
        dark = stype in DARK_KINDS
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
    """Register a Unicode TTF on the fpdf instance; return the family name."""
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

    t = get_palette(theme_name)
    deck_title = data.get("title", "Presentation")
    slides = data["slides"]
    total = len(slides)

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
        dark = stype in DARK_KINDS
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
        theme: Named template palette (business|fashion|tech|health|education|minimal).
        filename: Optional explicit filename (must end .html).

    Returns:
        Absolute path to the generated .html file.
    """
    try:
        data = _parse_slides(slides_json)
        spec = get_template(theme)
        data, _warnings = normalize_outline(data, spec, clamp_pages=False)
        target = _resolve_pptx_output(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        name = filename if filename and filename.endswith(".html") else \
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.html"
        path = _unique_pptx_path(target, name)
        path.write_text(_render_html_deck(data, spec), encoding="utf-8")
        return f"Created {path} with {len(data['slides'])} slides (template={theme})"
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
        theme: Named template palette (business|fashion|tech|health|education|minimal).
        filename: Optional explicit filename (must end .pdf).

    Returns:
        Absolute path to the generated .pdf file.
    """
    try:
        data = _parse_slides(slides_json)
        get_template(theme)
        data, _warnings = normalize_outline(data, get_template(theme), clamp_pages=False)
        target = _resolve_pptx_output(output_dir)
        name = filename if filename and filename.endswith(".pdf") else \
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(data.get('title', title))}.pdf"
        path = _render_pdf_deck(data, target, theme, filename=_unique_pptx_path(target, name).name)
        return f"Created {path} with {len(data['slides'])} slides (template={theme})"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating PDF deck: {e}"


# =============================================================================
# Document → outline → deck tools (the user's 4-step flow)
# =============================================================================

_DRAFT_SYSTEM_PROMPT = """You are a senior presentation designer. Turn the source document into a deck outline.

Output EXACTLY one JSON object with this schema (no markdown fences, no commentary):
{{
  "title": "<deck title>",
  "slides": [
    {{"type": "title", "title": "<deck title>", "subtitle": "<one-line summary>"}},
    {{"type": "agenda", "title": "Agenda", "bullets": ["<section 1>", ...]}},
    {{"type": "content", "title": "<one core idea>", "bullets": ["<3-5 bullets>"], "highlight": ["<key number substring>"], "speaker_notes": "<1-2 sentences>"}},
    {{"type": "data", "title": "<numbers topic>", "bullets": ["<≤6 KPI cards, e.g. '42% growth'>"]}},
    {{"type": "section", "title": "<new part>", "subtitle": "<optional>"}},
    {{"type": "timeline", "title": "<sequence>", "bullets": ["<≤6 ordered steps>"]}},
    {{"type": "quote", "title": "<punchy statement>"}},
    {{"type": "conclusion", "title": "Conclusion", "bullets": ["<2-4 takeaways>"]}},
    {{"type": "closing", "title": "Thank You", "subtitle": "<optional>"}}
  ]
}}

Slide types: title (cover), agenda (structure), section (part divider), content (one idea, 3–5 bullets),
data (KPIs/numbers, ≤6 cards), timeline (ordered steps), quote (single bold statement),
conclusion (takeaways), closing (last slide).

Rules:
- Produce {pages} slides total (cover + agenda + content + data + conclusion + closing included).
- Each bullet ≤ {bullet_max_chars} characters and ≤ 12 words.
- NEVER invent facts: every figure must come from the source document. Keep numbers and percentages.
- Content slides: one core idea each; data slides for anything number-heavy.
- Return ONLY the JSON object."""

_REFINE_SYSTEM_PROMPT = """You are a meticulous slide editor. Here is a draft deck outline JSON.
Refine it so the final deck is excellent:
- Punchier, concrete titles; remove fluff.
- Tight bullets (≤12 words each); keep every number accurate to the source.
- Keep 12–15 slides; cover first (type "title"), closing last (type "closing").
- Do not add facts that are not in the source.
Return ONLY the corrected JSON object with the exact same schema (no markdown fences)."""


def _resolve_doc_path(path: str) -> str:
    """Resolve a possibly-relative document path against known locations.

    Agents naturally pass paths relative to their workspace (e.g.
    ``upload/report.pdf`` — the sandbox tools resolve those against the agent
    workspace), while this tool executes in the backend process whose cwd is
    ``backend/``. Resolution order:
      1. absolute path that exists,
      2. path relative to the backend cwd,
      3. basename match inside any agent workspace ``upload/`` dir
         (``outputs/agents/*/upload`` and ``outputs/projects/*/agents/*/upload``).
    Returns the original path when nothing matches so the caller surfaces a
    clear error.
    """
    p = Path(path)
    if p.is_absolute() and p.exists():
        return str(p)
    if p.exists():
        return str(p.resolve())
    basename = p.name
    try:
        from services.workspace_manager import get_workspace_manager
        base = Path(get_workspace_manager().base_dir)
    except Exception:  # noqa: BLE001 — fall back to the conventional outputs root
        base = Path(__file__).resolve().parent.parent / "outputs"
    for pattern in ("agents/*/upload", "projects/*/agents/*/upload"):
        for upload_dir in base.glob(pattern):
            cand = upload_dir / basename
            if cand.exists():
                return str(cand)
    return str(p)


def _read_document_text(path: str) -> str:
    """Extract text from a .pdf / .docx / .md / .txt source document."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(str(p))
        try:
            return "\n\n".join(page.get_text("text") for page in doc)[:MAX_DOC_CHARS]
        finally:
            doc.close()
    if ext == ".docx":
        import docx as _docx
        d = _docx.Document(str(p))
        return "\n\n".join(par.text for par in d.paragraphs if par.text.strip())[:MAX_DOC_CHARS]
    if ext == ".pptx":
        ppt = Presentation(str(p))
        parts = []
        for slide in ppt.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    parts.append(shape.text)
        return "\n\n".join(parts)[:MAX_DOC_CHARS]
    # md / txt / anything else → plain UTF-8 read
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:MAX_DOC_CHARS]
    except Exception:
        return p.read_text(encoding="latin-1", errors="ignore")[:MAX_DOC_CHARS]


def _extract_json(text: Any) -> Optional[Dict[str, Any]]:
    s = str(text or "")
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(s[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _llm_outline(model, doc_text: str, title: str, template: Dict[str, Any],
                 pages: int) -> Dict[str, Any]:
    """Two LLM passes: draft (12–15 pages) then refine. Returns the JSON outline."""
    from langchain_core.messages import HumanMessage, SystemMessage

    cons = template["constraints"]
    target = max(cons["pages_min"], min(pages or cons["pages_max"], cons["pages_max"]))
    doc_snippet = doc_text[:MAX_LLM_INPUT_CHARS]
    draft_sys = _DRAFT_SYSTEM_PROMPT.format(
        pages=target,
        bullet_max_chars=cons["bullet_max_chars"],
    )
    draft = model.invoke([
        SystemMessage(content=draft_sys),
        HumanMessage(content=f"Document title: {title}\n\n--- Document ---\n{doc_snippet}"),
    ])
    outline = _extract_json(draft.content)
    if not outline:
        raise ValueError("the outline LLM did not return valid JSON")

    refined = model.invoke([
        SystemMessage(content=_REFINE_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(outline, ensure_ascii=False, indent=2)),
    ])
    refined_outline = _extract_json(refined.content)
    return refined_outline or outline


def _load_outline_model():
    from langgraph.llm import build_chat_model
    return build_chat_model(temperature=0)


@tool
def list_deck_templates() -> str:
    """List the available deck templates (theme + layout sets) with a short
    description of each, so the caller can pick one for doc_to_deck / gen_pptx."""
    rows = _list_templates()
    if not rows:
        return "No deck templates available."
    lines = ["## Deck templates", ""]
    for r in rows:
        has = "✓" if r["has_template_file"] else "✗ (template file missing)"
        lines.append(f"- **{r['id']}** — {r['name']}  [{has}]")
    return "\n".join(lines)


@tool
def doc_to_slides_outline(file_path: str, template: str = "business", pages: int = 0) -> str:
    """Turn a document (.md / .txt / .pdf / .docx) into a validated slides outline.

    Reads the document server-side, then runs two LLM passes (draft → refine)
    producing a 12–15 slide outline JSON. The outline is normalized against the
    selected template's constraints (page clamp, bullet caps, auto-highlight of
    key numbers). Feed the returned JSON into gen_html_deck / gen_pptx, or use
    doc_to_deck to render both formats in one call.

    Args:
        file_path: Absolute path of the source document.
        template: Template id (business|fashion|tech|health|education|minimal).
        pages: Target slide count (0 = template default, 12–15).

    Returns:
        The normalized outline as a JSON string.
    """
    try:
        spec = get_template(template)
        text = _read_document_text(_resolve_doc_path(file_path))
        if not text or not text.strip():
            return f"Error: could not extract text from {file_path}"
        title = Path(file_path).stem
        model = _load_outline_model()
        outline = _llm_outline(model, text, title, spec, pages)
        normalized, warnings = normalize_outline(outline, spec, clamp_pages=True)
        payload = {"outline": normalized, "warnings": warnings, "template": spec["id"]}
        return json.dumps(payload, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 — surface to the agent
        return f"Error generating outline: {e}"


@tool
def doc_to_deck(file_paths: str, template: str = "business", formats: str = "html,pptx",
                output_dir: str = "", pages: int = 0) -> str:
    """Convert one or more documents (.md / .txt / .pdf / .docx) into themed
    HTML + PPTX decks in a single call (batch supported).

    Pipeline: read each document → LLM outline (12–15 slides, draft → refine)
    → normalize against the template → render HTML (single file, no CDN) and
    PPTX (from the template's own layouts). With multiple documents, each doc
    becomes a section of one combined deck.

    Args:
        file_paths: JSON array of absolute document paths, e.g.
            '["/abs/doc1.md", "/abs/doc2.pdf"]' (a single path is fine too).
        template: Template id (business|fashion|tech|health|education|minimal).
        formats: Comma-separated outputs: html, pptx (pdf also supported).
        output_dir: Output directory (inside the presentation output folder).
        pages: Target slide count (0 = template default).

    Returns:
        Paths of the generated files.
    """
    try:
        spec = get_template(template)
        cons = spec["constraints"]
        try:
            paths = json.loads(file_paths) if isinstance(file_paths, str) else file_paths
        except json.JSONDecodeError:
            paths = [file_paths]
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in paths if str(p).strip()]
        if not paths:
            return "Error: no file_paths provided"

        model = _load_outline_model()
        # Resolve source docs (relative paths → agent workspace upload/), and
        # remember which agent workspace they came from so a bare relative
        # output_dir like "generated" lands in THAT agent's generated/ folder.
        resolved_paths = [_resolve_doc_path(p) for p in paths]
        workspace_root = None
        for rp in resolved_paths:
            wr = _agent_workspace_root(rp)
            if wr:
                workspace_root = wr
                break

        per_doc = []
        single = len(paths) == 1
        if single:
            # Content pages this doc may contribute (cover + closing are added
            # by the combined deck).
            alloc = pages or cons["pages_max"] - 2
        else:
            # Allocate the page budget across docs BEFORE outlining so the
            # combined deck fits the template's pages_max without truncation.
            structural = 2 + len(paths) + 1  # cover + agenda + N section + closing
            alloc = max(3, (cons["pages_max"] - structural) // len(paths))
        # The LLM also builds its own cover/agenda/closing (stripped on
        # combine), so ask for alloc + 3.
        target_per_doc = alloc + 3

        for p in resolved_paths:
            text = _read_document_text(p)
            if not text or not text.strip():
                return f"Error: could not extract text from {p}"
            title = Path(p).stem
            outline = _llm_outline(model, text, title, spec, target_per_doc)
            per_doc.append({"name": title, "outline": outline})

        # Combine into one deck: cover → agenda(docs) → per-doc section + slides → closing.
        combined: Dict[str, Any] = {
            "title": per_doc[0]["name"] if single else "Combined Deck",
            "slides": [
                {"type": "title", "title": per_doc[0]["outline"].get("title", per_doc[0]["name"]) if single
                 else "Combined Deck", "subtitle": "Generated from source documents"},
            ],
        }
        if not single:
            combined["slides"].append({
                "type": "agenda", "title": "Agenda",
                "bullets": [d["name"] for d in per_doc],
            })
        for i, d in enumerate(per_doc):
            if not single:
                combined["slides"].append({"type": "section", "title": d["name"]})
            content = [
                s for s in d["outline"].get("slides", [])
                # Per-doc structural slides are replaced by the combined
                # deck's own cover / agenda / closing.
                if s.get("type") not in {"title", "agenda", "closing"}
            ]
            # Cap this doc's contribution so every doc survives the clamp.
            combined["slides"].extend(content[:alloc])
        combined, warnings = normalize_outline(combined, spec, clamp_pages=True)

        target = _resolve_pptx_output(output_dir, workspace_root=workspace_root)
        target.mkdir(parents=True, exist_ok=True)
        base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(combined['title'])}"
        created: List[str] = []
        fmt_list = [f.strip().lower() for f in formats.split(",") if f.strip()]

        if "html" in fmt_list:
            html_path = _unique_pptx_path(target, f"{base}.html")
            html_path.write_text(_render_html_deck(combined, spec), encoding="utf-8")
            created.append(str(html_path))
        if "pptx" in fmt_list:
            pptx_path = _render_pptx(combined, spec, target, filename=f"{base}.pptx")
            created.append(str(pptx_path))
        if "pdf" in fmt_list:
            pdf_path = _render_pdf_deck(combined, target, spec["id"], filename=f"{base}.pdf")
            created.append(str(pdf_path))

        if not created:
            return f"Error: no recognized formats in {formats!r} (use html, pptx, pdf)"
        note = f" ({len(warnings)} normalization warnings)" if warnings else ""
        return "Created:\n" + "\n".join(f"- {p}" for p in created) + note
    except Exception as e:  # noqa: BLE001 — surface to the agent
        return f"Error generating deck: {e}"


def main() -> None:
    """Quick smoke test of the template renderers (no LLM)."""
    from services.deck_templates import list_templates
    print(list_templates())
    outline = {
        "title": "Smoke Test",
        "slides": [
            {"type": "title", "title": "Smoke Test", "subtitle": "Template pipeline"},
            {"type": "agenda", "title": "Agenda", "bullets": ["Intro", "Numbers", "Close"]},
            {"type": "content", "title": "Key Idea", "bullets": ["First point", "42% growth", "Third point"], "highlight": ["42%"]},
            {"type": "data", "title": "KPIs", "bullets": ["42% growth", "€1.2M revenue", "3.4x ROI"]},
            {"type": "closing", "title": "Thank You"},
        ],
    }
    spec = get_template("business")
    out = Path("/tmp/langconfig-tools/presentations")
    pptx = _render_pptx(outline, spec, out)
    html = out / "smoke.html"
    html.write_text(_render_html_deck(outline, spec), encoding="utf-8")
    print("pptx:", pptx)
    print("html:", html)


if __name__ == "__main__":
    main()
