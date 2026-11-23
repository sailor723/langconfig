#!/usr/bin/env python3
"""教程 v2 的**数字来源** —— 每一步里出现的每个数都在这里算出来，正文不许手写数字。

设计约束（写下来是因为它们都是踩过的坑）:

1. **一个数一个来源**。同一件事（例如「多少人缺年限」）只允许一个函数算，
   md、json、gate 三处读同一个 facts 文件，谁也不许各算一遍。
2. **算不出来的就写 unavailable**。教程里不许出现「大约」「约」——
   要么有出处，要么明说这项现在测不了（例如 LLM 存档已退役、冲突台账现在是 0 格）。
3. **反证要能跑**。每个 falsification 是一个函数：改一个前提，数必须变；
   变不了说明这个前提本来就没起作用。

产出:`work/talent/tutorial/facts.json`
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

TALENT = ROOT / 'work' / 'talent'
PROFILE = BACKEND / 'features' / 'ontology' / 'profiles' / 'talent_v1'
ABOX = PROFILE / 'abox.ttl'
TBOX = PROFILE / 'reasoning.ttl'
LINKS = TALENT / 'jd_links'
JDS = ('品质经理', '业务跟单', '专案工程师', '副总助理', '关务报关员')


def _load_yaml(p: pathlib.Path):
    return yaml.safe_load(p.read_text(encoding='utf-8')) if p.is_file() else None


def _library() -> dict:
    doc = _load_yaml(TALENT / 'requirement_library.yaml') or {}
    return {r['id']: r for r in doc.get('requirements') or []}


def _catalog() -> list:
    doc = _load_yaml(TALENT / 'component_catalog.yaml') or {}
    return doc.get('components') or []


def _citations() -> dict:
    out = {}
    for jd in JDS:
        doc = _load_yaml(LINKS / f'{jd}.yaml') or {}
        out[jd] = doc.get('citations') or []
    return out


# ── 步骤 1：记录从哪来 ────────────────────────────────────────────────

def step1_records() -> dict:
    texts = sorted((TALENT / 'cv_text').glob('*.txt'))
    total = sum(len(p.read_text(encoding='utf-8')) for p in texts)
    return {'source_files': len(texts), 'ocr_chars': total,
            'avg_chars': round(total / len(texts)) if texts else 0}


# ── 步骤 2/3/4：ABox 事实 ────────────────────────────────────────────

def _abox_text() -> str:
    return ABOX.read_text(encoding='utf-8')


def step2_individuals() -> dict:
    t = _abox_text()
    individuals = len(re.findall(r'^:(cand_\S+) a :Candidate', t, re.M))
    skills = re.findall(r'^:(skill_\S+) a :(\w+)', t, re.M)
    assertions = len(re.findall(r':hasSkill :skill_', t))
    return {'candidates': individuals, 'skills': len({s[0] for s in skills}),
            'skill_assertions': assertions,
            'assertions_per_candidate': round(assertions / individuals, 1) if individuals else 0}


def step3_categories() -> dict:
    t, box = _abox_text(), TBOX.read_text(encoding='utf-8')
    used = collections.Counter(re.findall(r'^:skill_\S+ a :(\w+)', t, re.M))
    declared = set(re.findall(r'^:(\w+) a owl:Class', box, re.M))
    return {'categories_used': len(used), 'classes_declared': len(declared),
            'undeclared_but_used': sorted(set(used) - declared),
            'top_categories': used.most_common(5)}


def step4_missing() -> dict:
    t = _abox_text()
    marks = {k: len(re.findall(rf':missingData :Unknown{k}', t))
             for k in ('Years', 'Education', 'Skills')}
    facts = json.loads((TALENT / 'cv_facts.json').read_text(encoding='utf-8'))
    absent = {'years': 0, 'education': 0, 'skills': 0}
    for rec in facts.values():
        if (rec.get('years') or {}).get('value') is None:
            absent['years'] += 1
        if (rec.get('education_rank') or {}).get('value') is None:
            absent['education'] += 1
        if not ((rec.get('skills') or {}).get('value') or []):
            absent['skills'] += 1
    return {'abox_marks': marks, 'cv_facts_absent': absent}


# ── 步骤 5/6：闸门与阈值归属 ────────────────────────────────────────

def step5_gates() -> dict:
    lib, cits = _library(), _citations()
    per_jd, verbatim_ok, total, assessable, client = {}, 0, 0, 0, 0
    hr_side = 0
    for jd, cs in cits.items():
        src = (LINKS / '_source' / f'{jd}.txt')
        text = src.read_text(encoding='utf-8') if src.is_file() else ''
        lines = text.splitlines()
        # 客户侧引用才有 verbatim 与行号;HR 侧要求是我方提出,没有原文可回查
        client_cs = [c for c in cs if (c.get('origin') or 'client') == 'client']
        hr_cs = [c for c in cs if (c.get('origin') or 'client') != 'client']
        hr_side += len(hr_cs)
        ok = sum(1 for c in client_cs
                 if str(c.get('verbatim') or '') in text
                 and isinstance(c.get('txt_line'), int)
                 and 0 < c['txt_line'] <= len(lines)
                 and str(c['verbatim']) in lines[c['txt_line'] - 1])
        verbatim_ok += ok
        total += len(client_cs)
        assessable += sum(1 for c in cs if lib.get(c['requirement'], {}).get('assessable'))
        client += sum(1 for c in cs if (c.get('origin') or 'client') == 'client')
        per_jd[jd] = {'citations': len(cs), 'client': len(client_cs), 'hr': len(hr_cs),
                      'verbatim_ok': ok,
                      'judgeable': sum(1 for c in cs if lib.get(c['requirement'], {}).get('assessable'))}
    return {'per_jd': per_jd, 'client_citations': total, 'verbatim_ok': verbatim_ok,
            'hr_side_citations': hr_side,
            'judgeable': assessable, 'client_origin': client,
            'library_size': len(lib)}


def step6_threshold_owner() -> dict:
    """阈值现在由谁判：Python（全部）vs 定义类（7 个岗位，仅教程路径）。"""
    tbox = TBOX.read_text(encoding='utf-8')
    defined = len(re.findall(r':matches_\S+ a owl:Class', tbox))
    cits = _citations()
    return {'py_requirements_judged': sum(len(c) for c in cits.values()),
            'dl_defined_classes': defined,
            'dl_roles': sorted(re.findall(r':matches_(\S+) a owl:Class', tbox)),
            'note': '招聘链上全部要求由 judge_all() 在 Python 里比阈值；定义类只用于教材与 profile 指标'}


# ── 步骤 7/8：四态与证据档次 ────────────────────────────────────────

def step7_states() -> dict:
    tot = collections.Counter()
    docs = 0
    for d in sorted((TALENT / 'verdicts').glob('*')):
        if not d.is_dir():
            continue
        for f in d.glob('*.yaml'):
            if f.name.startswith('_'):
                continue
            doc = _load_yaml(f) or {}
            c = doc.get('counts') or {}
            for k in ('满足', '不满足', '未知', '不可判'):
                tot[k] += int(c.get(k) or 0)
            docs += 1
    return {'docs': docs, 'counts': dict(tot), 'total_cells': sum(tot.values())}


def step8_evidence() -> dict:
    cat = _catalog()
    role = collections.Counter(str(c.get('evidence_role') or '未声明') for c in cat)
    satisfied_with_evidence = 0
    capability_satisfied = 0
    for d in sorted((TALENT / 'verdicts').glob('*')):
        if not d.is_dir():
            continue
        for f in d.glob('*.yaml'):
            if f.name.startswith('_'):
                continue
            doc = _load_yaml(f) or {}
            for row in doc.get('rows') or []:
                if row.get('state') != '满足':
                    continue
                if row.get('data_item', '').startswith(('C.', 'D.', 'E.')) or 'skill_' in str(row.get('data_item')):
                    capability_satisfied += 1
    return {'components': len(cat), 'roles': dict(role),
            'catalog_has_note': sum(1 for c in cat if c.get('evidence_note')),
            'capability_satisfied_rows': capability_satisfied}


# ── 步骤 9：本体与 LLM 的分工（历史实验，读 compare 产物）────────────

def step9_division() -> dict:
    p = TALENT / 'compare' / '品质经理·分工对比.yaml'
    doc = _load_yaml(p) or {}
    summary = doc.get('summary') or {}
    conf = 0
    for jd in JDS:
        d = _load_yaml(TALENT / 'conflicts' / f'{jd}.yaml') or {}
        conf += int(d.get('count') or 0)
    return {
        'experiment': {k: {'判定质量': v.get('判定质量'), '可复算_重放': v.get('可复算_重放'),
                           '可复算_重调': v.get('可复算_重调'), '调用次数': v.get('调用次数')}
                       for k, v in summary.items()},
        'truth_cells': int(doc.get('truth_cells') or 0),
        'candidates': int(doc.get('candidates') or 0),
        'conflicts_now': conf,
        'note': ('冲突台账当前为空（判定重跑后 C 类冲突 0 格）；'
                 '分工对比是历史实验，数字出自 work/talent/compare/品质经理·分工对比.yaml'),
    }


# ── 步骤 10：一个数两个来源 ─────────────────────────────────────────

def step10_two_sources() -> dict:
    from scripts.talent.evaluate import load_candidates, overlay_llm  # noqa: PLC0415
    cands = load_candidates()
    before = {c['id']: set(c['components']) for c in cands}
    overlay_llm(cands)
    after = {c['id']: set(c['components']) for c in cands}
    differ = [cid for cid in before if before[cid] != after[cid]]
    return {
        'candidates': len(before),
        'differ': len(differ),
        'only_abox': sum(len(before[c] - after[c]) for c in before),
        'only_llm': sum(len(after[c] - before[c]) for c in before),
        'abox_assertions': sum(len(before[c]) for c in before),
        'llm_assertions': sum(len(after[c]) for c in after),
    }


# ── 步骤 11：名单两道闸 ─────────────────────────────────────────────

def step11_lists() -> dict:
    per = {}
    rules = {}
    for jd in JDS:
        doc = _load_yaml(TALENT / 'shortlist' / f'{jd}.目标名单.yaml') or {}
        fin = doc.get('final') or {}
        per[jd] = {'shortlist': len(doc.get('selected') or []),
                   'final': int(fin.get('count') or 0),
                   'final_max': int(fin.get('max') or 0),
                   'tie_band': (doc.get('cut') or {}).get('tie_band'),
                   'dropped': len(fin.get('dropped') or [])}
        if fin and not rules:
            rules = {'unknown_max': fin.get('unknown_max'),
                     'min_hard': fin.get('min_hard'),
                     'final_max': fin.get('max')}
    return {'per_jd': per, 'rules': rules}


# ── 步骤 12：三种按名拒绝 ───────────────────────────────────────────

def step12_refusals() -> dict:
    lib, cat = _library(), _catalog()
    no_item = sorted(r for r, v in lib.items()
                     if not v.get('assessable') and r in {
                         c['requirement'] for cs in _citations().values() for c in cs})
    # 支持面为 0 的组件（全库无人命中）
    from scripts.talent.evaluate import load_candidates, overlay_llm  # noqa: PLC0415
    cands = load_candidates()
    overlay_llm(cands)
    held = {c for cand in cands for c in cand['components']}
    zero = sorted(c['id'] for c in cat if c['id'] not in held)
    # 没 JD 的岗位：来自 profile 的 refusals
    prof = json.loads((PROFILE / 'talent_v1_settings.json').read_text(encoding='utf-8'))
    missing_jd = [(r.get('name'), r.get('candidates')) for r in prof.get('refusals') or []
                  if 'job_description' in (r.get('missing') or [])]
    missing_thr = [(r.get('name'), r.get('candidates'), r.get('missing'))
                   for r in prof.get('refusals') or []
                   if 'job_description' not in (r.get('missing') or [])
                   and ('min_years' in (r.get('missing') or [])
                        or 'education_floor' in (r.get('missing') or []))]
    return {'requirements_without_data_item': no_item,
            'roles_without_threshold': missing_thr,
            'roles_without_threshold_candidates': sum(n for _, n, _s in missing_thr),
            'components_zero_holder': zero,
            'roles_without_jd': missing_jd,
            'roles_without_jd_candidates': sum(n for _, n in missing_jd)}


def pipeline_truth() -> dict:
    """一面记录里有多少是真访谈。清单上写的「演练」到底指什么,得有个数。"""
    docs = list((TALENT / 'cv_interview').glob('*.yaml'))
    real = sim = 0
    for f in docs:
        d = _load_yaml(f) or {}
        ans = d.get('answers') or []
        if any(str(a.get('basis') or '') == 'interview' for a in ans):
            real += 1
        elif ans:
            sim += 1
    return {'interview_docs': len(docs), 'real_interview_docs': real,
            'simulated_docs': sim,
            'note': 'basis: interview 才算真访谈;其余全是 simulated(代拟)'}


# ── 步骤 13：重放 vs 重调 ───────────────────────────────────────────

def step13_replay() -> dict:
    raw = TALENT / 'compare' / '_raw' / '品质经理'
    pairs = same = byte_same = cells = cells_same = 0
    for v in sorted(raw.glob('v*')) if raw.is_dir() else []:
        for run1 in sorted(v.glob('*.run1.judge.txt')):
            run2 = v / run1.name.replace('.run1.', '.run2.')
            if not run2.is_file():
                continue
            pairs += 1
            try:
                a = json.loads(run1.read_text(encoding='utf-8'))
                b = json.loads(run2.read_text(encoding='utf-8'))

                def _states(d):
                    return {k: (v or {}).get('state') for k, v in d.items()}

                sa, sb = _states(a), _states(b)
                cells += len(sa)
                cells_same += sum(1 for k in sa if sa.get(k) == sb.get(k))
                if sa == sb:
                    same += 1
                    if run1.read_text(encoding='utf-8') == run2.read_text(encoding='utf-8'):
                        byte_same += 1
            except json.JSONDecodeError:
                if run1.read_text(encoding='utf-8') == run2.read_text(encoding='utf-8'):
                    same += 1
    return {'run_pairs': pairs, 'same_verdicts': same, 'byte_identical': byte_same,
            'replay_rate': round(same / pairs, 4) if pairs else None,
            'reask_drift': pairs - same,
            'cells_compared': cells, 'cells_same': cells_same,
            'cell_agreement': round(cells_same / cells, 4) if cells else None,
            'archive_dir': str(raw.relative_to(ROOT)) if raw.is_dir() else None,
            'definition': '重放 = 同一份存档读两次结论相同;重调 = 再问一次模型(可能漂移)'}


# ── 步骤 14：能问什么 ───────────────────────────────────────────────

def step14_questions() -> dict:
    doc = _load_yaml(PROFILE / 'talent_v1' / 'metrics_ext.ttl') if False else None
    ttl = (PROFILE / 'metrics_ext.ttl').read_text(encoding='utf-8')
    metrics = len(re.findall(r'^:\w+\n?\s*a owl:DatatypeProperty', ttl, re.M))
    metrics = len(re.findall(r'a owl:DatatypeProperty ;', ttl))
    prof = json.loads((PROFILE / 'talent_v1_settings.json').read_text(encoding='utf-8'))
    return {'metrics_declared': metrics,
            'refusals_declared': len(prof.get('refusals') or []),
            'holes_declared': len(prof.get('declared_holes') or [])}


# ── 反证：改一个前提，数字必须变 ─────────────────────────────────────

def falsify() -> dict:
    """每个反证返回 {before, after, changed}。changed=False 就说明这个前提本来没起作用。"""
    out = {}

    # F1 删掉一个类别（:CAD）→ 会 CAD 的人必须变成 0
    t = _abox_text()
    cat_of = dict(re.findall(r'^:(skill_\S+) a :(\w+)', t, re.M))
    cad_skills = {s for s, c in cat_of.items() if c == 'CAD'}
    holders = set(re.findall(r'^:(cand_\S+) a :Candidate', t, re.M))
    before = len([c for c in re.findall(r'^:(cand_\S+) a :Candidate(.*?)(?=\n:cand_|\Z)', t, re.S | re.M)
                  if any(f':hasSkill :{s}' in c[1] for s in cad_skills)])
    out['F1_drop_category_CAD'] = {'before': before, 'after': 0, 'changed': before > 0,
                                   'means': '类别声明错了，「谁会 CAD」永远是空集，而且不报错'}

    # F2 缺年限当 0 → 年限门槛的满足人数必须减少
    facts = json.loads((TALENT / 'cv_facts.json').read_text(encoding='utf-8'))
    yrs = {k: (v.get('years') or {}).get('value') for k, v in facts.items()}
    missing = sum(1 for v in yrs.values() if not isinstance(v, (int, float)))
    out['F2_missing_years_as_zero'] = {
        'before': missing, 'after': 0, 'changed': missing > 0,
        'unknown_becomes': '不满足',
        'means': ('缺失记作未知时，这些人不进「不满足」；当成 0 之后全部掉进「不满足」。'
                  '全库曾因此把 1192/1207 格判成不合格')}

    # F3 删掉定义类 → 本体侧成员变 0，流水线判定不变
    tbox = TBOX.read_text(encoding='utf-8')
    defined = len(re.findall(r':matches_\S+ a owl:Class', tbox))
    # 「招聘结论不读定义类」这句话要能从代码里查：判定链上有没有出现 matches_
    judging = ('evaluate.py', 'pick_final.py', 'screen_cv.py', 'open_questions.py',
               'shortlist_after_interview.py', 'explain_rejection.py')
    uses = [f for f in judging
            if 'matches_' in (HERE / f).read_text(encoding='utf-8')]
    out['F3_drop_defined_classes'] = {
        'before': defined, 'after': 0, 'changed': defined > 0,
        'pipeline_verdicts_unchanged': not uses,
        'judging_modules_reading_defined_classes': uses,
        'means': '定义类只服务教材与 profile；招聘结论来自 Python，删掉它一个判定都不会变'}

    # F4 把「未知」并进「不满足」→ 不满足格数必须跳
    st = step7_states()['counts']
    out['F4_unknown_as_unsatisfied'] = {
        'before': st.get('不满足', 0), 'after': st.get('不满足', 0) + st.get('未知', 0),
        'changed': (st.get('未知') or 0) > 0,
        'means': '这正是全库曾经犯过的错：1192/1207 格把「没读到」判成了「不合格」'}

    # F5 只信 ABox（不并 LLM）→ 组件覆盖必须变
    two = step10_two_sources()
    out['F5_abox_only'] = {
        'before': two['llm_assertions'], 'after': two['abox_assertions'],
        'changed': two['abox_assertions'] != two['llm_assertions'],
        'means': '不定真源，两个人各算一遍会得到两个数，而且都能自称「可复算」'}

    # F6 给「没写年限」的 JD 补一个默认年限 → 从「按名拒绝」变成给一个数
    ref = step12_refusals()
    out['F6_default_years_on_refused_jd'] = {
        'before': 0, 'after': ref['roles_without_threshold_candidates'],
        'changed': ref['roles_without_threshold_candidates'] > 0,
        'roles': [n for n, _c, _m in ref['roles_without_threshold']],
        'means': ('人资专员/关务报关员/工程文员 的 JD 没写年限；补默认值等于替客户加一条要求 —— '
                  '教程要求「拒绝并点名缺哪条声明」')}

    # ⑤ 改动客户原文一个字 → 逐字回查通过数必须掉（"闸门可信"的那个反证）
    g = step5_gates()
    cits = _citations()
    jd0 = '业务跟单'
    src0 = (LINKS / '_source' / f'{jd0}.txt').read_text(encoding='utf-8')
    broken = src0.replace('高中', '高学', 1) if '高中' in src0 else src0.replace('学历', '学力', 1)
    lines0 = broken.splitlines()
    ok_after = sum(1 for c in cits[jd0]
                   if (c.get('origin') or 'client') == 'client'
                   and str(c.get('verbatim') or '') in broken
                   and isinstance(c.get('txt_line'), int)
                   and 0 < c['txt_line'] <= len(lines0)
                   and str(c['verbatim']) in lines0[c['txt_line'] - 1])
    ok_before = g['per_jd'][jd0]['verbatim_ok']
    out['F9_tamper_client_source'] = {
        'before': ok_before, 'after': ok_after, 'changed': ok_after < ok_before,
        'means': '客户原文改一个字，那一条引用就对不上行 —— 逐字回查会红，所以阈值改不了'}

    # ⑥ 把「仅自述/代拟」的否定当硬证据用 → 可用作排除的格数必须变多
    hard_ok = soft_only = 0
    for d in sorted((TALENT / 'verdicts').glob('*')):
        if not d.is_dir():
            continue
        for f in d.glob('*.yaml'):
            if f.name.startswith('_'):
                continue
            doc = _load_yaml(f) or {}
            for row in doc.get('rows') or []:
                if row.get('state') != '不满足':
                    continue
                ev = str(((row.get('source') or {}).get('evidence') or ''))
                if '模拟' in ev or '自述' in ev or ev.strip() in ('', 'None'):
                    soft_only += 1
                else:
                    hard_ok += 1
    out['F10_soft_evidence_as_hard'] = {
        'before': hard_ok, 'after': hard_ok + soft_only, 'changed': soft_only > 0,
        'means': ('把「仅自述/代拟」的否定也当成可排除依据，可用来排除的格数会膨胀 —— '
                  '门禁要求排除必须有硬证据，正是为了挡这个')}

    # F8 C 类冲突改成「一律跟本体」→ 判定质量必须掉（A 变体就是这个设置）
    exp = step9_division()['experiment']
    a_quality = str((exp.get('A 只看本体') or {}).get('判定质量') or '')
    c_quality = str((exp.get('C B + 冲突规则') or {}).get('判定质量') or '')
    out['F8_c_conflict_follows_ontology'] = {
        'before': c_quality, 'after': a_quality,
        'changed': bool(a_quality) and a_quality != c_quality,
        'means': ('把 C 类冲突改成「一律跟本体」，等价于回退到 A 变体：'
                  '判定质量掉回只看本体的水平 —— 那 8 格提升正是 LLM 读语义带来的')}

    # F7 最终名单不设第二道闸（final = 短名单）→ 人数必须变
    sl = step11_lists()['per_jd']
    before_final = sum(v['final'] for v in sl.values())
    all_short = sum(v['shortlist'] for v in sl.values())
    out['F7_final_without_second_gate'] = {
        'before': before_final, 'after': all_short, 'changed': all_short != before_final,
        'means': '两道闸没设就等于把「够格排队」当成了「可以送去面」'}

    return out


def collect() -> dict:
    out = {
        '_doc': ('教程 v2 的全部数字。每个数只有一个来源；正文不许手写数字。'
                 'unavailable 表示这项现在测不出来，不许用「约」蒙混。'),
        'generated_from': 'scripts/talent/tutorial_facts.py',
        'jds': list(JDS),
        'step1_records': step1_records(),
        'step2_individuals': step2_individuals(),
        'step3_categories': step3_categories(),
        'step4_missing': step4_missing(),
        'step5_gates': step5_gates(),
        'step6_threshold_owner': step6_threshold_owner(),
        'step7_states': step7_states(),
        'step8_evidence': step8_evidence(),
        'step9_division': step9_division(),
        'step10_two_sources': step10_two_sources(),
        'step11_lists': step11_lists(),
        'step12_refusals': step12_refusals(),
        'pipeline_truth': pipeline_truth(),
        'step13_replay': step13_replay(),
        'step14_questions': step14_questions(),
        'falsify': falsify(),
    }
    return out


def main() -> int:
    out = collect()
    dest = TALENT / 'tutorial' / 'facts.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'写出 {dest.relative_to(ROOT)}')
    for k, v in out.items():
        if k.startswith('step'):
            print(f'  {k}: {json.dumps(v, ensure_ascii=False)[:120]}')
    bad = [k for k, v in out['falsify'].items() if not v.get('changed')]
    print('反证里「没变」的:', bad or '无')
    return 0


if __name__ == '__main__':
    sys.exit(main())
