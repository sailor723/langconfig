#!/usr/bin/env python3
"""业务优先条件:列给用户挑、挑完落到 jd_inputs、然后重排面试名单。

这是给 **agent** 用的接口 —— 用户不需要知道 `skill_线束行业知识` 这种 id,
agent 把下面这张表念给用户,用户说"我要第 2 和第 5 条",agent 就 `--select` 它们。

    python -m scripts.talent.priorities --jd 品质经理 --list
        → 打一张带**命中人数**的选择表(命中人数是在当前初筛池上算的)

    python -m scripts.talent.priorities --jd 品质经理 --select P-IND-HARNESS P-CUST-AUDIT
        → 写进 jd_inputs/<JD>.yaml 的 interview_priorities

    python -m scripts.talent.priorities --jd 品质经理 --show
    python -m scripts.talent.priorities --jd 品质经理 --clear

**优先条件不是过滤**:命中的人排在前面,没命中的仍然留在候选池里。
挑完必须重跑 `pick_interview_list` 才生效。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import priority_rules as PR  # noqa: E402
from scripts.talent.evaluate import load_candidates, overlay_hr, overlay_llm  # noqa: E402

INPUTS = ROOT / 'work' / 'talent' / 'jd_inputs'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'


def load_ji(jd: str) -> tuple[pathlib.Path, dict]:
    p = INPUTS / f'{jd}.yaml'
    d = (yaml.safe_load(p.read_text(encoding='utf-8')) if p.is_file() else {}) or {}
    return p, (d if isinstance(d, dict) else {'jd': jd})


def pool(jd: str) -> tuple[list, dict]:
    cands = [c for c in load_candidates() if not c['duplicate']]
    overlay_llm(cands)
    overlay_hr(cands)
    by = {c['id']: c for c in cands}
    sl = yaml.safe_load((SHORTLIST / f'{jd}.yaml').read_text(encoding='utf-8')) \
        if (SHORTLIST / f'{jd}.yaml').is_file() else {}
    kept = [by[c] for c in (sl.get('kept') or []) if c in by]
    return kept, PR.make_ctx(jd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--list', action='store_true', help='列可选条件 + 命中人数')
    ap.add_argument('--select', nargs='*', default=None, help='按 id 选中(空格分隔)')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--clear', action='store_true')
    ap.add_argument('--decided-by', default='admin')
    args = ap.parse_args()

    items = PR.load_catalog()
    if not items:
        raise SystemExit('priority_catalog.yaml 不存在或为空')
    kept, ctx = pool(args.jd)

    if args.select is not None and not args.select and not args.clear:
        print('✗ --select 后面没给条件 id。')
        print('   看有哪些:`python -m scripts.talent.priorities --jd ' + args.jd + ' --list`')
        return 2

    if args.list or (args.select is None and not args.show and not args.clear):
        print(f'{args.jd} · 初筛池 {len(kept)} 人 · 可选业务优先条件:\n')
        print(f"{'#':>2} {'id':22} {'条件':34} {'命中':>5}  说明")
        for i, it in enumerate(items, 1):
            n = PR.hits(it['rule'], kept, ctx)
            cav = f" ⚠{it['caveat']}" if it.get('caveat') else ''
            print(f"{i:>2} {it['id']:22} {str(it.get('name'))[:32]:34} {n:>4}人  "
                  f"{str(it.get('why') or '')[:26]}{cav}")
        cur = (load_ji(args.jd)[1].get('interview_priorities') or {}).get('criteria') or []
        print('\n当前已选:' + ('、'.join(c.get('id') or c.get('name') for c in cur) if cur else '(无)'))
        print('\n挑法:--select P-IND-HARNESS P-CUST-AUDIT   (按 id,不是按序号也行)')
        return 0

    p, d = load_ji(args.jd)
    if args.clear:
        d.pop('interview_priorities', None)
        p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8')
        print('已清空优先条件')
        return 0

    if args.show:
        cur = (d.get('interview_priorities') or {}).get('criteria') or []
        if not cur:
            print('(未设业务优先条件)')
        for c in cur:
            print(f"  {c.get('id') or '?'} {c.get('name')}  ← {c.get('why') or ''}")
        return 0

    # --select:支持 id,也支持序号(方便用户说"第 2 和第 5 条")
    chosen = []
    for tok in args.select or []:
        it = next((x for x in items if x['id'] == tok), None)
        if it is None and tok.isdigit() and 1 <= int(tok) <= len(items):
            it = items[int(tok) - 1]
        if it is None:
            print(f'✗ 不认识的条件: {tok}')
            return 2
        chosen.append(it)
    if not chosen:
        print('✗ 没选中任何条件')
        return 2

    crit = [{'id': it['id'], 'name': it['name'], 'rule': it['rule'],
             'why': it.get('why'), 'caveat': it.get('caveat')} for it in chosen]
    d['interview_priorities'] = {'decided_by': args.decided_by,
                                 'decided_at': dt.date.today().isoformat(),
                                 'criteria': crit}
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8')

    print(f'✓ {args.jd}:已选 {len(crit)} 条优先条件 → {p.relative_to(ROOT)}')
    for it in chosen:
        print(f"   {it['id']:22} {it['name']:30} 池内命中 {PR.hits(it['rule'], kept, ctx)} 人")
    print('\n下一步:python -m scripts.talent.pick_interview_list --jd ' + args.jd
          + '   (重排面试名单)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
