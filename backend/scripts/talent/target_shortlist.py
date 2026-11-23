#!/usr/bin/env python3
"""第 3b 步(已退役):按 HR 给的目标人数,把短名单填到 N —— 只凭简历,**没有一面数据**。

    2026-11-23 起,第 5 步(`shortlist_after_interview.py`)用一面数据产出
    `shortlist/<JD>.目标名单.yaml`,那才是第 6 步读的名单。
    这个脚本只在"还没面、必须先把人数定下来"时用,产物改名 `3b目标人数.yaml`,
    不再占用 `目标名单` 这个名字。

## 为什么需要这一步

第 3 步(`screen_cv`)的规矩是「只排除不挑选」:拿简历里直接写着的事实剔掉明显不合格的人,
其余全留。它有它的道理(CV 只覆盖判定所需数据的 16%,按分数挑等于挑"谁简历写得多")。

但 HR 的现实是:**他只能面 5~8 个人**。169 人不是名单,是灾难。

所以这一步把「填到 N」这件真实动作**显式化**,并守住两条:

1. **不用分数排序**。分层依据只有「证据类型 × 有没有过客户门槛」,每一层都能一句话说清
   为什么排在前一层后面。
2. **每一次放宽都记录在案**。要凑够 N 个人,只能从下面三种"放宽"里选,选了哪个就写哪个,
   并标明它**需要客户点头**:

       R1 把「做过品质、但被一条客户门槛挡住」的人提上来   ← 等于临时放宽那条客户门槛
       R2 把「只有弱证据(客诉/8D、SPC 这类)」的人提上来   ← 等于降低证据标准
       R3 接受「语料里根本没有这类背景」的人               ← 等于放弃这条硬要求

   三条都要客户/HR 明确点头。**脚本不会替你选** —— 它只按 1→2→3 的顺序填到 min,
   把用到哪几条写在输出里,剩下的由人决定要不要继续。

## 分层(全部确定性,同一份数据跑两次必须一样)

    T1  过全部硬门槛 + 品质经历 A/B 档           ← 最硬
    T2  过全部硬门槛 + 只有弱动作                ← 疑似
    T3  品质经历 A/B 档,但被一条客户门槛挡住     ← 需复议(用即 R1)
    T4  其余(过门槛但没有品质证据)              ← 用即 R3

层内排序:硬动作数 → 该段月数 → 岗位名是否在品质序列 → 候选人 id(保证可重跑)。

用法:
    python -m scripts.talent.target_shortlist --jd 品质经理
    python -m scripts.talent.target_shortlist --jd 品质经理 --target-min 5 --target-max 8
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

SHORTLIST = ROOT / "work" / "talent" / "shortlist"
INPUTS = ROOT / "work" / "talent" / "jd_inputs"
QUALITY = ROOT / "work" / "talent" / "cv_quality.json"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"

TIERS = {
    "T1": "过全部客户硬门槛 + 品质经历有硬证据",
    "T2": "过全部客户硬门槛 + 只有弱证据(客诉/8D、SPC 之类)",
    "T3": "品质经历有硬证据,但被一条客户门槛挡住",
    "T4": "过客户门槛但没有品质证据",
}
RELAXATION = {
    "T2": "R2 降低了证据标准(弱证据也算)",
    "T3": "R1 临时放宽了一条客户门槛",
    "T4": "R3 放弃了「品质岗经历」这条硬要求",
}


def _rank(cid: str, q: dict) -> tuple:
    """层内排序:证据强度,不是"匹配度"。全部可从数据算出来,所以可重跑。"""
    v = q.get(cid) or {}
    return (-len(v.get("hard") or []), -(v.get("months") or 0),
            0 if v.get("kind") == "A" else 1, cid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--target-min", type=int, default=None)
    ap.add_argument("--target-max", type=int, default=None)
    args = ap.parse_args()

    sl_f = SHORTLIST / f"{args.jd}.yaml"
    if not sl_f.is_file():
        print(f"先跑 screen_cv --jd {args.jd}")
        return 2
    sl = yaml.safe_load(sl_f.read_text(encoding="utf-8")) or {}
    q = json.loads(QUALITY.read_text(encoding="utf-8")) if QUALITY.is_file() else {}
    facts = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.is_file() else {}
    gate = sl.get("quality_gate") or {}

    # 目标人数:命令行优先,其次 HR 写在 jd_inputs 里的指令
    tgt = {}
    inp = INPUTS / f"{args.jd}.yaml"
    if inp.is_file():
        tgt = (yaml.safe_load(inp.read_text(encoding="utf-8")) or {}).get("shortlist_target") or {}
    tmin = args.target_min or tgt.get("min")
    tmax = args.target_max or tgt.get("max")
    if not tmin:
        print("没有目标人数:在 jd_inputs/<JD>.yaml 写 shortlist_target.min,或传 --target-min")
        return 2

    # 第 5 步的池子应当是**面过的人**(面试名单),不是整个初筛池 ——
    # 没面过的人没有第 4 步数据,把他们塞进短名单等于跳过了采集。
    lst_path = SHORTLIST / f"{args.jd}.面试名单.yaml"
    lst = (yaml.safe_load(lst_path.read_text(encoding="utf-8")) if lst_path.is_file() else {}) or {}
    interviewed = [c for c in (lst.get("selected") or [])]
    if interviewed and not getattr(args, "from_pool", False):
        kept = interviewed
        print(f"  池子:面试名单 {len(kept)} 人(而不是初筛池 {len(sl.get('kept') or [])} 人)")
    else:
        kept = list(sl.get("kept") or [])
    blocked = [x["candidate"] for x in (gate.get("blocked_by_other_requirements") or [])]
    passed = set(gate.get("passed") or kept)

    tiers: dict[str, list[str]] = {"T1": [], "T2": [], "T3": [], "T4": []}
    for cid in kept:
        v = q.get(cid) or {}
        verdict = v.get("verdict")
        if verdict == "待核" or verdict == "读不出":
            # 「待核」不是硬证据也不是弱证据 —— 它是"我们还不知道"。
            # 之前这里按 kind(A/B 档)就塞进 T1,于是两个"月份都没读出来"的人
            # 被当成硬证据选进目标名单。待核的人要排在硬证据之后、弱证据之前。
            tiers["T2"].append(cid)
            continue
        if cid in passed and (v.get("kind") in ("A", "B")):
            tiers["T1"].append(cid)
        elif cid in passed:
            tiers["T2"].append(cid)
        else:
            tiers["T4"].append(cid)
    tiers["T3"] = blocked
    for k in tiers:
        tiers[k].sort(key=lambda c: _rank(c, q))

    picked, used_tiers, relaxations = [], [], []
    for k in ("T1", "T2", "T3", "T4"):
        for cid in tiers[k]:
            if len(picked) >= tmin:
                break
            picked.append(cid)
            if k not in used_tiers:
                used_tiers.append(k)
                if k in RELAXATION:
                    relaxations.append(RELAXATION[k])
        if len(picked) >= tmin:
            break

    short = tmin - len(picked)
    out = {
        "jd": args.jd,
        "step": "3b 目标人数填表(已退役 · 只凭简历 · 第 5 步不要读它)",
        "target": {"min": tmin, "max": tmax, "asked_by": tgt.get("asked_by", "hr")},
        "tiers": {k: {"rule": TIERS[k], "n": len(v), "candidates": v} for k, v in tiers.items()},
        "selected": picked,
        "used_tiers": used_tiers,
        "relaxations": relaxations,
        "shortfall": short,
        "note": ("凑到目标人数用到了放宽,每一条都需要客户/HR 点头;" if relaxations else "")
                + ("目标人数凑不满,缺口 %d 人 —— 不要用更低标准硬凑。" % short if short else ""),
    }
    DOCS = SHORTLIST / f"{args.jd}.3b目标人数.yaml"
    DOCS.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"目标人数 {tmin}~{tmax} 人(来自 {tgt.get('asked_by', 'hr')})")
    for k in ("T1", "T2", "T3", "T4"):
        print(f"  {k} {TIERS[k]:<38} {len(tiers[k]):>4} 人"
              + ("  ← 采用" if k in used_tiers else ""))
    print(f"\n选中 {len(picked)} 人" + (f",还差 {short} 人" if short else ""))
    if relaxations:
        print("用到的放宽(**都需要客户/HR 点头**):")
        for r in relaxations:
            print(f"  ⚠ {r}")
    if short:
        print(f"  ⚠ 缺口 {short} 人:语料里能凑的都凑了,不要用更低标准硬凑。")
    for cid in picked:
        v = q.get(cid) or {}
        _v = (q.get(cid) or {}).get("verdict")
        tag = ("需复议" if cid in blocked
               else "待核" if _v in ("待核", "读不出")
               else ("弱证据" if cid in tiers["T2"] else "硬证据"))
        print(f"  [{tag}] {cid.replace('cand_', '')[:46]}"
              f"{(v.get('kind') or '-')}档 {v.get('months')}月 {','.join(v.get('hard') or []) or '-'}")
    print(f"\n写出 {DOCS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
