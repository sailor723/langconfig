#!/usr/bin/env python3
"""第 3 步的真正产物:一份**能照着打电话**的面试名单(默认 10 人)。

初筛保留 150 人,那个数字不是名单,是"过了客户门槛的全部人"。HR 打不完,
所以第 3 步要再往前推一步:**从 150 里挑出值得花电话费的 10 个人**,并写清每人要问什么。

排序只用**真实证据**,绝不用模拟填充出来的字段:
    ① 品质岗经历有硬证据(A 档岗位名 / B 档职责+时长已知)
    ② 客户门槛过且有余量(年龄在区间内、学历达标、专业命中、年限够)
    ③ 简历里**真的**抽出过 JD 要的能力项(cv_facts.skills,不含 cv_mock)
    ④ 待核项少的优先(同样值得面,打一个电话能问完的先面)

产物:
    shortlist/<JD>.面试名单.yaml|md  —— 10 人 + 每人"为什么值得面" + "这次问什么"
    jd_inputs/<JD>.yaml 里记 interview_target(谁定的、哪天)

用法:
    python -m scripts.talent.pick_interview_list --jd 品质经理 --target 10
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

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    BASIS_FIELD, PROP_FIELD, load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
INPUTS = ROOT / 'work' / 'talent' / 'jd_inputs'
QUALITY = ROOT / 'work' / 'talent' / 'cv_quality.json'
OPENQ = ROOT / 'work' / 'talent' / 'open_questions'
TEXT = ROOT / 'work' / 'talent' / 'cv_text'


def _evidence_role(cat: dict) -> dict:
    """组件的证据档次:hard=有可验证载体(系统/报告/客户审核/图表),soft=只能靠陈述。"""
    return {c["id"]: c.get("evidence_role", "soft") for c in cat.get("components") or []}


def real_components(cid: str, cv: dict) -> set:
    """只用简历里抽到过的组件 —— 刻意不并 cv_mock,否则排序就排的是模拟数据。"""
    skills = ((cv.get(cid) or {}).get('skills') or {}).get('value') or []
    return {f"skill_{s.get('name')}" for s in skills if s.get('name')}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--target', type=int, default=0, help='要面几个人(默认读 jd_inputs.interview_target,否则 10)')
    ap.add_argument('--decided-by', default='admin')
    args = ap.parse_args()

    ji_path = INPUTS / f'{args.jd}.yaml'
    ji = yaml.safe_load(ji_path.read_text(encoding='utf-8')) if ji_path.is_file() else {}
    target = args.target or int((ji.get('interview_target') or {}).get('n') or 10)
    # 业务优先条件:不是硬过滤(会把人滤光),是**排队顺序**——
    # 业务说"先看这两类人",那就把他们排在前面,其余人依然是候选池的一部分。
    prio = (ji.get('interview_priorities') or {})
    prio_items = prio.get('criteria') or []
    from scripts.talent import priority_rules as _PRmod
    _ctx = _PRmod.make_ctx(args.jd)

    mode, _src = interview_policy.mode_for(args.jd)
    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}
    cv = json.loads((ROOT / 'work' / 'talent' / 'cv_facts.json').read_text(encoding='utf-8'))
    quality = json.loads(QUALITY.read_text(encoding='utf-8')) if QUALITY.is_file() else {}

    sl = yaml.safe_load((SHORTLIST / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
    kept = [c for c in (sl.get('kept') or []) if c in by_id]

    # 待核项(按人) —— 面试时照着问的东西
    # 注意:OPENQ 是**目录**,要判断的是目录里那份 yaml —— 判 is_file() 会永远为 False,
    # 于是每个人的"待核项"都变成 0(实测就是这么错的,还排出了一份"全都不用问"的名单)。
    oq_path = OPENQ / f'{args.jd}.yaml'
    oq = (yaml.safe_load(oq_path.read_text(encoding='utf-8')) if oq_path.is_file() else {}) or {}
    if not isinstance(oq, dict):
        oq = {}
    ask_by_cand: dict[str, list] = {}
    for it in (oq.get('queue') or []):
        ask_by_cand.setdefault(it['candidate'], []).append(it)

    # 品质岗经历只对"要求品质/领域经历"的 JD 有含义。业务跟单要的是订单/MOQ/ERP,
    # 拿"品质硬证据"排它,等于把 10 个工程师/经理排到 270 个跟单员前面 —— 实测就是这样。
    ROLE = _evidence_role(cat)
    # 客户自己在原文里写了「…优先」的条款 —— 那是**客户授权的排序依据**,不是我们的偏好
    PREFER = [c["id"] for c in link.get("citations") or []
              if "优先" in str(c.get("verbatim") or "")]
    import json as _json
    _hrf = ROOT / "work" / "talent" / "hr_facts.json"
    HRF = _json.loads(_hrf.read_text(encoding="utf-8")) if _hrf.is_file() else {}
    if PREFER:
        print(f"  客户写的「优先」条款:{'、'.join(PREFER)} → 参与同档内排序")
    needs_quality = any(
        (lib.get(c["requirement"]) or {}).get("attribute") in ("C.2", "C.3", "C.4", "C.5", "C.6")
        or any(str(x).startswith("skill_品质岗经历")
               for x in ((lib.get(c["requirement"]) or {}).get("components") or []))
        for c in link.get("citations") or []
    )
    if not needs_quality:
        print("  品质岗经历:本 JD 不要求 → 第②层不参与排序")

    rows = []
    for cid in kept:
        cand = by_id[cid]
        q = quality.get(cid) or {}
        verdict = q.get('verdict')
        onto = judge_all(cand, link, lib, atts)
        # 只用真实组件重判一次组件类要求(把 mock 排除在外)
        real = real_components(cid, cv)
        real_hits, hard_hits, soft_hits = 0, 0, 0
        seen_comp: set = set()      # 已计过分的组件(按能力去重,不按要求行)
        hard_comp: set = set(); soft_comp: set = set()
        for c in link['citations']:
            req = lib[c['requirement']]
            need = req.get('_resolved') or []
            hit = [x for x in need if x in real]
            if not hit:
                continue
            real_hits += 1
            # 按**能力项**计,不按要求行计:ERP 同时被 C-04「熟悉ERP」与 C-05「熟练ERP+Excel」
            # 引用,按行计会把同一个技能算两遍,把证据档虚抬一档(实测 10 人全是 hard=2)。
            for x in hit:
                if x in seen_comp:
                    continue
                seen_comp.add(x)
                if ROLE.get(x) == 'hard':
                    hard_hits += 1; hard_comp.add(x.replace('skill_', ''))
                else:
                    soft_hits += 1; soft_comp.add(x.replace('skill_', ''))
        gates = sum(1 for r, cell in onto.items() if cell['state'] == '满足')
        n_ask = len(ask_by_cand.get(cid) or [])
        iv_file = ROOT / 'work' / 'talent' / 'cv_interview' / f"{cid.replace('cand_', '')}.yaml"
        iv_real = iv_sim = 0
        if iv_file.is_file():
            doc = yaml.safe_load(iv_file.read_text(encoding='utf-8')) or {}
            for a in (doc.get('answers') or []):
                if interview_policy.is_real_basis(a):
                    iv_real += 1
                else:
                    iv_sim += 1
        # 业务优先条件命中数 —— 走 priority_rules,和 `priorities --list` 报的是同一套判定
        from scripts.talent import priority_rules as _PR
        prio_hits, prio_names = 0, []
        for it in prio_items:
            rule = it.get('rule') or {'kind': 'component_any',
                                      'components': it.get('components') or []}
            if _PR.met(rule, cand, _ctx):
                prio_hits += 1
                prio_names.append(it.get('name') or '?')
        # 客户「优先」条款命中数(按判定结果,不自己发明口径)
        _v = judge_all(cand, link, lib, atts)
        _rid2req = {c["id"]: c["requirement"] for c in link["citations"]}
        prefer_hits = sum(1 for rid in PREFER
                          if (_v.get(_rid2req.get(rid)) or {}).get("state") == "满足")
        # 稳定性:平均在职年限(从工作段算出来的量,不是自述)
        tenure = ((HRF.get(cid) or {}).get("avg_tenure_years") or {}).get("value") or 0
        years = cand.get("yearsPlatform")
        rows.append({
            'candidate': cid,
            'prefer_hits': prefer_hits, 'tenure': round(float(tenure), 1),
            'years': years,
            'prio_hits': prio_hits, 'prio_names': prio_names,
            'iv_real': iv_real, 'iv_sim': iv_sim,
            'quality': verdict if needs_quality else '—',
            'quality_kind': q.get('kind'),
            'quality_months': q.get('months'),
            'quality_quote': (q.get('quote') or '')[:60],
            'gates_ok': gates,          # 本体(含 mock)判满足条数,仅作参考
            'real_hits': real_hits,     # 简历里真有证据的 JD 能力项数
            'hard_hits': hard_hits, 'soft_hits': soft_hits,
            'hard_items': sorted(hard_comp), 'soft_items': sorted(soft_comp),
            'major': cand.get('major'), 'fulltime': cand.get('fullTime'),
            'quality_quote': (q.get('quote') or '')[:120],
            'n_ask': n_ask,
            'age': cand.get('age'),
            'edu': cand.get('educationRank'),
        })

    TIER = {'有': 0, '待核': 1, '读不出': 2, '无': 3}
    import hashlib
    # 2026-11-22 admin 定:**证据档在前,规则只在同证据档内生效**。
    # 之前规则在最前面,于是"规则全中但一条能力证据都没有"的人能压过"证据 2 项"的人
    # (业务跟单实测:段___研发工程主管 证据 0 项却排第 5)。那等于用偏好掩盖证据不足。
    # 排序阶梯(2026-11-22 实测:旧的"硬→软→规则→待核"在第 10 位有 13 人并列,
    # 加上"客户优先条款 + 年限 + 稳定性"之后切线唯一)。
    rows.sort(key=lambda r: (-r['hard_hits'],                      # ① 硬证据(可验证载体)
                             -r['soft_hits'],                      # ② 软证据(仅陈述)
                             -r['prio_hits'],                      # ③ 用户选的业务优先条件
                             -r['prefer_hits'],                    # ④ 客户原文写的「优先」条款
                             # ⑤ 年限:客户要求「2年以上…经验」,年限长优先;
                             #    读不出来记 -1 排最后(**这是排序口径,不是判他不合格**)
                             -(r['years'] if isinstance(r['years'], (int, float)) else -1),
                             -r['tenure'],                         # ⑥ 稳定性(平均在职年限)
                             r['n_ask'],                           # ⑦ 待核项(成本)
                             TIER.get(r['quality'], 9),            # ⑧ 品质岗经历(JD 需要时)
                             hashlib.sha256(r['candidate'].encode()).hexdigest()))   # ⑨ 哈希兜底
    # 已有真一面的先剔出来(不用再面);只有模拟的标"待复核"
    done = [r for r in rows if r['iv_real']]
    rows = [r for r in rows if not r['iv_real']]
    picked = rows[:target]

    # 切线是否唯一 —— 机器算出来的事实,写进产物,免得"名次可不可读"靠嘴说
    def _key(r):
        y = r['years'] if isinstance(r['years'], (int, float)) else -1
        return (-r['hard_hits'], -r['soft_hits'], -r['prio_hits'], -r['prefer_hits'],
                -y, -r['tenure'], r['n_ask'], TIER.get(r['quality'], 9))

    _k = _key(picked[-1]) if picked else None
    tie_band = sum(1 for r in rows if _key(r) == _k) if _k else 0
    cut = {'position': len(picked), 'tie_band': tie_band, 'hash_decided': tie_band > 1,
           'note': ('切线唯一 —— 名次可读' if tie_band == 1 else
                    f'切线落在 {tie_band} 人并列区内,谁上都行(按哈希排)')}

    dest_yaml = SHORTLIST / f'{args.jd}.面试名单.yaml'
    dest_md = SHORTLIST / f'{args.jd}.面试名单.md'
    dest_yaml.write_text(yaml.safe_dump({
        'jd': args.jd, 'step': '3 初筛 → 面试名单',
        'target': target,
        'decided_by': args.decided_by,
        'pool': len(kept),
        'rank_rule': ['① 硬证据项数(可验证载体:系统/报告/客户审核/图表),多者优先',
                      '② 软证据项数(只能靠陈述的),多者优先',
                      '③ 用户选的业务优先条件命中数',
                      '④ 客户原文写的「优先」条款命中数(客户授权的排序依据)',
                      '⑤ 总年限(客户要求 2 年以上;读不出来排最后 —— 排序口径,不是不合格)',
                      '⑥ 稳定性:平均在职年限(从工作段算出,不是自述)',
                      '⑦ 待核项数(成本,不是优劣)',
                      '⑧ 品质岗经历(仅当本 JD 要求时)',
                      '⑨ sha256(候选人 id):确定性兜底,不按文件名/姓氏排'],
        'priorities': [it.get('name') for it in prio_items],
        'cut': cut,
        'selected': [r['candidate'] for r in picked],
        'already_real_interview': [r['candidate'] for r in done],
        'rows': picked,
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    EDU = {1: '初中', 2: '中专/高中', 3: '大专', 4: '本科', 5: '硕士', 6: '博士'}
    CV_DOCS = ROOT / 'work' / 'talent' / 'cv_docs'

    def cv_link(cid: str) -> str:
        """第 3 步时多数人还没定稿 —— 只有定稿存在的才给链接,不编。"""
        doc = CV_DOCS / f"{cid.replace('cand_', '')}.定稿.md"
        return f'[看 CV](#tal:cv/{cid})' if doc.is_file() else '—'

    md = [f'# 面试名单 · {args.jd}', '',
          f'从初筛保留的 **{len(kept)}** 人里挑 **{target}** 人。排序只用真实证据,**不含任何模拟填充**。', '',
          '| # | 候选人 | 业务优先 | 品质岗经历 | 简历真有的能力项 | 待核 | 年龄 | 学历 | CV |',
          '|---|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(picked, 1):
        q = r['quality'] or '—'
        # 本 JD 不要品质岗经历时(q == '—'),别把"某段 127 个月"挂上去 —— 那是别的岗的数
        qk = f"{r['quality_kind'] or '—'}档" if (r['quality_months'] and q != '—') else ''
        qs = f"{q}" + (f"({qk} {r['quality_months']}月)" if qk else '')
        flag = ' *(已模拟面过,需复核)*' if r['iv_sim'] else ''
        pn = '、'.join(r['prio_names']) or '—'
        from scripts.talent import names as _names
        nm = _names.name_of(r['candidate'])
        edu = EDU.get(r['edu']) or '—'
        md.append(f"| {i} | {nm}{flag} | {pn} | {qs} | "
                  f"{r['real_hits']} 项 | {r['n_ask']} | {r['age'] or '—'} | {edu} | "
                  f"{cv_link(r['candidate'])} |")
    # 每人一段可展开的详情 —— **已去掉**。
    # 展开面板现在由 CV 弹层承担(表格里的「看 CV」点开就是定稿全文),
    # 同一批信息在 md 里再抄一遍会让每份名单长到 900 行,而读者只想要那张表。
    md += []
    dest_md.write_text('\n'.join(md), encoding='utf-8')

    # 记下目标 —— 谁定的、哪天,写在 jd_inputs 里
    if ji_path.is_file():
        if not isinstance(ji, dict):
            ji = {}
        ji['interview_target'] = {'n': target, 'decided_by': args.decided_by,
                                  'decided_at': '2026-11-21',
                                  'why': '初筛保留人数太多,第 3 步要给出可执行的面试批次'}
        ji_path.write_text(yaml.safe_dump(ji, allow_unicode=True, sort_keys=False), encoding='utf-8')

    print(f'面试名单:从 {len(kept)} 人挑 {target} 人 → {dest_md.relative_to(ROOT)}')
    print(f"  切线:第 {cut['position']} 位 tie_band={cut['tie_band']} —— {cut['note']}")
    if len(picked) < target:
        # 凑不够要吼出来:这通常意味着初筛条件太严,或者池子里真没这么多人
        print(f'  ⚠ 只凑到 {len(picked)} 人(目标 {target})—— 池子里没更多符合条件的人'
              f'或初筛门槛过严(已排除 {len(sl.get("excluded") or [])} 人)')
    for i, r in enumerate(picked[:target], 1):
        print(f"  {i:>2}. {r['candidate'].replace('cand_','')[:34]:34} "
              f"品质岗={r['quality']} 真能力项={r['real_hits']} 待核={r['n_ask']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
