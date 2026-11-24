#!/usr/bin/env python3
"""给「第 3 步 · HR 一面」补上**HR 评语**（模拟）。

## 为什么这一步必须有

第 3 步的产物是"补全的 CV + HR 评语"——一面（HR 那通电话，**必需**）问完数据之后，
HR 要写一段"这个人怎么样"。现在 `cv_interview/<人>.yaml` 里只有 `answers`，没有评语：
数据齐了、判断却没人说，第 5 步挑人时业务看不到任何"人话"。

所以这里按**已有证据**写一段评语（不做无根据的夸奖），并标 `basis: simulated`：

    review:
      text: ………
      basis: simulated        ← 代拟，不是真访谈
      by: HR（模拟）
      evidence: [依据到哪些格/哪些能力项]

评语**不进判定**（它不改变任何四态），只给人读；但它必须**能追到证据** ——
"沟通好、抗压"这种没有出处的评语，等于把面试官的印象当成事实。

用法:
    python -m scripts.talent.mock_hr_comment --jd 品质经理
    python -m scripts.talent.mock_hr_comment --jd 品质经理 --force
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
INTERVIEW = TALENT / 'cv_interview'
SHORTLIST = TALENT / 'shortlist'
DRAFT = TALENT / 'jd_draft'


def _queue(jd: str) -> tuple[set[str], dict]:
    """这份 JD 的面试名单 + 各人的判定摘要（评语要能追到证据）。"""
    p = SHORTLIST / f'{jd}.目标名单.yaml'
    ids: set[str] = set()
    rows: dict[str, dict] = {}
    if p.is_file():
        d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        for cid in (d.get('selected') or []):
            ids.add(cid)
        for r in d.get('rows') or []:
            cid = r.get('candidate') or r.get('id')
            if cid:
                rows[cid] = r
    iv = SHORTLIST / f'{jd}.面试名单.yaml'
    if iv.is_file():
        d = yaml.safe_load(iv.read_text(encoding='utf-8')) or {}
        for cid in (d.get('selected') or []):
            ids.add(cid)
    return ids, rows


def comment_for(cid: str, row: dict, ans: int, ratio: str) -> tuple[str, list[str]]:
    """按证据写一段评语。没有证据就不夸 —— 只陈述"读到了什么"。"""
    hard = row.get('hard_hits')
    soft = row.get('soft_hits')
    sat = row.get('satisfied')
    unk = row.get('unknown')
    parts, ev = [], []
    if isinstance(sat, int):
        parts.append(f"逐条判定里满足 {sat} 条、未知 {unk if isinstance(unk, int) else '—'} 条")
        ev.append(f'判定摘要：满足{sat}/未知{unk}')
    if isinstance(hard, int) and hard:
        parts.append(f"有 {hard} 项可验证的硬证据（客户审核/报告/系统类）")
        ev.append(f'硬证据 {hard} 项')
    elif isinstance(soft, int) and soft:
        parts.append(f"能力项多为自述（软证据 {soft} 项），需要业务面时现场举例")
        ev.append(f'软证据 {soft} 项')
    if ans:
        parts.append(f"一面补充了 {ans} 条结构化答案（模拟）")
        ev.append(f'一面答案 {ans} 条')
    parts.append(f"数据填充度 {ratio}")
    ev.append(f'数据填充度 {ratio}')
    body = '；'.join(parts)
    text = (f"（HR 模拟评语，不是真访谈）{body}。"
            f"建议业务面重点确认：能力项能否举出具体一段做法，以及到岗与通勤是否接受。")
    return text, ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    jd = args.jd
    ids, rows = _queue(jd)
    if not ids:
        print(f'{jd}: 没有面试名单，先跑 step 3（screen_cv + pick_interview_list）')
        return 1
    n = 0
    for cid in sorted(ids):
        p = INTERVIEW / f"{cid.replace('cand_', '')}.yaml"
        if not p.is_file():
            continue
        d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        if d.get('review') and not args.force:
            continue
        answers = d.get('answers') or []
        row = rows.get(cid) or {}
        ratio = f"{len(answers)} 条"
        text, ev = comment_for(cid, row, len(answers), ratio)
        d['review'] = {'text': text, 'basis': 'simulated', 'by': 'HR（模拟）',
                       'evidence': ev,
                       'note': '评语不进判定（不改变任何四态），只给人读；basis=simulated 表示代拟'}
        p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=100),
                     encoding='utf-8')
        n += 1
    print(f'{jd}: 给 {n} 份面试记录补上 HR 评语（模拟，不进判定）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
