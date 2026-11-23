#!/usr/bin/env python3
"""把 `jd_links/draft/<JD>.yaml`（LLM 草稿）**逐条复核后转正**成 `jd_links/<JD>.yaml`，
并顺手把第 2 步需要的另外两份文件建出来（决策账本、回填参数）。

## 为什么要有这一步（而不是把草稿直接 cp 过去）

草稿是 LLM 写的，它给的行号与引文**必须现场重算**。这个脚本只做一件事：
**每条 verbatim 必须在原文里逐字出现、txt_line 必须真的指向那一行**，
对不上就整体拒绝（退出码 1），不写任何文件 —— 半份引用比没有更危险。

它**不做**业务判断：粒度拆不拆、阈值该不该加严、软素质怎么处置，
一律写进 `jd_reviews/<JD>.yaml` 且 `signoff: pending`，等业务签字。

## 产出

    work/talent/jd_links/<JD>.yaml     引用文件（verbatim/行号已复核）
    work/talent/jd_reviews/<JD>.yaml   决策账本（只登记待定事项）
    work/talent/jd_inputs/<JD>.yaml    面试人数 / 短名单 / 最终名单 / 业务优先条件

## 用法

    python -m scripts.talent.promote_jd --jd 副总助理 --jd 关务报关员 \
        --interview 20 --shortlist 5,10 --final-max 5
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

TALENT = ROOT / 'work' / 'talent'
LINKS = TALENT / 'jd_links'
DRAFT = LINKS / 'draft'
REVIEWS = TALENT / 'jd_reviews'
INPUTS = TALENT / 'jd_inputs'
LIBRARY = TALENT / 'requirement_library.yaml'

#: 客户原文里常见的段标题 —— 用来给 sections 分类，找不到就留空，不猜。
SECTION_HINTS = ('资格要求', '职务简述', '工作内容', '岗位职责', '事务表述', '修改履历', '任职要求')


def load_lib() -> dict:
    doc = yaml.safe_load(LIBRARY.read_text(encoding='utf-8')) or {}
    return {r['id']: r for r in doc.get('requirements') or []}


def verify(jd: str, draft: dict, src_lines: list[str], src: str, lib: dict) -> list[str]:
    """返回问题清单。空 = 全对。"""
    problems = []
    seen = {}
    for c in draft.get('citations') or []:
        cid, v = c.get('id'), str(c.get('verbatim') or '')
        if not v:
            problems.append(f'{cid}: 没有 verbatim')
            continue
        if v not in src:
            problems.append(f'{cid}: verbatim 不在原文里 —— {v[:40]}')
            continue
        ln = c.get('txt_line')
        if not isinstance(ln, int) or not (1 <= ln <= len(src_lines)) or v not in src_lines[ln - 1]:
            problems.append(f'{cid}: txt_line {ln} 不指向含该引文的行')
        rid = c.get('requirement')
        if rid not in lib:
            problems.append(f'{cid}: requirement {rid} 不在要求库里')
        elif rid in seen:
            problems.append(f'{cid}: requirement {rid} 与 {seen[rid]} 重复 —— '
                            f'判定按 requirement 聚合,两条会让同一句算两遍')
        else:
            seen[rid] = cid
    return problems


def build_links(jd: str, draft: dict, src_lines: list[str]) -> dict:
    cits = []
    for c in draft.get('citations') or []:
        out = {'id': c['id'], 'requirement': c['requirement'], 'verbatim': c['verbatim'],
               'source_text': c.get('source_text') or src_lines[(c['txt_line'] or 1) - 1],
               'txt_line': c['txt_line'], 'tier': c.get('tier') or 'essential',
               'origin': c.get('origin') or 'client'}
        if c.get('value'):
            out['value'] = c['value']
        if c.get('year_basis'):
            out['year_basis'] = c['year_basis']
        out['note'] = (c.get('note') or '').strip() or (
            '由 `llm_draft_jd` 起草,本文件已复核 verbatim 与行号;粒度与阈值未做业务判断,'
            '见 jd_reviews 的同 JD 账本。')
        cits.append(out)

    # 段:按引用行落在哪个段标题之后粗略归类;找不到标题就写「资格要求」区间
    first = min(c['txt_line'] for c in cits) if cits else 1
    last = max(c['txt_line'] for c in cits) if cits else len(src_lines)
    lines_with_hint = [(i, ln.strip()) for i, ln in enumerate(src_lines, 1)
                       if any(h in ln for h in SECTION_HINTS)]

    return {
        'jd': jd,
        'department': draft.get('department') or '',
        'source_file': draft.get('source_file') or '',
        'source_text': f'work/talent/jd_links/_source/{jd}.txt',
        'extracted_with': ('先由 `llm_draft_jd` 起草,再由 `promote_jd` 逐条复核 verbatim 与行号;'
                           '原文一个字未改'),
        'role_type': 'staff',
        'role_basis': 'promote_jd 未做岗位性质判断 —— 归属需人工确认(见 jd_reviews 的 role_decision)',
        'role_confirmed': False,
        'sections': {
            1: f'抬头 / 文件信息（第 1–{max(1, first - 1)} 行）',
            2: f'资格要求（第 {first}–{last} 行,共 {len(cits)} 条引用）',
        },
        'section_hints_found': [f'第 {i} 行: {t[:30]}' for i, t in lines_with_hint[:8]],
        'count': {
            'source_section': f'第 {first}–{last} 行',
            'atomic_requirements': len(cits),
            'client_requirements': len(cits),
            'hr_requirements': 0,
            'count_note': ('由 LLM 起草、promote_jd 复核,粒度未做业务判断;'
                           'HR 侧要求本 JD 未登记(没有签字的签署不写进来)。'),
        },
        'citations': cits,
    }


def build_reviews(jd: str, lib: dict, cits: list[dict]) -> dict:
    soft = [c['id'] for c in cits
            if (lib.get(c['requirement']) or {}).get('data_class') == 'soft']
    unassessable = [c['id'] for c in cits
                    if not (lib.get(c['requirement']) or {}).get('assessable')]
    return {
        'jd': jd, 'ref': f'jd_links/{jd}.yaml',
        'role_decision': {
            'question': 'role_type 该记 manager 还是 staff',
            'current': 'staff',
            'why': 'promote_jd 未做判断:归属要看客户原文的「直接下属」等线索,不能让脚本猜。',
            'signoff': 'pending'},
        'decisions': [
            {'id': f'D-{jd}-01', 'kind': 'coverage', 'subject': (unassessable or [None])[0],
             'applies_to': unassessable, 'decision': 'deferred', 'signoff': 'pending',
             'why': (f'这 {len(unassessable)} 条在要求库里 assessable: false(或没有数据项),'
                     '对所有人都是「不可判」:不进判定分母,也不许拿来淘汰人。'),
             'cost': '要让它可判,得先给这些要求定数据项 —— 改的是要求库那一层,不在引用文件里。'},
            {'id': f'D-{jd}-02', 'kind': 'scope', 'subject': (soft or [None])[0],
             'applies_to': soft, 'decision': 'deferred', 'signoff': 'pending',
             'why': (f'这 {len(soft)} 条是软素质(数据类 soft),没有任何可判的数据项。'
                     '演练里它们只出现在名单上,不参与排名与淘汰。'),
             'cost': '把软素质做成可判=设计一套结构化面试量表,现在没有。'},
        ],
        'scope_notes': [
            {'id': f'D-{jd}-03', 'kind': 'scope', 'signoff': 'pending',
             'note': ('HR 侧要求(到岗/在职时长/稳定性/预算/通勤)本 JD **未登记**:'
                      '品质经理那 5 条是 2026-11-20 经 admin 签字的一批,不能照抄(同 业务跟单 先例)。'
                      '所以第 5b 步的硬门槛只剩客户条款。')},
        ],
    }


def build_inputs(jd: str, cits: list[dict], lib: dict, n_iv: int,
                 sl_min: int, sl_max: int, final_max: int) -> dict:
    prio = []
    for c in cits:
        comps = (lib.get(c['requirement']) or {}).get('components') or []
        if not comps:
            continue
        prio.append({
            'id': f"P-{c['id']}",
            'name': (lib.get(c['requirement']) or {}).get('name') or c['requirement'],
            'rule': {'kind': 'component_any', 'components': list(comps)},
            'why': f"客户原文「{str(c['verbatim'])[:24]}」({c['id']})",
            'caveat': '组件词表偏窄(DEF-01),可能漏人'})
    return {
        'jd': jd,
        'interview_target': {'n': n_iv, 'decided_by': 'admin', 'decided_at': '2026-11-23',
                             'why': '第 3 步要给出可执行的面试批次'},
        'interview_priorities': {'decided_by': 'admin', 'decided_at': '2026-11-23',
                                 'criteria': prio},
        'shortlist': {'min': sl_min, 'max': sl_max, 'asked_by': 'hr', 'set_by': 'admin',
                      'set_at': '2026-11-23', 'note': '第 5a 步:一面之后够格进下一轮评估的人'},
        'final_max': final_max,
        'final_note': ('第 5b 步:送去用人部门面的人。硬门槛 0 不满足 + 硬证据≥1 + 未知≤3,'
                       '不硬凑'),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', action='append', required=True)
    ap.add_argument('--interview', type=int, default=20)
    ap.add_argument('--shortlist', default='5,10', help='min,max')
    ap.add_argument('--final-max', type=int, default=5)
    ap.add_argument('--force', action='store_true', help='覆盖已存在的 jd_links')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    sl_min, sl_max = (int(x) for x in args.shortlist.split(','))
    lib = load_lib()

    failed = 0
    for jd in args.jd:
        draft_p = DRAFT / f'{jd}.yaml'
        src_p = LINKS / '_source' / f'{jd}.txt'
        if not draft_p.is_file() or not src_p.is_file():
            print(f'{jd}: 缺草稿或原文（{draft_p if not draft_p.is_file() else src_p}）')
            failed += 1
            continue
        draft = yaml.safe_load(draft_p.read_text(encoding='utf-8')) or {}
        src = src_p.read_text(encoding='utf-8')
        src_lines = src.splitlines()
        problems = verify(jd, draft, src_lines, src, lib)
        if problems:
            print(f'{jd}: ❌ 复核不通过（{len(problems)} 项）—— 不写任何文件')
            for p in problems[:6]:
                print('   ', p)
            failed += 1
            continue

        dest = LINKS / f'{jd}.yaml'
        if dest.is_file() and not args.force:
            print(f'{jd}: jd_links 已存在,跳过（--force 覆盖）')
            continue

        links = build_links(jd, draft, src_lines)
        reviews = build_reviews(jd, lib, links['citations'])
        inputs = build_inputs(jd, links['citations'], lib, args.interview,
                              sl_min, sl_max, args.final_max)
        assessable = [c['id'] for c in links['citations']
                      if (lib.get(c['requirement']) or {}).get('assessable')]
        print(f'{jd}: ✓ {len(links["citations"])} 条引用复核通过 · 可判 {len(assessable)} 条'
              f'（{", ".join(assessable) or "无"}）')
        if args.dry:
            continue
        dest.write_text(yaml.safe_dump(links, allow_unicode=True, sort_keys=False, width=100),
                        encoding='utf-8')
        REVIEWS.mkdir(parents=True, exist_ok=True)
        (REVIEWS / f'{jd}.yaml').write_text(
            '# 决策账本 —— 「谁、何时、为什么」这么定的独立记录。只能由人改。\n'
            '# 本文件由 promote_jd 建立:只登记待定事项,一律 signoff: pending。\n'
            + yaml.safe_dump(reviews, allow_unicode=True, sort_keys=False, width=100),
            encoding='utf-8')
        INPUTS.mkdir(parents=True, exist_ok=True)
        (INPUTS / f'{jd}.yaml').write_text(
            yaml.safe_dump(inputs, allow_unicode=True, sort_keys=False, width=100),
            encoding='utf-8')
        print(f'   写出 jd_links / jd_reviews / jd_inputs 三份')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
