#!/usr/bin/env python3
"""Build the docx deliverable from the one source of truth.

    python scripts/build_data_agent_docs.py

Reads `docs/system-architecture/data-agent.md` and writes:

* `docs/system-architecture/data-agent.docx` — the full document: headings, bullets, tables and
  the diagrams, in reading order.

Why generate instead of hand-maintaining a second copy: the markdown is what gets reviewed and
diffed. A hand-written docx drifts from it silently; a generated one cannot.

There used to be a generated deck (`.pptx`) here too. It was removed — python-pptx lays text out
with none of the care a document needs (CJK line breaking, column widths, overflow), and nobody
presented it. The "overview" the deck was for still exists as Part I of the markdown, which reads
fine anywhere and stays diffable.

Requires python-docx (present in the backend venv).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "system-architecture"
ASSETS = ROOT / "docs" / "assets"
SRC = DOCS / "data-agent.md"


# ─────────────────────────────────────────────────────────────── markdown slice
def parse(text: str) -> list[dict]:
    """A tiny markdown reader: headings, bullets, tables, images, paragraphs."""
    out: list[dict] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("```"):
            # 围栏内的东西是**字面**的：`# 注释` 不是标题、`| a | b |` 不是表格。
            # 2026-11-26 的 bug：docx 里多出一个 "grill · <key>" 一级标题，就是这条没做。
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append({"kind": "code", "lines": code})
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            out.append({"kind": "h", "level": len(m.group(1)), "text": m.group(2).strip()})
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)", line.strip())
        if m:
            out.append({"kind": "img", "alt": m.group(1), "src": m.group(2)})
            i += 1
            continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append({"kind": "table", "rows": rows})
            continue
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]).strip())
                i += 1
            out.append({"kind": "bullets", "items": items})
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip())
                i += 1
            out.append({"kind": "bullets", "items": items})
            continue
        if line.lstrip().startswith(">"):
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip().lstrip(">").strip())
                i += 1
            out.append({"kind": "quote", "text": " ".join(q for q in quote if q)})
            continue
        out.append({"kind": "p", "text": line.strip()})
        i += 1
    return out


def plain(text: str) -> str:
    """Markdown inline syntax off — what a slide/docx run actually shows."""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return text.strip()


def image_path(src: str) -> pathlib.Path | None:
    p = (SRC.parent / src).resolve()
    for cand in (p.with_suffix(".png"), p):
        if cand.exists():
            return cand
    return None


# ──────────────────────────────────────────────────────────────────────── docx

# ─────────────────────────────────────────────── 目录：书签 + 内部超链接（Word 里可点）
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("build_toc", pathlib.Path(__file__).with_name("build_toc.py"))
_toc = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_toc)

_hspec = _ilu.spec_from_file_location(
    "build_data_agent_html", pathlib.Path(__file__).with_name("build_data_agent_html.py"))
_html_builder = _ilu.module_from_spec(_hspec)
_hspec.loader.exec_module(_html_builder)


def _footer(doc, mark: str) -> None:
    """页脚：版本 · 日期 · 页码。页码用 `PAGE` 域，Word 里会随分页变。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    para = doc.sections[0].footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(f"{mark} · 第 ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    run._r.addnext(fld)
    para.add_run(" 页")
    for r in para.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = RGBColor(0x8A, 0x96, 0xA3)


def _slug(text: str) -> str:
    return _toc.slug(text)


def _bookmark(paragraph, name: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    bid = str(abs(hash(name)) % 100000)
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bid)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bid)
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _internal_link(paragraph, text: str, anchor: str, *, bold: bool = False, indent: int = 0) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), anchor)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    colour = OxmlElement("w:color"); colour.set(qn("w:val"), "1F4E79"); rpr.append(colour)
    ul = OxmlElement("w:u"); ul.set(qn("w:val"), "single"); rpr.append(ul)
    if bold:
        rpr.append(OxmlElement("w:b"))
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = ("    " * indent) + text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def build_docx(blocks: list[dict], out: pathlib.Path) -> str:
    from docx import Document
    from docx.shared import Inches, Pt

    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    mark = _html_builder.stamp(SRC.read_text(encoding="utf-8"))
    doc.core_properties.title = "Ontology Studio · 总文档（合并版）"
    doc.core_properties.comments = mark
    doc.core_properties.version = mark.split()[3] if len(mark.split()) > 3 else ""
    _footer(doc, mark)
    for b in blocks:
        if b["kind"] == "h":
            heading = doc.add_heading(plain(b["text"]), level=min(b["level"], 3))
            _bookmark(heading, _slug(b["text"]))
        elif b["kind"] == "p":
            doc.add_paragraph(plain(b["text"]))
        elif b["kind"] == "code":
            para = doc.add_paragraph()
            rows = [plain(x) for x in b["lines"]]
            for k, row in enumerate(rows):
                run = para.add_run(row)
                run.font.name = "Consolas"
                run.font.size = Pt(9)
                if k < len(rows) - 1:
                    run.add_break()
        elif b["kind"] == "quote":
            para = doc.add_paragraph(plain(b["text"]))
            para.style = doc.styles["Intense Quote"]
        elif b["kind"] == "bullets":
            for it in b["items"]:
                m = re.match(r"^\s*\[?\**([^\]]*?)\**\]?\(#([^)]+)\)\s*$", it.strip())
                if m:      # 目录项 → 内部超链接（Word 里点一下就跳到那一节）
                    para = doc.add_paragraph()
                    _internal_link(para, m.group(1).replace("**", ""), m.group(2),
                                   bold=it.strip().startswith("- **"), indent=0)
                else:
                    doc.add_paragraph(plain(it), style="List Bullet")
        elif b["kind"] == "table":
            rows = b["rows"]
            if not rows:
                continue
            cols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = "Light Grid Accent 1"
            for r, row in enumerate(rows):
                for c in range(cols):
                    table.cell(r, c).text = plain(row[c]) if c < len(row) else ""
        elif b["kind"] == "img":
            p = image_path(b["src"])
            if p:
                doc.add_picture(str(p), width=Inches(6.3))
    doc.save(str(out))
    return f"{out.name}: {len(doc.paragraphs)} paragraphs"


def main() -> int:
    if not SRC.is_file():
        print(f"no source at {SRC}", file=sys.stderr)
        return 2
    blocks = parse(SRC.read_text(encoding="utf-8"))
    print(build_docx(blocks, DOCS / "data-agent.docx"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
