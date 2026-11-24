#!/usr/bin/env python3
"""把第 2 步的**标准 40 格定稿**翻译成第 3 步能用的**判定输入**。

## 为什么需要这一层

第 3 步（初筛）原来读 `jd_links/<JD>.yaml` + `requirement_library.yaml` —— 那是**旧版式**
（客户 66 个字段）的产物。现在定稿是标准 40 格，而且里面有 18 格是「HR 模拟确认」。
两个源并存会让"到底按哪份 JD 筛"变成第二个真相，所以中间加一层显式翻译：

    jd_drafts/<JD>.draft.json（第 2 步定稿）  +  jd_links/<JD>.yaml（机器阈值）
        → jd_requirements/<JD>.yaml（一条要求一行，带来源与"能不能拿来剔人"）

## 三条硬规矩（照 OVERVIEW 第 ③ 步）

1. **只有 A.1 性别 / A.2 年龄 / B.1 学历** 允许拿来剔除人 —— 这三项是简历里直接写着的。
   C.4 平均在职 / C.7 近5年 / A.3 到岗 / A.4 通勤 / A.5 薪资 是推导或一面才有 → `can_exclude: false`。
2. 原话含「等/优先/相关/不限/类」的阈值（如专业）**不剔人**（DEF-04：白名单不是穷举）。
3. 来源必须写清：`客户原文` / `文本规则` / `HR 模拟确认`。
   **HR 模拟确认的格子能进判定，但产物里必须标"依赖模拟值"** —— 它不是客户口径。

用法:
    python -m scripts.talent.build_jd_requirements --jd 品质经理
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
DRAFT_DIR = TALENT / 'jd_draft'
LINKS = TALENT / 'jd_links'
OUT = TALENT / 'jd_requirements'

#: 只允许拿这三项剔除人（简历里直接写着的属性）
CAN_EXCLUDE = {'A.1', 'A.2', 'B.1'}
#: 阈值不是穷举的信号 —— 出现就不能拿来剔人
FUZZY = ('等', '优先', '相关', '不限', '类')
#: 数据项 → requirement_library 里的算子口径（judge 要用）
OP_BY_ITEM = {'A.1': 'in', 'A.2': 'between', 'A.3': '<=', 'A.4': '<=', 'A.5': '<=',
              'B.1': '>=', 'B.2': 'in', 'B.3': '=', 'C.1': '>=', 'C.2': 'in',
              'C.4': '>=', 'C.6': '>=', 'C.7': '<='}
EDU_RANK = {'初中': 1, '高中': 2, '中专': 2, '大专': 3, '本科': 4, '硕士': 5, '博士': 6}


def _machine_value(item: str, text: str) -> dict | None:
    """从定稿里的**人读值**解析出机器阈值（只在解析得出时才给）。"""
    if not text:
        return None
    t = str(text)
    if item == 'A.2':
        m = re.search(r'(\d{2})\s*[~\-—至]\s*(\d{2})', t)
        return {'min': int(m.group(1)), 'max': int(m.group(2)), 'unit': '岁'} if m else None
    if item == 'B.1':
        for label, rank in EDU_RANK.items():
            if label in t:
                return {'num': rank}
        return None
    if item == 'B.2':
        parts = [x for x in re.split(r'[/、，,]', re.sub(r'等.*$', '', t)) if x.strip()]
        return {'in': parts, 'open_word': '等' if '等' in t else None} if parts else None
    if item == 'B.3':
        return {'num': True} if t.strip() in ('是', '需要', '要求', '全日制') else None
    if item in ('C.1', 'C.4', 'C.6'):
        m = re.search(r'(\d+(?:\.\d+)?)\s*年', t)
        return {'num': float(m.group(1)), 'unit': '年'} if m else None
    if item in ('A.3', 'C.7'):
        m = re.search(r'(\d+)', t)
        return {'num': int(m.group(1))} if m else None
    if item == 'A.5':
        m = re.search(r'(\d+)\s*[Kk千]', t)
        return {'num': int(m.group(1)), 'unit': 'K'} if m else None
    return None


def build(jd: str) -> dict:
    draft = json.loads((DRAFT_DIR / f'{jd}.draft.json').read_text(encoding='utf-8'))
    link_p = LINKS / f'{jd}.yaml'
    link = yaml.safe_load(link_p.read_text(encoding='utf-8')) if link_p.is_file() else {}
    cits = {c['id']: c for c in link.get('citations') or []}

    rows = []
    for r in draft['rows']:
        item = (r.get('data_item') or '').split('(')[0].strip()
        if not item or item.startswith('skill_') or r.get('assessable') != 'judgeable':
            continue
        # 阈值：优先用 jd_links 里的机器值（逐字引用附带），否则从定稿值解析
        value = None
        for cid in (r.get('cites') or []):
            if cits.get(cid, {}).get('value'):
                value = cits[cid]['value']
                break
        if value is None:
            value = _machine_value(item, r.get('value'))
        fuzzy = any(f in str(r.get('value') or '') for f in FUZZY)
        why_no = None
        if item not in CAN_EXCLUDE:
            why_no = f'{item} 不是"简历里直接写着"的属性（推导或一面才有）→ 不参与剔除'
        elif fuzzy:
            why_no = f'定稿值含「{[f for f in FUZZY if f in str(r.get("value"))][0]}」→ 白名单不是穷举'
        elif value is None:
            why_no = '解析不出机器阈值'
        elif r['state'] == '原文·空值':
            why_no = '客户写了栏目但值为空'

        req_id = (r.get('source_requirement') or ['REQ-DRAFT-' + r['code'].replace('F.', '')])[0]
        rows.append({
            'template_code': r['code'],
            'requirement': req_id if req_id and not req_id.endswith('*') else
                           'REQ-DRAFT-' + r['code'].replace('F.', ''),
            'label': r['label'],
            'data_item': item,
            'op': OP_BY_ITEM.get(item),
            'value': value,
            'source': r['state'],
            'basis': 'hr_response_mock' if r['state'] == 'HR 模拟确认' else
                     ('text_rule' if str(r.get('evidence') or '').startswith('["文本规则')
                      else 'client_verbatim'),
            'evidence_required': r.get('missing_means') and None,   # 占位，下面补
            'can_exclude': why_no is None,
            'cannot_exclude_why': why_no,
            'quote': (r.get('evidence') or [''])[0] if r.get('evidence') else '',
            'missing_means': r.get('missing_means'),
        })

    out = {
        '_doc': ('第 3 步判定输入：由第 2 步标准 40 格定稿翻译而来（一条要求一行）。'
                 'can_exclude=true 的项才允许拿来剔除候选人；其余只参与第 5 步排序。'),
        'jd': jd,
        'generated_from': f'jd_draft/{jd}.draft.json + jd_links/{jd}.yaml',
        'role_type': link.get('role_type'),
        'requirements': rows,
        'summary': {
            'total': len(rows),
            'can_exclude': sum(1 for r in rows if r['can_exclude']),
            'hr_mock_based': sum(1 for r in rows if r['basis'] == 'hr_response_mock'),
            'text_rule_based': sum(1 for r in rows if r['basis'] == 'text_rule'),
        },
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    args = ap.parse_args()
    data = build(args.jd)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f'{args.jd}.yaml'
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110),
                 encoding='utf-8')
    s = data['summary']
    print(f"{args.jd}: 判定输入 {s['total']} 条 · 可拿来剔除人 {s['can_exclude']} 条"
          f"（HR 模拟确认 {s['hr_mock_based']} · 文本规则 {s['text_rule_based']}）→ {p.relative_to(ROOT)}")
    for r in data['requirements']:
        flag = '✔剔除' if r['can_exclude'] else '—'
        print(f"  {flag} {r['data_item']:5s} {r['label']:12s} {str(r['value'])[:28]:30s}"
              f" {r['source']:8s} {r['cannot_exclude_why'] or ''}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
