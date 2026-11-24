#!/usr/bin/env python3
"""**模拟 HR 的回复**：对定稿里那几格「AI 模拟」逐格给一个 HR 口径（同意 / 改成 / 不采纳）。

## 为什么要有这一步

定稿里 18~27 格是 AI 按公司画像模拟的。这些格子**只有 HR 与业务能拍板**。真人不回之前，
流程会卡在「等确认」上 —— 所以先模拟一版回复把链条跑通，但**必须标清是模拟**：

    work/talent/jd_draft/<JD>.hr_response.yaml    HR 的逐格回复（模拟）
    → 重跑 draft_jd / render_jd_standard，那几格从「AI 模拟」变成「HR 模拟确认（未签字）」

## 三种回复

| decision | 含义 | 落到定稿 |
|---|---|---|
| `accept` | 就按 AI 模拟的来 | 值不变，状态升为 HR 模拟确认 |
| `change` | 改一个值（HR 的口径替掉 AI 的） | 值换成 HR 给的，状态 HR 模拟确认 |
| `reject` | 这条不写进 JD（例如不设性别门槛） | 保留「不适用/不写」，记原因 |

**绝不写进 `company_profile.yaml`**：那是公司默认口径；HR 针对某一份 JD 的回复属于这一份，
混进画像会让下一份 JD 也跟着变。

用法:
    python -m scripts.talent.mock_hr_response --jd 品质经理
    python -m scripts.talent.mock_hr_response --all
    python -m scripts.talent.mock_hr_response --jd 品质经理 --force
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
DRAFT_DIR = TALENT / 'jd_draft'

MOCK_STATE = '我方建议·待确认'

#: 按字段给 HR 的典型回复口径（没列到的默认 accept）。
#  值写的是"HR 会怎么说"，不是"我们希望什么"。
HR_RULES: dict[str, dict] = {
    'F.SALARY': {'decision': 'change', 'value': '10~15K，预算上限 15K',
                 'note': '按今年品质岗预算上调 1K；上限 15K 是硬顶，超了走特批'},
    'F.COMMUTE': {'decision': 'change', 'value': '单程 ≤ 90 分钟（有厂车）',
                  'note': '厂车覆盖东莞全域，90 分钟内都算可接受；跨市不考虑'},
    'F.JD_JOB_GRADE': {'decision': 'change', 'value': 'E3（资深员工）',
                       'note': '品质经理原文直接下属为「无」，按员工岗资深档 E3，不套 M 序列'},
    'F.REPORTS_TO': {'decision': 'change', 'value': '厂长',
                     'note': '品保课直接向厂长汇报（品保部目前空缺）'},
    'F.GENDER': {'decision': 'reject', 'value': '（不写）',
                 'note': '公司口径：除涉密/更衣岗外不设性别门槛，这一格不写进 JD'},
    'F.JD_HEADCOUNT': {'decision': 'accept', 'note': '确实补 1 人'},
    'F.JD_HIRING_REASON': {'decision': 'accept', 'note': '原任已于上月离职，属替补'},
    'F.SHIFT': {'decision': 'accept', 'note': '品质岗随产线跟班，常白班为主'},
    'F.CLEARANCE': {'decision': 'accept', 'note': '敏感岗统一做背调（无犯罪 + 学历）'},
    'F.JD_CONFIDENTIALITY': {'decision': 'accept', 'note': '接触客户图纸，必须签保密协议'},
    'F.JD_CONTRACT_TYPE': {'decision': 'accept', 'note': '全职劳动合同'},
}


def build(jd: str) -> dict:
    d = json.loads((DRAFT_DIR / f'{jd}.draft.json').read_text(encoding='utf-8'))
    rows = [r for r in d['rows'] if r['state'] == MOCK_STATE]
    out: dict[str, dict] = {}
    for r in rows:
        rule = HR_RULES.get(r['code']) or {'decision': 'accept', 'note': '同意按此执行'}
        out[r['code']] = {
            'decision': rule['decision'],
            'value': rule.get('value', r.get('value')),
            'note': rule.get('note', ''),
            'by': 'HR（模拟）',
            'basis': 'hr_response_mock',
        }
    return {
        '_doc': ('HR 对「AI 模拟」格子的逐格回复（**模拟**，bar 上没签字）。 '
                 'accept=按模拟的来 / change=改成 HR 的口径 / reject=不写进 JD。 '
                 '重跑 draft_jd 后这些格子状态变成「HR 模拟确认（未签字）」。'),
        'jd': jd,
        'stage': 'hr-response-mock',
        'reviewed_by': 'HR（模拟）',
        'signed': False,
        'responses': out,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    jds = sorted(p.stem.replace('.draft', '') for p in DRAFT_DIR.glob('*.draft.json')) \
        if args.all else [args.jd or '']
    if not jds or not jds[0]:
        ap.error('给 --jd 或 --all')
    for jd in jds:
        dst = DRAFT_DIR / f'{jd}.hr_response.yaml'
        if dst.is_file() and not args.force:
            print(f'{jd}: 已有 HR 回复稿，跳过（--force 覆盖）')
            continue
        data = build(jd)
        dst.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110),
                       encoding='utf-8')
        dec = [v['decision'] for v in data['responses'].values()]
        print(f'{jd}: {len(dec)} 格 HR 回复 → accept {dec.count("accept")} / '
              f'change {dec.count("change")} / reject {dec.count("reject")} → {dst.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
