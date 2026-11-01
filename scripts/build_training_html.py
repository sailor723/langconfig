#!/usr/bin/env python
"""Render the training run book to one self-contained HTML file.

Why HTML on top of the markdown:

* **Classroom projection.** A single file, no network, no markdown previewer, no
  font surprises — double-click and it fills a projector.
* **Print to PDF from the same source.** The stylesheet has a print block, so
  `Cmd-P → Save as PDF` from the browser gives the handout, with diagrams vector-
  sharp because the SVGs are inlined, not rasterised.
* **Nothing to keep in sync.** This reads `docs/tutorial/agent-training-runbook.md`
  and inlines the diagrams from `docs/assets/`. Edit the markdown, re-run,
  done — there is no second copy of the text.

Usage::

    cd <repo>
    backend/.venv/bin/python scripts/build_training_html.py
    # → docs/tutorial/agent-training-runbook.html

    backend/.venv/bin/python scripts/build_training_html.py --pdf
    # → ...runbook.html + ...runbook.pdf (A4, fonts ×0.6; --pdf-scale=0.75 to taste)

    backend/.venv/bin/python scripts/build_training_html.py --pdf \
        --src=docs/tutorial/training-day.md --out=docs/tutorial/training-day.html
    # any sibling doc, same stylesheet and PDF pipeline (0.75 reads better for a
    # one-page organizer sheet than the run book's 0.6)

    ... --pdf --pdf-font="Noto Serif CJK SC"
    # override the print CJK face. It must have TrueType (glyf) outlines — see
    # PDF_CJK_FONT. The build prints a warning if a CFF-outline font still got in.

Why the PDF pass picks its own CJK font (the short version):

    A PDF can carry correct Unicode text and still *look* like garbage, because
    display uses the embedded font program while copying uses the ToUnicode map.
    WeasyPrint writes PingFang/Hiragino (CFF outlines) as /FontFile3 /OpenType,
    which CoreGraphics — Preview, Quick Look, iOS — refuses to render: correct
    text layer, broken glyphs. Every font in the finished PDF must therefore be
    /FontFile2 (TrueType). The build checks and warns.

Hints for a live session:

* the tables of contents on the right links to every step;
* each step's heading carries its number, so you can call out "第 1.2 步" and
  everyone lands in the same place;
* the 「应该看到」 blocks are styled so a wrong result is obvious on screen.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "docs" / "tutorial" / "agent-training-runbook.md"
ASSETS = REPO / "docs" / "assets"
OUT = REPO / "docs" / "tutorial" / "agent-training-runbook.html"

CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#4f46e5; --bg:#ffffff; --soft:#f8fafc; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font: 16px/1.75 -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
.layout { display:grid; grid-template-columns: 1fr 300px; gap:48px; max-width:1180px; margin:0 auto; padding:56px 32px 120px; }
article { min-width:0; }
h1 { font-size:32px; line-height:1.3; margin:0 0 8px; letter-spacing:-.2px; }
h1 + blockquote { margin-top:20px; }
h2 { font-size:23px; margin:52px 0 14px; padding-top:18px; border-top:1px solid var(--line); }
h3 { font-size:18px; margin:32px 0 10px; }
h4 { font-size:16px; margin:24px 0 8px; color:#334155; }
p, li { color:#1e293b; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
blockquote { margin:18px 0; padding:14px 18px; background:var(--soft);
             border-left:3px solid var(--accent); border-radius:0 6px 6px 0; color:#334155; }
blockquote p { margin:6px 0; }
code { font: 13.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
       background:#f1f5f9; padding:2px 5px; border-radius:4px; color:#0f172a; }
pre { margin:16px 0; padding:14px 16px; background:#0f172a; border-radius:8px; overflow:auto; }
pre code { background:none; color:#e2e8f0; padding:0; font-size:13px; line-height:1.6; }
table { width:100%; border-collapse:collapse; margin:16px 0; font-size:14px; }
th, td { padding:8px 10px; border:1px solid var(--line); text-align:left; vertical-align:top; }
th { background:var(--soft); font-weight:600; }
hr { border:0; border-top:1px solid var(--line); margin:40px 0; }
/* diagrams are rendered at their natural size; cap them so a wide graph does
   not dominate the page — 70% of the column keeps them readable on a projector */
img { max-width:70%; height:auto; display:block; margin:20px auto; }
figure { margin:24px 0; }
figure svg { max-width:70%; height:auto; display:block; margin:0 auto; }
figcaption { font-size:.82em; color:#9aa4b2; text-align:center; margin-top:6px; }
figcaption { font-size:13px; color:var(--muted); margin-top:8px; }
nav { position:sticky; top:40px; align-self:start; font-size:13px; max-height:calc(100vh - 80px); overflow:auto; }
nav .title { font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-size:11px; margin-bottom:10px; }
nav a { display:block; padding:3px 0; color:#475569; }
nav a.h3 { padding-left:14px; color:#64748b; font-size:12.5px; }
nav a:hover { color:var(--accent); }
.badge { display:inline-block; font-size:11.5px; padding:2px 8px; border-radius:999px;
         background:#eef2ff; color:#4338ca; margin-left:6px; vertical-align:middle; }
@media print {
  .layout { display:block; max-width:none; padding:0; }
  nav { display:none; }
  h2 { break-after:avoid; page-break-after:avoid; }
  table, pre, blockquote, figure { break-inside:avoid; page-break-inside:avoid; }
  pre { background:#f8fafc; border:1px solid var(--line); }
  pre code { color:#0f172a; }
  a { color:inherit; }
}
"""


def inline_svgs(md: str) -> str:
    """Replace `![alt](assets/x.svg)` with the SVG's own markup.

    Inlined rather than linked so the file is genuinely one file: no missing-image
    boxes when it is mailed, projected from another machine, or printed.
    """
    def repl(m: re.Match) -> str:
        alt, rel = m.group(1), m.group(2)
        # The markdown lives in docs/tutorial/ and links `../assets/x.svg` so it
        # renders on GitHub; resolve against the assets dir either way.
        path = (ASSETS / Path(rel).name).resolve()
        if not path.exists():
            return m.group(0)
        svg = path.read_text(encoding="utf-8")
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
        return f'<figure>{svg}<figcaption>{html.escape(alt)}</figcaption></figure>'

    return re.sub(r"!\[([^\]]*)\]\((\.\./assets/[^)]+|assets/[^)]+)\)", repl, md)


def add_heading_ids(rendered_html: str) -> str:
    """Give every h1/h2/h3 an id so the sidebar and the markdown TOC can link.

    markdown-it does not emit ids (no slug plugin installed), and a 600-line run book
    is unusable in a session without a jump list. Slugs are derived from the heading
    text with a counter, because step titles repeat ("练习" appears many times).
    """
    seen: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        level, text = m.group(1), m.group(2)
        plain = re.sub(r"<[^>]+>", "", text).strip()
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", plain).strip("-").lower() or "s"
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        return f'<h{level} id="{slug}">{text}</h{level}>'

    return re.sub(r"<h([123])>(.*?)</h\1>", repl, rendered_html, flags=re.S)


def build_toc(rendered_html: str) -> str:
    items = []
    for level, anchor, text in re.findall(
        r'<h([23])[^>]*id="([^"]*)"[^>]*>(.*?)</h\1>', rendered_html, re.S
    ):
        label = re.sub(r"<[^>]+>", "", text).strip()
        cls = "h3" if level == "3" else ""
        items.append(f'<a class="{cls}" href="#{anchor}">{html.escape(label)}</a>')
    return '<nav><div class="title">Steps</div>' + "".join(items) + "</nav>"


def scale_fonts(css: str, scale: float) -> str:
    """Shrink every absolute font size in the stylesheet by `scale`.

    The classroom sheet and the handout want different sizes: 16px reads well on
    a projector, ~9.6px fits a printed page. Scaling the stylesheet (instead of
    shipping a second stylesheet) keeps one source of layout truth.
    """
    css = re.sub(
        r"font-size:\s*([\d.]+)px",
        lambda m: f"font-size:{float(m.group(1)) * scale:.2f}px",
        css,
    )
    css = re.sub(
        r"font:\s*([\d.]+)px/",
        lambda m: f"font: {float(m.group(1)) * scale:.2f}px/",
        css,
    )
    # diagrams are sized relative to the text, so they shrink with it
    for old, new in (
        ("img { max-width:70%", f"img {{ max-width:{70 * scale:.0f}%"),
        ("figure svg { max-width:70%", f"figure svg {{ max-width:{70 * scale:.0f}%"),
    ):
        css = css.replace(old, new)
    return css


PDF_PAGE_CSS = """
@page {
  size: A4;
  margin: 14mm 12mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages);
                   font-size: 8px; color: #94a3b8; }
}
"""

# Why the PDF asks for a different CJK family than the screen:
#
#   Screen: PingFang SC (what macOS and every Chinese reader here expects).
#   PDF:    Songti SC, because PingFang has **CFF outlines** and WeasyPrint 70 writes
#           those as /FontFile3 with /Subtype /OpenType around a bare `OTTO` CFF dump.
#           Chromium's pdf.js copes; CoreGraphics does not — Preview shows the Chinese
#           as garbage glyphs while the text layer still extracts fine, so a
#           text-extraction check says "the PDF is fine" and it isn't.
#
# Songti SC has TrueType (glyf) outlines, so its program lands as /FontFile2, which
# every viewer renders. It is also the conventional Chinese print face. Verified by
# OCR'ing the rendered page through PDFKit (PreView's own engine): PingFang → no
# Chinese recognised at all, Songti/Hei/Arial Unicode → recognised cleanly.
PDF_CJK_FONT = "Songti SC"


def pdf_page_css(cjk_font: str) -> str:
    """Stylesheet fragment for the PDF pass: A4 page box + embeddable CJK families.

    Both rules matter. The `body` one keeps body text out of CFF fonts; the `pre/code`
    one keeps *Chinese inside code blocks* out of the hand-written fallback Pango picks
    on its own (it chose Hannotate SC — also CFF — for every CJK character in a
    `<code>` span, which put garbage glyphs back in the one place people copy from).
    """
    return PDF_PAGE_CSS + f"""
body {{ font-family: "{cjk_font}", sans-serif; }}
pre, pre code, code, kbd {{ font-family: Menlo, "{cjk_font}", monospace; }}
"""


def fixup_svg_fonts(doc: str, cjk_font: str) -> str:
    """Give the inlined diagrams' `font-family="Menlo"` a CJK fallback, print copy only.

    Document CSS does not reach into an inline SVG here — WeasyPrint honours the
    presentation attribute, so `svg text {{ font-family: … }}` in the print stylesheet
    changed nothing (measured: PingFang still embedded). Every diagram in `docs/assets/`
    says `font-family="Menlo"`, and Menlo has no CJK, so each Chinese label fell through
    to the system default (PingFang, CFF outlines) and rendered as garbage in Preview
    while the rest of the page was fine. Rewriting the attribute to a font *list* keeps
    the diagram's Latin in Menlo and sends only its Chinese to the embeddable face.

    This runs on the print copy only, so the on-screen HTML keeps PingFang.
    """
    for quote in ('"', "'"):
        doc = doc.replace(f"font-family={quote}Menlo{quote}",
                          f"font-family={quote}Menlo, {cjk_font}, monospace{quote}")
    return doc


def warn_about_cff_fonts(pdf_path: Path) -> None:
    """Report fonts that will likely render as garbage in Preview / Adobe.

    A CFF-outline font embedded as /FontFile3 /OpenType is the specific combination
    CoreGraphics refuses. Nothing here can fix it — the point is to fail loudly at
    build time instead of finding out when someone opens the handout.
    """
    try:
        import pypdf
    except ImportError:
        return
    suspects = set()
    for page in pypdf.PdfReader(str(pdf_path)).pages:
        fonts = (page.get("/Resources") or {}).get("/Font")
        if not fonts:
            continue
        for ref in fonts.get_object().values():
            font = ref.get_object()
            descendants = font.get("/DescendantFonts")
            if not descendants:
                continue
            descriptor = descendants.get_object()[0].get_object().get("/FontDescriptor")
            if not descriptor:
                continue
            descriptor = descriptor.get_object()
            stream = descriptor.get("/FontFile3")
            if stream is None:
                continue
            stream = stream.get_object()
            if stream.get_data()[:4] == b"OTTO":
                suspects.add(str(font.get("/BaseFont")).split("+")[-1])
    if suspects:
        print(
            f"  ⚠️  {pdf_path.name}: CFF-outline fonts embedded as /FontFile3 "
            f"/OpenType — Preview and Adobe render these as garbage: "
            f"{', '.join(sorted(suspects))}\n"
            f"      fix: rebuild with --pdf-font=<a TrueType-outline CJK face>"
        )


def write_pdf(doc: str, scale: float, out: Path | None = None,
              cjk_font: str = PDF_CJK_FONT) -> Path | None:
    """Print the built document to A4 PDF with WeasyPrint.

    WeasyPrint rather than a headless browser: it renders the inlined SVG
    diagrams as vector art in one process, no browser sandbox to launch.
    """
    exe = shutil.which("weasyprint") or "/opt/homebrew/bin/weasyprint"
    if not Path(exe).exists():
        print("weasyprint not found — PDF skipped (brew install weasyprint)")
        return None

    out = out or OUT
    pdf_path = out.with_suffix(".pdf")
    tmp_html = out.with_suffix(".print.html")
    tmp_html.write_text(
        fixup_svg_fonts(
            scale_fonts(doc, scale).replace("</style>", f"{pdf_page_css(cjk_font)}</style>", 1),
            cjk_font,
        ),
        encoding="utf-8",
    )
    try:
        subprocess.run([exe, str(tmp_html), str(pdf_path)], check=True,
                       capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        print(f"weasyprint failed: {exc.stderr.strip()[-400:]}")
        return None
    finally:
        tmp_html.unlink(missing_ok=True)
    return pdf_path


def main() -> int:
    args = dict(a.split("=", 1) if "=" in a else (a, "") for a in sys.argv[1:] if a.startswith("--"))
    # --src=/--out= let the same stylesheet and PDF pipeline render a sibling doc
    # (e.g. training-day.md); with no flags this is still exactly the run book.
    src = Path(args["--src"]).resolve() if args.get("--src") else SRC
    out = Path(args["--out"]).resolve() if args.get("--out") else OUT
    if not src.exists():
        sys.exit(f"not found: {src}")
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        sys.exit("markdown-it-py missing: backend/.venv/bin/pip install markdown-it-py")

    md_text = inline_svgs(src.read_text(encoding="utf-8"))
    md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table")
    body = add_heading_ids(md.render(md_text))

    title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title_text = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else src.stem

    doc = f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title_text)}</title>
<style>{CSS}</style>
</head><body>
<div class="layout">
<article>{body}</article>
{build_toc(body)}
</div>
</body></html>
"""
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)}  ({len(doc)/1024:.1f} KB, diagrams inlined)")

    if "--pdf" in args:
        scale = float(args.get("--pdf-scale", 0.6))
        cjk_font = args.get("--pdf-font") or PDF_CJK_FONT
        pdf = write_pdf(doc, scale, out, cjk_font)
        if pdf:
            print(f"wrote {pdf.relative_to(REPO)}  ({pdf.stat().st_size/1024:.0f} KB, "
                  f"字号 ×{scale}, 中文字体 {cjk_font})")
            warn_about_cff_fonts(pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
