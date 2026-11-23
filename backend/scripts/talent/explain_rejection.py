#!/usr/bin/env python3
"""为什么这个人没过 —— 一份能直接放在业务领导桌上的判定说明。

这是整套系统里**唯一对外**的产物。HR 拿它回答业务领导那句必问的话:
「这个人为什么不行?」而这句话的回答质量,决定了这套系统能不能在客户那里立住。

所以这份说明的每一行都必须能追问到底:

    条款 C-01 是什么      → JD 原文第几行、逐字写的什么
    判的是什么数据项       → 数据项名(D 本体里那个属性/组件)
    他的值是多少           → 值 + **这个值从哪来**(简历引文 / HR 计算 / 一面记录 / 平台)
    阈值是多少             → JD 给的取值与算子
    所以判定是什么         → 四态之一

四个状态不许合并,尤其是**未知**(他没提供)和**不可判**(这条要求没有数据项 / JD 没给标准)。
把这两样混成"不满足",等于向业务领导撒谎 —— 他不会知道"我们其实没测"。

产物:
    work/talent/verdicts/<JD>/<候选人>.md     给人看(含话术)
    work/talent/verdicts/<JD>/<候选人>.yaml   给机器查(门禁按这个复算)
    work/talent/verdicts/<JD>/_index.md       这一批人的总览

可复算:每份说明都带输入指纹与重跑命令。改过任何输入(JD 原文、阈值、本体词表、
简历事实)指纹就变,门禁会把旧说明标成过期 —— **不让一份说明在输入变了以后还挂在墙上**。

用法:
    python -m scripts.talent.explain_rejection --jd 品质经理 --ids <候选id> ...
    python -m scripts.talent.explain_rejection --jd 品质经理 --interviewed
    python -m scripts.talent.explain_rejection --jd 品质经理 --verify      # 只查过期/不一致
"""
from __future__ import annotations

import argparse
import hashlib
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
    BASIS_FIELD, CATALOG, LIBRARY, LINKS, PROP_FIELD, load_candidates, overlay_hr,
    overlay_interview, overlay_llm, overlay_mock)
from scripts.talent import names as _names  # noqa: E402
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

OUT = ROOT / 'work' / 'talent' / 'verdicts'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
HR_FACTS = ROOT / 'work' / 'talent' / 'hr_facts.json'
CV_IV = ROOT / 'work' / 'talent' / 'cv_interview'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
DEFECTS = ROOT / 'work' / 'talent' / 'known_defects.yaml'


def load_defects() -> list:
    """已知缺陷登记。判定说明要主动交代"这一行可能受哪个缺陷影响" ——
    等业务领导现场问倒,比自己先说清楚要贵得多。"""
    if not DEFECTS.is_file():
        return []
    doc = yaml.safe_load(DEFECTS.read_text(encoding='utf-8')) or {}
    return doc.get('defects') or []


def defects_for(req: dict, rows_defects: list) -> list:
    rid = req.get('id')
    comps = set(req.get('_resolved') or req.get('components') or [])
    out = []
    for d in rows_defects:
        aff = d.get('affects') or {}
        if rid in (aff.get('requirements') or []) or (comps & set(aff.get('components') or [])):
            out.append(d)
    return out

STATES = ('满足', '不满足', '未知', '不可判')


def threshold_cn(row: dict) -> str:
    """阈值要能读出口。{'min':25,'max':40} 摆在业务领导面前等于没说。"""
    t = row.get('threshold')
    op = row.get('op')
    if isinstance(t, str):
        return t
    if not isinstance(t, dict):
        return '—' if t is None else str(t)
    if op == 'between' and 'min' in t and 'max' in t:
        return f"{t['min']}~{t['max']}"
    if 'num' in t:
        return f"≥ {t['num']}"
    if 'in' in t:
        return '命中其中之一:' + '、'.join(t['in'])
    return json.dumps(t, ensure_ascii=False)
#: 客户侧门槛:这些条款过不去,不是我方判断,是客户原文定的,必须由客户拍板才能放宽
CLIENT_GATE_ATTRS = {'A.2': '年龄', 'B.1': '学历'}

#: 数据项取自哪里(优先级从高到低)。
SRC_ORDER = ('interview', 'cv_facts', 'hr_facts', 'platform')


# ───────────────────────────────────────────────────── 值的来源:这是整份说明的骨架
def load_facts() -> tuple[dict, dict]:
    cv = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    hr = json.loads(HR_FACTS.read_text(encoding='utf-8')) if HR_FACTS.is_file() else {}
    return cv, hr


def interview_answers(cid: str) -> dict:
    """一面记录里的 props / establishes,带上「真人说过」还是「我方拟的」。"""
    p = CV_IV / f"{cid.replace('cand_', '')}.yaml"
    if not p.is_file():
        return {'props': {}, 'components': {}, 'real': False}
    doc = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    props, comps = {}, {}
    real = False
    for a in doc.get('answers') or []:
        is_real = interview_policy.is_real_basis(a)
        real = real or is_real
        tag = '一面记录' if is_real else '一面记录(模拟)'
        q = a.get('question') or a.get('q') or ''
        v = a.get('answer') or a.get('a') or ''
        for k, val in (a.get('props') or {}).items():
            props[k] = {'value': val, 'source': tag,
                        'evidence': (v or '')[:80] or f'{k}={val}', 'quote': q[:60]}
        for c in a.get('establishes') or []:
            comps[c] = {'source': tag, 'evidence': (v or '')[:80], 'quote': q[:60]}
    return {'props': props, 'components': comps, 'real': real}


def _basis_cn(basis: str) -> str:
    return {'stated': '简历原文', 'inferred': '简历推断', 'computed': 'HR 计算',
            'computed_unverified': 'HR 计算(未核)', 'rejected': '已否决'}.get(basis, basis or '?')


def value_provenance(cid: str, prop: str, cand: dict, cv: dict, hr: dict, iv: dict) -> dict:
    """这个数据项的值是哪来的。找不到就如实说找不到 —— 不许编来源。"""
    for key, rec in (iv['props'] or {}).items():
        if key == prop:
            return {'kind': '一面记录', 'detail': rec['source'],
                    'evidence': rec['evidence'], 'question': rec['quote'],
                    'real': iv['real']}
    f = (cv.get(cid) or {}).get(prop)
    if isinstance(f, dict) and f.get('value') is not None:
        b = f.get('basis')
        # 「简历推断」比「HR 计算」诚实:这个值是从出生年月推出来的,不是 HR 填的
        kind = {'stated': '简历原文', 'inferred': '简历推断',
                'computed': '简历推算'}.get(b, _basis_cn(b))
        return {'kind': kind, 'detail': 'cv_facts',
                'evidence': f.get('quote') or '', 'basis': b}
    h = (hr or {}).get(cid) or {}
    if prop in h and isinstance(h[prop], dict):
        ev = h[prop].get('evidence') or []
        return {'kind': _basis_cn(h[prop].get('basis')), 'detail': 'hr_facts',
                'evidence': '; '.join(str(x) for x in ev[:3]), 'basis': h[prop].get('basis')}
    if cand.get(prop) is not None:
        return {'kind': '平台计算', 'detail': 'abox/平台', 'evidence': ''}
    return {'kind': '无', 'detail': '库中没有这个值', 'evidence': ''}


def component_provenance(comp: str, cv: dict, cid: str, iv: dict, quality: dict) -> dict:
    for name, rec in (iv['components'] or {}).items():
        if name == comp:
            return {'kind': '一面记录', 'detail': rec['source'],
                    'evidence': rec['evidence'], 'question': rec['quote'], 'real': iv['real']}
    skills = ((cv.get(cid) or {}).get('skills') or {}).get('value') or []
    label = comp.replace('skill_', '')
    for s in skills:
        if str(s.get('name')) == label:
            return {'kind': '简历原文', 'detail': 'cv_facts.skills',
                    'evidence': s.get('quote') or '', 'basis': 'stated'}
    q = (quality or {}).get('quality') or {}
    if comp in ('skill_岗位经历',) or (q.get('verdict') and comp == 'skill_品质岗经历'):
        return {'kind': 'HR 计算', 'detail': 'cv_quality', 'evidence': str(q.get('quote') or '')[:80]}
    return {'kind': '无', 'detail': '库中没有这个组件', 'evidence': ''}


# ───────────────────────────────────────────────────── 一条要求的完整链条
def explain_requirement(c, req, cand, atts, cv, hr, iv, quality) -> dict:
    from scripts.talent.evaluate import COVERAGE, judge_attribute, judge_component

    rid, cit = c['id'], c
    _origin = cit.get('origin') or 'client'
    # HR 侧要求不是客户原话:没有 verbatim / 行号。这时"来源"写我方依据,而不是留空 ——
    # 留空会让门禁判成"追不到底",读者也看不出这条是谁提的。
    _ctext = cit.get('verbatim') or ''
    if _origin == 'hr' and not _ctext:
        _why = cit.get('rationale') or req.get('rationale') or req.get('note') or '见 jd_links 的 origin: hr 条目'
        _ctext = '[我方提出] ' + str(_why)[:80]
    row = {'clause': rid, 'requirement': c['requirement'], 'name': req.get('name'),
           'client_text': _ctext, 'client_line': cit.get('txt_line'),
           'origin': _origin}
    attr_id = req.get('attribute')
    if attr_id and not req.get('_resolved'):
        att = atts.get(attr_id) or {}
        state, why = judge_attribute(att, req, cit, cand, '')
        prop = PROP_FIELD.get(attr_id)
        if attr_id in ('C.1', 'C.6'):
            # 年限类要求的供给侧字段由 year_basis 决定 —— 必须和 judge_attribute 走同一套解析,
            # 否则说明里的"他的值"会和判定用的值不是同一个(实测踩过:C-05 判 2 年,说明却显示空)。
            basis = (cit.get('year_basis') or req.get('year_basis') or 'platform')
            prop = BASIS_FIELD.get(basis, 'yearsPlatform')
        row.update({
            'data_item': f'{attr_id} {att.get("label") or ""}'.strip(),
            'value': cand.get(prop) if prop else None,
            'threshold': cit.get('value') or {},
            'op': req.get('op'),
            'state': state, 'why': why,
            'source': value_provenance(c['requirement'] and cand['id'], prop, cand, cv, hr, iv)
            if prop else {'kind': '无', 'detail': '属性没有供给侧字段', 'evidence': ''},
            'client_gate': CLIENT_GATE_ATTRS.get(attr_id),
        })
    elif req.get('_resolved'):
        needed = req['_resolved']
        held = [x for x in needed if x in cand['components']]
        # denied 必须一起传:判定说明与名单/选人要用**同一套**判定。
        # 不传的话,"一面明确否认"在这里仍记未知,于是名单说不满足 2 条、
        # 判定说明只写 1 条 —— 同一个人两份文件对不上(实测就出过)。
        state, why = judge_component(cand['components'], needed, req.get('match'),
                                     denied=cand.get('_denied'))
        if state == '满足':
            from scripts.talent.evaluate import component_evidence
            lv = [component_evidence(cand['id'], x, cv, iv.get('raw') or {}) for x in held]
            best = max(lv, key=lambda v: {'strong': 2, 'weak': 1, 'none': 0}.get(v, 0)) if lv else 'weak'
            row_evidence = '案例/实测' if best == 'strong' else '仅自述'
        else:
            row_evidence = None
        row.update({
            'data_item': '、'.join(x.replace('skill_', '') for x in needed),
            'value': ('命中 ' + '、'.join(x.replace('skill_', '') for x in held)) if held else '无',
            # 阈值要写"这条要求自己的口径",不许写全局默认 —— 否则说明里的话和实际判定不符
            'threshold': (f"命中其中至少 {int((req.get('match') or {}).get('n') or 1)} 项"
                          if (req.get('match') or {}).get('kind') == 'any_of'
                          else f'命中率 ≥ {COVERAGE:.0%}({len(needed)} 项中至少 '
                               f'{int(-(-COVERAGE * len(needed) // 1))} 项)'),
            'op': 'component_coverage',
            'state': state, 'why': why,
            'evidence': row_evidence,
            'sources': [dict(component_provenance(x, cv, cand['id'], iv, quality),
                             component=x.replace('skill_', '')) for x in held] or [],
            'missing': [x.replace('skill_', '') for x in needed if x not in cand['components']],
            # 否定证据:判「不满足」时必须说清"读完了什么、里面没有什么"
            'absence': ({} if held else {
                'checked': 'cv_facts.skills(整份简历抽取的技能项)',
                'n_skills': len(((cv.get(cand['id']) or {}).get('skills') or {}).get('value') or []),
                'not_found': [x.replace('skill_', '') for x in needed],
                'note': '抽取器把这份简历读了一遍,抽出的技能项里没有上面这几项;'
                        '抽取的每条引文都在门禁里校验过是原文子串。',
            }),
            'client_gate': None,
        })
    else:
        _why = req.get('blocked_by') or '属性/组件未建'
        if _why == '属性/组件未建':
            _why = '库里没有任何数据项能判这一条(不是候选人缺数据,是这条要求还没有对应的字段)'
        row.update({'data_item': '—', 'value': None, 'threshold': None, 'op': None,
                    'state': '不可判', 'why': _why,
                    'source': {'kind': '无', 'detail': '这条要求没有数据项', 'evidence': ''},
                    'client_gate': None})
    row['defects'] = [d['id'] for d in defects_for(
        dict(req, id=row['requirement'], _resolved=req.get('_resolved')), DEFECT_LIST)]
    return row


DEFECT_LIST: list = []


# ───────────────────────────────────────────────────── 给业务领导的话术(条款驱动)
def headline(cand: dict, rows: list, jd: str) -> tuple[str, str]:
    bad = [r for r in rows if r['state'] == '不满足']
    unk = [r for r in rows if r['state'] == '未知']
    na = [r for r in rows if r['state'] == '不可判']
    ok = [r for r in rows if r['state'] == '满足']
    judgeable = len([r for r in rows if r['state'] != '不可判'])

    if not bad:
        verdict = '不看条款就淘汰的理由不成立'
        line = (f"在 {jd} 的可判 {judgeable} 条要求上,他没有**不满足**的条款"
                f"(满足 {len(ok)} 条"
                + (f',另有 {len(unk)} 条我们没读到数据' if unk else '')
                + ')。')
        return verdict, line

    first = bad[0]
    gate = first.get('client_gate')
    verdict = f"卡在 {first['clause']}「{first['name']}」"
    if gate:
        line = (f"结论:**卡在客户原文第 {first['client_line']} 行的「{first['client_text']}」** ——"
                f"他的{gate}是 {first['value']},这条门槛是客户定的,不是我方判断。"
                f"要放宽只有一条路:请客户书面确认这一条可以松。")
    else:
        line = (f"结论:**卡在 {first['clause']}「{first['name']}」** ——"
                f"客户原文「{first['client_text']}」,要求 {first['threshold']},"
                f"他是「{first['value']}」。")
    line = line.rstrip('。')
    extra = []
    if len(bad) > 1:
        extra.append(f'还有 {len(bad) - 1} 条也不满足')
    if unk:
        extra.append(f'{len(unk)} 条我们没读到数据(标「未知」,不当作不合格)')
    if na:
        extra.append(f'{len(na)} 条这条 JD 没有数据项(标「不可判」,对所有人一样)')
    if extra:
        line += '。此外,' + ';'.join(extra)
    line += '。'
    if len(bad) == 1 and gate:
        line += f'**只要客户把这一条放宽,他就没有其他不满足了。**'
    return verdict, line


def fingerprint(cid: str, jd: str, cand: dict, cv: dict, hr: dict) -> str:
    """输入指纹:任何输入变了,指纹就变 —— 旧说明必须因此过期。"""
    h = hashlib.sha256()
    parts = [LINKS / f'{jd}.yaml', CATALOG, LIBRARY]
    for p in parts:
        if p.is_file():
            h.update(p.read_bytes())
    h.update(json.dumps(cv.get(cid) or {}, ensure_ascii=False, sort_keys=True).encode())
    h.update(json.dumps((hr or {}).get(cid) or {}, ensure_ascii=False, sort_keys=True).encode())
    ivf = CV_IV / f"{cid.replace('cand_', '')}.yaml"
    if ivf.is_file():
        h.update(ivf.read_bytes())
    h.update(json.dumps({k: cand.get(k) for k in
                         ('age', 'educationRank', 'yearsPlatform', 'major', 'gender')},
                        ensure_ascii=False, sort_keys=True).encode())
    h.update(json.dumps(sorted(cand.get('components') or []), ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def render(cid: str, jd: str, cand: dict, rows: list, fp: str, mode: str) -> tuple[str, dict]:
    import collections
    st = collections.Counter(r['state'] for r in rows)
    st.setdefault('复议', 0)
    verdict, line = headline(cand, rows, jd)
    # 显示姓名(编造·演示)。文件名与判定键仍是 candidate id —— 只换显示。
    name = _names.name_of(cid)
    short = cid.replace('cand_', '')

    doc = {
        'jd': jd, 'candidate': cid, 'name': name, 'short_id': short,
        'fingerprint': fp, 'scope': mode,
        'counts': {s: st[s] for s in STATES},
        'judgeable': len([r for r in rows if r['state'] != '不可判']),
        'verdict': verdict,
        'headline': line,
        'blocked_by': [{'clause': r['clause'], 'name': r['name'],
                        'client_text': r['client_text'], 'client_line': r['client_line'],
                        'value': r['value'], 'threshold': r['threshold'],
                        'source': r.get('source') or {'kind': '见 sources'},
                        'client_gate': r.get('client_gate')} for r in rows
                       if r['state'] == '不满足'],
        'absence_evidence': [{'clause': r['clause'], **r['absence']} for r in rows
                             if r.get('absence')],
        'unknown': [{'clause': r['clause'], 'name': r['name'],
                     'data_item': r['data_item'], 'why': r['why']} for r in rows
                    if r['state'] == '未知'],
        'not_judgeable': [{'clause': r['clause'], 'name': r['name'], 'why': r['why']}
                          for r in rows if r['state'] == '不可判'],
        'known_defects': sorted({d for r in rows for d in (r.get('defects') or [])}),
        'disputes': [{'clause': r['clause'], 'name': r['name'], **r['dispute']}
                     for r in rows if r.get('dispute')],
        'rows': rows,
    }

    md = [f'# 判定说明 · {name}', '',
          f'**岗位**:{jd} · **用途**:回答「这个人为什么没过」 · '
          f'**范围**:{ {"pick": "第 5 步选人", "shortlist": "第 3 步短名单"}.get(mode, mode) }', '',
          '## 一句话结论', '', f'> {line}', '',
          f'| 可判条款 | 满足 | **不满足** | 未知 | 不可判 |', '|---|---|---|---|---|',
          f"| {len([r for r in rows if r['state'] != '不可判'])} | {st['满足']} | "
          f"**{st['不满足']}** | {st['未知']} | {st['不可判']} |", '']

    # 能说明白的,"不满足"必须逐条落到客户原文
    bad = [r for r in rows if r['state'] == '不满足']
    if bad:
        md += ['## 不满足的条款(逐条可追)', '',
               '| 条款 | 客户原文 | 行号 | 数据项 | 他的值 | 要求 | 值来自 |',
               '|---|---|---|---|---|---|---|']
        for r in bad:
            src = r.get('source') or {}
            src_txt = src.get('kind', '?')
            if src.get('detail'):
                src_txt += f"({src['detail']})"
            ev = (src.get('evidence') or '')[:40]
            if ev:
                src_txt += f'「{ev}」'
            ab = r.get('absence') or {}
            if ab:
                src_txt = (f"整份简历抽到 {ab.get('n_skills', 0)} 项技能,"
                           f"其中没有 {'、'.join(ab.get('not_found') or [])}"
                           f"(抽取引文已过门禁)")
            thr = threshold_cn(r)
            md.append(f"| {r['clause']} {r['name']} | {r['client_text']} | "
                      f"{r.get('client_line')} | {r['data_item']} | {r['value']} | "
                      f"{thr} | {src_txt} |")
        md.append('')

    # 未知 ≠ 不满足,必须单独写
    unk = [r for r in rows if r['state'] == '未知']
    if unk:
        md += ['## 我们没读到的(标「未知」,**不当作不合格**)', '',
               '| 条款 | 数据项 | 为什么没读到 |', '|---|---|---|']
        for r in unk:
            md.append(f"| {r['clause']} {r['name']} | {r['data_item']} | {r['why']} |")
        md += ['', '> 这一栏的意思是「我们不知道」,不是「他不行」。'
               '要把它变成结论,得先去补数据(一面问、要证件、让客户补口径)。', '']

    na = [r for r in rows if r['state'] == '不可判']
    if na:
        md += ['## 这条 JD 判不了的(标「不可判」,对所有人一样)', '',
               '| 条款 | 为什么判不了 |', '|---|---|']
        for r in na:
            md.append(f"| {r['clause']} {r['name']} | {r['why']} |")
        md += ['', '> 「不可判」是**JD 或数据模型**的问题,不是候选人的问题。'
               '它不参与任何人的满足率计算,但它该被记下来,作为下一版 JD 要补的东西。', '']

    shaky = [(r, [d for d in DEFECT_LIST if d['id'] in (r.get('defects') or [])])
             for r in rows if r['state'] == '不满足' and r.get('defects')]
    if shaky:
        md += ['## 会被追问的地方(先自己知道)', '',
               '下面这些「不满足」受了**已知缺陷**影响,业务领导或候选人追问时,'
               '这几条最容易站不住。**先说清楚,别等被问。**', '',
               '| 条款 | 现在的判定 | 可能的问题 | 怎么答 |', '|---|---|---|---|']
        for r, ds in shaky:
            for d in ds:
                md.append(f"| {r['clause']} {r['name']} | {r['state']} | "
                          f"{d['title']}({d['id']}) | {d.get('direction', '')} —— "
                          f"修法是:{d.get('fix', '')} |")
        md += ['', '> 这几行的判定在缺陷修好之后**可能翻转**。'
               '如果这个人的去留就压在这几条上,建议等修完再定。', '']

    disp = [r for r in rows if r.get('dispute')]
    if disp:
        md += ['## 待裁冲突(本体与 LLM 判得不一样)', '',
               '四态里没有「复议」—— 这一栏的意思是**这一条我们不替你拍板**。'
               '上表保留的是本体的判定,下面是 LLM 说的另一半;两边引文都在,人一看就知道该信谁。', '',
               '| 条款 | 本体 | LLM | LLM 的理由 | LLM 的引文 |', '|---|---|---|---|---|']
        for r in disp:
            d = r['dispute']
            md.append(f"| {r['clause']} {r['name']} | {d['ontology']} | {d['llm']} | "
                      f"{str(d.get('llm_why') or '')[:40]} | "
                      f"「{str(d.get('llm_quote') or '')[:36]}」 |")
        md += ['', '> 裁决规则:A 数据值 / B 阈值 / D 不可判 → 跟本体;C 类(判定冲突)→ 人裁。'
               '**别让脚本替人裁。**', '']

    md += ['## 逐条明细', '', '| 条款 | 判定 | 证据强度 | 依据 | ⚠ 已知缺陷 |',
           '|---|---|---|---|---|']
    for r in rows:
        d = ', '.join(r.get('defects') or []) or '——'
        via = f" · {r['via']}" if r.get('via') else ''
        ev = r.get('evidence') or '—'
        md.append(f"| {r['clause']} {r['name']} | **{r['state']}** | {ev} | {r['why']}{via} | {d} |")

    aff = {d['id']: d for r in rows for d in
           [x for x in DEFECT_LIST if x['id'] in (r.get('defects') or [])]}
    if aff:
        md += ['', '## 这份说明适用的已知缺陷(必须一起说)', '',
               '下面这些缺陷会直接影响上表的结论。**拿着说明去见业务领导时,要主动交代,'
               '不要等人问。**', '',
               '| 编号 | 是什么 | 方向 | 影响哪几条 | 怎么修 |', '|---|---|---|---|---|']
        for d in sorted(aff.values(), key=lambda x: x['id']):
            rq = '、'.join(d.get('affects', {}).get('requirements') or []) or '—'
            md.append(f"| **{d['id']}** | {d['title']} | {d.get('direction', '')} | {rq} | "
                      f"{d.get('fix', '')} |")
        md += ['', '> 登记在 `work/talent/known_defects.yaml`。修完一条,把它从登记里删掉;'
               '门禁会核对登记里的条款是否还在被影响。', '']
    md += ['', '## 怎么复算这份说明', '', '```bash',
           'cd <repo>/backend && set -a && source ../.env; set +a',
           f'env -u PGPORT .venv/bin/python -m scripts.talent.explain_rejection '
           f'--jd {jd} --ids {cid}',
           f'env -u PGPORT .venv/bin/python -m scripts.talent.explain_rejection '
           f'--jd {jd} --verify      # 只查:输入有没有变、结论有没有漂',
           '```', '',
           f'**输入指纹** `{fp}` —— JD 原文、阈值、本体词表、简历事实、一面记录,'
           '任何一样改了,这个指纹就变,旧说明自动过期。', '']
    return '\n'.join(md), doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--ids', nargs='*', default=None)
    ap.add_argument('--interviewed', action='store_true', help='所有有访谈档案的人')
    ap.add_argument('--shortlist', action='store_true', help='第 3 步短名单 + 需复议的人')
    ap.add_argument('--verify', action='store_true', help='只校验已有说明是否过期/漂移')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    global DEFECT_LIST
    DEFECT_LIST = load_defects()
    mode, _src = interview_policy.mode_for(args.jd)
    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    # **不再并 cv_mock**(2026-11-23):那是「简历缺字段的模拟填充」,在没有一面数据时用的。
    # 现在一面把字段填满了,再叠一层 mock 就等于名单读真数据、判定说明读真+假,
    # 同一个人两份文件对不上(实测 24/40 人不一致:名单 10 满足,说明写成 12)。
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}
    cv, hr = load_facts()
    quality = json.loads((ROOT / 'work' / 'talent' / 'cv_quality.json')
                         .read_text(encoding='utf-8')) \
        if (ROOT / 'work' / 'talent' / 'cv_quality.json').is_file() else {}

    if args.ids:
        ids = [i if i.startswith('cand_') else f'cand_{i}' for i in args.ids]
    elif args.interviewed:
        ids = [f'cand_{p.stem}' for p in sorted(CV_IV.glob('*.yaml'))]
    elif args.shortlist:
        sl = yaml.safe_load((SHORTLIST / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
        ids = list(sl.get('kept') or [])
        ids += [b['candidate'] for b in
                ((sl.get('quality_gate') or {}).get('blocked_by_other_requirements') or [])]
    else:
        raise SystemExit('给 --ids / --interviewed / --shortlist 之一')
    ids = [i for i in ids if i in by_id]
    if args.limit:
        ids = ids[:args.limit]

    dest = OUT / args.jd
    dest.mkdir(parents=True, exist_ok=True)
    scope = 'shortlist' if args.shortlist else 'pick'

    if args.verify:
        bad = stale = 0
        for cid in ids:
            f = dest / f"{cid.replace('cand_', '')}.yaml"
            if not f.is_file():
                print(f'  [MISSING] {cid} —— 没有说明')
                bad += 1
                continue
            old = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            cand = by_id[cid]
            fp = fingerprint(cid, args.jd, cand, cv, hr)
            if old.get('fingerprint') != fp:
                print(f'  [STALE] {cid} —— 输入已变,旧说明过期')
                stale += 1
                continue
            rows = [explain_requirement(c, lib[c['requirement']], cand, atts, cv, hr,
                                        interview_answers(cid), quality.get(cid))
                    for c in link['citations']]
            live = {r['clause']: r['state'] for r in rows}
            oldm = {r['clause']: r['state'] for r in (old.get('rows') or [])}
            if live != oldm:
                diff = {k: (oldm.get(k), live.get(k)) for k in live if oldm.get(k) != live.get(k)}
                print(f'  [DRIFT] {cid} —— 结论漂了: {diff}')
                bad += 1
        print(f'\n校验完 {len(ids)} 份:过期 {stale} · 不一致/缺失 {bad}')
        return 0 if (bad == 0 and stale == 0) else 1

    index = []
    for n, cid in enumerate(ids, 1):
        cand = by_id[cid]
        iv = interview_answers(cid)
        rows = [explain_requirement(c, lib[c['requirement']], cand, atts, cv, hr, iv,
                                    quality.get(cid)) for c in link['citations']]
        fp = fingerprint(cid, args.jd, cand, cv, hr)
        # 组合 C:把 LLM 判定并进来(不可判硬保护、冲突标复议)
        try:
            from scripts.talent.pick_final import apply_combo_c
            onto_map = {c['requirement']: {'state': r['state'], 'why': r['why'],
                                           'citation': r['clause']} for c, r in zip(link['citations'], rows)}
            merged, conflicts = apply_combo_c(cid, args.jd, onto_map, link)
            for c, r in zip(link['citations'], rows):
                m = merged.get(c['requirement'])
                if not m:
                    continue
                if m['state'] == '复议':
                    # 四态里没有「复议」—— 它是流程状态,不是判定。
                    # 说明里保留本体的判定,同时把 LLM 的另一半摆出来,等人裁。
                    r['dispute'] = {'ontology': r['state'], 'llm': m['why'],
                                    'llm_quote': m.get('llm_quote'), 'llm_why': m.get('llm_why')}
                    r['via'] = '冲突待裁(说明保留本体判定)'
                elif m['state'] != r['state']:
                    r['state'] = m['state']
                    r['why'] = m['why']
                    r['via'] = m.get('来源')
            doc_conflicts = conflicts
        except Exception:
            doc_conflicts = []
        md, doc = render(cid, args.jd, cand, rows, fp, scope)
        base = dest / cid.replace('cand_', '')
        base.with_suffix('.md').write_text(md, encoding='utf-8')
        base.with_suffix('.yaml').write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding='utf-8')
        import collections
        st = collections.Counter(r['state'] for r in rows)
        st.setdefault('复议', 0)
        index.append((cid, doc['verdict'], st))
        print(f"  [{n}/{len(ids)}] {cid.replace('cand_', '')[:34]:34} "
              f"满足{st['满足']} 不满足{st['不满足']} 未知{st['未知']} "
              f"不可判{st['不可判']}" + (f" 复议{st['复议']}" if st['复议'] else ""))

    # 给业务领导看的第二层:这些人集体卡在哪、放开哪条能救几个
    import collections as C
    block_counter = C.Counter()
    gate_users = C.defaultdict(list)
    for cid, verdict, st in index:
        doc = yaml.safe_load((dest / f"{cid.replace('cand_', '')}.yaml").read_text(encoding='utf-8')) or {}
        for b in doc.get('blocked_by') or []:
            block_counter[b['clause'] + ' ' + str(b.get('name'))] += 1
            if b.get('client_gate'):
                gate_users[(b['clause'], b['client_gate'])].append(
                    (_names.name_of(cid), doc.get('headline', '')))

    md = [f'# 判定总览 · {args.jd}', '',
          f'{len(index)} 人。每人的「为什么」在各自的 md 里,**每条都落到 JD 原文行号与值来源**。', '',
          '## 这批人集体卡在哪', '',
          '| 条款 | 卡住的人次 |', '|---|---|']
    for k, v in block_counter.most_common():
        md.append(f'| {k} | **{v}** |')
    if gate_users:
        md += ['', '## 放开哪一条客户门槛,能救回谁', '',
               '> 这些条款是**客户原文**定的,不是我方判断。要放宽只有一条路:客户书面确认。', '',
               '| 客户门槛 | 卡住的人 |', '|---|---|']
        for (clause, gate), who in gate_users.items():
            md.append(f"| {clause}({gate}) | " + '、'.join(n for n, _ in who) + ' |')
    md += ['', '## 逐人', '',
           '| 候选人 | 一句话结论 | 满足 | 不满足 | 未知 | 不可判 |', '|---|---|---|---|---|---|']
    for cid, verdict, st in index:
        md.append(f"| [{_names.name_of(cid)}]({cid.replace('cand_', '')}.md) | {verdict} | "
                  f"{st['满足']} | {st['不满足']} | {st['未知']} | {st['不可判']} |")
    md += ['', '> 「未知」= 我们没读到数据,不当作不合格;'
           '「不可判」= 这条 JD 没有数据项 / 没给标准,对所有人一样。', '']
    (dest / '_index.md').write_text('\n'.join(md), encoding='utf-8')
    print(f'\n写出 {(dest / "_index.md").relative_to(ROOT)} 与 {len(index)} 份说明')
    return 0


if __name__ == '__main__':
    sys.exit(main())
