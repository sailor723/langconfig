#!/usr/bin/env python3
"""第 5 步：目标名单（基于**一面之后**的数据）—— 最终筛一次，找出目标候选人。

产物就是 `shortlist/<JD>.目标名单.yaml|md`。`docs/talent/PROCESS.md` 第 5 步写的产物名就是它，
所以这里**不再另起 `短名单` 这个文件名** —— 曾经并存过两份名单,结果第 6 步读的是旧的、
第 5 步筛的是新的,两把尺子排出两个顺序。

## 和 3b「目标名单」的区别

| | 3b 目标人数(`target_shortlist`,已退役) | 5 目标名单(本脚本) |
|---|---|---|
| 什么时候跑 | 第 3 步之后、还没面 | **第 4 步之后**，有 `cv_interview/` |
| 池子 | 初筛 kept 全体 | **面试名单 ∩ 有定稿** |
| 证据 | 只有简历 | 简历 **∪** 一面（坐实的能力项、补齐的属性） |
| 用途 | 决定面谁 | **第 6 步从这 8 人里选 4** |

3b 是"人手不够、只能面 N 个"时的应急分层；现在 30/10 个人面完了，
第 5 步要回答的是另一个问题：**面完之后，谁还站在名单上。**

## 排序：沿用第 3 步批准的九层阶梯（见 `work/talent/OVERVIEW.md`「排序口径」一节），只换证据来源

    ① 硬证据项数（可验证载体：系统/报告/客户审核/图表）
    ② 软证据项数（只能靠陈述）
    ③ 用户选的业务优先条件命中数
    ④ 客户原文「……优先」条款被判定满足的条数
    ⑤ 总年限（读不出来排最后 —— 排序口径，不是判他不合格）
    ⑥ 稳定性：平均在职年限（从工作段算，不是自述）
    ⑦ 待核项数（成本，不是优劣）
    ⑧ 品质岗经历（仅当本 JD 要求）
    ⑨ sha256(candidate id) —— 确定性兜底

**证据来源变了，规则没变。** ①②两层现在算的是「简历证据 ∪ 一面坐实的证据」，
并且每个证据项都记着来自哪边（`resume` / `interview` / `interview(模拟)`）。

## 切线

从 `jd_inputs.shortlist_target` 读 min/max（HR 定的）：

1. 先取到 **min** 人 —— 不够就如实报 shortfall，不硬凑；
2. 再往 **max** 扩，扩的条件是"下一个人至少有一项硬证据"，否则停在 min；
3. 写 `cut.tie_band`：切线处并列几人。并列 >1 时名次**不可读**，按哈希定，必须说明。

## 不满足怎么办

**排序**不用「不满足」当层（九层阶梯里没有它，加进去等于偷偷改规则）——
但**切线**要用：名单上不该出现违背客户硬门槛（A/B 类）的人，这与第 3 步
「排除必须有硬证据」是同一口径。所以：

1. 先在**没有客户门槛不满足**的人里按九层阶梯排、按 min→max 切；
2. 只有在干净的人不够 min 时，才从"带门槛不满足"的人里补，
   每补一个都写进 `relaxations`，标明**需要客户/HR 点头**；
3. 能力类（C/D/E）的不满足**不影响进名单** —— 那是需要业务面谈判的，不是门槛。

## 用法

    python -m scripts.talent.shortlist_after_interview --jd 品质经理
    python -m scripts.talent.shortlist_after_interview --jd 品质经理 --target 5   # 硬指定人数
    python -m scripts.talent.shortlist_after_interview --jd 品质经理 --dry        # 只看不写
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent import names as _names  # noqa: E402
from scripts.talent.pick_final import apply_combo_c, judge_all, load_inputs  # noqa: E402

SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
INPUTS = ROOT / 'work' / 'talent' / 'jd_inputs'
QUALITY = ROOT / 'work' / 'talent' / 'cv_quality.json'
OPENQ = ROOT / 'work' / 'talent' / 'open_questions'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
HR_FACTS = ROOT / 'work' / 'talent' / 'hr_facts.json'
INTERVIEW = ROOT / 'work' / 'talent' / 'cv_interview'

#: 最终名单的硬条件(第 5b 步)。短名单只问"谁排前面",最终名单要问"谁没有硬伤"。
FINAL_RULE = ('硬门槛(A/B 类客户阈值 + HR 侧 5 条)0 条不满足',
              '至少 1 项硬证据(简历或一面坐实)',
              '未知 ≤3 条(再多就说明关键项还没读到)')
FINAL_UNKNOWN_MAX = 3
FINAL_MIN_HARD = 1

#: 判「不满足」时**能当门槛用的**要求。只放阈值明确、口径无争议的客户条款。
#: REQ-B-MAJOR(专业)故意不在里面:客户写的是「…机械工程等」——开区间,
#: 且口径未定(DEF-04:子串 vs 断词),拿它剔人等于用一个待拍的规则剔 19/30。
BLOCKING = ('REQ-A-AGE-RANGE', 'REQ-B-EDU-LEVEL',
            # HR 侧 5 条也是硬约束(到岗/在职时长/稳定性/预算/通勤):达不到就是达不到
            'REQ-HR-NOTICE', 'REQ-HR-TENURE', 'REQ-HR-STABILITY',
            'REQ-HR-SALARY', 'REQ-HR-COMMUTE')

RANK_RULE = [
    '① 硬证据项数(可验证载体:系统/报告/客户审核/图表),多者优先',
    '② 软证据项数(只能靠陈述的),多者优先',
    '③ 用户选的业务优先条件命中数',
    '④ 客户原文写的「优先」条款被判定满足的条数',
    '⑤ 总年限(客户要求 X 年以上;读不出来排最后 —— 排序口径,不是不合格)',
    '⑥ 稳定性:平均在职年限(从工作段算出,不是自述)',
    '⑦ 待核项数(成本,不是优劣)',
    '⑧ 品质岗经历(仅当本 JD 要求)',
    '⑨ sha256(候选人 id):确定性兜底,不按文件名/姓氏排',
]


def _components_of(lib: dict, link: dict) -> tuple[dict, dict]:
    """每条要求要哪些组件 / 属性；以及组件的证据档次。"""
    req_need = {c['requirement']: list(lib[c['requirement']].get('_resolved') or [])
                for c in link['citations']}
    cat = yaml.safe_load((ROOT / 'work' / 'talent' / 'component_catalog.yaml')
                         .read_text(encoding='utf-8'))
    role = {c['id']: c.get('evidence_role', 'soft') for c in cat.get('components') or []}
    return req_need, role


def _resume_components(cid: str, cv: dict) -> set:
    skills = ((cv.get(cid) or {}).get('skills') or {}).get('value') or []
    return {f"skill_{s.get('name')}" for s in skills if s.get('name')}


def _interview_doc(cid: str) -> dict:
    p = INTERVIEW / f"{cid.replace('cand_', '')}.yaml"
    return (yaml.safe_load(p.read_text(encoding='utf-8')) if p.is_file() else {}) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--target', type=int, default=0,
                    help='硬指定人数(默认按 jd_inputs.shortlist_target 的 min→max 规则)')
    ap.add_argument('--decided-by', default='admin')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    ji_path = INPUTS / f'{args.jd}.yaml'
    ji = (yaml.safe_load(ji_path.read_text(encoding='utf-8')) if ji_path.is_file() else {}) or {}
    tgt = ji.get('shortlist') or ji.get('shortlist_target') or {'min': 5, 'max': 10}
    lo, hi = int(tgt.get('min') or 5), int(tgt.get('max') or 10)
    final_max = int(ji.get('final_max') or 5)

    mode, src = interview_policy.mode_for(args.jd)
    allow_sim = mode == interview_policy.MOCK_ALLOWED
    print(f'采信规则 {mode}({src})')

    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_interview(cands, allow_simulated=allow_sim)
    by_id = {c['id']: c for c in cands}
    cv = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    hr = json.loads(HR_FACTS.read_text(encoding='utf-8')) if HR_FACTS.is_file() else {}
    quality = json.loads(QUALITY.read_text(encoding='utf-8')) if QUALITY.is_file() else {}

    lst = yaml.safe_load((SHORTLIST / f'{args.jd}.面试名单.yaml').read_text(encoding='utf-8')) or {}
    pool = [c for c in (lst.get('selected') or []) if c in by_id]
    with_iv = [c for c in pool if _interview_doc(c).get('answers')]
    if not with_iv:
        print('面试名单里没有一份一面记录 —— 第 5 步要用一面数据,先跑第 4 步')
        return 2
    print(f'面试名单 {len(pool)} 人 · 有一面记录 {len(with_iv)} 人')

    oq = yaml.safe_load((OPENQ / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
    ask_n = collections.Counter(it['candidate'] for it in (oq.get('queue') or []))

    req_need, role = _components_of(lib, link)
    # 只算**本 JD 引用到的**能力项。之前把候选人所有能力项都算进去,于是
    # 「业务跟单」的名单里排满了有品质硬证据的专案工程师 —— 拿别的岗的证据排这个岗。
    jd_comps = {x for v in req_need.values() for x in v}
    # 客户自己写的「……优先」条款：客户授权的排序依据，不是我方偏好
    prefer_ids = [c['id'] for c in link.get('citations') or []
                  if '优先' in str(c.get('verbatim') or '')]
    rid2req = {c['id']: c['requirement'] for c in link['citations']}
    judgeable = [c['requirement'] for c in link['citations']
                 if lib[c['requirement']].get('assessable')
                 or lib[c['requirement']].get('_resolved')]
    needs_quality = any(
        (lib.get(c['requirement']) or {}).get('attribute') in ('C.2', 'C.3', 'C.4', 'C.5', 'C.6')
        or any(str(x).startswith('skill_品质岗经历')
               for x in ((lib.get(c['requirement']) or {}).get('components') or []))
        for c in link.get('citations') or [])

    prio_items = ((ji.get('interview_priorities') or {}).get('criteria') or [])
    from scripts.talent import priority_rules as PR
    pr_ctx = PR.make_ctx(args.jd)

    rows = []
    for cid in with_iv:
        cand = by_id[cid]
        iv = _interview_doc(cid)
        # 证据：简历 ∪ 一面坐实。每一项都记住来源，档案上要能指回去。
        res_comps = _resume_components(cid, cv)
        iv_comps, iv_sim_comps = set(), set()
        iv_real_n = iv_sim_n = 0
        for a in (iv.get('answers') or []):
            real = interview_policy.is_real_basis(a)
            if real:
                iv_real_n += 1
            else:
                iv_sim_n += 1
            for comp in (a.get('establishes') or []):
                iv_comps.add(comp)
                if not real:
                    iv_sim_comps.add(comp)
        all_comps = (res_comps | iv_comps) & jd_comps
        hard, soft = [], []
        for comp in all_comps:
            (hard if role.get(comp) == 'hard' else soft).append(comp)

        verdicts = judge_all(cand, link, lib, atts)
        conflicts = []
        if allow_sim or True:
            verdicts, conflicts = apply_combo_c(cid, args.jd, verdicts, link)
        st = collections.Counter(v['state'] for v in verdicts.values())
        # 客户硬门槛上被判「不满足」的条款 —— 进名单就是放宽，必须记账
        gate_fails = [rid for rid, cell in verdicts.items()
                      if cell['state'] == '不满足' and rid in BLOCKING]
        # 客户条款上判了不满足、但口径未定/开区间的 —— 不拦人,但要写进出名单理由
        soft_fails = [rid for rid, cell in verdicts.items()
                      if cell['state'] == '不满足' and rid not in BLOCKING
                      and rid in {c['requirement'] for c in link['citations']
                                  if str(c.get('origin')) == 'client'
                                  or str(c.get('verbatim')) not in ('None', '')}]
        prio_hits, prio_names = 0, []
        for it in prio_items:
            rule = it.get('rule') or {'kind': 'component_any',
                                      'components': it.get('components') or []}
            if PR.met(rule, cand, pr_ctx):
                prio_hits += 1
                prio_names.append(it.get('name') or '?')
        prefer_hits = sum(1 for rid in prefer_ids
                          if (verdicts.get(rid2req.get(rid)) or {}).get('state') == '满足')
        tenure = ((hr.get(cid) or {}).get('avg_tenure_years') or {}).get('value') or 0
        q = quality.get(cid) or {}
        rows.append({
            'candidate': cid,
            'hard_items': sorted(hard), 'soft_items': sorted(soft),
            'hard_hits': len(hard), 'soft_hits': len(soft),
            'from_interview': sorted(iv_comps),
            'from_interview_simulated': sorted(iv_sim_comps),
            'resume_items': sorted(res_comps),
            'iv_real': iv_real_n, 'iv_sim': iv_sim_n,
            '满足': st['满足'], '不满足': st['不满足'],
            '未知': st['未知'], '不可判': st['不可判'], '冲突': conflicts,
            'gate_fails': gate_fails, 'soft_fails': soft_fails,
            'prio_hits': prio_hits, 'prio_names': prio_names,
            'prefer_hits': prefer_hits,
            'years': cand.get('yearsPlatform'),
            'tenure': round(float(tenure), 1),
            'n_ask': ask_n.get(cid, 0),
            'quality': (q.get('verdict') if needs_quality else '—') or '—',
            'quality_months': q.get('months') if needs_quality else None,
            'age': cand.get('age'), 'edu': cand.get('educationRank'),
            'verdicts': {rid: cell['state'] for rid, cell in verdicts.items()},
        })

    TIER = {'有': 0, '待核': 1, '读不出': 2, '无': 3, '—': 9}

    def key(r):
        y = r['years'] if isinstance(r['years'], (int, float)) else -1
        return (-r['hard_hits'], -r['soft_hits'], -r['prio_hits'], -r['prefer_hits'],
                -y, -r['tenure'], r['n_ask'], TIER.get(r['quality'], 9))

    rows.sort(key=lambda r: (key(r), hashlib.sha256(r['candidate'].encode()).hexdigest()))

    # 名单上不放"违背客户硬门槛"的人 —— 和第 3 步排除同口径。
    # 只有在干净的人不够 min 时才补，且逐条记账。
    clean = [r for r in rows if not r['gate_fails']]
    dirty = [r for r in rows if r['gate_fails']]
    print(f'  池内: 干净 {len(clean)} 人 · 带客户门槛不满足 {len(dirty)} 人')

    want = args.target or lo
    picked = clean[:want]
    if not args.target and len(picked) < hi:
        while len(picked) < hi and len(picked) < len(clean):
            nxt = clean[len(picked)]
            if nxt['hard_hits'] <= 0:
                print(f'  扩到 {len(picked)} 人停住:下一位 {nxt["candidate"][5:25]} 没有硬证据')
                break
            picked.append(nxt)
    relaxed = []
    if len(picked) < (args.target or lo):
        need = (args.target or lo) - len(picked)
        for r in dirty[:need]:
            picked.append(r)
            relaxed.append(r['candidate'])
        if relaxed:
            print(f'  ⚠ 干净的人不够 {args.target or lo} 人,补了 {len(relaxed)} 个带门槛不满足的')
    tail_key = key(picked[-1]) if picked else None
    tie_band = sum(1 for r in rows if key(r) == tail_key) if tail_key else 0

    # ── 第 5b 步:最终名单 ──
    # 短名单问"谁排前面",最终名单问"谁没有硬伤"。两道闸不是同一件事:
    # 短名单可以有 10 个人,送去用人部门面的最多 5 个,而且必须**明显少**。
    def _final_ok(r) -> bool:
        return (not r['gate_fails']
                and r['hard_hits'] >= FINAL_MIN_HARD
                and r['未知'] <= FINAL_UNKNOWN_MAX)

    final = [r for r in picked if _final_ok(r)][:final_max]
    final_cut_by_cap = len([r for r in picked if _final_ok(r)]) > final_max
    final_ids = {r['candidate'] for r in final}
    # 被最终闸挡掉的人:短名单里在,但没进最终名单 —— 每个人都要能说清为什么
    dropped = [{'candidate': r['candidate'],
                'why': (f"硬门槛不满足:{'、'.join(r['gate_fails'])}" if r['gate_fails'] else
                        (f"硬证据 {r['hard_hits']} 项(要求 ≥{FINAL_MIN_HARD})" if r['hard_hits'] < FINAL_MIN_HARD
                         else f"未知 {r['未知']} 条(要求 ≤{FINAL_UNKNOWN_MAX})"))}
               for r in picked if not _final_ok(r)]
    if final_cut_by_cap:
        # 合格的人比 5 个多 —— 按短名单顺序取前 5,后面的记在 dropped 里(原因写"名额")
        for r in picked:
            if _final_ok(r) and r['candidate'] not in final_ids:
                dropped.append({'candidate': r['candidate'],
                                'why': f'合格但超出 {final_max} 个名额(按短名单顺序)'})

    shortfall = max(0, lo - len(picked))
    flags = [{'candidate': r['candidate'],
              'why': f"客户硬门槛上判定不满足:{'、'.join(r['gate_fails'])}",
              'needs': '客户/HR 点头'}
             for r in picked if r['gate_fails']]
    relaxations = [{'candidate': c, 'rule': 'R0 把带客户门槛不满足的人补进名单',
                    'needs': '客户/HR 点头'} for c in relaxed]
    sim_only = [r['candidate'] for r in picked if r['iv_real'] == 0 and r['iv_sim'] > 0]

    cut = {'target_min': lo, 'target_max': hi, 'position': len(picked),
           'tie_band': tie_band, 'hash_decided': tie_band > 1,
           'note': ('切线唯一 —— 名次可读' if tie_band == 1 else
                    f'切线落在 {tie_band} 人并列区,谁上都行(按哈希排)')}

    doc = {
        'jd': args.jd,
        'step': '5 目标名单(基于一面数据)',
        'pool': {'interview_list': len(pool), 'with_interview': len(with_iv)},
        'target': {'min': lo, 'max': hi, 'asked_by': tgt.get('asked_by')},
        'interview_policy': {'mode': mode, 'source': src},
        'judgeable_requirements': len(judgeable),
        'total_requirements': len(link['citations']),
        'rank_rule': RANK_RULE,
        'evidence_note': ('证据分层按「简历 ∪ 一面坐实」算;from_interview 里标了 '
                          'from_interview_simulated 的那些是**模拟一面**给的,演练用'),
        'cut': cut,
        'shortfall': shortfall,
        'final': {
            'rule': list(FINAL_RULE),
            'max': final_max,
            'unknown_max': FINAL_UNKNOWN_MAX,   # 门禁照这个核,别在门禁里写死数字
            'min_hard': FINAL_MIN_HARD,
            'ids': [r['candidate'] for r in final],
            'count': len(final),
            'dropped': dropped,
            'note': ('最终名单 ⊂ 短名单,且人数明显更少:短名单是"够格排队",'
                     '最终名单是"送去用人部门面,不许有硬伤"'),
        },
        'flags': flags,
        'relaxations': relaxations,
        'simulated_interview_only': sim_only,
        'selected': [r['candidate'] for r in picked],
        # 整池的排序结果都存下来 —— 名单只存选中的人,"第 13 个人为什么没进"
        # 在产物里就查不到了,业务问起来只能重跑一遍。
        'rows': rows,
        'in_list': {r['candidate']: (r['candidate'] in {x['candidate'] for x in picked})
                    for r in rows},
    }
    dest = SHORTLIST / f'{args.jd}.目标名单.yaml'
    if not args.dry and dest.is_file():
        old_doc = yaml.safe_load(dest.read_text(encoding='utf-8')) or {}
        if not str(old_doc.get('step') or '').startswith('5'):
            # 老的是 3b 的「只凭简历凑人数」产物 —— 归档,不覆盖掉
            arch = ROOT / 'work' / 'talent' / '_retired' / '3b-目标名单-2026-11-23'
            arch.mkdir(parents=True, exist_ok=True)
            (arch / dest.name).write_text(dest.read_text(encoding='utf-8'), encoding='utf-8')
            print(f'  旧产物(3b)已归档 → {arch.relative_to(ROOT)}/{dest.name}')
    if not args.dry:
        dest.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100), encoding='utf-8')
        if isinstance(ji, dict):
            ji['shortlist_5'] = {'n': len(picked), 'decided_by': args.decided_by,
                                 'rule': 'min→max,扩的前提是下一位有硬证据'}
            ji_path.write_text(yaml.safe_dump(ji, allow_unicode=True, sort_keys=False,
                                              width=100), encoding='utf-8')

    # ── 人读版 ──
    md = [f'# 目标名单(第 5 步,基于一面)· {args.jd}', '']
    if allow_sim:
        md += ['> ⚠ **演练**:这份 JD 的一面记录全部是 `basis: simulated`(代拟)。'
               '排序可用来看流程是否成立,**不能当录用依据**。', '']
    md += [f'面试名单 **{len(pool)}** 人 → 有一面记录 **{len(with_iv)}** 人 → '
           f'目标名单 **{len(picked)}** 人(HR 给的是 {lo}~{hi})。', '',
           f'可判要求 **{len(judgeable)} / {len(link["citations"])}** 条;'
           f'其余没有可判的数据项,对所有人一样(不判)。', '']
    if shortfall:
        md += [f'> ⚠ 人数不足:目标至少 {lo} 人,实际 {len(picked)} 人 — 差 {shortfall}。'
               '不硬凑,缺的写在这里。', '']
    md += ['| # | 候选人 | 硬证据 | 软证据 | 满足/不满足/未知 | 业务优先 | 年限 | 一面 | CV |',
           '|---|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(picked, 1):
        ivtag = (f"真 {r['iv_real']} 条" if r['iv_real'] else
                 (f"模拟 {r['iv_sim']} 条" if r['iv_sim'] else '—'))
        nm = _names.name_of(r['candidate'])
        md.append(f"| {i} | {nm} | {r['hard_hits']} | {r['soft_hits']} | "
                  f"{r['满足']}/{r['不满足']}/{r['未知']} | "
                  f"{('、'.join(r['prio_names'])) or '—'} | {r['years'] if r['years'] is not None else '—'} | {ivtag} | "
                  f"[看 CV](#tal:cv/{r['candidate']}) |")
    md += ['', f"> 切线:第 {len(picked)} 名 · {cut['note']}", '']
    # ── 最终名单 ──
    md += [f'## 最终名单({len(final)} 人,上限 {final_max})—— 送去用人部门面的就是这些人', '',
           '短名单问的是「谁排前面」,最终名单问的是「谁没有硬伤」:', '']
    for r_ in FINAL_RULE:
        md.append(f'- {r_}')
    md += ['']
    if final:
        md += ['| # | 候选人 | 硬证据 | 未知 | 满足 | 说明 | CV |', '|---|---|---|---|---|---|---|']
        for i, r in enumerate(final, 1):
            md.append(f"| {i} | {_names.name_of(r['candidate'])} | {r['hard_hits']} | "
                      f"{r['未知']} | {r['满足']} | 短名单第 {picked.index(r) + 1} 位 | "
                      f"[看 CV](#tal:cv/{r['candidate']}) |")
    else:
        md += ['> **最终名单为空。** 短名单里没有一个人同时满足三条硬条件 —— '
               '这不是"没人可用",是"关键项还没读到"。按流程应该带着这张表回去补一面,而不是降标准凑人。', '']
    if dropped:
        # 前面是表格,标题前必须空一行,否则 markdown 会把标题并进表格里
        md += ['', '### 短名单里没进最终名单的人', '',
               '| 候选人 | 为什么 |', '|---|---|']
        for d_ in dropped:
            md.append(f"| {_names.name_of(d_['candidate'])} | {d_['why']} |")
        md += ['']
    # 排序陷阱:九层阶梯是「证据档在前」,于是证据多但判得不满足的人会排在
    # 证据少但判得干净的人前面。这不是 bug,是当初批准的规则 —— 但读者必须看得见。
    traps = []
    for i in range(len(picked)):
        for j in range(i + 1, len(picked)):
            a, b = picked[i], picked[j]
            if a['不满足'] > b['不满足'] and a['满足'] < b['满足']:
                traps.append((a, b))
    if traps:
        md += [f'## 排序陷阱({len(traps)} 处)—— 规则说清楚,别让人现场问住', '',
               '九层阶梯**先看证据多少,再看判得怎么样**。所以会出现下面这种倒挂:'
               '证据多的人判得不满足,却排在证据少但判得干净的人前面。', '',
               '| 排在前面 | 判定 | 排在后面 | 判定 |', '|---|---|---|---|']
        for a, b in traps[:6]:
            md.append(f"| {_names.name_of(a['candidate'])} | 满足 {a['满足']} / 不满足 {a['不满足']} | "
                      f"{_names.name_of(b['candidate'])} | 满足 {b['满足']} / 不满足 {b['不满足']} |")
        md += ['', '要把"判得干净"放到证据前面,就是在改已批准的排序规则 —— 那是业务/HR 的决定,不是脚本的。', '']
    if flags:
        md += ['## 需要点头的放宽', '', '| 候选人 | 问题 | 谁点头 |', '|---|---|---|']
        for f in flags:
            md.append(f"| {_names.name_of(f['candidate'])} | {f['why']} | {f['needs']} |")
        md.append('')
    if not flags:
        md += ['> 名单里**没有**违背客户硬门槛的人 —— 与第 3 步「排除必须有硬证据」同一口径。', '']

    # 每人一段可展开的证据明细 —— **已去掉**。
    # 每行都有「看 CV」,点开就是定稿全文;同一批信息在 md 里再抄一遍,
    # 一份名单会长到 190 行,而读者要的是那张表。
    out_of = [r for r in rows if r['candidate'] not in {x['candidate'] for x in picked}]
    if out_of:
        md += [f'## 没进名单的 {len(out_of)} 人(同一把尺子,排在后面)', '',
               '| 名次 | 候选人 | 硬/软 | 满足/不满足/未知 | 差在哪 |', '|---|---|---|---|---|']
        for i, r in enumerate(out_of, len(picked) + 1):
            gap = []
            if r['hard_hits'] < picked[-1]['hard_hits']:
                gap.append('硬证据少')
            if r['不满足'] > 0:
                gap.append(f"有 {r['不满足']} 条不满足")
            if r['n_ask'] > picked[-1]['n_ask']:
                gap.append(f"待核 {r['n_ask']} 项")
            md.append(f"| {i} | {_names.name_of(r['candidate'])} | "
                      f"{r['hard_hits']}/{r['soft_hits']} | "
                      f"{r['满足']}/{r['不满足']}/{r['未知']} | "
                      f"{('、'.join(gap)) or '切线前的都进了,是被切线挡住的'} |")
        md += ['', '> 名单只到切线为止 —— 切线与并列情况见上面的 `cut`。', '']
    md += [f'> 人数口径:`jd_inputs` 里 `shortlist` = {lo}~{hi}、`final_max` = {final_max}'
           ' —— 短名单是"够格排队",最终名单是"送去用人部门面"。', '',
           '> 这份名单**只从面过的人里挑**。没进名单的人不是不合格,是这一轮没排到 —— '
           '每个人仍在 `verdicts/` 里有逐条判定说明。', '']
    if not args.dry:
        (SHORTLIST / f'{args.jd}.目标名单.md').write_text('\n'.join(md), encoding='utf-8')

    print(f'  切线:第 {len(picked)} 名 · tie_band={tie_band} · {cut["note"]}')
    print(f'  最终名单 {len(final)} 人(上限 {final_max}):'
          + ('  ——— 空' if not final else ''))
    for i, r in enumerate(final, 1):
        print(f"    {i}. {r['candidate'][5:45]}  (硬{r['hard_hits']} 未知{r['未知']} 满足{r['满足']})")
    if traps:
        print(f'  ⚠ 排序陷阱 {len(traps)} 处:证据多但判得不满足的人排在判得干净的人前面')
    print(f'  目标名单 {len(picked)} 人:' + ('  (--dry,未写盘)' if args.dry else ''))
    for i, r in enumerate(picked, 1):
        print(f"    {i}. 硬{r['hard_hits']} 软{r['soft_hits']} 满足{r['满足']} 不满足{r['不满足']} "
              f"未知{r['未知']} {r['candidate'][5:45]}")
    if flags:
        print(f'  ⚠ {len(flags)} 人带着客户门槛不满足进名单 —— 需要点头')
    if not args.dry:
        print(f'写出 {(SHORTLIST / (args.jd + ".目标名单.yaml")).relative_to(ROOT)} 与 .md')
    return 0


if __name__ == '__main__':
    sys.exit(main())
