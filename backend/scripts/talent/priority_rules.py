#!/usr/bin/env python3
"""业务优先条件的规则引擎 —— 目录里的每条规则在这里落地成一次判定。

为什么要单独一个模块:`priorities.py`(报数给用户看)和 `pick_interview_list.py`(排序)
必须用**同一套判定**,否则会出现"目录说命中 42 人、名单里却排不到"这种对不上的情况。

规则种类(目录里 kind 的取值):

    component_any   简历里真有其中任一能力项
    prop_between    某个数值字段在 [min, max]
    prop_gte        某个数值字段 ≥ value
    prop_eq         某个字段等于 value
    quality_verdict 品质岗经历判定在 in_ 里(有/待核/读不出/无)
    quality_months  品质岗时长 ≥ min(时长读不出来算不命中)
    interview_real  真一面答案条数 ≥ min
    asked_max       待核项数 ≤ max(成本条件)

**一律只用真实证据**:能力项取 cv_facts.skills,不看 cv_mock(模拟填充)。
"""
from __future__ import annotations

import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / 'work' / 'talent' / 'priority_catalog.yaml'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
QUALITY = ROOT / 'work' / 'talent' / 'cv_quality.json'
OPENQ = ROOT / 'work' / 'talent' / 'open_questions'
CV_IV = ROOT / 'work' / 'talent' / 'cv_interview'


def load_catalog() -> list:
    if not CATALOG.is_file():
        return []
    return (yaml.safe_load(CATALOG.read_text(encoding='utf-8')) or {}).get('items') or []


def _real_skills(cid: str, cv: dict) -> set:
    sk = ((cv.get(cid) or {}).get('skills') or {}).get('value') or []
    return {f"skill_{s['name']}" for s in sk if s.get('name')}


def make_ctx(jd: str) -> dict:
    """把判定要用到的外部数据一次性装好,避免每条规则重复读盘。"""
    cv = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    q = json.loads(QUALITY.read_text(encoding='utf-8')) if QUALITY.is_file() else {}
    asked = {}
    p = OPENQ / f'{jd}.yaml'
    if p.is_file():
        for it in ((yaml.safe_load(p.read_text(encoding='utf-8')) or {}).get('queue') or []):
            asked[it['candidate']] = asked.get(it['candidate'], 0) + 1
    return {'cv': cv, 'quality': q, 'asked': asked}


def real_interview_count(cid: str) -> int:
    from scripts.talent import interview_policy
    f = CV_IV / f"{cid.replace('cand_', '')}.yaml"
    if not f.is_file():
        return 0
    doc = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
    return sum(1 for a in (doc.get('answers') or []) if interview_policy.is_real_basis(a))


def met(rule: dict, cand: dict, ctx: dict) -> bool:
    kind = rule.get('kind')
    cid = cand['id']
    if kind == 'component_any':
        want = set(rule.get('components') or [])
        return bool(want & _real_skills(cid, ctx['cv']))
    if kind in ('prop_between', 'prop_gte', 'prop_eq'):
        v = cand.get(rule.get('prop'))
        if v is None:
            return False
        if kind == 'prop_between':
            return rule.get('min', -10**9) <= v <= rule.get('max', 10**9)
        if kind == 'prop_gte':
            return v >= rule.get('value', 0)
        return v == rule.get('value')
    if kind == 'quality_verdict':
        return (ctx['quality'].get(cid) or {}).get('verdict') in (rule.get('in_') or [])
    if kind == 'quality_months':
        q = ctx['quality'].get(cid) or {}
        if not q.get('months_known'):
            return False          # 时长读不出来就不算命中,不拿 0 冒充
        return (q.get('months') or 0) >= rule.get('min', 0)
    if kind == 'interview_real':
        return real_interview_count(cid) >= rule.get('min', 1)
    if kind == 'asked_max':
        return ctx['asked'].get(cid, 0) <= rule.get('max', 999)
    return False


def hits(rule: dict, cands: list, ctx: dict) -> int:
    return sum(1 for c in cands if met(rule, c, ctx))
