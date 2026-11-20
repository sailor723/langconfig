#!/usr/bin/env python3
"""把 Neo4j 里的用例 1 画成一张图 —— 9 个维度全部在场,包括这个 JD 没碰到的 4 个。

为什么要单独写这个脚本,而不是随手 dot:第一版只画了"JD 的要求能走到"的 5 个维度,
于是 F 资质证书 / G 合规约束 / H 语言 / I 身体条件 从图上消失了。
**一个维度没被这份 JD 用到,和这个维度不存在,是两件事** —— 图上必须能看出区别,
否则下一个人会以为能力全集只有 5 类。

所以每个维度都是一个 cluster,内容取自 `component_catalog.yaml`,与任何 JD 无关;
JD 的部分叠加在上面。没被用到的维度画成灰色虚线,标「本 JD 未涉及」。

用法:
    python -m scripts.talent.render_graph --profile features/ontology/profiles/talent_v1/talent_v1_settings.json
    ... --open        (渲染后直接打开 SVG)
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LINK = ROOT / "work" / "talent" / "jd_links" / "品质经理.yaml"
OUT = ROOT / "work" / "talent" / "graph"

FONT = "PingFang SC"
GREY = "#b0b0b0"
USED_FILL = "white"


def _id(prefix: str, value: str) -> str:
    return f'{prefix}_{abs(hash(value)) % 100000}_{value.translate(str.maketrans("", "", ".-+/ ()"))[:14]}'


def build(catalog: dict, link: dict) -> str:
    reqs = link["requirements"]
    dims = catalog["dimensions"]
    atts = catalog["attributes"]
    cats = catalog["categories"]
    comps = {c["id"]: c for c in catalog["components"]}

    # 这份 JD 用到了哪些维度 / 属性 / 组件
    att_by_id = {a["id"]: a for a in atts}
    used_dims, used_atts, used_comps = set(), set(), set()
    for r in reqs:
        if r.get("attribute"):
            att = att_by_id.get(r["attribute"])
            if att:
                used_dims.add(att["dimension"])
                used_atts.add(att["id"])
        if r.get("dimension"):
            used_dims.add(r["dimension"])
        for c in r.get("components") or []:
            used_comps.add(c)
            used_dims.add("D")

    L = [
        "digraph talent {",
        '  rankdir=LR; compound=true; splines=true; nodesep=0.14; ranksep=0.85;',
        f'  graph [fontname="{FONT}", bgcolor="white", fontsize=11];',
        f'  node  [fontname="{FONT}", fontsize=9, shape=box, style="rounded,filled", fillcolor="{USED_FILL}", color="#888888"];',
        f'  edge  [fontname="{FONT}", fontsize=7, arrowsize=0.55];',
        "",
        "  // ── 能力全集:9 个维度,每个一个 cluster。与任何 JD 无关。",
    ]

    for dim in dims:
        did = dim["id"]
        used = did in used_dims
        style = "rounded" if used else "rounded,dashed"
        color = "#4a7ba7" if used else GREY
        tag = "" if used else "  · 本 JD 未涉及"
        L.append(f"  subgraph cluster_{did} {{")
        L.append(f'    label="{did} {dim["label"]}{tag}"; fontsize=10; '
                 f'color="{color}"; style="{style}"; fontcolor="{"#1a1a1a" if used else GREY}";')
        L.append(f'    {_id("dim", did)} [label="{did} {dim["label"]}", shape=box, style="bold,rounded", '
                 f'fillcolor="{"#d6e4f0" if used else "#f2f2f2"}", color="{color}", fontsize=10];')
        if did == "D":
            for cat in cats:
                hit = any(comps[c]["category"] == cat["id"] for c in used_comps)
                cid = _id("cat", cat["id"])
                L.append(f'    {cid} [label="{cat["label"]}\\n({cat["component_count"]})", '
                         f'fillcolor="{"#eaeaea" if not hit else "#e8eef5"}", '
                         f'color="{GREY if not hit else "#7a9cc0"}", fontsize=8];')
                L.append(f"    {did} -> {cid} [style=invis];")
        else:
            for att in atts:
                if att["dimension"] != did:
                    continue
                hit = att["id"] in used_atts
                aid = _id("att", att["id"])
                L.append(f'    {aid} [label="{att["id"]} {att["label"]}", '
                         f'fillcolor="{"#d8efd8" if hit else USED_FILL}", '
                         f'color="{"#2e7d32" if hit else "#bbbbbb"}", fontsize=8];')
                L.append(f"    {did} -> {aid} [style=invis];")
        L.append("  }")
        L.append("")

    L.append("  // ── 这份 JD 实际要求的组件(叶子)")
    for cid in sorted(used_comps):
        nid = _id("comp", cid)
        L.append(f'  {nid} [label="{comps[cid]["label"]}", fillcolor="#ffd9d9", color="#c62828", fontsize=8];')
        cat = _id("cat", comps[cid]["category"])
        L.append(f"  {cat} -> {nid} [color=\"#c62828\", style=dotted, arrowhead=none];")
    L.append("")

    L.append("  // ── JD 与它的 10 条要求")
    jd = _id("jd", link["jd"])
    L.append(f'  {jd} [label="JD\\n{link["jd"]}", shape=note, fillcolor="#ffe6a7", '
             f'color="#b8860b", fontsize=11];')
    for r in reqs:
        q = _id("req", r["id"])
        # 用原句当标签(截断),不用行号 —— 行号是机读锚点,不是给眼睛看的
        txt = (r.get("source_text") or r.get("verbatim") or "").strip().rstrip("；。")
        if len(txt) > 16:
            txt = txt[:16] + "…"
        L.append(f'  {q} [label="{r["id"]}\\n{txt}", fillcolor="#dce9f7", '
                 f'color="#4a7ba7", fontsize=8];')
        L.append(f"  {jd} -> {q} [color=\"#4a7ba7\"];")
        if r.get("attribute"):
            L.append(f'  {q} -> {_id("att", r["attribute"])} [color="#2e7d32", label="约束"];')
        elif r.get("dimension"):
            L.append(f'  {q} -> {_id("dim", r["dimension"])} [color="#8e24aa", style=dashed, '
                     f'label="只到维度"];')
        for c in r.get("components") or []:
            L.append(f'  {q} -> {_id("comp", c)} [color="#c62828"];')
    L.append("")

    L.append("  // ── 候选人(只画这次进图的 5 个)")
    import os
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
            cands = s.run("MATCH (c:Candidate)-[:HAS_COMPONENT]->(k:Component) "
                          "RETURN c.id AS id, collect(k.id) AS comps ORDER BY size(comps) DESC").data()
    finally:
        driver.close()
    for row in cands:
        nid = _id("cand", row["id"])
        short = row["id"].replace("cand_", "")
        L.append(f'  {nid} [label="{short[:20]}\\n{len(row["comps"])} 个组件", shape=ellipse, '
                 f'fillcolor="#e8f5e9", color="#1b5e20", fontsize=8];')
        for c in row["comps"]:
            L.append(f'  {nid} -> {_id("comp", c)} [color="#1b5e20", style=dashed, arrowhead=none];')
    L.append("}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="uc1", help="输出文件名(不含扩展名)")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    link = yaml.safe_load(LINK.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)

    dot_text = build(catalog, link)
    dot_path = OUT / f"{args.name}.dot"
    dot_path.write_text(dot_text, encoding="utf-8")

    used = {r.get("attribute") for r in link["requirements"] if r.get("attribute")}
    used |= {r.get("dimension") for r in link["requirements"] if r.get("dimension")}
    dims = catalog["dimensions"]
    touched = {d["id"] for d in dims
               if d["id"] in used or any(c["dimension"] == d["id"] for c in catalog["attributes"]
                                         if c["id"] in used) or d["id"] == "D"}
    print(f"维度 {len(dims)} 个 · 本 JD 涉及 {len(touched)} 个"
          f"({', '.join(sorted(touched))}) · 未涉及 {len(dims) - len(touched)} 个"
          f"({', '.join(sorted({d['id'] for d in dims} - touched))})")

    for fmt in ("svg", "png"):
        target = OUT / f"{args.name}.{fmt}"
        cmd = ["dot", f"-T{fmt}", str(dot_path), "-o", str(target)]
        if fmt == "png":
            cmd[1:1] = ["-Gdpi=170"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  {fmt} 渲染失败: {r.stderr.strip()[:200]}")
            return 1
        print(f"  {target.relative_to(ROOT)}  {target.stat().st_size // 1024}K")

    if args.open:
        subprocess.run(["open", str(OUT / f"{args.name}.svg")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
