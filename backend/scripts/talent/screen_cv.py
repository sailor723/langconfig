#!/usr/bin/env python3
"""第 3 步:HR 看 CV 出短名单 —— **只排除,不挑选**。

这一环是整条流水线里最容易做错的一步,错法只有一种:**用"分数"去挑人**。

为什么不能挑:实测 CV 只够 join 要的 16% 数据项(10 个 JD / 154 个数据项 / 25 项)。
剩下 84% 在一面里才拿得到。一份简历写得细的人,不等于能干;写得少的人,也不等于不行。
按分数排序挑出来的前 N 名,跟"谁的简历写得多"高度相关 —— 那不是筛选,那是筛简历。

所以这一步只做一件事:**把明确不合格的剔掉**。
    剔掉的判据  只有 CV 里真的读到、且真的与要求冲突的项
    读不到      → 保留(不是"保留待定",是直接进短名单)
    读到了且符合 → 保留
    判不了的    → 保留(判不了是我的模型问题,不是他的问题)

一句话:**这一步只保证"不会把明显不行的人送去一面",不负责"选出最像的人"。**
后者是第 5 步(本体 + join)的事,而且必须在一面数据齐了之后做。

用法:
    python -m scripts.talent.screen_cv --jd 品质经理
    python -m scripts.talent.screen_cv --jd 品质经理 --list     # 打印名单
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent.evaluate import (  # noqa: E402
    CATALOG, FACTS, LIBRARY, LINKS, TRUSTED, load_candidates, overlay_llm)

COLLECTION = ROOT / "work" / "talent" / "collection"
OUT = ROOT / "work" / "talent" / "shortlist"

#: 只认这些 basis —— 与 evaluate 一致,不在这里另立口径
TRUST = TRUSTED

#: 第 3 步只许用**简历里直接写着的**属性排除人。
#: 为什么把 A.3/A.4/A.5/C.4/C.7 挡在外面:那几个是从工作段推出来的
#: (OCR 缺公司名、起止切不全都会让值偏),拿一个已知会偏的推导量去排除人,
#: 比"读到了学历不够"危险得多。这类要求留到第 5 步参与排序,不参与排除。
STATED_ONLY = {"A.1", "A.2", "B.1"}

#: 允许用来排除的算子。只认**数值/序数阈值** —— "落在区间""不低于"。
#: 枚举(in)一律不用于排除:JD 原话常写「机电一体化/电子技术/…**等**工程类专业」,
#: 白名单是举例不是穷举,拿它剔人会把"材料成型及控制工程"这种真工程专业也剔掉。
EXCLUDING_OPS = {"between", ">=", "<=", "="}

#: 原话里出现这些词,说明这条阈值不是穷举的,不能拿来排除
FUZZY = ("等", "优先", "相关", "不限", "类")

#: 属性 id → evaluate 的候选人字段名。目录里写的 prop 是 PG 列名(education_rank),
#: evaluate 里是驼峰(educationRank)—— 这两套名字必须显式对上,不能靠猜。
CAND_KEY = {"A.1": "gender", "A.2": "age", "B.1": "educationRank",
            "B.2": "major", "B.3": "fullTime", "C.1": "yearsStated"}


def judge(item: dict, atts: dict, cand: dict, citation: dict) -> tuple[str, str]:
    """判**一个数据项**。返回 (满足/不满足/未知, 为什么)。

    只有"不满足"能用来排除;未知和不可判都必须保留。
    """
    att_id = item["attach"]
    key = CAND_KEY.get(att_id)
    if not key:
        return "不可判", f"{att_id} 没有供给侧字段"
    value = cand.get(key)
    if value is None:
        return "未知", f"{key} 没读到"
    val = citation.get("value") or {}
    op = item.get("op") or ""
    if op == "between" and "min" in val and "max" in val:
        return (("满足" if val["min"] <= value <= val["max"] else "不满足"),
                f"{val['min']}~{val['max']} vs {value}")
    if op == ">=" and "num" in val:
        return (("满足" if value >= val["num"] else "不满足"), f">={val['num']} vs {value}")
    if op == "in":
        want = val.get("in") or []
        if not want:
            return "不可判", "白名单是空的"
        # 子串匹配:简历写「机电一体化技术」,JD 写「机电一体化」—— 同一件事的两种写法。
        # 但只在**命中白名单**时放行,不命中仍判不满足(这一步是排除法,宽松的只能是"保留")。
        hit = [w for w in want if w in str(value) or str(value) in w]
        return (("满足" if hit else "不满足"), f"{want} vs {value}")
    return "不可判", f"算子 {op} 这一步不判"


def cites_by_req(link: dict) -> dict:
    return {c["requirement"]: c for c in link["citations"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--facts", choices=["abox", "llm"], default="llm")
    ap.add_argument("--list", action="store_true", help="打印短名单里的人")
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    atts = {a["id"]: a for a in cat["attributes"]}
    lib = {r["id"]: r for r in yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))["requirements"]}
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    spec = yaml.safe_load((COLLECTION / f"{args.jd}.yaml").read_text(encoding="utf-8"))

    # 只有 CV 类别(cv)的项允许参与排除。稀薄的、必问的一律不参与 ——
    # 拿"CV 里没有"当理由排除人,就是把采集计划的缺口算到候选人头上。
    screenable, not_screenable = {}, {}
    for s in spec["items"]:
        if s.get("req_source") != "cv":
            continue
        rid = s["requirement"]
        if rid in screenable or rid in not_screenable:
            continue
        req = lib[rid]
        verbatim = cites_by_req(link)[rid].get("verbatim") or ""
        op = req.get("op")
        why = None
        if s["attach"] and s["attach"] not in STATED_ONLY:
            why = (f"{s['attach']} 是从简历推出来的量(不是直接写着),"
                   f"推导会偏 —— 不用于排除")
        elif op not in EXCLUDING_OPS:
            why = f"算子是 {op},不是阈值 —— 不用于排除"
        elif any(f in verbatim for f in FUZZY):
            why = f"原话含「{[f for f in FUZZY if f in verbatim][0]}」,白名单不是穷举 —— 不用于排除"
        if why:
            not_screenable[rid] = why
        else:
            # op 写在要求上,但判的时候要按数据项走 —— 所以并进 item,别让 judge 去猜
            screenable[rid] = {"item": {**s, "op": op}, "req": req}

    cands = load_candidates()
    if args.facts == "llm":
        overlay_llm(cands)
    pool = [c for c in cands if not c["duplicate"]]
    cites = {c["requirement"]: c for c in link["citations"]}

    rows, excluded = [], []
    for cand in pool:
        verdicts, kill = {}, []
        for rid, s in screenable.items():
            item = s["item"]
            state, why = judge(item, atts, cand, cites[rid])
            verdicts[rid] = (state, why)
            if state == "不满足":
                kill.append({"requirement": rid, "requirement_name": s["req"].get("name"),
                             "verbatim": cites[rid].get("verbatim"),
                             "data_item": item["data_item"], "why": why})
        row = {"candidate": cand["id"], "excluded": bool(kill), "reasons": kill,
               "verdicts": {k: v[0] for k, v in verdicts.items()}}
        rows.append(row)
        if kill:
            excluded.append(row)

    kept = [r for r in rows if not r["excluded"]]
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.jd}.yaml"
    out.write_text(yaml.safe_dump({
        "jd": link.get("jd"), "step": "3 短名单(只排除)",
        "rule": "只用 CV 类别(cv)的数据项排除;读不到/判不了一律保留",
        "facts": args.facts,
        "count": {"pool": len(pool), "kept": len(kept), "excluded": len(excluded)},
        "screenable_requirements": sorted(screenable),
        "not_screenable": not_screenable,
        "excluded": [{"candidate": r["candidate"], "reasons": r["reasons"]} for r in excluded],
        "kept": [r["candidate"] for r in kept],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"第 3 步 · {link.get('jd')} · 事实源 {args.facts} · 去重后 {len(pool)} 人")
    print(f"  参与排除的要求:{', '.join(sorted(screenable))}")
    for rid, why in sorted(not_screenable.items()):
        print(f"  不参与:{rid:24s} {why}")
    print(f"  保留 {len(kept)} 人 · 排除 {len(excluded)} 人 "
          f"({100*len(excluded)/max(1,len(pool)):.0f}%)")
    why = collections.Counter(r["reasons"][0]["requirement"] for r in excluded)
    for rid, n in why.most_common():
        print(f"    {rid:24s} {lib[rid].get('name','')[:16]:18s} 排除 {n:3d} 人")
    states = collections.Counter()
    for r in rows:
        for rid, s in r["verdicts"].items():
            states[(rid, s)] += 1
    print("\n  各要求的判决分布(只算可筛项):")
    for rid in sorted(screenable):
        c = collections.Counter({k[1]: v for k, v in states.items() if k[0] == rid})
        print(f"    {rid:24s} 满足{c['满足']:3d} 不满足{c['不满足']:3d} "
              f"未知{c['未知']:3d} 不可判{c['不可判']:3d}")
    print(f"\n写出 {out.relative_to(ROOT)}")
    if args.list:
        print("\n短名单:")
        for r in kept:
            print("  ", r["candidate"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
