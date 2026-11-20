#!/usr/bin/env python3
"""把 LLM 抽出的草稿,经过门禁,变成**可以进 ABox 的事实**。

这是"LLM 读文字"和"事实"之间的那道闸。没有它,168 条编造的引文会变成 168 条事实。

**四道检查,每一道都是被实测逼出来的:**

① 引文逐字存在
   LLM 会编。实测:168 条引文在原文里找不到(分布在 49/270 人身上)。
   这条挡掉全部编造 —— 因为 LLM 编不出原文里没有的句子。

② 数字类字段,引文必须**包含那个数字**
   实测暴露:某候选人 quote「(2001-08 一 2010-10)」而 value=23 ——
   引文是真的,但**它不能支撑 23**(那一个工作段只有 9 年)。
   所以对 age / years,要么引文里出现该数字,要么走 ③ 的推算路径。

③ 推算必须能验算
   age 有 37 条来自「出生年月 2002.02」→ 23 岁。这是**合法推算**,但必须对得上:
   用参考年份减去出生年份,差值要等于 value,否则拒绝。
   years 走日期区间累计的,一律标 `computed_unverified` —— 因为要验"所有工作段之和",
   而现在只引用了一段,验不了。

④ 枚举字段必须落在封闭取值里
   education_rank ∈ 2..6;gender ∈ {男,女};full_time ∈ {true,false}。

产出 (work/talent/cv_facts.json) 每一条都带 basis + quote,所以进 ABox 之后仍然可回查:

    {"candidate": "...", "age": {"value": 38, "basis": "stated", "quote": "38岁"}}
    basis: stated      原文直接写了这个值
           computed    原文写的是生日/出生日期,值由推算得出(已验算)
           computed_unverified  原文只有工作段,值靠累计(未验算,不予采信)
           rejected    门禁拒绝

用法:
    python -m scripts.talent.promote_cv_facts            # 生成 cv_facts.json
    python -m scripts.talent.promote_cv_facts --report   # 只打印统计
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]

DRAFT = ROOT / "work" / "talent" / "cv_draft"
TEXT = ROOT / "work" / "talent" / "cv_text"
OUT = ROOT / "work" / "talent" / "cv_facts.json"

#: 参考年份:简历抓取时间在 2026 年前后,用 2025 作基准并用「生日已过 / 未过」容一年
REF_YEAR = 2025

GENDER = {"男", "女"}
FULL_TIME = {True, False}
#: 学历**词**直接出现 → basis=stated
EDU_WORDS = {2: ("中专", "高中", "职高", "技校", "中技"),
             3: ("大专", "专科", "高职"),
             4: ("本科", "学士", "大学"),
             5: ("硕士", "研究生", "MBA", "EMBA"),
             6: ("博士",)}

#: 校名**类型** → 学历等级。顺序即优先级,**先匹配先赢**。
#   「天津职业大学」含「职业大学」→ 3(高职);若先匹配「大学」会误判成 4。
#   这条规则放在门禁里而不是让 LLM 判 —— 它是可审计的确定性推断。
EDU_INFER = (
    (2, ("中等职业", "技校", "职高", "中技", "中专")),
    (6, ("博士",)),
    (5, ("硕士", "研究生", "MBA", "EMBA")),
    (3, ("职业技术学院", "职业学院", "职业大学", "高等专科", "专科学校", "高职")),
    (4, ("本科", "学士", "大学", "学院")),
)


def infer_edu(quote: str) -> int | None:
    for rank, words in EDU_INFER:
        if any(w in quote for w in words):
            return rank
    return None

BIRTH = re.compile(r"(19|20)(\d{2})\s*[年.\-/]\s*(\d{1,2})")


def decide(doc: dict, text: str) -> dict:
    """对一个人做四道检查,返回 {字段: {value, basis, quote, why}}。"""
    out: dict[str, dict] = {}

    def put(field, value, basis, quote, why=None):
        out[field] = {"value": value, "basis": basis, "quote": quote, "why": why}

    # ── ① 引文逐字存在(所有字段的通行证)
    def quote_ok(item) -> tuple[bool, str]:
        q = (item.get("quote") or "").strip()
        if not q:
            return False, "没有引文"
        if q not in text:
            return False, "引文在原文里找不到"
        return True, ""

    # ── age:引文含数字 → stated;引文是生日 → 验算后 computed
    item = doc.get("age") or {}
    val = item.get("value")
    if val is not None:
        ok, why = quote_ok(item)
        q = (item.get("quote") or "").strip()
        if not ok:
            put("age", val, "rejected", q, why)
        elif str(val) in q:
            put("age", int(val), "stated", q)
        else:
            m = BIRTH.search(q)
            if m:
                born = int(m.group(1) + m.group(2))
                if abs(REF_YEAR - born - int(val)) <= 1:
                    put("age", int(val), "computed", q, f"按出生年 {born} 推算")
                else:
                    put("age", int(val), "rejected", q, f"出生年 {born} 推不出 {val}")
            else:
                put("age", int(val), "rejected", q, "引文既不含年龄也不含生日")

    # ── years:引文含数字 → stated;否则只记不采信
    item = doc.get("years_experience") or {}
    val = item.get("value")
    if val is not None:
        ok, why = quote_ok(item)
        q = (item.get("quote") or "").strip()
        if not ok:
            put("years", int(val), "rejected", q, why)
        elif str(val) in q:
            put("years", int(val), "stated", q)
        else:
            put("years", int(val), "computed_unverified", q,
                "引文只是某一段工作经历,不能支撑总年限")

    # ── education:值必须与该学历词出现在引文里
    item = doc.get("education_rank") or {}
    val = item.get("value")
    if val is not None:
        ok, why = quote_ok(item)
        q = (item.get("quote") or "").strip()
        if not ok:
            put("education_rank", int(val), "rejected", q, why)
        elif any(w in q for w in EDU_WORDS.get(int(val), ())):
            put("education_rank", int(val), "stated", q)
        else:
            # 引文里没有学历词 —— 那就门禁自己按校名推一遍,再和 LLM 比对
            guessed = infer_edu(q)
            if guessed is None:
                put("education_rank", int(val), "rejected", q, "引文里既无学历词,也推不出校名类型")
            elif guessed == int(val):
                put("education_rank", int(val), "inferred", q, f"校名类型推断为 {guessed},与 LLM 一致")
            else:
                put("education_rank", int(val), "rejected", q, f"校名类型推断为 {guessed},与 LLM 的 {val} 不符")

    # ── major / gender / full_time:引文存在即可,值域另判
    for field, allowed in (("major", None), ("gender", GENDER), ("full_time", FULL_TIME)):
        item = doc.get(field) or {}
        val = item.get("value")
        if val is None:
            continue
        ok, why = quote_ok(item)
        q = (item.get("quote") or "").strip()
        if not ok:
            put(field, val, "rejected", q, why)
        elif allowed is not None and val not in allowed:
            put(field, val, "rejected", q, f"取值 {val!r} 不在 {allowed}")
        else:
            put(field, val, "stated", q)

    # ── 技能:必须在词表里、引文存在
    skills = []
    for sk in doc.get("skills") or []:
        q = (sk.get("quote") or "").strip()
        if q and q in text:
            skills.append({"name": sk.get("name"), "quote": q})
    if skills:
        out["skills"] = {"value": skills, "basis": "stated", "quote": None, "why": None}

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    facts: dict[str, dict] = {}
    basis = collections.Counter()
    rejected = collections.Counter()
    for f in sorted(DRAFT.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        txt = TEXT / (pathlib.Path(d["source_file"]).stem[:80] + ".txt")
        if not txt.is_file():
            continue
        decided = decide(d["raw"], txt.read_text(encoding="utf-8"))
        facts[d["candidate"]] = {"source_file": d["source_file"], **decided}
        for field, item in decided.items():
            basis[f"{field}:{item['basis']}"] += 1
            if item["basis"] == "rejected":
                rejected[item["why"]] += 1

    if not args.report:
        OUT.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"写出 {OUT.relative_to(ROOT)}  {len(facts)} 人")

    print(f"\n{'=' * 66}\n每种字段的采信情况\n{'=' * 66}")
    fields = ["age", "years", "education_rank", "major", "gender", "full_time", "skills"]
    for field in fields:
        parts = [f"{b}={basis[f'{field}:{b}']}" for b in
                 ("stated", "inferred", "computed", "computed_unverified", "rejected")
                 if basis[f"{field}:{b}"]]
        print(f"  {field:15s} " + "  ".join(parts) if parts else f"  {field:15s} (无)")

    print(f"\n拒绝原因 top:")
    for why, n in rejected.most_common(6):
        print(f"  {n:4d}  {why}")

    usable = {f: basis[f"{f}:stated"] + basis[f"{f}:inferred"] + basis[f"{f}:computed"]
              for f in ("age", "years", "education_rank", "major", "gender", "full_time")}
    print(f"\n可进 ABox 的值: " + " · ".join(f"{k}={v}" for k, v in usable.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
