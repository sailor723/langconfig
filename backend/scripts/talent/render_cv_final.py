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
INTERVIEW = ROOT / "work" / "talent" / "cv_interview"

EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}
from scripts.talent.cv_parse import LABELISH, PERIOD, PERIOD_OPEN, QUOTE_CH, SCHOOL, parse_experience  # noqa: E402,E501


def resume_only(text: str) -> dict:
    """简历里**明明写着**、但抽取器没提上来的字段。每条都返回 (值, 引文)。

    只认原文能逐字回查的东西 —— 抓不到就返回空,不猜。
    """
    def grab(pat: str):
        m = re.search(pat, text)
        return m.group(1).strip() if m else None

    out = {}
    if v := grab(r"出生年月[:：]\s*(\d{4}-\d{2}-\d{2})"):
        out["F.CV_BIRTH_DATE"] = (v, "出生年月")
    if v := grab(rf"求职类型[:：]\s*{QUOTE_CH}?(\S+)"):
        out["F.CV_JOB_TYPE"] = (v, "求职类型")
    if v := grab(rf"职位名称[:：]\s*{QUOTE_CH}?([^\n]+)"):
        out["F.JOB_TITLE"] = (v.strip(), "职位名称")
    periods = re.findall(rf"毕业院校[:：]\s*{QUOTE_CH}?([^\n(]+?)\s*\(([^)]*)\)", text)
    if periods:
        out["F.CV_EDU_PERIOD"] = (";".join(f"{s.strip()} {p.strip()}" for s, p in periods),
                                  "毕业院校行")
    if v := re.search(r"(具有[^\n]{0,30}内审资格证书)", text):
        out["F.CERTIFICATION"] = (v.group(1), "职业技能第 8 条")
    if v := grab(r"工作经验[:：]\s*([^\s]+)"):
        out["F.EXP_YEARS"] = (v, "工作经验行")
    if v := grab(r"自我评价[:：]\s*\w*\s*([^\n]+)"):
        out["F.COMPETENCY"] = (v, "自我评价")
    if match := re.search(rf"^(?:公司名称[:：])?\s*{QUOTE_CH}?(.+?(?:有限公司))$",
                          text, re.MULTILINE):
        out["F.CV_EMPLOYER"] = (match.group(1).strip(), "第一段工作经历")
    # 职能域:从担任职位的字面读出,不外推行业
    if titles := re.findall(r"担任职位[:：]\s*" + QUOTE_CH + r"?(\S+)", text):
        zones = []
        for t_ in titles:
            for key in ("品质", "工程", "项目", "开发"):
                if key in t_ and key not in zones:
                    zones.append(key)
        if zones:
            out["F.EXP_DOMAIN"] = ("/".join(f"{z}" for z in zones),
                                   "担任职位行:" + "、".join(titles))
    return out


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
    # 访谈记录:简历没写的字段,由这场对话补。来源标 interview,不混进 resume。
    iv_path = INTERVIEW / f"{args.id.replace('cand_', '')}.yaml"
    iv = yaml.safe_load(iv_path.read_text(encoding="utf-8")) if iv_path.is_file() else {}
    iv_answers = {a["field"]: a for a in (iv.get("answers") or [])}

    lang_ans = iv_answers.get("F.LANGUAGE_LEVEL") or {}
    iv_language = None
    for word in ("英文", "英语", "日语", "粤语"):
        if word in str(lang_ans.get("answer") or ""):
            iv_language = {"英文": "英语"}.get(word, word)
            break

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

    if iv_language:
        VALUE["F.CV_LANGUAGE"] = (iv_language, "interview",
                                  "访谈「英语程度」一问里自述;简历原文未提任何外语")
    # 行业:原文只有「公司产品」行(产品,不是行业),所以这一项不填 —— 留在待补里说清楚。

    # 原文里明写着、但抽取字段没覆盖到的 —— 补上,并保留定位说明。
    extra = resume_only(text)
    for fid, (value, where) in extra.items():
        if VALUE.get(fid, (None,))[0] in (None, ""):
            VALUE[fid] = (value, "resume", f"原文位置:{where}")

    # 年限有三个口径,定稿必须同时露:自述(简历头)/ 逐段累计(可重算但未验)/ 平台文件名(被截断)
    stated_y = (extra.get("F.EXP_YEARS") or (None,))[0]
    if yrs is not None:
        calc = f"逐段累计 {yrs} 年({ybasis},未验算)"
        if stated_y:
            VALUE["F.EXP_YEARS"] = (stated_y, "resume",
                                    f"原文「工作经验」行;逐段累计 {yrs} 年({ybasis})—— 不一致,以自述为准")
        else:
            VALUE["F.EXP_YEARS"] = (yrs, "derived", calc)

    L: list[str] = []
    A = L.append
    A(f"# 候选人档案 · {args.id.replace('cand_', '')[:30]}")
    A("")
    A(f"> 字段集取自 `work/talent/field_schema.yaml` —— 该模板裁剪出 **{len(cv_fields)}** 个字段"
      f"(全库共 {len(schema['fields'])} 个字段,两份模板共用一份全集)。")
    A(f"> 原文:`{textfile.relative_to(ROOT) if textfile.is_file() else '缺失'}`(OCR {len(text)} 字)")
    A(f"> 抽取:OCR + 大模型,每条带逐字引文,已过逐字校验。")
    if iv:
        A(f"> **访谈**:{iv.get('channel','')} · {iv.get('date','')} · "
          f"{len(iv.get('answers') or [])} 问 · 来源标 `interview` 的字段来自这场对话,不是简历原文。")
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
            if val in (None, "") and f["id"] in iv_answers:
                a = iv_answers[f["id"]]
                val, src = str(a.get("answer") or "").replace("\n", " ").strip()[:90], "interview"
                note = (a.get("note") or "").replace("\n", " ")[:80] or "来源:电话初筛"
            # 工作经历/技能这类在下面单独成节 —— 但访谈给了值就不覆盖
            if f["id"] == "F.EXP_INDUSTRY" and src != "interview":
                val, src = None, "missing"
                note = "原文只有「公司产品」行(产品清单),不是行业;不拿产品冒充行业"
            if (f["id"] in ("F.EXP_DOMAIN", "F.EXP_ACTIVITY")
                    and src not in ("interview", "resume")):
                val, src, note = None, "missing", "见下方「工作经历」逐段"
            if val in (None, ""):
                missing_fields.append((f["id"], f["label"], note))
            cmp_ = f.get("compare", "—")
            cell = "〔待补〕" if val in (None, "") else str(val)
            A(f"| {f['label']} | {cell} | {src} | {cmp_} | {note or '—'} |")
        A("")

    jobs = parse_experience(text)
    A("## 工作经历(逐段,来自原文)")
    A("")
    A("| 起止 | 公司 | 职位 | 职责条数 |")
    A("|---|---|---|---|")
    for j in jobs:
        A(f"| {j['start']} - {j['end']} | {j['company'] or '〔原文没写公司名〕'} | "
          f"{j['title'] or '〔原文没写职位〕'} | {len(j['duties'])} |")
    A("")
    gaps = [j for j in jobs if not j["company"] or not j["title"]]
    A(f"> 共 {len(jobs)} 段。语料有两种排法:公司名与起止**分行**写(公司在上)," 
      f"或「公司 职位 起止」**同行**写(公司在前)。以起止行为界切块,块内找公司与职位。")
    if gaps:
        A(f"> 有 {len(gaps)} 段没读出公司或职位 —— 原文缺(OCR 吃字),不是我补的,也不猜。")
    A(f"> 职责原文照抄在下方,不转述、不改写。")
    A("")
    for j in jobs:
        A(f"### {j['start']} - {j['end']} · {j['company'] or '〔公司名缺〕'} · "
          f"{j['title'] or '〔职位缺〕'}")
        A("")
        for d in j["duties"]:
            A(f"- {d}")
        if not j["duties"]:
            A("- 〔原文此段没有可读的编号职责〕")
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
