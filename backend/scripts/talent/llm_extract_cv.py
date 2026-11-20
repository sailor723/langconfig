#!/usr/bin/env python3
"""用 LLM 读一份简历 —— 只抽"原文说了什么",每条都带逐字引文。

为什么是这一步:277 人里 **年限未读到 129、年龄未读到 170、学历未读到 71、专业 0**。
名单排得再漂亮,分母是空的就不可信。而这三个洞不是模型能力问题 ——
正则认不出"2019.04—2019.08 在深圳…做导购"这种日期区间,人能读出来,LLM 也能。

分工还是那条底线:

    LLM          读 OCR 文本,产出 (字段, 值, 逐字引文)
    代码         校对引文是否真在文本里、值是否在规定取值范围内
    门禁         最终判定(引文不通过就丢弃,不进 ABox)
    人           只看"这个值理解得对不对"

**绝不做的三件事:**
  · 不让 LLM 打分/排名 —— 那会让"为什么她排第 7"永远答不了
  · 不把结论直接写进 ABox —— 先进 draft,门禁过了才算
  · 不在没有引文时编值 —— 读不出就报 null,**null 不是 0,也不是"不合格"**

OCR 缓存复用 extract.py 的 `ocr_pdf`(按 sha256+dpi+lang 命中),所以重跑免费。

用法:
    python -m scripts.talent.llm_extract_cv --id cand_李___38岁_行政专员_智通简历_编号
    python -m scripts.talent.llm_extract_cv --id <id> --show-text
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

CV_CACHE = ROOT / "work" / "talent" / "cv_cache"
CV_TEXT = ROOT / "work" / "talent" / "cv_text"
DRAFT = ROOT / "work" / "talent" / "cv_draft"
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
ABOX = BACKEND / "features" / "ontology" / "profiles" / "talent_v1" / "abox.ttl"

EDU_SCALE = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}


def _llm(prompt: str, max_tokens: int = 2000) -> str:
    from config import Settings
    s = Settings()
    if not s.DEEPSEEK_API_KEY:
        raise SystemExit("没有 DEEPSEEK_API_KEY")
    body = json.dumps({"model": "deepseek-chat", "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{s.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {s.DEEPSEEK_API_KEY}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def ocr(source_file: str) -> str:
    """OCR 一次、缓存永用。文本也另存一份,门禁要拿它验引文。"""
    from scripts.talent import extract as E

    pdf = ROOT / "client" / "team-4" / "unzipped" / "简历307份" / source_file
    if not pdf.is_file():
        raise SystemExit(f"找不到简历: {pdf}")
    CV_CACHE.mkdir(parents=True, exist_ok=True)
    text, how = E.ocr_pdf(pdf, CV_CACHE, 200, "chi_sim+eng")
    CV_TEXT.mkdir(parents=True, exist_ok=True)
    out = CV_TEXT / (pdf.stem[:80] + ".txt")
    out.write_text(text, encoding="utf-8")
    return text


def build_prompt(text: str, skills: list[str]) -> str:
    """不用 f-string —— 示例里的 {} 会被当格式字段(踩过)。"""
    skill_menu = "、".join(skills)
    head = (
        "你是简历信息抽取器。下面是一份中文简历的 OCR 文本(可能有错字、断行、乱序)。\n\n"
        "请抽取下列字段。**每个值都必须给出原文引文**(quote):从文本里逐字复制的片段,\n"
        "不许改写、不许补字、不许把两处文字拼起来。读不出来就填 null,并在 why 里说明。\n\n"
        "字段说明:\n"
        "  age              年龄(整数)。可从「生日/出生年月」推算,推了就写 age_basis: \"birthday\" 或 \"stated\"\n"
        "  years_experience 工作总年限(整数)。必须能从工作经历的起止时间推出来;\n"
        "                   重叠的段只算一次,在读不出时就填 null\n"
        "  education_rank   最高学历,只能取 2=中专/高中 3=大专 4=本科 5=硕士 6=博士\n"
        "  major            专业名称(如 人力资源管理),没有就 null\n"
        "  full_time        是否全日制,true / false / null\n"
        "  gender           男 / 女 / null\n"
        "  skills           文本里**明确出现**的技能,且必须来自这个封闭词表:\n"
        "                   " + skill_menu + "\n"
        "                   只挑明确写了或明确对应得上的;不确定就不要写。\n\n"
        "输出一个 JSON 对象,形状如下(每个字段都有 quote 与 confidence):\n"
        "{\n"
        '  "age": {"value": null, "quote": null, "why": null},\n'
        '  "years_experience": {"value": null, "quote": null, "why": null},\n'
        '  "education_rank": {"value": null, "quote": null, "why": null},\n'
        '  "major": {"value": null, "quote": null, "why": null},\n'
        '  "full_time": {"value": null, "quote": null, "why": null},\n'
        '  "gender": {"value": null, "quote": null, "why": null},\n'
        '  "skills": [{"name": "Excel", "quote": "熟练使用Excel"}]\n'
        "}\n"
        "只输出 JSON,不要解释。\n\n简历文本:\n"
    )
    return head + text[:4000]


def verify(doc: dict, text: str, skills_by_label: dict[str, str]) -> dict:
    """校对:每条引文必须真的在这份文本里;学历必须在 2..6;技能必须在词表里。"""
    bad = {"quote_missing": [], "quote_invented": [], "value_invalid": []}
    for field in ("age", "years_experience", "education_rank", "major", "full_time", "gender"):
        item = doc.get(field) or {}
        q = (item.get("quote") or "").strip()
        if item.get("value") is None:
            continue
        if not q:
            bad["quote_missing"].append(field)
        elif q not in text:
            bad["quote_invented"].append((field, q[:40]))
    edu = (doc.get("education_rank") or {}).get("value")
    if edu is not None and edu not in EDU_SCALE:
        bad["value_invalid"].append(("education_rank", edu))
    for sk in doc.get("skills") or []:
        q = (sk.get("quote") or "").strip()
        if q and q not in text:
            bad["quote_invented"].append(("skill", f"{sk.get('name')}: {q[:30]}"))
        if sk.get("name") not in skills_by_label:
            bad["value_invalid"].append(("skill", sk.get("name")))
    return bad


def abox_truth(cid: str) -> dict:
    """ABox 里现有的值,用来对照 —— 不是真值,是"上一次抽取的结果"。"""
    import rdflib
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF

    ns = "https://cube.local/ontology/talent_v1#"
    g = rdflib.Graph()
    g.parse(ABOX, format="turtle")

    def one(node, prop):
        for v in g.objects(node, URIRef(ns + prop)):
            return int(v) if isinstance(v, Literal) and str(v).isdigit() else str(v)
        return None

    node = URIRef(ns + cid)
    if (node, RDF.type, URIRef(ns + "Candidate")) not in g:
        return {}
    return {"years": one(node, "yearsExperience"), "education": one(node, "educationRank"),
            "age": one(node, "age"),
            "skills": sorted(str(o).rsplit("#", 1)[-1] for o in g.objects(node, URIRef(ns + "hasSkill")))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--source-file", default="", help="不给就读 ABox 里的 sourceFile")
    ap.add_argument("--show-text", action="store_true")
    args = ap.parse_args()

    truth = abox_truth(args.id)
    src = args.source_file or (truth.get("sourceFile") if truth else "")
    if not src:
        import psycopg2, os
        conn = psycopg2.connect(host=os.environ.get("ONTOLOGY_DB_HOST", "127.0.0.1"),
                                port=int(os.environ.get("ONTOLOGY_DB_PORT", "5433")),
                                dbname="talent_db", user=os.environ.get("ONTOLOGY_DB_USER"),
                                password=os.environ.get("ONTOLOGY_DB_PASSWORD", ""))
        with conn.cursor() as cur:
            cur.execute("select source_file from candidate where id=%s", (args.id,))
            row = cur.fetchone()
        conn.close()
        if not row:
            raise SystemExit(f"ID 不在库里: {args.id}")
        src = row[0]

    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    skills_by_label = {c["label"]: c["id"] for c in catalog["components"]}
    text = ocr(src)
    print(f"候选人: {args.id}")
    print(f"简历  : {src}")
    print(f"OCR   : {len(text)} 字")
    if args.show_text:
        print("─" * 70); print(text[:1200]); print("─" * 70)

    raw = _llm(build_prompt(text, list(skills_by_label)))
    m = re.search(r"\{.*\}", raw, re.S)
    doc = json.loads(m.group(0)) if m else {}
    DRAFT.mkdir(parents=True, exist_ok=True)
    (DRAFT / f"{args.id}.json").write_text(
        json.dumps({"candidate": args.id, "source_file": src, "raw": doc,
                    "model": "deepseek-chat", "temperature": 0,
                    "review_status": "draft"}, ensure_ascii=False, indent=1), encoding="utf-8")

    bad = verify(doc, text, skills_by_label)
    print("\n── LLM 抽取(与 ABox 现值对照)──")
    LABEL = {"age": "年龄", "years_experience": "年限", "education_rank": "学历",
             "major": "专业", "full_time": "全日制", "gender": "性别"}
    TRUTH_KEY = {"age": "age", "years_experience": "years", "education_rank": "education"}
    for field, label in LABEL.items():
        item = doc.get(field) or {}
        val = item.get("value")
        old = truth.get(TRUTH_KEY.get(field, "")) if field in TRUTH_KEY else None
        shown = val if val is not None else "null"
        if field == "education_rank" and val in EDU_SCALE:
            shown = f"{val}({EDU_SCALE[val]})"
        mark = ""
        if field in TRUTH_KEY:
            mark = f"   ABox={old if old is not None else '未读到'}"
        print(f"   {label:5s} {str(shown):12s}{mark}")
        if item.get("quote"):
            print(f"         引文「{item['quote'][:56]}」")

    got = [s.get("name") for s in doc.get("skills") or []]
    print(f"\n   技能 {len(got)} 个: {'·'.join(got) if got else '(无)'}")
    print(f"        ABox 里原有 {len(truth.get('skills') or [])} 个")

    print(f"\n── 校对 ──")
    print(f"   引文编造     {len(bad['quote_invented'])}  {bad['quote_invented'][:3]}")
    print(f"   有值无引文   {len(bad['quote_missing'])}   {bad['quote_missing']}")
    print(f"   取值不合法   {len(bad['value_invalid'])} {bad['value_invalid'][:3]}")
    print(f"\n草稿: work/talent/cv_draft/{args.id}.json")
    return 0 if not any(bad.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
