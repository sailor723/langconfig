#!/usr/bin/env python3
"""用 LLM 起草一份 JD 的引用 —— 但只让它"读懂文字",不让它"做判断"。

分工是这套东西的底线:

    LLM 做       从职务说明书里抽原子要求,并给出**逐字引文**
    代码做       校对引文是否真的在原文里、行号对不对、要求 id 是否存在
    门禁做       最终的判定 —— check_component_catalog 的 9 项引用检查
    人做         "这条要求拆得对不对" 这种粒度判断

为什么必须有引文:LLM 编不出原文里没有的句子 —— 至少过不了逐字校验这一关。
没有引文的抽取,就是现在这 26 条正则的水平:只给结论,错了也查不出来
(「AI」被认成 skill_Illustrator,8 个人凭空匹配,就是这么来的)。

**菜单模式**:prompt 里带上要求库现有的 id 与名字,让模型优先复用,
匹配不上才提议新 id。不这样做,每份 JD 都会凭空造一套新要求名字,
共享就永远发生不了 —— 而共享正是把要求库拆成 JD 无关那一层的全部理由。

用法:
    python -m scripts.talent.llm_draft_jd --name 业务助理 \
        --doc "client/team-4/unzipped/职务说明书10份/3.业务助理职务说明书.doc"
    python -m scripts.talent.llm_draft_jd --name 工程文员 --doc ... --section 资格要求

产出(都不写库):
    work/talent/jd_links/_source/<name>.txt      原文(textutil 或 openpyxl 抽取)
    work/talent/jd_links/draft/<name>.llm.json   LLM 原始输出,可追溯
    work/talent/jd_links/draft/<name>.yaml       草稿引用,review_status: draft
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

# 往上找带 work/talent/component_catalog.yaml 的那一层 —— 别数 parents[i],
# 数错一次就会把产物写到 backend/work/ 下面(实测踩过)。
ROOT = pathlib.Path(__file__).resolve().parent
while not (ROOT / "work" / "talent" / "component_catalog.yaml").is_file():
    if ROOT == ROOT.parent:
        raise SystemExit("找不到仓库根(work/talent/component_catalog.yaml)")
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402

LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
SRC_DIR = ROOT / "work" / "talent" / "jd_links" / "_source"
DRAFT_DIR = ROOT / "work" / "talent" / "jd_links" / "draft"

DIMENSIONS = {
    "A": "人口属性(性别/年龄)", "B": "教育(学历/专业/全日制)",
    "C": "经历(年限/领域/行业)", "D": "技能(具体工具/能力项)",
    "E": "素质(沟通/责任心/执行力…,简历判不出)", "F": "资质证书",
    "G": "合规(保密/无犯罪)", "H": "语言熟练度", "I": "身体条件",
}


# ────────────────────────────────────────── 抽取原文
def extract_text(doc: pathlib.Path, out: pathlib.Path) -> str:
    """文本从哪来:macOS 的 textutil 读 .doc/.docx,openpyxl 读 .xlsx。"""
    suffix = doc.suffix.lower()
    if suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(doc, data_only=True)
        chunks = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c not in (None, "")]
                if cells:
                    chunks.append(" | ".join(cells))
        text = "\n".join(chunks)
    else:
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(doc)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"textutil 失败: {r.stderr[:200]}")
        text = r.stdout
    text = "\n".join(l for l in text.splitlines() if l.strip())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


# ────────────────────────────────────────── LLM
def _key():
    from config import Settings
    s = Settings()
    if not s.DEEPSEEK_API_KEY:
        raise SystemExit("没有 DEEPSEEK_API_KEY —— 先用 --no-llm 走别的路")
    return s.DEEPSEEK_API_KEY, s.DEEPSEEK_API_BASE.rstrip("/")


def call(prompt: str, max_tokens: int = 4000) -> str:
    key, base = _key()
    body = json.dumps({"model": "deepseek-chat", "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def build_prompt(text: str, menu: str, head: int) -> str:
    """拼 prompt。**不要用 f-string** —— 里面的 {min:25} 这类示例会被当成格式字段
    (实测报错:Space not allowed in string format specifier)。所以用拼接。"""
    batch = "\n".join(f"{i}. {l}" for i, l in enumerate(text.split("\n")[:head], 1))
    dims = "\n".join(f"  {k} = {v}" for k, v in DIMENSIONS.items())
    head_part = (
        "你是招聘要求抽取器。下面是某份职务说明书的前 " + str(head) + " 行(已带行号)。\n\n"
        "任务:只抽取【任职资格 / 资格要求】段落里的**原子要求**。\n\n"
        "原子要求的定义:一件**独立可判定**的事。\n"
        "  · 一句话含两件独立的事(「学历:全日制大专以上,中文文秘专业优先」)→ 拆成两条\n"
        "  · 只是修饰(「沟通能力好」)→ 不拆\n"
        "  · 小标题(「技能:」「素质:」「任职资格」)→ 不算要求\n\n"
        "维度只能取以下 8 个之一:\n" + dims + "\n\n"
        "**最重要的一条:优先复用已有的要求。** 下面是要求库现有条目(id — 名字 — 维度)。\n"
        "如果这条要求表达的是同一个意思,就用它的 id;意思不同才提议新的 id。\n"
        "新 id 用 REQ-<维度>-<短名> 的形式,全大写,例如 REQ-D-EXCEL。\n\n"
        + menu + "\n\n"
        "对每一条输出这些字段:\n"
        "  quote                  从原文**逐字复制**的片段。不许改写、不许补字、不许换标点。\n"
        "  line                   该片段所在行号\n"
        "  dimension              A/B/C/D/E/F/G/H 之一\n"
        "  tier                   essential 或 desirable(原文写\"优先\"的是 desirable)\n"
        "  subject                这条考察什么,简短中文(如 性别/学历/Office/沟通)\n"
        "  requirement            复用的要求库 id,或新提议的 id\n"
        "  value                  该要求在这份 JD 里的取值。没有取值就写 null:\n"
        '                           {"num": 3}                     学历等级\n'
        '                           {"min": 25, "max": 38}         年龄区间\n'
        '                           {"in": ["女"]}                  枚举\n'
        '                           {"num": 2, "domain": "文职"}    年限 + 领域\n'
        "  measurable_from_resume true 或 false\n\n"
        "只输出 JSON 数组,不要任何解释。\n\n原文:\n"
    )
    return head_part + batch


def parse(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise SystemExit(f"LLM 没有返回 JSON 数组:\n{raw[:400]}")
    return json.loads(m.group(0))


# ────────────────────────────────────────── 校对
def _overlap(subject: str, name: str) -> int:
    """中文没有空格,所以用 2-字片段的重叠量做粗判。0 表示主题与要求名毫无共同点。"""
    a, b = (subject or ""), (name or "")
    if not a or not b:
        return 0
    grams = {a[i:i + 2] for i in range(max(1, len(a) - 1))}
    return sum(1 for g in grams if len(g) == 2 and g in b)


def verify(items: list[dict], text: str, lib_ids: set[str], names: dict[str, str]) -> dict:
    lines = text.split("\n")
    report = {"bad_quote": [], "bad_line": [], "new_ids": [], "subjects": {}}
    for it in items:
        q = (it.get("quote") or "").strip()
        if not q or q not in text:
            report["bad_quote"].append((it.get("subject"), q[:40]))
        real = [n + 1 for n, l in enumerate(lines) if q and q in l]
        if it.get("line") not in real:
            report["bad_line"].append((it.get("subject"), it.get("line"), real))
        rid = it.get("requirement") or ""
        if rid and rid not in lib_ids and rid not in [x[0] for x in report["new_ids"]]:
            report["new_ids"].append((rid, it.get("subject"), it.get("dimension")))
        report["subjects"][it.get("subject") or "?"] = rid
        # 复用但主题与要求名毫无重叠 → 很可能把 A 塞进了 B 的 id
        if rid in lib_ids and _overlap(it.get("subject") or "", names.get(rid, "")) == 0:
            report.setdefault("suspect_reuse", []).append(
                (it.get("subject"), rid, names.get(rid, "")))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="岗位名,决定输出文件名")
    ap.add_argument("--doc", required=True, help="原始职务说明书路径")
    ap.add_argument("--head", type=int, default=30, help="喂给模型的前 N 行")
    ap.add_argument("--department", default="", help="隶属部门(可选)")
    args = ap.parse_args()

    cand = [pathlib.Path(args.doc), pathlib.Path.cwd() / args.doc, ROOT / args.doc]
    doc = next((c.resolve() for c in cand if c.is_file()), None)
    if doc is None:
        print(f"找不到职务说明书: {args.doc}")
        return 2
    if not doc.is_file():
        print(f"找不到 {doc}")
        return 2
    src = SRC_DIR / f"{args.name}.txt"
    text = extract_text(doc, src)
    print(f"原文: {src.relative_to(ROOT)}  {len(text.splitlines())} 行")

    library = yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))
    reqs = library["requirements"]
    lib_ids = {r["id"] for r in reqs}
    menu = "\n".join(f"  {r['id']:26s} {r['name'][:24]:26s} {r['dimension']}" for r in reqs)
    print(f"菜单: {len(reqs)} 条已有要求")

    raw = call(build_prompt(text, menu, args.head))
    items = parse(raw)
    (DRAFT_DIR / f"{args.name}.llm.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    names = {r["id"]: r["name"] for r in reqs}
    rep = verify(items, text, lib_ids, names)
    print(f"\nLLM 抽出 {len(items)} 条")
    lines = text.split("\n")
    for it in items:
        q = (it.get("quote") or "").strip()
        ok = bool(q) and q in text
        rid = it.get("requirement") or "?"
        mark = "复用" if rid in lib_ids else "新"
        print(f"  [{'✓' if ok else '✗'}] 行{it.get('line'):<3} {it.get('dimension')}/"
              f"{it.get('tier'):9s} {mark}:{rid:26s} 「{q[:34]}」")

    print(f"\n引文找不到: {len(rep['bad_quote'])}/{len(items)} "
          f"· 行号不符: {len(rep['bad_line'])}/{len(items)} "
          f"· 新要求 {len(rep['new_ids'])} 条")
    for rid, subject, dim in rep["new_ids"]:
        print(f"    新: {rid:26s} {dim} {subject}")
    suspect = rep.get("suspect_reuse") or []
    if suspect:
        print(f"\n⚠ 可能误复用 {len(suspect)} 条(主题与要求名无共同点,需人工审):")
        for subject, rid, name in suspect:
            print(f"    「{subject}」→ {rid}({name})")

    # 生成草稿引用
    VALUE_KEYS = ("num", "min", "max", "in", "domain", "bool")
    citations = []
    for i, it in enumerate(items, 1):
        q = (it.get("quote") or "").strip()
        full = next((l.strip() for l in lines if q and q in l), q)
        cit = {"id": f"{args.name[:2].upper()}-{i:02d}",
               "requirement": it.get("requirement"),
               "verbatim": q, "source_text": full,
               "txt_line": it.get("line"), "tier": it.get("tier", "essential")}
        val = it.get("value")
        if isinstance(val, dict) and any(k in val for k in VALUE_KEYS):
            cit["value"] = {k: v for k, v in val.items() if k in VALUE_KEYS}
        cit["llm"] = {"model": "deepseek-chat", "temperature": 0,
                      "subject": it.get("subject"),
                      "measurable_from_resume": it.get("measurable_from_resume"),
                      "requirement_reused": (it.get("requirement") in lib_ids)}
        citations.append(cit)

    draft = {
        "jd": args.name,
        "department": args.department,
        "source_file": str(pathlib.Path(args.doc)),
        "source_text": str(src.relative_to(ROOT)),
        "extracted_with": "textutil/openpyxl",
        "drafted_by": "deepseek-chat, temperature=0 —— **草稿,未人工审核**",
        "review_status": "draft",
        "count": {"source_section": "任职资格", "atomic_requirements": len(citations),
                  "count_note": f"LLM 从原文前 {args.head} 行抽出;粒度需人工审。"},
        "citations": citations,
        "excluded": [],
    }
    out = DRAFT_DIR / f"{args.name}.yaml"
    out.write_text(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False,
                                  default_flow_style=False, width=200), encoding="utf-8")
    print(f"\n草稿: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
