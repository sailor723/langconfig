#!/usr/bin/env python3
"""给 CV 里缺失的数据项补**模拟值**,只为把第 5 步的管道端到端跑通。

为什么要有这个东西:第 4 步(HR 一面)还没跑。270 人里只有 10 人有一面记录,
而 9 条可判要求里有 5 条的供给率不到 20%(品质问题分析 4/270 = 1.5%)。
在这个状态下跑第 5 步,等于用 4 个人的数据去判 270 个人。

补模拟值的目的是**验证管道**,不是产出结论。所以它必须带三道锁:

    ① 落地在独立文件 `cv_mock/<候选>.yaml`,**绝不写进 cv_facts.json**
       (真事实要能一眼分清哪些是读来的、哪些是编的)
    ② 每个值都写 `basis: mock` + `rule` + `seed` —— 重跑得到同一个值,可以复算
    ③ 已有真值的一律不动;个人身份字段(姓名/电话/邮箱/婚姻/籍贯)**不补**

用法:
    python -m scripts.talent.mock_fill --jd 品质经理 --scope all
    python -m scripts.talent.mock_fill --jd 品质经理 --scope shortlist
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import BASIS_FIELD, PROP_FIELD, load_candidates, overlay_hr, overlay_llm  # noqa: E402
from scripts.talent.pick_final import load_inputs  # noqa: E402

OUT = ROOT / 'work' / 'talent' / 'cv_mock'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'

#: 模拟生成规则。**故意不用 LLM**:LLM 会按"他像什么样"去编,而这里要的是
#: "如果 HR 打了电话,可能得到什么" —— 一个带明确分布的抽样,偏差看得见。
PROP_RULES = {
    'age': ('年龄:28 + 均匀取 0..18 → 28~46 岁', lambda u, yrs: 28 + int(u * 19)),
    'educationRank': ('学历:按经验给 3(大专)或 4(本科),各 50%',
                      lambda u, yrs: 4 if u < 0.5 else 3),
    'major': ('专业:60% 落在客户点名的 5 个词里,40% 给「工商管理」',
              lambda u, yrs: '机电一体化技术' if u < 0.2 else
              '电子技术' if u < 0.4 else '自动化' if u < 0.55 else
              '工业工程' if u < 0.58 else '机械工程' if u < 0.6 else '工商管理'),
    'yearsPlatform': ('总年限:3 + 均匀取 0..12 → 3~15 年', lambda u, yrs: 3 + int(u * 13)),
    'yearsStated': ('声明年限:与总年限同分布 3~15 年', lambda u, yrs: 3 + int(u * 13)),
    'yearsComputed': ('推算年限:与总年限同分布 3~15 年', lambda u, yrs: 3 + int(u * 13)),
}

#: 组件类按"行业/岗位的概率"抽。这些数字**没有依据**,是我为了让分布合理挑的 ——
#: 所以必须写在产物里,不能藏。
COMP_RULES = {
    'skill_线束行业知识': 0.40, 'skill_品质问题分析': 0.45, 'skill_客户验厂': 0.25,
    'skill_英语': 0.35, 'skill_8D报告': 0.30, 'skill_QC七大手法': 0.30,
    'skill_SPC': 0.20, 'skill_CPK': 0.18, 'skill_6S': 0.30, 'skill_5WHY': 0.22,
}

#: 绝不补的字段(个人身份 + 与判定无关的敏感项)
NEVER = {'name', 'phone', 'email', 'marital', 'hometown', 'id_number', 'gender'}


def _u01(cid: str, field: str) -> float:
    """确定性随机:同一个候选人 + 同一个字段,永远同一个数 —— 重跑可复算。"""
    h = hashlib.sha256(f'{cid}|{field}'.encode()).hexdigest()
    return int(h[:12], 16) / float(0xFFFFFFFFFFFF)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--scope', choices=['all', 'shortlist'], default='all')
    args = ap.parse_args()

    pol = (interview_policy.load().get('mock_fill') or {})
    if pol.get('mode') != 'allowed' or args.jd not in (pol.get('scope') or []):
        raise SystemExit(f'mock_fill 未授权:{args.jd}。先在 interview_policy.yaml 里登记。')

    cat, lib, link, atts = load_inputs(args.jd)
    cands = [c for c in load_candidates() if not c['duplicate']]
    overlay_llm(cands)
    overlay_hr(cands)
    by_id = {c['id']: c for c in cands}

    ids = [c['id'] for c in cands]
    if args.scope == 'shortlist':
        sl = yaml.safe_load((SHORTLIST / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
        ids = [c for c in (sl.get('kept') or []) if c in by_id]

    props, comps = set(), set()
    for c in link['citations']:
        req = lib[c['requirement']]
        if req.get('_resolved'):
            comps |= set(req['_resolved'])
        elif req.get('attribute'):
            attr = req['attribute']
            prop = (BASIS_FIELD.get(c.get('year_basis') or req.get('year_basis') or 'platform',
                                    'yearsPlatform')
                    if attr in ('C.1', 'C.6') else PROP_FIELD.get(attr))
            if prop and prop not in NEVER:
                props.add(prop)

    OUT.mkdir(parents=True, exist_ok=True)
    filled, filled_comp, entries = {}, {}, 0
    for cid in ids:
        cand = by_id[cid]
        doc = {'candidate': cid, 'jd': args.jd, 'basis': 'mock',
               'policy': 'interview_policy.yaml#mock_fill', 'props': {}, 'components': {}}
        for prop in sorted(props):
            if cand.get(prop) is not None:
                continue
            desc, fn = PROP_RULES.get(prop, ('未知规则:取 3', lambda u, y: 3))
            u = _u01(cid, prop)
            doc['props'][prop] = {'value': fn(u, cand.get('yearsPlatform') or 0),
                                  'basis': 'mock', 'rule': desc, 'seed': round(u, 6),
                                  'note': '为了让第 5 步能跑而补的模拟值,不是事实'}
            filled[prop] = filled.get(prop, 0) + 1
            entries += 1
        for comp in sorted(comps):
            if comp in cand['components']:
                continue
            p = COMP_RULES.get(comp, 0.25)
            u = _u01(cid, comp)
            if u < p:
                doc['components'][comp] = {'held': True, 'basis': 'mock',
                                           'rule': f'按 {p:.0%} 概率抽中(seed={u:.6f})',
                                           'note': '模拟值,不是事实'}
                filled_comp[comp] = filled_comp.get(comp, 0) + 1
                entries += 1
        if doc['props'] or doc['components']:
            (OUT / f"{cid.replace('cand_', '')}.yaml").write_text(
                yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding='utf-8')

    print(f'mock_fill · {args.jd} · {args.scope} · {len(ids)} 人 → 补 {entries} 个值')
    print('  数值类:', {k: v for k, v in filled.items() if v})
    print('  组件类:', {k.replace('skill_', ''): v for k, v in filled_comp.items() if v})
    print(f'  落地: {OUT.relative_to(ROOT)}/ (每人一份, basis: mock)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
