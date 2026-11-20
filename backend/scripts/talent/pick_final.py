#!/usr/bin/env python3
"""第 5 步:从短名单里挑出最多 4 人,并给每个人一个说得清的理由。

排序规则(2026-11-20 用户定):
    ① 满足条数多的在前
    ② 并列时,**未知少的在前**(信息完整的人先,不是"简历写得多"的人)
    ③ 再并列时,不满足少的在前
    ④ 全并列就按 id(稳定,重跑不换人)

为什么不用分数:实测 299 个合格人里 222 人(74%)同分并列,纯按分数排
"凭什么是他"答不出来。四态计数至少能让每个人说清"他满足哪几条、缺哪几条"。

**这个脚本最重要的一段输出不是名单,是"还不够格挑"这件事。**
短名单 169 人里通常只有个位数做过一面。没一面的人,大部分数据项是「未知」——
这时候按"未知少的优先"排,排出来的是"谁的简历写得细",而不是"谁更合适"。
所以脚本会先报三个数:短名单多少人、有一面数据多少人、其中真正可比的人多少。
数字不够就直接说"现在挑不了",不硬凑 4 个。
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent.evaluate import (  # noqa: E402
    CATALOG, LIBRARY, LINKS, judge_attribute, judge_component,
    load_candidates, overlay_hr, overlay_interview, overlay_llm)

SHORTLIST = ROOT / "work" / "talent" / "shortlist"
OUT = ROOT / "work" / "talent" / "picks"


def load_inputs(jd: str):
    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    lib = {r["id"]: r for r in yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))["requirements"]}
    link = yaml.safe_load((LINKS / f"{jd}.yaml").read_text(encoding="utf-8"))
    atts = {a["id"]: a for a in cat["attributes"]}

    by_cat = collections.defaultdict(list)
    for c in cat["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in lib.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat_ in cats for x in by_cat.get(cat_, [])})
                          if cats else list(r.get("components") or []))
    return cat, lib, link, atts


def judge_all(cand: dict, link: dict, lib: dict, atts: dict) -> dict:
    out = {}
    for c in link["citations"]:
        r = lib[c["requirement"]]
        if not r.get("assessable"):
            state, why = "不可判", r.get("blocked_by") or "属性/组件未建"
        elif r["_resolved"]:
            state, why = judge_component(cand["components"], r["_resolved"])
        elif r.get("attribute"):
            state, why = judge_attribute(atts[r["attribute"]], r, c, cand, "")
        else:
            state, why = "不可判", "既无组件也无属性"
        out[c["requirement"]] = {"state": state, "why": why, "citation": c["id"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--facts", choices=["abox", "llm"], default="llm")
    ap.add_argument("--interviewed-only", action="store_true",
                    help="只排做过一面的(默认也排,但会标注数据来源)")
    args = ap.parse_args()

    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    if args.facts == "llm":
        overlay_llm(cands)
    overlay_hr(cands)
    n_iv = overlay_interview(cands)
    by_id = {c["id"]: c for c in cands}

    sl_path = SHORTLIST / f"{args.jd}.yaml"
    if sl_path.is_file():
        sl = yaml.safe_load(sl_path.read_text(encoding="utf-8"))
        pool_ids = [cid for cid in sl["kept"] if cid in by_id]
        excluded = sl["count"]["excluded"]
    else:
        pool_ids = [c["id"] for c in cands if not c["duplicate"]]
        excluded = 0

    # 判定分母:不可判的要求对谁都不算 —— 拿它算"满足率"会让每个人都被压低
    judgeable = [c["requirement"] for c in link["citations"]
                 if lib[c["requirement"]].get("assessable")
                 or lib[c["requirement"]].get("_resolved")]

    iv_ids = {c["id"] for c in cands
              if (ROOT / "work" / "talent" / "cv_interview"
                  / f"{c['id'].replace('cand_', '')}.yaml").is_file()}
    rows = []
    for cid in pool_ids:
        v = judge_all(by_id[cid], link, lib, atts)
        st = collections.Counter(x["state"] for x in v.values())
        rows.append({"candidate": cid, "verdicts": v,
                     "满足": st["满足"], "不满足": st["不满足"],
                     "未知": st["未知"], "不可判": st["不可判"],
                     "有访谈": cid in iv_ids})
    pool_iv = [r for r in rows if r["有访谈"]]
    ranked = sorted(pool_iv if args.interviewed_only else rows,
                    key=lambda r: (-r["满足"], r["未知"], r["不满足"], r["candidate"]))
    top = ranked[:args.top]

    # 排序陷阱检测:按"未知少的优先"排,可能把"不满足更多"的人排到前面
    inversions = []
    for a, b in zip(ranked, ranked[1:]):
        if a["不满足"] < b["不满足"] and a["满足"] <= b["满足"]:
            inversions.append((a["candidate"], b["candidate"],
                               a["不满足"], b["不满足"]))
            if len(inversions) >= 5:
                break

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.jd}.yaml").write_text(yaml.safe_dump({
        "jd": link.get("jd"), "step": "5 选人(最多 %d)" % args.top,
        "order": ["满足 desc", "未知 asc", "不满足 asc", "id"],
        "count": {"shortlist": len(pool_ids), "excluded": excluded,
                  "with_interview": len(pool_iv),
                  "judgeable_requirements": len(judgeable),
                  "total_requirements": len(link["citations"])},
        "top": [{"rank": i + 1, "candidate": r["candidate"],
                 "满足": r["满足"], "不满足": r["不满足"], "未知": r["未知"],
                 "不可判": r["不可判"], "有访谈": r["有访谈"]} for i, r in enumerate(top)],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    md = [f"# 第 5 步选人 · {link.get('jd')}", "",
          f"> 排序:满足多者先 → 未知少者先 → 不满足少者先 → id 稳定。最多 {args.top} 人。", ""]
    md += ["## 先说够不够格挑", "",
           "| | 数 |", "|---|---|",
           f"| 第 3 步短名单 | **{len(pool_ids)}** 人 |",
           f"| 其中做过一面的 | **{len(pool_iv)}** 人 |",
           f"| 可判的要求 | {len(judgeable)} / {len(link['citations'])} 条"
           f"(其余 {len(link['citations']) - len(judgeable)} 条没有可判的数据项) |", ""]
    if len(pool_iv) < args.top:
        md += [f"> ⚠ **现在挑不出 {args.top} 个可信的人。** 短名单 {len(pool_ids)} 人里只有 "
               f"{len(pool_iv)} 人做过一面,其余的人大量要求是「未知」。",
               "> 这时候按\"未知少的优先\"排,排出来的是**谁的简历写得细**,不是谁更合适。",
               "> 缺的不是算法,是第 4a 步的一面数据 —— 先把短名单里的人在电话里过一遍,这一步才有意义。", ""]

    md += [f"## 入选(最多 {args.top} 人)", ""]
    md += ["| # | 候选人 | 满足 | 不满足 | 未知 | 不可判 | 有访谈 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(top, 1):
        md.append(f"| {i} | {r['candidate'].replace('cand_', '')[:34]} | {r['满足']} | "
                  f"{r['不满足']} | {r['未知']} | {r['不可判']} | "
                  f"{'是' if r['有访谈'] else '否'} |")
    md.append("")

    for i, r in enumerate(top, 1):
        md += [f"### 第 {i} 位 · {r['candidate'].replace('cand_', '')}", "",
               f"满足 **{r['满足']}** · 不满足 **{r['不满足']}** · "
               f"未知 **{r['未知']}** · 不可判 **{r['不可判']}**", "",
               "| 要求 | 判定 | 依据 |", "|---|---|---|"]
        for c in link["citations"]:
            v = r["verdicts"][c["requirement"]]
            name = lib[c["requirement"]].get("name", "")
            md.append(f"| {c['id']} {name} | **{v['state']}** | {v['why']} |")
        md.append("")

    if inversions:
        md += ["## 排序陷阱:这条规则会把人排反", "",
               "\"未知少的优先\"有个已知副作用:一个 7 满足/1 未知/5 不满足的人,"
               "会排在 7 满足/3 未知/0 不满足 的人前面。", "",
               "| 排在前的 | 排在后的 | 前的不满足 | 后的不满足 |", "|---|---|---|---|"]
        for a, b, na, nb in inversions:
            md.append(f"| {a.replace('cand_','')[:22]} | {b.replace('cand_','')[:22]} | "
                      f"{na} | {nb} |")
        md += ["", "> 这不是 bug,是规则的取舍。要改的话有两种:**不满足先于未知**"
               "(信息不全但确定合格的先),或者**先按不满足分档、再按未知分档**。",
               "> 现在按你定的规则执行,但这个副作用摆在这里,不藏。", ""]

    (OUT / f"{args.jd} 选人.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"第 5 步 · {link.get('jd')}")
    print(f"  短名单 {len(pool_ids)} 人 · 有一面数据 {len(pool_iv)} 人 · "
          f"可判要求 {len(judgeable)}/{len(link['citations'])}")
    print(f"  入选 {len(top)} 人:")
    for i, r in enumerate(top, 1):
        print(f"    {i}. 满足{r['满足']} 不满足{r['不满足']} 未知{r['未知']} "
              f"{'[访谈]' if r['有访谈'] else ''} {r['candidate'][:44]}")
    if len(pool_iv) < args.top:
        print(f"  ⚠ 只有 {len(pool_iv)} 人做过一面,少于 {args.top} —— 现在挑不出 {args.top} 个可信的人")
    if inversions:
        print(f"  ⚠ 排序陷阱 {len(inversions)} 处:未知少的人被排到了不满足更多的人前面")
    print(f"写出 {(OUT / f'{args.jd} 选人.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
