#!/usr/bin/env python3
"""Convert the LangConfig HTML slide deck into an editable .pptx.

Reads docs/system-architecture-slides.zh-CN.html (or any deck passed as argv[1])
and rebuilds every <section class="slide"> with native PowerPoint shapes:
text boxes, card rectangles, native tables, callouts, chips and bullet lists.
Mermaid diagrams become a labelled placeholder box (they cannot be reproduced
as editable native shapes).

Usage:
    python3 scripts/slides_to_pptx.py [input.html] [output.pptx]
"""

import math
import sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# ---------------------------------------------------------------------------
# Theme (mirrors the HTML deck's paper/clay palette)
# ---------------------------------------------------------------------------
INK = RGBColor.from_string("262522")      # near-black body text
INK2 = RGBColor.from_string("6B675D")     # muted body text
MUTED = RGBColor.from_string("938C7D")    # faint labels
CLAY = RGBColor.from_string("CC785C")     # accent
CLAY_D = RGBColor.from_string("D9896F")   # accent on dark backgrounds
PAPER = RGBColor.from_string("F5F4EF")    # slide background
PAPER2 = RGBColor.from_string("F7F4EC")   # row stripe
WHITE = RGBColor.from_string("FFFFFF")
LINE = RGBColor.from_string("E2DED2")     # card / table borders
DARK = RGBColor.from_string("1A1916")     # title slide background
CREAM = RGBColor.from_string("F0ECE1")
CREAMM = RGBColor.from_string("C9C2B2")

LATIN = "Arial"         # latin typeface
CJK = "Microsoft YaHei"  # east-asian typeface (falls back on mac to PingFang)
MONO = "Consolas"
TITLE_LATIN = "Georgia"

# Layout constants (16:9, 13.333 x 7.5 in)
PAGE_W = 13.333
PAGE_H = 7.5
MARGIN = 0.55
GAP = 0.08            # vertical gap between blocks
H_MAX = PAGE_H - 2 * MARGIN
W_MAX = PAGE_W - 2 * MARGIN

# Base font sizes (pt); scaled down together when a slide overflows
F = dict(kicker=9, title=22, lead=12, h3=13, para=11,
         card_t=11.5, card_b=10, table=9, rule=11, chip=9.5,
         code=8.5, list=10.5, mermaid=9.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def set_font(run, size, bold=False, italic=False, color=INK, mono=False,
             latin=None):
    """Configure a run's font, including the east-asian typeface for CJK."""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = MONO if mono else (latin or LATIN)
    # east-asian font so Chinese characters use the intended CJK face
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", MONO if mono else CJK)


def parse_runs(el):
    """Flatten an element into (text, bold, mono, italic) run tuples."""
    runs = []

    def walk(node, bold=False, mono=False, italic=False):
        if isinstance(node, NavigableString):
            text = str(node)
            if text:
                runs.append((text, bold, mono, italic))
            return
        name = node.name
        if name in ("b", "strong"):
            bold = True
        elif name in ("code", "pre"):
            mono = True
        elif name in ("i", "em"):
            italic = True
        elif name == "br":
            runs.append(("\n", bold, mono, italic))
            return
        for child in node.children:
            walk(child, bold, mono, italic)

    walk(el)
    return runs


def plain(el):
    """Plain normalized text of an element (used for tables / chips)."""
    return " ".join(el.get_text("", strip=True).split())


def cost(ch, mono):
    """Width cost of one character, in 'em' units."""
    if ch == " ":
        return 0.3
    if ord(ch) > 0x2E7F:      # CJK and beyond are full-width
        return 1.0
    return 0.62 if mono else 0.55


def est_lines(runs, font_pt, width_in):
    """Estimate wrapped line count for a run list inside a box."""
    if not runs or width_in <= 0.2:
        return 1
    width_pt = width_in * 72.0
    per_line = max(1.0, width_pt / font_pt)   # em-units that fit per line
    lines = 0
    for text, _b, mono, _i in runs:
        for seg in text.split("\n"):
            units = sum(cost(ch, mono) for ch in seg)
            lines += max(1, math.ceil(units / per_line)) if units else 1
    return lines


def est_height(runs, font_pt, width_in):
    """Estimated rendered height in inches for a run list."""
    lines = est_lines(runs, font_pt, width_in)
    return lines * font_pt * 1.32 / 72.0


def add_para(tf, runs, size, color=INK, first=False, space_after=2,
             align=None, mono_all=False, latin=None):
    """Add a paragraph with styled runs to a text frame."""
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    p.space_after = Pt(space_after)
    p.line_spacing = 1.15
    if align:
        p.alignment = align
    for text, bold, mono, italic in runs:
        r = p.add_run()
        r.text = text
        set_font(r, size, bold=bold, italic=italic, color=color,
                 mono=mono or mono_all, latin=latin)
    return p


def add_box(slide, x, y, w, h, fill, line_color=None, rounded=False,
            radius=0.08):
    """Add a (rounded) rectangle shape and return it."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        try:
            shape.adjustments[0] = radius
        except Exception:
            pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line_color is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line_color
        shape.line.width = Pt(0.75)
    shape.shadow.inherit = False
    return shape


def add_textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    """Add a text box with sensible defaults and return its text frame."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    return tf


# ---------------------------------------------------------------------------
# HTML -> block model
# ---------------------------------------------------------------------------
def extract_blocks(node):
    """Convert a section's child nodes into a flat list of layout blocks."""
    blocks = []

    def walk(container, out):
        for child in container.children:
            if not isinstance(child, Tag):
                continue
            cls = child.get("class") or []
            name = child.name
            if name == "div" and "grid" in cls:
                c1, c2 = split_grid(child)
                out.append(("cols", c1, c2))
            elif name == "div" and "card" in cls:
                h4 = child.find("h4")
                p = child.find("p")
                title = card_title(h4) if h4 else ""
                body = parse_runs(p) if p else []
                out.append(("card", title, body))
            elif name == "div" and "kicker" in cls:
                out.append(("kicker", plain(child)))
            elif name == "div" and "rule" in cls:
                out.append(("rule", parse_runs(child)))
            elif name == "div" and "chips" in cls:
                out.append(("chips", [plain(s) for s in child.find_all("span")]))
            elif name == "div" and "mermaid-wrap" in cls:
                out.append(("mermaid", None))
            elif name in ("h1", "h2"):
                out.append(("title", parse_runs(child)))
            elif name == "h3":
                out.append(("h3", parse_runs(child)))
            elif name == "p" and "lead" in cls:
                out.append(("lead", parse_runs(child)))
            elif name == "p":
                out.append(("para", parse_runs(child)))
            elif name == "table":
                out.append(("table", parse_table(child)))
            elif name == "pre" and "code" in cls:
                out.append(("code", plain(child)))
            elif name == "ul":
                out.append(("list", [parse_runs(li) for li in child.find_all("li")],
                           False))
            elif name == "ol":
                out.append(("list", [parse_runs(li) for li in child.find_all("li")],
                           True))
            elif isinstance(child, Tag):
                walk(child, out)   # generic wrapper -> recurse

    walk(node, blocks)
    return blocks


def card_title(h4):
    """Card heading: prefix the .num marker with a separator, e.g. '1 · UI'."""
    num = h4.find(class_="num")
    rest = "".join(h4.get_text("", strip=True).split())
    if num:
        n = num.get_text(strip=True)
        rest = rest[len(n):].strip()
        return f"{n} · {rest}".strip(" ·")
    return rest


def split_grid(grid):
    """Split a .grid container's children into two columns of blocks."""
    kids = [c for c in grid.children if isinstance(c, Tag)]
    if not kids:
        return [], []
    if len(kids) == 1:
        return extract_blocks(kids[0]), []
    half = (len(kids) + 1) // 2
    return extract_block_list(kids[:half]), extract_block_list(kids[half:])


def extract_block_list(kids):
    blocks = []
    for k in kids:
        blocks.extend(extract_blocks(k))
    return blocks


def parse_table(table):
    """Rows as list of lists of plain cell text; first row may be a header."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [plain(td) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# Measure + render
# ---------------------------------------------------------------------------
def block_height(b, width, scale):
    kind = b[0]
    if kind == "kicker":
        return 0.24
    if kind == "title":
        return 0.52
    if kind == "lead":
        return est_height(b[1], F["lead"] * scale, width) + 0.04
    if kind == "h3":
        return 0.30
    if kind == "para":
        return est_height(b[1], F["para"] * scale, width) + 0.04
    if kind == "card":
        _, title, body = b
        h = 0.14
        if title:
            h += 0.26
        if body:
            h += est_height(body, F["card_b"] * scale, width - 0.24)
        return h
    if kind == "table":
        return table_height(b[1], width, scale)
    if kind == "rule":
        return est_height(b[1], F["rule"] * scale, width - 0.3) + 0.24
    if kind == "chips":
        return chip_height(b[1], width, scale)
    if kind == "mermaid":
        return 0.55
    if kind == "code":
        return est_height([(b[1], False, True, False)], F["code"] * scale,
                          width - 0.2) + 0.22
    if kind == "list":
        _, items, ordered = b
        total = 0.06
        for item in items:
            total += est_height(item, F["list"] * scale, width - 0.35) + 0.05
        return total
    if kind == "cols":
        _, c1, c2 = b
        h1 = measure(c1, (width - 0.12) / 2, scale)
        h2 = measure(c2, (width - 0.12) / 2, scale)
        return max(h1, h2)
    return 0.3


def measure(blocks, width, scale):
    """Total height of a block list (inches)."""
    if not blocks:
        return 0
    return sum(block_height(b, width, scale) for b in blocks) + \
        GAP * (len(blocks) - 1)


def table_height(rows, width, scale):
    if not rows:
        return 0.3
    ncols = max(len(r) for r in rows)
    col_w = col_widths(rows, width)
    total = 0
    for i, row in enumerate(rows):
        max_lines = 1
        for j, cell in enumerate(row[:ncols]):
            runs = [(cell, False, False, False)]
            lines = est_lines(runs, F["table"] * scale, col_w[j] - 0.12)
            max_lines = max(max_lines, lines)
        total += max_lines * F["table"] * scale * 1.3 / 72 + 0.10
    return total


def col_widths(rows, width):
    """Column widths: first column wider, the rest share the remainder."""
    ncols = max(len(r) for r in rows)
    if ncols <= 1:
        return [width]
    first = min(2.1, width * 0.38)
    rest = (width - first) / (ncols - 1)
    return [first] + [rest] * (ncols - 1)


def chip_height(chips, width, scale):
    """Chips wrap onto multiple lines; estimate the wrapped height."""
    lines = 1
    cur = 0.0
    for c in chips:
        w = chip_width(c, scale)
        if cur + w > width:
            lines += 1
            cur = w
        else:
            cur += w
    return lines * (F["chip"] * scale * 1.3 / 72 + 0.14) + 0.05


def chip_width(text, scale):
    units = sum(cost(ch, False) for ch in text)
    return units * F["chip"] * scale / 72 + 0.26


def render_blocks(slide, blocks, x, y, width, scale, y_cap=None):
    """Draw blocks top-to-bottom; returns the final y position."""
    for b in blocks:
        y += GAP
        y = render_block(slide, b, x, y, width, scale)
        if y_cap and y > y_cap:
            return y
    return y


def render_block(slide, b, x, y, width, scale):
    kind = b[0]
    if kind == "kicker":
        tf = add_textbox(slide, x, y, width, 0.26)
        add_para(tf, [(b[1], True, False, False)], F["kicker"] * scale,
                 color=CLAY, first=True, space_after=0)
        return y + 0.24
    if kind == "title":
        tf = add_textbox(slide, x, y, width, 0.6)
        add_para(tf, b[1], F["title"] * scale, color=INK, first=True,
                 space_after=0)
        return y + 0.52
    if kind == "lead":
        tf = add_textbox(slide, x, y, width, est_height(b[1], F["lead"] * scale, width) + 0.05)
        add_para(tf, b[1], F["lead"] * scale, color=INK2, first=True,
                 space_after=0)
        return y + est_height(b[1], F["lead"] * scale, width) + 0.04
    if kind == "h3":
        tf = add_textbox(slide, x, y, width, 0.32)
        add_para(tf, b[1], F["h3"] * scale, color=INK, first=True, space_after=0)
        return y + 0.30
    if kind == "para":
        h = est_height(b[1], F["para"] * scale, width)
        tf = add_textbox(slide, x, y, width, h + 0.05)
        add_para(tf, b[1], F["para"] * scale, color=INK2, first=True,
                 space_after=0)
        return y + h + 0.04
    if kind == "card":
        _, title, body = b
        h = block_height(b, width, scale)
        add_box(slide, x, y, width, h, WHITE, line_color=LINE, rounded=True)
        tf = add_textbox(slide, x + 0.14, y + 0.05, width - 0.28, h - 0.1)
        if title:
            add_para(tf, [(title, True, False, False)], F["card_t"] * scale,
                     color=INK, first=True, space_after=2)
        if body:
            add_para(tf, body, F["card_b"] * scale, color=INK2, space_after=0)
        return y + h
    if kind == "table":
        h = table_height(b[1], width, scale)
        render_table(slide, b[1], x, y, width, h, scale)
        return y + h
    if kind == "rule":
        h = block_height(b, width, scale)
        add_box(slide, x, y, width, h, WHITE, line_color=LINE, rounded=True)
        add_box(slide, x, y + 0.06, 0.06, h - 0.12, CLAY)   # left accent bar
        tf = add_textbox(slide, x + 0.2, y + 0.05, width - 0.35, h - 0.1)
        add_para(tf, b[1], F["rule"] * scale, color=INK2, first=True,
                 space_after=0)
        return y + h
    if kind == "chips":
        return render_chips(slide, b[1], x, y, width, scale)
    if kind == "mermaid":
        add_box(slide, x, y, width, 0.5, PAPER2, line_color=LINE, rounded=True)
        tf = add_textbox(slide, x, y, width, 0.5, anchor=MSO_ANCHOR.MIDDLE)
        add_para(tf, [("（Mermaid 图 — 详见 HTML 原稿）", False, False, True)],
                 F["mermaid"] * scale, color=MUTED, first=True,
                 align=PP_ALIGN.CENTER, space_after=0)
        return y + 0.55
    if kind == "code":
        h = block_height(b, width, scale)
        add_box(slide, x, y, width, h, WHITE, line_color=LINE, rounded=True)
        tf = add_textbox(slide, x + 0.14, y + 0.07, width - 0.28, h - 0.14)
        add_para(tf, [(b[1], False, True, False)], F["code"] * scale,
                 color=INK, first=True, space_after=0, mono_all=True)
        return y + h
    if kind == "list":
        _, items, ordered = b
        h = block_height(b, width, scale)
        tf = add_textbox(slide, x, y, width, h)
        for i, item in enumerate(items):
            prefix = f"{i + 1:02d}  " if ordered else "•  "
            runs = [(prefix, True, False, False)] + item
            add_para(tf, runs, F["list"] * scale, color=INK2,
                     first=(i == 0), space_after=3)
        return y + h
    if kind == "cols":
        _, c1, c2 = b
        col_w = (width - 0.12) / 2
        h1 = measure(c1, col_w, scale)
        h2 = measure(c2, col_w, scale)
        render_blocks(slide, c1, x, y, col_w, scale)
        if c2:
            render_blocks(slide, c2, x + col_w + 0.12, y, col_w, scale)
        return y + max(h1, h2)
    return y


def render_table(slide, rows, x, y, width, height, scale):
    ncols = max(len(r) for r in rows)
    nrows = len(rows)
    tbl_shape = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y),
                                       Inches(width), Inches(height))
    tbl = tbl_shape.table
    widths = col_widths(rows, width)
    for j, w in enumerate(widths):
        tbl.columns[j].width = Inches(w)
    for i, row in enumerate(rows):
        # treat first row as header only if all cells are short labels
        header = i == 0 and all(len(c) <= 14 for c in row)
        for j in range(ncols):
            text = row[j] if j < len(row) else ""
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = CLAY if header else (WHITE if i % 2 else PAPER2)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = text
            set_font(r, F["table"] * scale, bold=header,
                     color=WHITE if header else INK)


def render_chips(slide, chips, x, y, width, scale):
    chip_h = F["chip"] * scale * 1.3 / 72 + 0.14
    cur_x, cur_y = x, y
    max_y = y
    for c in chips:
        w = chip_width(c, scale)
        if cur_x + w > x + width:
            cur_x = x
            cur_y += chip_h + 0.05
        add_box(slide, cur_x, cur_y, w, chip_h, WHITE, line_color=LINE,
                rounded=True, radius=0.5)
        tf = add_textbox(slide, cur_x, cur_y, w, chip_h,
                         anchor=MSO_ANCHOR.MIDDLE)
        add_para(tf, [(c, False, False, False)], F["chip"] * scale,
                 color=INK2, first=True, align=PP_ALIGN.CENTER, space_after=0)
        cur_x += w
        max_y = max(max_y, cur_y + chip_h)
    return max_y


# ---------------------------------------------------------------------------
# Title slide (dark, centered)
# ---------------------------------------------------------------------------
def build_title_slide(slide, section):
    add_box(slide, 0, 0, PAGE_W, PAGE_H, DARK)   # full-bleed dark background
    kicker = section.find(class_="kicker")
    h1 = section.find("h1")
    tline = section.find(class_="tline")
    chips = [plain(s) for s in section.find_all(class_="chip")]
    tfoot = section.find(class_="tfoot")

    y = 1.7
    if kicker:
        tf = add_textbox(slide, 1.5, y, PAGE_W - 3, 0.4)
        add_para(tf, [(plain(kicker), True, False, False)],
                 F["kicker"] * 1.2, color=CLAY_D, first=True,
                 align=PP_ALIGN.CENTER, space_after=0)
        y += 0.5
    if h1:
        tf = add_textbox(slide, 1.5, y, PAGE_W - 3, 1.2)
        add_para(tf, [(h1.get_text(strip=True), True, False, False)],
                 40, color=CREAM, first=True, align=PP_ALIGN.CENTER,
                 space_after=0, latin=TITLE_LATIN)
        y += 1.15
    if tline:
        runs = parse_runs(tline)
        h = est_height(runs, 14, PAGE_W - 5) + 0.05
        tf = add_textbox(slide, 2.5, y, PAGE_W - 5, h)
        add_para(tf, runs, 14, color=CREAMM, first=True,
                 align=PP_ALIGN.CENTER, space_after=0)
        y += h + 0.5
    if chips:
        render_chips_centered(slide, chips, y)
        y += chip_height(chips, PAGE_W - 3, 1.0) + 0.6
    if tfoot:
        tf = add_textbox(slide, 1.5, PAGE_H - 1.0, PAGE_W - 3, 0.4)
        add_para(tf, [(plain(tfoot), False, False, False)], 9,
                 color=MUTED, first=True, align=PP_ALIGN.CENTER, space_after=0)


def render_chips_centered(slide, chips, y):
    """Center a row of chips around the horizontal middle of the slide."""
    width = PAGE_W - 3
    total = sum(chip_width(c, 1.0) for c in chips)
    x = (PAGE_W - total) / 2
    render_chips(slide, chips, x, y, total, 1.0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build(src_path, dst_path):
    html = Path(src_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.select("section.slide")
    print(f"Parsed {len(sections)} slides from {src_path}")

    prs = Presentation()
    prs.slide_width = Inches(PAGE_W)
    prs.slide_height = Inches(PAGE_H)
    blank = prs.slide_layouts[6]

    for i, section in enumerate(sections):
        slide = prs.slides.add_slide(blank)
        # paper background
        bg = add_box(slide, 0, 0, PAGE_W, PAGE_H, PAPER)
        bg.name = f"bg{i}"

        if "dark" in (section.get("class") or []):
            build_title_slide(slide, section)
            continue

        blocks = extract_blocks(section)
        if not blocks:
            continue

        # auto-fit: shrink fonts until the block stack fits the slide
        scale = 1.0
        while measure(blocks, W_MAX, scale) > H_MAX and scale > 0.55:
            scale -= 0.05

        render_blocks(slide, blocks, MARGIN, MARGIN, W_MAX, scale)
        print(f"  [{i + 1:02d}] {section.get('data-title', '')}  (scale {scale:.2f})")

    prs.core_properties.title = "LangConfig 系统架构"
    prs.core_properties.author = "LangConfig"
    prs.save(dst_path)
    print(f"Saved: {dst_path}  ({len(sections)} slides)")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else \
        "docs/system-architecture-slides.zh-CN.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else \
        "docs/system-architecture-slides.zh-CN.pptx"
    build(src, dst)
