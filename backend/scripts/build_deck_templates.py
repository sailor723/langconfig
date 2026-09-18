#!/usr/bin/env python3
"""Build themed .pptx template files (masters + layouts) for the deck pipeline.

Each template = one .pptx base file whose *theme* (colors, fonts) and
*layouts* (cover / section / content / data / closing) are authored here with
python-pptx, then saved under backend/templates/decks/. Generation later opens
the template file and fills its layouts — the library-native theme/layout
system the deck pipeline is built on.

    cd backend && .venv/bin/python scripts/build_deck_templates.py            # all
    cd backend && .venv/bin/python scripts/build_deck_templates.py business    # one

Idempotent: re-running overwrites the files.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches  # noqa: E402
from lxml import etree  # noqa: E402

from services.deck_templates import (  # noqa: E402
    DARK_KINDS,
    TEMPLATES_DIR,
    TEMPLATE_SPECS,
)

_EMU_IN = 914400


def _rgb(hex_str: str) -> RGBColor:
    hex_str = (hex_str or "#000000").lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


# ── Theme part edits (clrScheme / fontScheme) ─────────────────────────────

def _theme_root(prs: Presentation):
    """The theme part's XML root (a:officeTheme), read from its blob.

    python-pptx has no dedicated XML wrapper for the theme part in 1.0.x, so
    we parse the part blob with lxml, edit clrScheme/fontScheme, and write the
    serialized XML back through ``_blob``.
    """
    from lxml import etree
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    master = prs.slide_masters[0]
    part = master.part.part_related_by(RT.THEME)
    return etree.fromstring(part.blob), part


def _set_theme_colors(prs: Presentation, palette: dict) -> None:
    """Rewrite the a:clrScheme of the theme part from the palette.

    Library-native theming: placeholder text that does not set an explicit
    color inherits these theme colors, so the whole deck follows the palette.
    """
    theme, part = _theme_root(prs)
    theme_elements = theme.find(qn("a:themeElements"))
    clr_scheme = theme_elements.find(qn("a:clrScheme")) if theme_elements is not None else None
    if clr_scheme is None:
        return
    mapping = {
        "dk1": palette["primary"],       # darkest text
        "lt1": palette["bg"],            # lightest background
        "dk2": palette["body"],          # secondary text
        "lt2": palette["card"],          # light fill
        "accent1": palette["accent"],
        "accent2": palette["accent_light"],
        "accent3": palette["accent_dark"],
        "accent4": palette["muted"],
        "accent5": palette["muted"],
        "accent6": palette["card_line"],
        "hlink": palette["accent"],
        "folHlink": palette["accent_dark"],
    }
    for tag, hexval in mapping.items():
        el = clr_scheme.find(qn(f"a:{tag}"))
        if el is None:
            continue
        # Replace any existing srgbClr/sysClr child with our srgbClr.
        for child in list(el):
            el.remove(child)
        srgb = etree.SubElement(el, qn("a:srgbClr"))
        srgb.set("val", hexval.lstrip("#"))
    part._blob = etree.tostring(theme, xml_declaration=True, encoding="UTF-8", standalone=True)


def _set_theme_fonts(prs: Presentation, fonts: dict) -> None:
    """Set the theme font scheme (latin + CJK 'ea') for major/minor fonts."""
    theme, part = _theme_root(prs)
    theme_elements = theme.find(qn("a:themeElements"))
    font_scheme = theme_elements.find(qn("a:fontScheme")) if theme_elements is not None else None
    if font_scheme is None:
        return
    for scope in ("majorFont", "minorFont"):
        node = font_scheme.find(qn(f"a:{scope}"))
        if node is None:
            continue
        for tag, typeface in (("latin", fonts["latin"]), ("ea", fonts["cjk"]), ("cs", fonts["latin"])):
            el = node.find(qn(f"a:{tag}"))
            if el is not None:
                el.set("typeface", typeface)
    part._blob = etree.tostring(theme, xml_declaration=True, encoding="UTF-8", standalone=True)


# ── Master text styles (cascade to every layout/slide) ────────────────────

def _set_def_rpr(lvl, size, bold, color_hex, fonts) -> None:
    """Set the default run properties on an a:lvlXpPr node."""
    def_rpr = lvl.find(qn("a:defRPr"))
    if def_rpr is None:
        def_rpr = lvl.makeelement(qn("a:defRPr"), {})
        lvl.append(def_rpr)
    def_rpr.set("sz", str(size))
    def_rpr.set("spc", "0")
    if bold:
        def_rpr.set("b", "1")
    else:
        def_rpr.set("b", "0")
    for tag in ("a:solidFill", "a:latin", "a:ea", "a:cs"):
        el = def_rpr.find(qn(tag))
        if el is not None:
            def_rpr.remove(el)
    solid = def_rpr.makeelement(qn("a:solidFill"), {})
    clr = solid.makeelement(qn("a:srgbClr"), {"val": color_hex.lstrip("#")})
    solid.append(clr)
    latin = def_rpr.makeelement(qn("a:latin"), {"typeface": fonts["latin"]})
    ea = def_rpr.makeelement(qn("a:ea"), {"typeface": fonts["cjk"]})
    cs = def_rpr.makeelement(qn("a:cs"), {"typeface": fonts["latin"]})
    def_rpr.append(solid)
    def_rpr.append(latin)
    def_rpr.append(ea)
    def_rpr.append(cs)


def _set_master_text_styles(master, palette: dict, fonts: dict) -> None:
    """Style the master's title/body txStyles so all layouts inherit them."""
    tx_styles = master.element.find(qn("p:txStyles"))
    if tx_styles is None:
        return
    title_style = tx_styles.find(qn("p:titleStyle"))
    body_style = tx_styles.find(qn("p:bodyStyle"))
    if title_style is not None:
        lvl1 = title_style.find(qn("a:lvl1pPr"))
        if lvl1 is not None:
            _set_def_rpr(lvl1, 3000, True, palette["primary"], fonts)
    if body_style is not None:
        for i, tag in enumerate(("a:lvl1pPr", "a:lvl2pPr", "a:lvl3pPr"), start=1):
            lvl = body_style.find(qn(tag))
            if lvl is not None:
                _set_def_rpr(lvl, 1800 - (i - 1) * 100, False, palette["body"], fonts)


# ── Layout restyling ───────────────────────────────────────────────────────

def _clear_placeholders(layout, keep_idx: set) -> None:
    for ph in list(layout.placeholders):
        if ph.placeholder_format.idx not in keep_idx:
            ph._element.getparent().remove(ph._element)


def _move_placeholder(layout, idx: int, x, y, w, h) -> None:
    for ph in layout.placeholders:
        if ph.placeholder_format.idx == idx:
            ph.left, ph.top, ph.width, ph.height = Inches(x), Inches(y), Inches(w), Inches(h)
            ph.text_frame.word_wrap = True
            return


def _add_rect(layout, x, y, w, h, color_hex, rounded=False) -> None:
    """Append a rectangle shape to a LAYOUT's spTree via raw XML.

    python-pptx's LayoutShapes is read-only (no add_shape), so decoration
    shapes on layouts are injected directly into the spTree.
    """
    from lxml import etree
    from pptx.util import Inches as _In  # noqa: F401 (Emu math below)

    sp_tree = layout._element.find(qn("p:cSld")).find(qn("p:spTree"))
    sp = etree.SubElement(sp_tree, qn("p:sp"))
    nv_sp_pr = etree.SubElement(sp, qn("p:nvSpPr"))
    c_nv_pr = etree.SubElement(nv_sp_pr, qn("p:cNvPr"))
    c_nv_pr.set("id", str(900 + len(sp_tree)))
    c_nv_pr.set("name", f"deco_{len(sp_tree)}")
    etree.SubElement(nv_sp_pr, qn("p:cNvSpPr"))
    sp_pr = etree.SubElement(sp, qn("p:spPr"))
    xfrm = etree.SubElement(sp_pr, qn("a:xfrm"))
    off = etree.SubElement(xfrm, qn("a:off"))
    off.set("x", str(int(Inches(x))))
    off.set("y", str(int(Inches(y))))
    ext = etree.SubElement(xfrm, qn("a:ext"))
    ext.set("cx", str(int(Inches(w))))
    ext.set("cy", str(int(Inches(h))))
    geom = etree.SubElement(sp_pr, qn("a:prstGeom"))
    geom.set("prst", "roundRect" if rounded else "rect")
    etree.SubElement(geom, qn("a:avLst"))
    fill = etree.SubElement(sp_pr, qn("a:solidFill"))
    srgb = etree.SubElement(fill, qn("a:srgbClr"))
    srgb.set("val", color_hex.lstrip("#"))
    ln = etree.SubElement(sp_pr, qn("a:ln"))
    etree.SubElement(ln, qn("a:noFill"))


def _accent_top_strip(layout, palette: dict) -> None:
    sw = 13.333
    third = sw / 3
    for i, cname in enumerate(("accent_light", "accent", "accent_dark")):
        _add_rect(layout, i * third, 0, third, 0.07, palette[cname])


def _restyle_layout(layout, kind: str, palette: dict, fonts: dict) -> None:
    dark = kind in DARK_KINDS
    layout.background.fill.solid()
    layout.background.fill.fore_color.rgb = _rgb(palette["dark_bg" if dark else "bg"])

    if kind in {"title", "closing"}:
        _clear_placeholders(layout, {0, 1})
        _move_placeholder(layout, 0, 0.6, 2.35, 12.13, 1.6)
        _move_placeholder(layout, 1, 0.6, 4.15, 12.13, 0.9)
        # accent underline below the title
        _add_rect(layout, 5.47, 3.95, 2.4, 0.05, palette["accent"])
    elif kind in {"section", "agenda"}:
        _clear_placeholders(layout, {0, 1})
        _move_placeholder(layout, 0, 0.9, 2.55, 11.5, 1.3)
        _move_placeholder(layout, 1, 0.9, 3.95, 11.5, 0.8)
        _accent_top_strip(layout, palette)
    elif kind == "quote":
        _clear_placeholders(layout, {0})
        _move_placeholder(layout, 0, 0.9, 2.9, 11.5, 1.8)
        _accent_top_strip(layout, palette)
    else:  # content / data / timeline / conclusion
        _clear_placeholders(layout, {0, 1})
        _move_placeholder(layout, 0, 0.9, 0.45, 11.5, 1.0)
        _move_placeholder(layout, 1, 0.9, 1.95, 11.5, 4.9)
        _accent_top_strip(layout, palette)


# ── Build ─────────────────────────────────────────────────────────────────

def build_template(template_id: str) -> Path:
    spec = TEMPLATE_SPECS[template_id]
    palette, fonts, layout_map = spec["palette"], spec["fonts"], spec["layout_map"]

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    _set_theme_colors(prs, palette)
    _set_theme_fonts(prs, fonts)
    master = prs.slide_masters[0]
    _set_master_text_styles(master, palette, fonts)

    # kind → layout index (dedupe kinds sharing a layout).
    for kind, idx in layout_map.items():
        layout = master.slide_layouts[idx]
        _restyle_layout(layout, kind, palette, fonts)

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{template_id}.pptx"
    prs.save(str(path))
    return path


# ── Preview mode: render one demo deck into every template ────────────────

_SAMPLE_OUTLINE = {
    "title": "Template Preview",
    "slides": [
        {"type": "title", "title": "Template Preview", "subtitle": "Business deck — 12–15 pages, themed layouts"},
        {"type": "agenda", "title": "Agenda", "bullets": ["Overview", "Key Numbers", "Roadmap", "Conclusion"]},
        {"type": "content", "title": "Core Idea", "bullets": [
            "One core idea per slide, 3–5 bullets",
            "Revenue grew 42% this quarter",
            "Every figure comes from the source document",
            "Bullets are clamped to fit the layout",
        ], "highlight": ["42%"]},
        {"type": "data", "title": "Key Numbers", "bullets": [
            "42% growth", "€1.2M revenue", "3.4x ROI", "18 new markets",
        ]},
        {"type": "timeline", "title": "Roadmap", "bullets": [
            "Q1 — Research", "Q2 — Pilot", "Q3 — Launch", "Q4 — Scale",
        ]},
        {"type": "quote", "title": "“Clarity beats cleverness.”"},
        {"type": "conclusion", "title": "Conclusion", "bullets": [
            "Controlled output, every run", "Same deck in HTML and PPTX",
        ]},
        {"type": "closing", "title": "Thank You", "subtitle": "Generated with LangConfig"},
    ],
}


def preview_template(template_id: str) -> Path:
    """Render the sample outline into one template → preview .pptx + .html."""
    from tools.presentation_tools import _render_html_deck, _render_pptx

    spec = TEMPLATE_SPECS[template_id]
    preview_dir = TEMPLATES_DIR / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = _render_pptx(_SAMPLE_OUTLINE, spec, preview_dir, filename=f"{template_id}.pptx")
    html_path = preview_dir / f"{template_id}.html"
    html_path.write_text(_render_html_deck(_SAMPLE_OUTLINE, spec), encoding="utf-8")
    return pptx_path


def build_gallery() -> Path:
    """A single gallery.html that iframes every template's HTML preview."""
    preview_dir = TEMPLATES_DIR / "previews"
    cards = []
    for tid in sorted(TEMPLATE_SPECS):
        spec = TEMPLATE_SPECS[tid]
        html_file = preview_dir / f"{tid}.html"
        if not html_file.exists():
            preview_template(tid)
        cards.append(
            f'<section style="margin:16px"><h2 style="font-family:sans-serif">'
            f'{spec["name"]} <code style="color:#888">{tid}</code></h2>'
            f'<iframe src="{tid}.html" style="width:100%;height:420px;border:1px solid #ddd;border-radius:8px"></iframe>'
            f'<p><a href="{tid}.pptx" download>Download {tid}.pptx</a></p></section>'
        )
    gallery = preview_dir / "gallery.html"
    gallery.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Deck template gallery</title></head>"
        f"<body style='background:#f5f5f5;margin:0'>{''.join(cards)}</body></html>",
        encoding="utf-8",
    )
    return gallery


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    preview_only = "--preview" in sys.argv
    targets = args or sorted(TEMPLATE_SPECS)
    for tid in targets:
        if tid not in TEMPLATE_SPECS:
            print(f"✗ unknown template {tid!r}; known: {sorted(TEMPLATE_SPECS)}")
            return 1
        if preview_only:
            path = preview_template(tid)
            print(f"✓ preview {tid}: {path}")
            continue
        path = build_template(tid)
        print(f"✓ {tid}: {path}")
    if preview_only:
        gallery = build_gallery()
        print(f"✓ gallery: {gallery}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
