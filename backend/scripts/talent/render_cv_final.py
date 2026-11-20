#!/usr/bin/env python3
"""渲染**定稿版**候选人档案 —— 字段集由 `field_schema.yaml` 定死,不按好看裁剪。

和 JD 那边同一个原则,而且是**同一份字段全集**:
    field_schema.yaml 是全集;本文件只裁剪 cv 非 null 的字段。
    JD 渲染器裁剪 jd 非 null 的字段。两份模板,一份全集。

字段来源三种,都标出来:
    resume   简历原文有      → 值 + 逐字引文
    derived  由原文推出      → 值 + 推导方式(必须能验算)
    missing  原文没有        → 〔待补〕 + 为什么需要它

另外每条字段会标「两侧可比性」——取自 field_schema 的 compare 判定:
    both / not_comparable / cv_only
这让读的人知道:这一项 JD 那边也在用(能比),还是只有简历有(单边)。

用法:
    python -m scripts.talent.render_cv_final --id cand_xxx
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

SCHEMA = ROOT / "work" / "talent" / "field_schema.yaml"
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
TEXT = ROOT / "work" / "talent" / "cv_text"
OUT = ROOT / "work" / "talent" / "cv_docs"

EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}


def load_candidate(cid: str) -> dict:
    import psycopg2
    conn = psycopg2.connect(host=os.environ["ONTOLOGY_DB_HOST"],
                            port=int(os.environ["ONTOLOGY_DB_PORT"]), dbname="talent_db",
                            user=os.environ["ONTOLOGY_DB_USER"],
                            password=os.environ["ONTOLOGY_DB_PASSWORD"])
    with conn.cursor() as cur:
        cur.execute("select id, source_file, salary_min_k, salary_max_k, age, "
                    "education_rank, years_experience from candidate where id=%s", (cid,))
        row = cur.fetchone()
    conn.close()
    if not row:
        raise SystemExit(f"找不到候选人 {cid}")
    return {"id": row[0], "source_file": row[1], "salary_min": row[2], "salary_max": row[3],
            "age": row[4], "edu": row[5], "years": row[6]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    args = ap.parse_args()

    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    facts = json.loads(FACTS.read_text(encoding="utf-8")).get(args.id) or {}
    cand = load_candidate(args.id)
    textfile = TEXT / (pathlib.Path(cand["source_file"]).stem[:80] + ".txt")
    text = textfile.read_text(encoding="utf-8") if textfile.is_file() else ""
    sec_label = schema["sections"]["cv"]
    cv_fields = [f for f in schema["fields"] if f.get("cv")]

    def fv(field):
        return (facts.get(field) or {}).get("value"), (facts.get(field) or {}).get("basis"), \
               ((facts.get(field) or {}).get("quote") or "").strip()

    # 字段 id → (值, 来源, 说明)。prop 已经在 field_schema 的 cv.prop 里声明过。
    age, abasis, aq = fv("age")
    edu, ebasis, eq = fv("education_rank")
    maj, mbasis, mq = fv("major")
    gen, gbasis, gq = fv("gender")
    yrs, ybasis, yq = fv("years")
    ft, ftbasis, ftq = fv("full_time")
    sk = [(s["name"], s.get("quote")) for s in (facts.get("skills") or {}).get("value") or []]

    VALUE = {
        "F.GENDER": (gen, "resume" if gbasis == "stated" else "missing",
                     f"引文「{gq}」" if gq else ""),
        "F.AGE": (age, "derived" if abasis == "computed" else "resume",
                  f"引文「{aq}」({abasis})" if aq else ""),
        "F.EDU_LEVEL": (EDU.get(edu, edu), "resume" if ebasis == "stated" else "derived",
                        f"引文「{eq}」({ebasis})" if eq else ""),
        "F.EDU_MAJOR": (maj, "resume", f"引文「{mq}」" if mq else ""),
        "F.EDU_FULLTIME": (ft, "resume" if ftbasis == "stated" else "missing",
                           f"引文「{ftq}」" if ftq else "270 份里几乎没有直接写「全日制」"),
        "F.EXP_YEARS": (yrs, "resume" if ybasis == "stated" else "missing",
                        f"引文「{yq}」({ybasis})" if yq else ""),
        "F.SKILL": (f"{len(sk)} 项" if sk else None, "resume" if sk else "missing", ""),
        "F.CERTIFICATION": (None, "missing", "证书逐条见下方「已识别能力项」"),
        "F.SALARY": (f"{cand['salary_min']}-{cand['salary_max']}K"
                     if cand["salary_min"] else None,
                     "resume" if cand["salary_min"] else "missing",
                     "来自招聘平台归档,非简历自述"),
    }

    L: list[str] = []
    A = L.append
    A(f"# 候选人档案 · {args.id.replace('cand_', '')[:30]}")
    A("")
    A(f"> 字段集取自 `work/talent/field_schema.yaml` —— 该模板裁剪出 **{len(cv_fields)}** 个字段"
      f"(全库共 {len(schema['fields'])} 个字段,两份模板共用一份全集)。")
    A(f"> 原文:`{textfile.relative_to(ROOT) if textfile.is_file() else '缺失'}`(OCR {len(text)} 字)")
    A(f"> 抽取:OCR + 大模型,每条带逐字引文,已过逐字校验。")
    A("")

    by_sec = collections.defaultdict(list)
    for f in cv_fields:
        by_sec[f["cv"]["section"]].append(f)

    missing_fields = []
    for code in sorted(by_sec):
        A(f"## {code} · {sec_label.get(code, code)}")
        A("")
        A("| 字段 | 值 | 来源 | 两侧 | 说明 |")
        A("|---|---|---|---|---|")
        for f in by_sec[code]:
            val, src, note = VALUE.get(f["id"], (None, "missing", ""))
            # 工作经历/技能这类在下面单独成节
            if f["id"] in ("F.EXP_DOMAIN", "F.EXP_ACTIVITY", "F.EXP_INDUSTRY"):
                val, src, note = None, "missing", "见下方「工作经历」逐段"
            if val in (None, ""):
                missing_fields.append((f["id"], f["label"], note))
            cmp_ = f.get("compare", "—")
            cell = "〔待补〕" if val in (None, "") else str(val)
            A(f"| {f['label']} | {cell} | {src} | {cmp_} | {note or '—'} |")
        A("")

    A("## 工作经历(逐段,来自原文)")
    A("")
    A("| 起止 | 公司 | 职位 |")
    A("|---|---|---|")
    pat = (r"(20\d{2}\s*[年.\-/]\s*\d{1,2}\s*月?\s*[-—~至]+\s*"
           r"(?:至今|20\d{2}\s*[年.\-/]\s*\d{1,2}\s*月?))[^\n]{0,80}")
    for m in re.finditer(pat, text):
        seg = m.group(0).replace("担任职位", "|").replace("职位:", "|")
        A(f"| {seg[:66]} |")
    A("")
    A("> 由正则从原文切出,可能不完整 —— 未切全的段落留在原文里,不在这里补写。")
    A("")

    if sk:
        comp_label = {c["label"]: c["id"] for c in catalog["components"]}
        A("## 已识别能力项(全部带原文引文)")
        A("")
        A("| 能力项 | 类别 | 原文引文 |")
        A("|---|---|---|")
        for name, quote in sk:
            cid = comp_label.get(name)
            cat = next((c["category"] for c in catalog["components"] if c["id"] == cid), "—")
            A(f"| {name} | {cat} | 「{(quote or '')[:44]}」 |")
        A("")

    A("## 待补清单")
    A("")
    A(f"按 `field_schema.yaml` 裁剪出的 {len(cv_fields)} 个字段,本档案有 "
      f"**{len(missing_fields)}** 项无值:")
    A("")
    A("| 字段 | 为什么需要 | 两侧可比性 |")
    A("|---|---|---|")
    cmap = {f["id"]: f.get("compare", "—") for f in cv_fields}
    for fid, label, note in missing_fields:
        A(f"| {label} | {note or '—'} | {cmap.get(fid, '—')} |")
    A("")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.id.replace('cand_', '')[:30]}.定稿.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"写出 {out.relative_to(ROOT)}  {len(L)} 行 · 字段 {len(cv_fields)} · "
          f"无值 {len(missing_fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
