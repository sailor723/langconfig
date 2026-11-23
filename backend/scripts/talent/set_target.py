#!/usr/bin/env python3
"""让用户直接定目标人数 —— 面试几个、短名单几个。写在 jd_inputs 里,带谁定的、哪天。

两个目标,别混:

    interview_target   第 3 步:从初筛池里挑**几个人去面**     (HR 打电话的产能)
    shortlist_target   第 5 步:面完之后**短名单留几个人**     (交给第 6 步去选 ≤4)

约束(自动校验,不满足就报错,不偷偷改):
    1 ≤ shortlist_min ≤ shortlist_max ≤ interview_target ≤ 池子大小
理由:面试批次必须 ≥ 短名单上限 —— 否则面完还不够挑,等于白面;
     面试批次也不可能超过池子里的人数。

用法:
    python -m scripts.talent.set_target --jd 品质经理 --interview 30 --shortlist 8~12
    python -m scripts.talent.set_target --jd 品质经理 --interview 10
    python -m scripts.talent.set_target --jd 品质经理 --show
    python -m scripts.talent.set_target --all --interview 20      # 所有 JD 统一改
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

INPUTS = ROOT / 'work' / 'talent' / 'jd_inputs'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'


def parse_range(text: str) -> tuple[int, int]:
    if not text:
        return (0, 0)
    if '~' in text:
        a, b = text.split('~', 1)
        return (int(a), int(b))
    n = int(text)
    return (n, n)


def show(jd: str) -> dict:
    p = INPUTS / f'{jd}.yaml'
    d = yaml.safe_load(p.read_text(encoding='utf-8')) if p.is_file() else {}
    if not isinstance(d, dict):
        d = {}
    it = (d.get('interview_target') or {})
    st = (d.get('shortlist_target') or {})
    sl = yaml.safe_load((SHORTLIST / f'{jd}.yaml').read_text(encoding='utf-8')) \
        if (SHORTLIST / f'{jd}.yaml').is_file() else {}
    pool = len((sl or {}).get('kept') or [])
    print(f'{jd}:')
    print(f"  面试批次 interview_target = {it.get('n') or '(未设,默认 10)'}"
          f"  —— {it.get('decided_by') or '—'} / {it.get('decided_at') or '—'}")
    print(f"  短名单   shortlist_target = {st.get('min')}~{st.get('max')}"
          f"  —— {st.get('asked_by') or '—'}")
    print(f'  初筛池   kept = {pool} 人')
    pr = (d.get('interview_priorities') or {}).get('criteria') or []
    print('  业务优先 ' + ('、'.join(c.get('name') or '?' for c in pr) if pr else '(未设)'))
    return {'interview': it.get('n'), 'min': st.get('min'), 'max': st.get('max'), 'pool': pool}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd')
    ap.add_argument('--all', action='store_true', help='对 jd_inputs 下所有 JD 生效')
    ap.add_argument('--interview', type=int, help='面试批次人数(第 3 步)')
    ap.add_argument('--shortlist', help='短名单区间,例 8~12 或 10')
    ap.add_argument('--decided-by', default='admin')
    ap.add_argument('--why', default='')
    ap.add_argument('--show', action='store_true')
    # 业务优先条件:可以重复给。格式 "名称=skill_组件,skill_组件"
    ap.add_argument('--priority', action='append', default=[],
                    help='业务优先条件,例:"线束行业=skill_线束行业知识"(可重复)')
    ap.add_argument('--clear-priorities', action='store_true')
    args = ap.parse_args()

    jds = []
    if args.all:
        jds = sorted(p.stem for p in INPUTS.glob('*.yaml'))
    elif args.jd:
        jds = [args.jd]
    elif args.show:
        jds = sorted(p.stem for p in INPUTS.glob('*.yaml'))
    else:
        ap.error('给 --jd 或 --all')

    if args.show or (not args.interview and not args.shortlist
                     and not args.priority and not args.clear_priorities):
        for jd in jds:
            show(jd)
            print()
        return 0

    today = dt.date.today().isoformat()
    for jd in jds:
        p = INPUTS / f'{jd}.yaml'
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(yaml.safe_dump({'jd': jd}, allow_unicode=True), encoding='utf-8')
        d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        if not isinstance(d, dict):
            d = {'jd': jd}
        cur = show(jd)

        it_n = args.interview if args.interview is not None else (cur['interview'] or 10)
        smin, smax = (parse_range(args.shortlist) if args.shortlist
                      else (cur['min'] or 5, cur['max'] or 8))

        errs = []
        if not (1 <= it_n <= 200):
            errs.append(f'面试批次 {it_n} 超出合理范围 1~200')
        if not (1 <= smin <= smax):
            errs.append(f'短名单区间 {smin}~{smax} 不合法')
        if it_n < smax:
            errs.append(f'面试批次 {it_n} < 短名单上限 {smax} —— 面完还不够挑。'
                        f'要么加大面试批次(建议 ≥{smax}),要么降低短名单上限')
        if cur['pool'] and it_n > cur['pool']:
            errs.append(f'面试批次 {it_n} > 初筛池 {cur["pool"]} 人 —— 池子里没这么多人')
        if errs:
            print(f'✗ {jd}:')
            for e in errs:
                print('   -', e)
            return 2

        d['interview_target'] = {
            'n': it_n, 'decided_by': args.decided_by, 'decided_at': today,
            'why': args.why or '用户指定面试批次',
        }
        if args.clear_priorities:
            d.pop('interview_priorities', None)
        elif args.priority:
            crit = []
            for item in args.priority:
                name, _, comps = item.partition('=')
                crit.append({'name': name.strip(),
                             'components': [x.strip() for x in comps.split(',') if x.strip()],
                             'note': '业务优先条件:命中者排在前面(不是硬过滤)'})
            d['interview_priorities'] = {'decided_by': args.decided_by, 'decided_at': today,
                                         'criteria': crit}
        d['shortlist_target'] = {
            'min': smin, 'max': smax, 'asked_by': (d.get('shortlist_target') or {}).get('asked_by') or 'hr',
            'set_by': args.decided_by, 'set_at': today,
        }
        p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8')
        gap = cur['pool'] - it_n
        _pr = [c['name'] for c in (d.get('interview_priorities') or {}).get('criteria') or []]
        print(f'✓ {jd}: 面试 {it_n} 人 · 短名单 {smin}~{smax} · 初筛池 {cur["pool"]} 人'
              + (f' · 业务优先 {"/".join(_pr)}' if _pr else '')
              + (f'(不面的 {gap} 人留在池里)' if gap > 0 else '')
              + f' → 写入 {p.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
