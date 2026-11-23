#!/usr/bin/env python3
"""一个候选人的详情 —— 给 Talent 面板的「候选人详情」用,也给命令行用。

为什么单独成模块:面试名单 md 只该是**名单**(一屏能扫完);每人 9 项待问、画像、
证据、原文都塞进去会把名单撑成 900 行。详情按需取,不写进名单。

数据全部来自已有产物,不新造:
    画像        cv_facts(值+basis)/ abox
    品质岗经历   cv_quality(verdict/kind/months/quote)
    能力项      cv_facts.skills ∩ JD 要组件,按 evidence_role 分硬/软
    待问项      open_questions/<JD>.yaml 里这个人的全部条目
    排序依据    interview_list 那套九层键的数值

用法:
    python -m scripts.talent.candidate_detail --jd 品质经理 --list
    python -m scripts.talent.candidate_detail --jd 品质经理 --id cand_xxx
    python -m scripts.talent.candidate_detail --jd 品质经理 --id cand_xxx --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import priority_rules as PR  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
OPENQ = ROOT / 'work' / 'talent' / 'open_questions'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
QUALITY = ROOT / 'work' / 'talent' / 'cv_quality.json'
HR_FACTS = ROOT / 'work' / 'talent' / 'hr_facts.json'
CATALOG = ROOT / 'work' / 'talent' / 'component_catalog.yaml'
CV_TEXT = ROOT / 'work' / 'talent' / 'cv_text'
CV_DOCS = ROOT / 'work' / 'talent' / 'cv_docs'


def _role_map() -> dict:
    d = yaml.safe_load(CATALOG.read_text(encoding='utf-8'))
    return {c['id']: c.get('evidence_role', 'soft') for c in d.get('components') or []}


def _asks(jd: str) -> dict:
    p = OPENQ / f'{jd}.yaml'
    out: dict[str, list] = {}
    if p.is_file():
        for it in (yaml.safe_load(p.read_text(encoding='utf-8')) or {}).get('queue') or []:
            out.setdefault(it['candidate'], []).append(it)
    return out


def _ji(jd: str) -> dict:
    d = ROOT / 'work' / 'talent' / 'jd_inputs' / f'{jd}.yaml'
    return (yaml.safe_load(d.read_text(encoding='utf-8')) if d.is_file() else {}) or {}


def interview_list(jd: str) -> dict:
    p = SHORTLIST / f'{jd}.面试名单.yaml'
    return (yaml.safe_load(p.read_text(encoding='utf-8')) if p.is_file() else {}) or {}


def load_ctx(jd: str) -> dict:
    from scripts.talent import interview_policy
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    mode, _ = interview_policy.mode_for(jd)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    cat, lib, link, atts = load_inputs(jd)
    return {
        'cands': {c['id']: c for c in cands},
        'lib': lib, 'link': link, 'atts': atts,
        'cv': json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {},
        'quality': json.loads(QUALITY.read_text(encoding='utf-8')) if QUALITY.is_file() else {},
        'hr': json.loads(HR_FACTS.read_text(encoding='utf-8')) if HR_FACTS.is_file() else {},
        'role': _role_map(), 'asks': _asks(jd), 'ji': _ji(jd), 'pctx': PR.make_ctx(jd),
    }


def detail(jd: str, cid: str, ctx: dict | None = None) -> dict:
    """一个候选人的全部可读事实。**只读已有产物,不重新判定、不造数。**"""
    ctx = ctx or load_ctx(jd)
    cand = ctx['cands'].get(cid)
    if not cand:
        raise SystemExit(f'库里没有 {cid}')
    cv, qual = ctx['cv'], ctx['quality'].get(cid) or {}
    hr = ctx['hr'].get(cid) or {}
    lst = interview_list(jd)
    row = next((r for r in (lst.get('rows') or []) if r.get('candidate') == cid), None)
    rank = (next((i for i, c in enumerate(lst.get('selected') or [], 1) if c == cid), None))

    skills = ((cv.get(cid) or {}).get('skills') or {}).get('value') or []
    real = {f"skill_{s['name']}" for s in skills if s.get('name')}
    reqs = []
    for c in ctx['link']['citations']:
        req = ctx['lib'][c['requirement']]
        hit = [x for x in (req.get('_resolved') or []) if x in real]
        reqs.append({'clause': c['id'], 'name': req.get('name'),
                     'client_text': c.get('verbatim'), 'client_line': c.get('txt_line'),
                     'hit': sorted(x.replace('skill_', '') for x in hit),
                     'hit_role': ['hard' if ctx['role'].get(x) == 'hard' else 'soft' for x in hit]})

    crit = (ctx['ji'].get('interview_priorities') or {}).get('criteria') or []
    prio = [it.get('name') for it in crit if PR.met(it.get('rule') or {}, cand, ctx['pctx'])]
    verdicts = judge_all(cand, ctx['link'], ctx['lib'], ctx['atts'])

    return {
        'candidate': cid, 'name': cid.replace('cand_', ''),
        'profile': {'age': cand.get('age'), 'education': cand.get('educationRank'),
                    'major': cand.get('major'), 'years': cand.get('yearsPlatform'),
                    'fullTime': cand.get('fullTime'), 'gender': cand.get('gender')},
        'quality': {k: qual.get(k) for k in
                    ('verdict', 'kind', 'months', 'months_known', 'quote', 'why_short')},
        'stability': {'avg_tenure_years': (hr.get('avg_tenure_years') or {}).get('value'),
                      'segments': (hr.get('segment_count') or {}).get('value'),
                      'recent5y': (hr.get('recent5y_segments') or {}).get('value')},
        'requirements': reqs,
        'verdicts': {c['id']: verdicts[c['requirement']]['state'] for c in ctx['link']['citations']},
        'priorities_hit': prio,
        'asks': ctx['asks'].get(cid) or [],
        'in_list': bool(row), 'rank': rank, 'rank_row': row,
        'sources': {
            'cv_text': next((str(p.relative_to(ROOT)) for p in CV_TEXT.glob('*.txt')
                             if cid.replace('cand_', '')[:10] in p.stem), None),
            'cv_doc': next((str(p.relative_to(ROOT)) for p in CV_DOCS.glob('*.md')
                            if cid.replace('cand_', '')[:10] in p.name), None),
        },
    }


def render_md(d: dict) -> str:
    p, q = d['profile'], d['quality']
    out = [f"# {d['name']}", '']
    if d.get('rank') and d.get('rank_row'):
        r = d['rank_row']
        out += [f"> 面试名单第 **{d['rank']}** 位。排序键:硬证据 {r.get('hard_hits', 0)} · "
                f"软证据 {r.get('soft_hits', 0)} · 规则 {r.get('prio_hits', 0)} · "
                f"客户优先 {r.get('prefer_hits', 0)} · "
                f"年限 {r.get('years') if r.get('years') is not None else '未知'} · "
                f"在职均值 {r.get('tenure')} 年 · 待核 {r.get('n_ask', 0)} 项", '']
    out += ['## 画像', '', '| 项 | 值 |', '|---|---|',
            f"| 年龄 | {p['age'] or '未知'} |", f"| 学历 | {p['education'] or '未知'} |",
            f"| 专业 | {p['major'] or '未知'} |",
            f"| 总年限 | {p['years'] if p['years'] is not None else '未知'} |",
            f"| 全日制 | {p['fullTime'] if p['fullTime'] is not None else '未知'} |", '']
    qkind = f" · {q.get('kind')}档" if q.get('kind') else ''
    qmon = f" · {q.get('months')} 月" if q.get('months') else ' · 时长未知'
    out += ['## 品质岗经历', '', f"判定 **{q.get('verdict') or '—'}**{qkind}{qmon}", '']
    if q.get('why_short'):
        out += [f"> {q['why_short']}", '']
    if q.get('quote'):
        out += [f"> 原文:「{str(q['quote'])[:160]}」", '']
    st = d['stability']
    out += ['## 稳定性', '',
            f"- 平均在职:{st['avg_tenure_years'] if st['avg_tenure_years'] is not None else '未知'} 年",
            f"- 工作段数:{st['segments'] or '未知'}",
            f"- 近 5 年段数:{st['recent5y'] if st['recent5y'] is not None else '未知'}", '']
    out += ['## 简历里真有的能力项', '', '| 条款 | 客户原文 | 命中项 | 性质 |', '|---|---|---|---|']
    any_hit = False
    for r in d['requirements']:
        if not r['hit']:
            continue
        any_hit = True
        roles = '、'.join('硬' if x == 'hard' else '软' for x in r['hit_role'])
        out.append(f"| {r['clause']} {r['name']} | {str(r['client_text'])[:40]} | "
                   f"{'、'.join(r['hit'])} | {roles} |")
    if not any_hit:
        out.append('| — | — | 无(简历里没有任何 JD 要求的能力项) | — |')
    out += ['', '## 逐条判定(本体)', '',
            '> 条款码(C-01…)是引用编号,单独看不出含义,所以这一列给了要求名与客户原文;',
            '> `行号` 指的是客户原文文件的行,能直接翻回去。', '',
            '| 条款 | 要求 | 客户原文 | 行号 | 判定 |', '|---|---|---|---|---|']
    _meta = {r['clause']: r for r in d['requirements']}
    for c, v in d['verdicts'].items():
        m = _meta.get(c) or {}
        out.append(f"| {c} | {m.get('name') or '—'} | "
                   f"「{str(m.get('client_text') or '')[:36]}」 | "
                   f"{m.get('client_line') or '—'} | **{v}** |")
    out += ['', f"## 这次要问({len(d['asks'])} 项)", '']
    if d['asks']:
        out += ['| # | 方式 | 谁问 | 问什么 | 答完解锁 |', '|---|---|---|---|---|']
        out += [f"| {i} | {a.get('method') or '面谈'} | {a['who']} | {a.get('how')} | "
                f"{a.get('unlock') or '—'} |" for i, a in enumerate(d['asks'], 1)]
    else:
        out.append('无待核项(资料已齐)。')
    out += ['', '## 材料', '']
    out += [f"- {k}: {v or '未找到'}" for k, v in (d['sources'] or {}).items()]
    if d['priorities_hit']:
        out += ['', f"命中的业务优先条件:{'、'.join(d['priorities_hit'])}"]
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--id')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.list or not args.id:
        lst = interview_list(args.jd)
        if not lst:
            print('还没有面试名单')
            return 0
        for i, cid in enumerate(lst.get('selected') or [], 1):
            print(f"{i:>2}. {cid.replace('cand_', '')}")
        return 0

    cid = args.id if args.id.startswith('cand_') else f'cand_{args.id}'
    d = detail(args.jd, cid)
    print(json.dumps(d, ensure_ascii=False, indent=1) if args.json else render_md(d))
    return 0


if __name__ == '__main__':
    sys.exit(main())
