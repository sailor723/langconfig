#!/usr/bin/env python3
"""把一份定稿渲染成 `.docx` —— **给人看的那一份**。

为什么 md 之外还要 docx:
  · `.md` 在应用内没法上色(`MarkdownBody` 不开内联 HTML,正文是第三方文本,不许执行),
    而「谁说的」这件事必须一眼看出来:客户原文 / 业务方补 / HR 补 / 我方建议,四者混在一张表里
    只靠文字区分,读者会看漏 —— 看漏的后果就是把某个人的补充当成客户的要求。
  · 业务方和 HR 真正会打开的是 Word,不是 markdown 源码。

所以分工是:**md 是数据源(可 diff、可门禁),docx 是呈现层**。两者同一份数据生成,不会分叉。

颜色约定(和图例一起印在正文最前面,不靠读者猜):
    客户原文   黑
    业务方补   蓝   #1F4E79
    HR 补      紫   #7030A0
    我方建议   灰斜体 #808080  —— 它不是任何人的要求,只是供反驳的草稿
    缺失       红   #C00000

用法:
    python -m scripts.talent.render_jd_docx --jd 品质经理
"""
from __future__ import annotations

import argparse
import json
import pathlib

import yaml
from docx import Document
from docx.shared import Pt, RGBColor

from scripts.talent.jd_template_loader import load as load_template, role_of
from scripts.talent.requirement_matrix import DIM as DIM_NAMES, build_rows, cv_total as mx_cv_total

ROOT = pathlib.Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "work" / "talent" / "jd_template.yaml"
DOCS = ROOT / "work" / "talent" / "jd_docs"
LINKS = ROOT / "work" / "talent" / "jd_links"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"

#: 来源 → (颜色, 是否斜体)。见模块开头:颜色是给人看的判据,不是装饰。
SOURCE_STYLE = {
    "client":   (RGBColor(0x00, 0x00, 0x00), False, "客户原文"),
    "business": (RGBColor(0x1F, 0x4E, 0x79), False, "业务方补充"),
    "hr":       (RGBColor(0x70, 0x30, 0xA0), False, "HR 补充"),
    "ours":     (RGBColor(0x80, 0x80, 0x80), True,  "我方建议"),
    "missing":  (RGBColor(0xC0, 0x00, 0x00), False, "缺失"),
}
OWNER_CN = {"business": "业务方", "hr": "HR"}   # 客户即业务方


def _write(cell, text: str, source: str, *, bold: bool = False) -> None:
    """往单元格写一段带来源配色的文字。空单元格也要写 —— 空的看不出是"没有"还是"漏了"。"""
    color, italic, _ = SOURCE_STYLE[source]
    para = cell.paragraphs[0] if not cell.paragraphs[0].runs else cell.add_paragraph()
    run = para.add_run(str(text))
    run.font.size = Pt(9)
    run.font.color.rgb = color
    run.italic = italic
    if bold:
        run.bold = True


def _header_row(table, labels: list[str]) -> None:
    for i, label in enumerate(labels):
        cell = table.rows[0].cells[i]
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(9)


def build(jd: str) -> pathlib.Path:
    link = yaml.safe_load((LINKS / f"{jd}.yaml").read_text(encoding="utf-8"))
    role, role_basis = role_of(link)
    if role is None:
        raise SystemExit(f"NOT RUN — {jd}:{role_basis}。先定 S1.11 岗位类别再出 docx。")
    tpl = load_template(role)
    fields_doc = json.loads((DOCS / f"{jd}.fields.json").read_text(encoding="utf-8"))
    fields = fields_doc["fields"]
    proposals = {p["code"]: p for p in fields_doc.get("proposals") or []}
    library = yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    hr_reqs = [r for r in library["requirements"] if str(r["id"]).startswith("REQ-HR-")]

    doc = Document()

    # ── 标题 + 图例 ────────────────────────────────────────────
    doc.add_heading(f"{jd} · 职务说明书(定稿)", level=0)
    doc.add_paragraph(
        f"来源:{link.get('source_file', '')}　·　客户原文 {len([c for c in link['citations'] if c.get('origin') == 'client'])} 条"
        f"　·　我方建议 {len(proposals)} 项　·　HR 补充要求 {len(hr_reqs)} 条"
    )
    legend = doc.add_paragraph()
    legend.add_run("颜色图例:").bold = True
    for key in ("client", "business", "hr", "ours", "missing"):
        color, italic, label = SOURCE_STYLE[key]
        run = legend.add_run(f"　▪ {label}")
        run.font.color.rgb = color
        run.italic = italic
    doc.add_paragraph(
        "客户原文可逐字回查到原文行号;业务方 / HR 的补充是正式内容但来源不同;"
        "我方建议未经确认不得使用,只在附录 F 与这里以灰斜体标出。"
    ).runs[0].font.size = Pt(9)

    # ── S1–S8:表格型字段 ───────────────────────────────────────
    for section in tpl["sections"]:
        doc.add_heading(f"{section['code']} {section['title']}", level=1)
        rows = section["fields"]
        table = doc.add_table(rows=1, cols=6)
        table.style = "Table Grid"
        _header_row(table, ["码", "字段", "内容", "状态", "谁填", "来源"])
        for f in rows:
            code = f["code"]
            got = fields.get(code) or {}
            value = got.get("value")
            status = got.get("status") or "JD 未写"
            row = table.add_row().cells
            _write(row[0], code, "client")
            _write(row[1], f["label"], "client")
            if code in set(tpl["not_applicable"]):
                why = str(f.get("why") or "").replace("**本版不适用**:", "").strip()
                _write(row[2], "—", "missing")
                _write(row[3], "本版不适用", "missing")
                _write(row[4], why[:40], "missing")
                _write(row[5], "—", "missing")
            elif code in proposals:
                # 我方建议:灰斜体,读的人一眼知道"这不是客户写的"
                _write(row[2], proposals[code]["value"], "ours")
                _write(row[3], "我方建议", "ours")
                _write(row[4], "—", "ours")
                _write(row[5], "我方建议", "ours")
            elif status == "不适用":
                _write(row[2], "—", "missing")
                _write(row[3], "不适用", "missing")
                _write(row[4], "—", "missing")
                _write(row[5], "—", "missing")
            elif value in (None, "", []):
                _write(row[2], "(客户未写)", "missing")
                _write(row[3], "缺失", "missing")
                _write(row[4], OWNER_CN.get(str(f.get("owner")), "—"), "missing")
                _write(row[5], "—", "missing")
            elif status == "我方填补":
                # 客户没写、我方按依据填的 —— 灰斜体,和"客户原文"必须一眼分开
                _write(row[2], str(value), "ours")
                _write(row[3], "我方填补", "ours")
                _write(row[4], OWNER_CN.get(str(f.get("owner")), "—"), "ours")
                _write(row[5], "我方填补(须确认)" if "须客户确认" in str(got.get("note") or "") else "我方填补", "ours")
            else:
                _write(row[2], str(value), "client")
                _write(row[3], "有值", "client")
                _write(row[4], "—", "client")
                _write(row[5], "客户原文", "client")

    # ── S3 任职资格:一张「维度 → 组件」矩阵(行数据与 md 共用)────
    doc.add_heading("S3 任职资格(维度 → 组件)", level=1)
    doc.add_paragraph(
        "一行 = 一条要求。组件是判人时真正要比对的东西;没有组件的行是区间/枚举类,直接比属性。"
        f"持有 = 持有份数 / {mx_cv_total(catalog)} 份简历。"
    ).runs[0].font.size = Pt(9)
    reqs = {r["id"]: r for r in library["requirements"]}
    atts = {a["id"]: a for a in catalog["attributes"]}
    comp_label = {c["id"]: c.get("label") or c["id"] for c in catalog["components"]}
    cites = link.get("citations") or []
    rows = build_rows(link, reqs, atts, comp_label, catalog, origin="client")
    t = doc.add_table(rows=1, cols=7)
    t.style = "Table Grid"
    _header_row(t, ["维度", "要求 / 组件", "客户原话", "行", "怎么判", "可判", "持有"])
    for d in "ABCDEFGHI":
        dim_rows = [r for r in rows if r["dim"] == d]
        if not dim_rows:
            row = t.add_row().cells
            _write(row[0], f"{d} {DIM_NAMES[d]}", "missing")
            _write(row[1], "本岗位未提", "missing")
            for i in range(2, 7):
                _write(row[i], "", "missing")
            continue
        for r in dim_rows:
            row = t.add_row().cells
            src = "client" if r["assessable"] else "missing"
            _write(row[0], f"{d} {DIM_NAMES[d]}", "client")
            _write(row[1], r["need"], "client")
            _write(row[2], f"「{r['verbatim']}」", "client")
            _write(row[3], str(r["line"]), "client")
            _write(row[4], r["how"], src)
            _write(row[5], "是" if r["assessable"] else "否", src)
            _write(row[6], r["holds"], "client")
    n_ok = sum(1 for r in rows if r["assessable"])
    doc.add_paragraph(f"合计 {len(rows)} 条 · 可判 {n_ok} · 判不了 {len(rows) - n_ok}"
                      "(判不了的照样留着,理由见「怎么判」列)").runs[0].font.size = Pt(9)

    # ── HR 招聘补充要求:正式内容,紫色 ──────────────────────────
    doc.add_heading("HR 招聘补充要求(正式内容,来源:HR)", level=1)
    doc.add_paragraph(
        "这些不是客户写的要求,是 HR 从招聘视角提出的。它们与客户要求同等参与判定,"
        "但必须写明是谁提的、为什么提 —— 否则下一个人会把它们当成客户的意思。"
    ).runs[0].font.size = Pt(9)
    t = doc.add_table(rows=1, cols=4)
    t.style = "Table Grid"
    _header_row(t, ["要求", "内容", "本 JD 是否已并入", "缺什么"])
    cited_hr = {c.get("requirement") for c in cites if c.get("origin") == "hr"}
    for r in hr_reqs:
        row = t.add_row().cells
        _write(row[0], r["id"], "hr")
        _write(row[1], str(r.get("name") or ""), "hr")
        _write(row[2], "已并入" if r["id"] in cited_hr else "未并入", "hr")
        _write(row[3], str(r.get("note") or "")[:120] or "—", "hr")

    # ── 附录 F 我方建议:灰斜体 ─────────────────────────────────
    doc.add_heading("附录 F · 我方建议(不是客户原文,未经确认不得使用)", level=1)
    if proposals:
        for p in proposals.values():
            para = doc.add_paragraph()
            run = para.add_run(f"{p['code']} {p['label']} — {p['value']}")
            run.font.color.rgb = SOURCE_STYLE["ours"][0]
            run.italic = True
            basis = doc.add_paragraph()
            r2 = basis.add_run(f"推导依据:{p.get('basis', '')}")
            r2.font.size = Pt(9)
            r2.italic = True
    else:
        doc.add_paragraph("(无)")

    out = DOCS / f"{jd}.定稿.docx"
    doc.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    args = ap.parse_args()
    if not (DOCS / f"{args.jd}.fields.json").is_file():
        print(f"先跑 render_jd_final --jd {args.jd}")
        return 2
    out = build(args.jd)
    print(f"写出 {out.relative_to(ROOT)}  ({out.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
