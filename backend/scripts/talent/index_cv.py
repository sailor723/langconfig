#!/usr/bin/env python3
"""把一份 JD 的 CV 定稿汇成一张**短表**，一列一个「看 CV」链接。

## 为什么需要它

侧栏原来把 39 份定稿当成 39 个文件平铺（`CV 定稿 · 名单第 N 位`），
一屏塞不下，而且顺序是反的 —— CV 是第 4 步的产物，却排在第 5 步名单后面。
现在侧栏只留**一条**汇总，点开就是这张表；表里每行只看"要不要点开"的信息，
点「看 CV」在弹层里读全文。

## 短表放什么

必放（决定要不要点开）：名次 · 姓名 · 年龄 · 学历 · 年限 · 现岗位 ·
硬/软证据 · 满足/不满足/未知 · 一面状态。
不放（留给弹层里的全文）：31 个字段表、工作经历逐段、一面逐条问答。

链接用自定义 scheme `#tal:cv/<candidate id>`，由前端 `MarkdownBody` 的自定义 `a`
拦截并打开弹层 —— md 里不写 HTML（正文不开 `rehype-raw`）。

用法：
    python -m scripts.talent.index_cv --jd 品质经理
    python -m scripts.talent.index_cv --all
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

from scripts.talent import names as _names

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

CV_DOCS = ROOT / 'work' / 'talent' / 'cv_docs'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
HR_FACTS = ROOT / 'work' / 'talent' / 'hr_facts.json'

EDU = {1: '初中', 2: '中专/高中', 3: '大专', 4: '本科', 5: '硕士', 6: '博士'}


def link(cid: str) -> str:
    return f'[看 CV](#tal:cv/{cid})'


def brief(jd: str) -> list[dict]:
    """一行一个人的短表数据。判定/证据来自第 5 步的目标名单（它已经算过，不重算）。"""
    tgt_path = SHORTLIST / f'{jd}.目标名单.yaml'
    if not tgt_path.is_file():
        return []
    tgt = yaml.safe_load(tgt_path.read_text(encoding='utf-8')) or {}
    rows = {r['candidate']: r for r in (tgt.get('rows') or [])}
    final_ids = list((tgt.get('final') or {}).get('ids') or [])
    order = list(tgt.get('selected') or []) + [c for c in rows if c not in set(tgt.get('selected') or [])]

    facts = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    # HR 评语来自第 3 步那通一面（cv_interview/<人>.yaml 的 review 段）
    iv_dir = ROOT / 'work' / 'talent' / 'cv_interview'

    def hr_comment(cid: str) -> str:
        q = iv_dir / f"{str(cid).replace('cand_', '')}.yaml"
        if not q.is_file():
            return ''
        try:
            d = yaml.safe_load(q.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError:
            return ''
        rev = d.get('review') or {}
        txt = str(rev.get('text') or '').replace('（HR 模拟评语，不是真访谈）', '').strip()
        if not txt:
            return ''
        return ('模拟·' if rev.get('basis') == 'simulated' else '') + txt
    out = []
    for rank, cid in enumerate(order, 1):
        doc = CV_DOCS / f"{str(cid).replace('cand_', '')}.定稿.md"
        if not doc.is_file():
            continue
        r = rows.get(cid) or {}
        f = facts.get(cid) or {}

        def val(key):
            item = f.get(key) or {}
            return item.get('value')

        tags = []
        if cid in final_ids:
            tags.append('最终')
        elif cid in set(tgt.get('selected') or []):
            tags.append('短名单')
        else:
            tags.append('面试名单')
        out.append({
            'rank': rank, 'cid': cid, 'tags': '、'.join(tags),
            'name': _names.name_of(cid),
            'age': val('age') or r.get('age'), 'edu': EDU.get(val('education_rank') or r.get('edu'), '—'),
            'years': r.get('years'), 'ask': r.get('n_ask'),
            'hard': r.get('hard_hits'), 'soft': r.get('soft_hits'),
            'ok': r.get('满足'), 'fail': r.get('不满足'), 'unknown': r.get('未知'),
            'iv': (f"模拟 {r.get('iv_sim')} 条" if r.get('iv_real') in (0, None) and r.get('iv_sim')
                   else (f"真 {r.get('iv_real')} 条" if r.get('iv_real') else '—')),
            'doc': doc,
            'hr': hr_comment(cid),
        })
    return out


def render(jd: str, rows: list[dict]) -> str:
    L = [f'# CV 定稿清单 · {jd}', '',
         f'共 **{len(rows)}** 份定稿（第 3 步产物：HR 一面补齐 + 评语，31 个字段逐份核对过）。',
         '表格只放"要不要点开"的信息；点 **看 CV** 在右侧弹层里读全文。', '',
         '| 名次 | 归属 | 候选人 | 年龄 | 学历 | 年限 | 待核 | 硬/软 | 满足/不满足/未知 | HR 评语（第 3 步一面后） | CV |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        L.append(f"| {r['rank']} | {r['tags']} | {r['name'][:30]} | {r['age'] or '—'} | {r['edu']} | "
                 f"{r['years'] if r['years'] is not None else '—'} | {r['ask'] or '—'} | "
                 f"{r['hard']}/{r['soft']} | {r['ok']}/{r['fail']}/{r['unknown']} | "
                 f"{(r.get('hr') or '—')[:60]} | {link(r['cid'])} |")
    L += ['', '> 定稿里的每一格要么有原文引文，要么标 `代拟(模拟)`。演练数据不能对外。', '']
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    jds = ([p.stem for p in sorted(SHORTLIST.glob('*.目标名单.yaml'))] if args.all
           else ([args.jd] if args.jd else []))
    jds = [j.replace('.目标名单', '') for j in jds]
    if not jds:
        ap.error('给 --jd <JD> 或 --all')
    CV_DOCS.mkdir(parents=True, exist_ok=True)
    for jd in jds:
        rows = brief(jd)
        if not rows:
            print(f'{jd}: 没有可汇总的定稿')
            continue
        dest = CV_DOCS / f'{jd}.CV清单.md'
        dest.write_text(render(jd, rows), encoding='utf-8')
        print(f'{jd}: {len(rows)} 份 → {dest.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
