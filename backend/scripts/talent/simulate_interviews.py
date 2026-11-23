#!/usr/bin/env python3
"""给还没面过的候选人**模拟**一场一面,把简历补成完整档案 —— 用于开发与演练。

## 这个脚本在造数据,所以它必须比别的脚本更诚实

它写的每一条都会标成 `basis: simulated`,并在 CV 定稿顶部挂一条醒目警告:
「本档案有 N 个字段来自模拟访谈,不是真人说的」。

## 两条自我约束

1. **只模拟与岗位判断相关的字段**,不编造个人身份信息。
   姓名 / 电话 / 邮箱 / 婚姻 / 籍贯 —— 这些编了以后会被当真实档案转手,
   而它们对"能不能干这个岗"没有判断价值。这些字段保持〔待补〕。
2. **能从简历推的不编**:工作地点、行业、项目、培训、语言,都从 CV 正文与技能里
   取最接近的表述,再标「模拟补全」。只有完全无据的才写我方假设。

用法:
    python -m scripts.talent.simulate_interviews --jd 品质经理
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

CVINTERVIEW = ROOT / "work" / "talent" / "cv_interview"
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
QUALITY = ROOT / "work" / "talent" / "cv_quality.json"
TEXT = ROOT / "work" / "talent" / "cv_text"
SHORTLIST = ROOT / "work" / "talent" / "shortlist"

#: **只模拟这些**。个人的姓名/电话/邮箱/婚姻/籍贯一律不编 —— 写了会被当真档案转手。
SIMULATE = {
    "F.WORK_LOCATION": ("现在住东莞哪个镇?到厂里通勤方便吗?",
                        "住东莞,到厂区通勤约 30 分钟内(模拟补全:按简历城市推断)"),
    "F.SALARY": ("期望薪资多少?",
                 "按现岗上浮 10–15% 可谈(模拟补全:简历未写期望,按同岗带宽估计)"),
    "F.AVAILABILITY": ("如果录用,多久能到岗?",
                       "一个月内(模拟补全:在职,按常规交接期)"),
    "F.CV_CURRENT_SALARY": ("目前年薪大概多少?",
                            "按市场同岗中位估计(模拟补全:简历未写)"),
    "F.EXP_INDUSTRY": ("之前主要做哪个行业?",
                       "制造业(模拟补全:由简历公司产品推断)"),
    "F.LANGUAGE_LEVEL": ("英语能用吗?书面和口语分别到什么程度?",
                         "能读写英文资料,口语可简单交流(模拟补全:按简历技能项估计)"),
    "F.EXP_ACTIVITY": ("简历上写的那几项工作,实际做到什么程度?能举一个例子吗?",
                       "按简历职责可复述一例(模拟补全:未访谈,仅按原文职责概括)"),
    "F.CV_PROJECTS": ("有没有印象比较深的项目?",
                      "按简历职责所述参与过产线/品质改善(模拟补全)"),
    "F.CV_TRAININGS": ("参加过哪些培训?有证书吗?",
                       "按简历证书项(模拟补全)"),
    "F.EDU_FULLTIME": ("学历是全日制还是在职读的?",
                       "按简历起止推断(模拟补全)"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    sl = yaml.safe_load((SHORTLIST / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    tg_f = SHORTLIST / f"{args.jd}.目标名单.yaml"
    tg = yaml.safe_load(tg_f.read_text(encoding="utf-8")) if tg_f.is_file() else {}
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    ids = list(tg.get("selected") or sl.get("kept") or [])
    if args.only:
        ids = [i for i in ids if args.only in i]

    CVINTERVIEW.mkdir(parents=True, exist_ok=True)
    made = 0
    for cid in ids:
        name = cid.replace("cand_", "")
        path = CVINTERVIEW / f"{name}.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        doc = doc or {}
        # **真访谈一律不碰** —— 有 answers 且里面没有 simulated 的,直接跳过
        real = [a for a in (doc.get("answers") or [])
                if str(a.get("basis") or "interview") not in ("simulated", "simulated_interview")]
        if real and not args.overwrite:
            print(f"  跳过 {name[:40]:42s} 有 {len(real)} 条真访谈答案")
            continue

        q = quality.get(cid) or {}
        answers = []
        for field, (question, answer) in SIMULATE.items():
            answers.append({
                "field": field,
                "question": question,
                "answer": answer,
                "basis": "simulated",
                "note": "**模拟答案**:开发/演练用,不是真人说的",
            })
        doc.update({
            "candidate": cid,
            "simulated": True,
            "channel": "模拟访谈(开发用,未真实进行)",
            "date": datetime.date.today().isoformat(),
            "interviewer": "—",
            "simulated_note": ("本文件 answers 全部是 `basis: simulated` —— 我方按简历与岗位常识推的,"
                               "不是访谈记录。任何对外场合必须先替换成真实答案。"),
            "answers": answers,
        })
        # 已有代拟 review 保留(别覆盖真访谈那类)
        if not doc.get("review") or str((doc.get("review") or {}).get("drafted_by")) == "ours":
            doc.setdefault("review", {})
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
                        encoding="utf-8")
        made += 1
        print(f"  模拟 {name[:40]:42s} {len(answers)} 条答案 · 品质证据 {q.get('kind') or '—'} 档")
    print(f"\n模拟 {made} 份。个人身份字段(姓名/电话/邮箱/婚姻/籍贯)**有意不编** —— 保持〔待补〕。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
