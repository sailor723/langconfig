#!/usr/bin/env python3
"""给一份 JD **自动生成填充稿**：引用能给的给引用，其余一律用公司画像 mock。

## 三类来源，格子只有这三种

| 来源 | 怎么来 | 进判定吗 |
|---|---|---|
| `客户原文` | `jd_links/<JD>.yaml` 的 citations（逐字 + 行号） | ✅ |
| `HR 侧` | citations 里 `origin: hr`（我方闸门取值） | ✅ |
| `AI 模拟` | `company_profile.yaml` 的默认口径（班制/劳保/地点/预算/职级/编制…） | ❌ 客户确认前不进 |

**为什么必须自动生成**：40 格里有 10~18 格客户从来不写。手工给每份 JD 编一遍，五份 JD 就会出现
五个版本的"两班倒"，最后没人知道哪个是真的 —— 所以 mock 全部来自**一处**公司画像，
并在定稿里逐格标 `AI 模拟` + 待谁确认。

## 产物

    work/talent/jd_draft/<JD>.fill.yaml      填充稿（可手改；改了就以手改为准）
    → 再跑 draft_jd / render_jd_standard 出定稿

用法:
    python -m scripts.talent.mock_fill_jd --jd 专案工程师
    python -m scripts.talent.mock_fill_jd --all
    python -m scripts.talent.mock_fill_jd --jd X --force    # 覆盖已存在的手改稿
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
DRAFT_DIR = TALENT / 'jd_draft'
LINKS = TALENT / 'jd_links'
TEMPLATE = TALENT / 'templates' / 'standard_jd_template.yaml'
PROFILE = TALENT / 'company_profile.yaml'

MOCK = '我方建议·待确认'


def _rows() -> list[dict]:
    doc = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8')) or {}
    return [f for s in doc.get('sections') or [] for f in s.get('fields') or []]


def _cites(jd: str) -> tuple[dict, list[dict]]:
    p = LINKS / f'{jd}.yaml'
    if not p.is_file():
        return {}, []
    d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    return d, d.get('citations') or []


def _value_of(c: dict) -> str:
    v = c.get('value')
    if isinstance(v, dict):
        if 'in' in v:
            s = '、'.join(str(x) for x in v['in'])
            return s + ('（等，开区间）' if v.get('open_word') else '')
        if 'min' in v and 'max' in v:
            return f"{v['min']}~{v['max']}{v.get('unit') or ''}"
        if 'num' in v:
            return f"{v['num']}{v.get('unit') or ''}" + (f"（{v['domain']}）" if v.get('domain') else '')
    eb = (c.get('verbatim') or '').strip()
    return eb


def _mock_value(code: str, jd: str, dept: str, role_label: str, prof: dict) -> tuple[str, str]:
    """公司画像 → (模拟值, 为什么这么模拟)。**所有 mock 只从 company_profile.yaml 取**。"""
    company = prof.get('company') or {}
    band = (prof.get('salary_bands') or {}).get(role_label or '员工岗', '')
    table = {
        'F.JD_JOB_PURPOSE': ((prof.get('purpose_template') or '').format(jd=jd, department=dept or '该部门'),
                             '客户稿没有岗位目的；按公司画像模板 + 部门名生成'),
        'F.JD_SUCCESS_CRITERIA': ('；'.join(prof.get('kpi_template') or []),
                                  '客户稿没有量化指标；按公司画像 KPI 模板'),
        'F.JD_JOB_GRADE': ((prof.get('grade_scale') or {}).get(role_label or '员工岗', ''),
                           f'客户稿没有职级；按 {role_label or "员工岗"} 台阶套档'),
        'F.JD_WORK_LOCATION': (company.get('plant') or '', '客户 10 份 JD 全没写厂区；按公司画像'),
        'F.SALARY': (band, '客户没给预算；按公司画像挂牌区间（判定前须换成客户真实预算）'),
        'F.COMMUTE': (company.get('commute') or '', 'HR 闸门缺取值；按「有厂车、单程一小时」'),
        'F.AVAILABILITY': ('≤ 4 周', '客户没给到岗周期；按 4 周上限'),
        'F.AVG_TENURE': ('≥ 2 年', 'HR 闸门；按「平均在职不低于 2 年」'),
        'F.RECENT_SEGMENTS': ('近 5 年 ≤ 3 家', 'HR 闸门；按「近 5 年不超过 3 家」'),
        'F.JD_HEADCOUNT': ('1 人', f"按公司画像编制口径（{company.get('headcount_policy') or ''}）"),
        'F.JD_HIRING_REASON': ('替补（原任离职）', '客户未说明；按公司画像的替补优先口径'),
        'F.SHIFT': (company.get('shift_policy') or '', '客户稿没有班制；按公司画像（一线岗才触发）'),
        'F.JD_ENVIRONMENT': (company.get('environment') or '', '客户稿没有作业环境；按公司画像'),
        'F.JD_PHYSICAL_DEMAND': (company.get('physical') or '', '客户稿没有体力要求；按公司画像'),
        'F.JD_PPE': (company.get('ppe_policy') or '', '客户稿没有劳保配置；按公司画像'),
        'F.JD_CONTRACT_TYPE': (company.get('contract') or '', '客户未写用工类型；按公司画像'),
        'F.CLEARANCE': (company.get('background_check') or '', '客户未提背调；按公司画像（敏感岗背调）'),
        'F.JD_CONFIDENTIALITY': (company.get('confidentiality') or '', '客户未提保密；按公司画像'),
        'F.DECISION_AUTHORITY': ('按课级主管权限：停线、让步接收、供应商扣款需报部门主管',
                                 '客户未写决策权限；按课级主管惯例'),
        'F.BUDGET_OWNERSHIP': ('部门品质成本与不良损失', '客户未写预算责任；按岗位职责推断'),
        'F.CROSS_DEPT': ('生产 / 工程 / 采购 / 客户', '客户未写跨部门接口；按公司组织推断'),
        'F.GENDER': ('（不设限）', '客户未写性别；按公司口径不筛'),
        'F.CERTIFICATION': ('（不作硬门槛，加分项）', '客户未写证书要求'),
        'F.LANGUAGE_LEVEL': ('（未要求）', '客户未写外语要求'),
        'F.COMPETENCY': ('（列名不判，需结构化面试量表）', '素质类没有数据项，对所有人不可判'),
        'F.EDU_FULLTIME': ('不限', '客户未写全日制'),
        'F.EXP_DOMAIN': ('（未限定领域）', '客户未写领域年限'),
        'F.JD_ACTIVITY_TEXT': ('（按职责条目执行，频次待定）', '客户的事务表述表为空'),
        'F.JD_ACTIVITY_FREQ': ('（按职责条目执行，频次待定）', '客户的事务表述表为空'),
        'F.REPORTS_TO': ('部门主管', '原文「直接上司」栏为空；按组织层级模拟'),
    }
    return table.get(code, ('（待客户补）', '客户稿没有这一项，也没有画像默认值'))


def build_fill(jd: str) -> dict:
    prof = yaml.safe_load(PROFILE.read_text(encoding='utf-8')) or {}
    links, cits = _cites(jd)
    by_req: dict[str, dict] = {}
    for c in cits:
        by_req.setdefault(c.get('requirement') or '', c)
    role_type = (links.get('role_type') or '').strip()
    role_label = {'staff': '员工岗', 'manager': '经理岗'}.get(role_type, '')
    dept = (links.get('department') or '').strip()

    # 基础盘：Phase 1 的**文本档**（22 格纯文本规则 + 18 格文本兜底）—— 一份实现，两处复用
    from services.talent_gap import text_gap_for  # noqa: PLC0415

    base = {f['code']: f for f in text_gap_for(jd)['fields']}

    over: dict[str, dict] = {}
    n_mock = n_text = n_cite = 0
    for f in _rows():
        code = f['code']
        cond = f.get('conditional_on') or ''

        # ① 条件字段：岗位类别不触发 → 不适用（不拿 mock 去填用不上的格）
        if f.get('requirement_level') == 'conditional' and cond.startswith('岗位类别='):
            need_mgr = '经理岗' in cond
            if role_label and ((need_mgr and role_label != '经理岗')
                               or (not need_mgr and role_label == '经理岗')):
                over[code] = {'state': '不适用', 'why': f'条件字段（{cond}），本 JD 是{role_label}'}
                continue

        # ② 引用能给的（含 REQ-D-* 这类通配）：一条字段可挂多条引用
        cands: list[dict] = []
        for pat in f.get('source_requirement') or []:
            if pat.endswith('*'):
                pre = pat[:-1]
                cands += [c for rid, c in by_req.items() if rid.startswith(pre)]
            elif pat in by_req:
                cands.append(by_req[pat])
        seen, uniq = set(), []
        for c in cands:
            if c['id'] not in seen:
                seen.add(c['id'])
                uniq.append(c)
        if uniq:
            vals = []
            for c in uniq[:4]:
                v = _value_of(c)
                if v and v not in vals:
                    vals.append(v)
            hr = all(c.get('origin') == 'hr' for c in uniq)
            over[code] = {'state': 'HR 侧' if hr else '客户原文',
                          'value': '；'.join(vals)[:160],
                          'cites': [c['id'] for c in uniq[:4]]}
            n_cite += 1
            continue

        # ③ 文本档判出来的（正文规则/兜底）→ 直接用，并标明"未抽引用"
        b = base.get(code) or {}
        if b.get('state') in ('原文', '原文·空值'):
            # 文本档用自己的词（原文 / 原文·空值），填充稿用 draft_jd 的词（客户原文 / 原文·空值）
            state = '客户原文' if b['state'] == '原文' else '原文·空值'
            item = {'state': state, 'value': b.get('value'), 'why': b.get('why') or '',
                    'basis': 'text-fallback' if b.get('needs_citation') else 'text-rule'}
            if b.get('needs_citation'):
                item['needs_citation'] = True
            if state == '原文·空值':
                # 客户写了栏目却没填 → 要写明"谁补"，否则草稿自检会判它没有交代
                item['needs'] = '客户补（栏目在、值是空的）'
            over[code] = item
            n_text += 1
            continue

        # ④ 都拿不到 → 公司画像 mock
        val, why = _mock_value(code, jd, dept, role_label, prof)
        over[code] = {'state': MOCK, 'basis': 'mock', 'value': val, 'why': why,
                      'needs': '客户/HR 确认'}
        n_mock += 1

    head = (f'# {jd} · 自动生成填充稿（引用 + 文本兜底 + 公司画像 mock）\n'
            f'#\n'
            f'# 生成器：scripts/talent/mock_fill_jd.py（--force 才覆盖手改）。\n'
            f'# 来源优先级：jd_links 逐字引用 → Phase 1 文本规则/兜底 → company_profile.yaml 的默认口径。\n'
            f'# 标 basis: mock 的格子**客户确认前不进判定**。\n')
    data = {'_doc': head, 'jd': jd, 'role_type': role_type,
            'counts': {'cite': n_cite, 'text': n_text, 'mock': n_mock},
            'overrides': over}
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--force', action='store_true', help='覆盖已存在的填充稿')
    args = ap.parse_args()
    jds = sorted(p.stem for p in LINKS.glob('*.yaml')) if args.all else [args.jd or '']
    if not jds or not jds[0]:
        ap.error('给 --jd 或 --all')
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for jd in jds:
        dst = DRAFT_DIR / f'{jd}.fill.yaml'
        if dst.is_file() and not args.force:
            print(f'{jd}: 已有填充稿，跳过（--force 覆盖）')
            continue
        data = build_fill(jd)
        dst.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110),
                       encoding='utf-8')
        n_mock = sum(1 for v in data['overrides'].values() if v.get('basis') == 'mock')
        n_cite = len(data['overrides']) - n_mock
        print(f'{jd}: 40 格 → 引用/HR {n_cite} · AI 模拟 {n_mock} → {dst.relative_to(ROOT)}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
