"""一份 JD 的**缺口**：40 格标准模板里，哪些能判、哪些等我方建议、哪些等客户给。

## 为什么必须有 jd 参数

缺口是**相对某一份 JD** 才成立的东西：同一个字段在品质经理是「客户原文」，
在专案工程师是「缺」。所以这里没有 "所有 JD 的缺口" 这种视图 ——
不传 `jd` 直接报错，而不是返回空表让人以为"没有缺口"。

## 两套口径，不许混

| source | 从哪来 | 状态数 | 回答的问题 |
|---|---|---|---|
| `draft` | `work/talent/jd_draft/<JD>.draft.json`（`draft_jd.py` 产物） | 7 | **定稿还差什么**：客户原文 / HR 侧 / 原文·空值 / 我方建议·待确认 / 待客户给 / 待客户确认 / 不适用 |
| `trial` | `work/talent/template_fill/fill.json`（`check_template_fill.py` 产物） | 5 | **客户稿覆盖到哪**：原文 / 原文·空值 / HR 侧 / 缺 / 不适用 |

差别不是"精度不同"，是**问题不同**：`trial` 只说客户写了没有，`draft` 才说定稿还缺谁点头。
所以返回值里带 `source`，界面上必须显示出来 —— 混在一起，数字一打架就没人再信。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Dict, List, Optional

ROOT = pathlib.Path(__file__).resolve().parents[2]
TALENT = ROOT / 'work' / 'talent'
DRAFT_DIR = TALENT / 'jd_draft'
FILL = TALENT / 'template_fill' / 'fill.json'
INPUTS = TALENT / 'jd_inputs'
TEMPLATE = TALENT / 'templates' / 'standard_jd_template.yaml'

#: 兜底默认（`jd_inputs/<JD>.yaml` 里没写 `default: true` 时用它）
FALLBACK_DEFAULT = '品质经理'

TRIAL_STATES = ('原文', '原文·空值', 'HR 侧', '缺', '不适用')
DRAFT_STATES = ('客户原文', 'HR 侧', '原文·空值', '我方建议·待确认',
                '待客户给', '待客户确认', '不适用')
#: 能进判定的状态 —— 其余一律「未知」/「不可判」，界面配色靠这个分档
JUDGING_STATES = {'客户原文', 'HR 侧', '原文'}


def known_jds() -> List[str]:
    """有哪些 JD：`jd_links/*.yaml`（引用复核过的客户 JD）∪ `uploads/*/`（Phase 1 上传件）。

    两处都算"有这份 JD"，因为它们都有正文（`jd_links/_source/<JD>.txt`）——
    缺口就是对着正文算的。**唯一真相是正文**，不是引用文件。
    """
    named = {p.stem for p in (TALENT / 'jd_links').glob('*.yaml')}
    ups = TALENT / 'uploads'
    if ups.is_dir():
        named |= {p.name for p in ups.iterdir() if p.is_dir()}
    return sorted(named)


def default_jd() -> str:
    """默认 JD：`jd_inputs/<JD>.yaml` 里 `default: true` 的那份。

    为什么不写死在代码里：换客户、换批次时默认份会变，改配置不该改代码。
    只有配置都没有时才退回常量，并且这个退回是**可见的**（返回值里带 source 说明）。
    """
    import yaml as _yaml

    for p in sorted(INPUTS.glob('*.yaml')):
        try:
            doc = _yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        except Exception:  # noqa: BLE001 —— 一份坏文件不该让整个清单打不开
            continue
        if doc.get('default') is True:
            return p.stem
    if FALLBACK_DEFAULT in known_jds():
        return FALLBACK_DEFAULT
    jds = known_jds()
    return jds[0] if jds else ''


def _tally(modes: List[str], states: tuple) -> Dict[str, int]:
    t = {k: 0 for k in states}
    for m in modes:
        t[m] = t.get(m, 0) + 1
    return t


def _from_draft(jd: str) -> Optional[Dict[str, Any]]:
    p = DRAFT_DIR / f'{jd}.draft.json'
    if not p.is_file():
        return None
    d = json.loads(p.read_text(encoding='utf-8'))
    rows = d.get('rows') or []
    fields = [{
        'code': r['code'], 'section': r['section'], 'label': r['label'],
        'level': r.get('level'), 'assessable': r.get('assessable'),
        'data_item': r.get('data_item'), 'value': r.get('value'),
        'state': r['state'], 'why': r.get('why') or '',
        'needs': r.get('needs') or '', 'evidence': r.get('evidence') or [],
        'in_judging': bool(r.get('in_judging')),
    } for r in rows]
    return {'fields': fields,
            'tally': dict(d.get('tally') or _tally([f['state'] for f in fields], DRAFT_STATES)),
            'source': 'draft', 'source_label': '定稿草稿（draft_jd.py）', 'note': ''}


def _from_fill(jd: str) -> Optional[Dict[str, Any]]:
    if not FILL.is_file():
        return None
    fd = json.loads(FILL.read_text(encoding='utf-8'))
    hit = next((j for j in fd.get('jds') or [] if j.get('jd') == jd), None)
    if hit is None:
        return None
    fields = [{
        'code': c['code'], 'section': c['section'], 'label': c['code'],
        'level': c.get('level'), 'assessable': c.get('assessable'),
        'data_item': c.get('data_item'), 'value': None,
        'state': c['state'], 'why': c.get('why') or '', 'needs': '', 'evidence': [],
        'in_judging': c.get('state') in JUDGING_STATES,
    } for c in hit.get('cells') or []]
    names = _template_labels()
    for f in fields:
        f['label'] = names.get(f['code'], f['code'])
    return {'fields': fields,
            'tally': _tally([f['state'] for f in fields], TRIAL_STATES),
            'source': 'trial', 'source_label': '客户稿覆盖度（check_template_fill.py）',
            'note': '这份 JD 还没做定稿草稿：下面的状态只说明客户稿写了没有，不说明定稿还缺谁点头。'}


def gap_for(jd: str) -> Dict[str, Any]:
    """某份 JD 的缺口。

    三档口径，优先级就是可信度顺序：
      ① draft —— 有定稿草稿（7 状态，含我方建议/待客户给）
      ② trial —— 5 份客户 JD 的试填结果（5 状态，只说客户稿写了没有）
      ③ text  —— Phase 1 上传件：只有原文，没有引用（4 状态）
    返回里的 `source` 必须显示出来 —— 三档混着读，数字一打架就没人再信。
    """
    if not jd:
        raise ValueError('jd 不能为空：缺口是相对某一份 JD 才成立的')
    if jd not in known_jds():
        raise KeyError(jd)

    got = _from_draft(jd) or _from_fill(jd)
    if got is None:
        if (TALENT / 'jd_links' / '_source' / f'{jd}.txt').is_file():
            g = text_gap_for(jd)
            g['note'] = ((g.get('note') or '') + ' 这份 JD 是上传进来的，还没有逐字引用。').strip()
            return g
        raise KeyError(jd)

    fields = got['fields']
    tally = got['tally']
    return {
        'jd': jd,
        'source': got['source'],
        'source_label': got['source_label'],
        'note': got['note'],
        'template_fields': len(fields),
        'tally': tally,
        'states': list(DRAFT_STATES if got['source'] == 'draft' else TRIAL_STATES),
        'in_judging': sum(1 for f in fields if f['in_judging']),
        'blockers': [{'code': f['code'], 'label': f['label'], 'why': f['why']}
                     for f in fields if f['state'] in ('待客户给', '缺')],
        'proposals': [{'code': f['code'], 'label': f['label'], 'value': f['value'],
                       'why': f['why'], 'needs': f['needs']}
                      for f in fields if f['state'] in ('我方建议·待确认', '待客户确认')],
        'fields': fields,
    }


def _template_labels() -> Dict[str, str]:
    """模板里的 code → 中文名（试填数据只存 code，界面要给人看得懂的）。"""
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(TEMPLATE.read_text(encoding='utf-8')) or {}
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, str] = {}
    for s in doc.get('sections') or []:
        for f in s.get('fields') or []:
            out[f['code']] = f.get('label_zh') or f['code']
    return out


def gap_summary(jd: str) -> Optional[Dict[str, Any]]:
    """侧栏一行小结用的瘦身版（不带 40 行表）。"""
    try:
        g = gap_for(jd)
    except (KeyError, ValueError):
        return None
    return {'jd': g['jd'], 'source': g['source'], 'tally': g['tally'],
            'in_judging': g['in_judging'], 'template_fields': g['template_fields'],
            'blockers': len(g['blockers']), 'proposals': len(g['proposals'])}


# ══════════════════════════════════════════════════════════════════════
# CV 侧：**一份具体的简历** 对着 CV 模板（26 字段）的缺口
#
# 为什么也要"一对一"：271 份简历的字段覆盖率不能代替"这一个人还缺什么"。
# 面试要问的就是这份缺口的清单 —— 拿全库统计去问一个人，等于问他已经写过的东西。
#
# 数据来源与可信度（都写进 basis，不许含糊）：
#   · cv_facts.json   —— 逐条事实带 quote 与 basis（stated / inferred / computed）
#   · cv_text/<id>.txt —— 客户 PDF 抽出的正文，**OCR 有噪声**（"居住地-广东东莞石碍镇"），
#     所以正则只认稳定的标题式字段，命中记「原文(正文)」，不命中记「缺」，绝不猜
#   · cv_interview/<id>.yaml —— 一面记录；有答案的项记「一面」，这是 CV 上没有的那部分
# ══════════════════════════════════════════════════════════════════════

CV_TEMPLATE = TALENT / 'templates' / 'standard_cv_template.yaml'
CV_FACTS = TALENT / 'cv_facts.json'
CV_TEXT = TALENT / 'cv_text'
CV_INTERVIEW = TALENT / 'cv_interview'
FAKE_NAMES = TALENT / 'fake_names.yaml'
CV_STATES = ('原文', '原文(脱敏)', '推断', '一面', '缺', '不适用')
CV_IN_JUDGING = {'原文', '原文(脱敏)', '推断', '一面'}


def cv_template_fields() -> List[Dict[str, Any]]:
    import yaml as _yaml
    doc = _yaml.safe_load(CV_TEMPLATE.read_text(encoding='utf-8')) or {}
    return [dict(f, section=s.get('code'), section_label=s.get('label_zh'))
            for s in doc.get('sections') or [] for f in s.get('fields') or []]


def _display_names() -> Dict[str, str]:
    import yaml as _yaml
    try:
        d = _yaml.safe_load(FAKE_NAMES.read_text(encoding='utf-8')) or {}
    except Exception:  # noqa: BLE001
        return {}
    names = d.get('names') or {}
    out: Dict[str, str] = {}
    if isinstance(names, list):          # 兼容 [{'id':..,'name':..}] 的写法
        for x in names:
            if isinstance(x, dict) and x.get('id'):
                out[str(x['id'])] = str(x.get('name') or x['id'])
        return out
    if isinstance(names, dict):
        for k, v in names.items():
            # fake_names.yaml 的值是 {name, basis, surname_kept, why} —— 只要 name
            out[str(k)] = str(v.get('name')) if isinstance(v, dict) else str(v)
    return out


def cv_list(limit: int = 400, search: str = '') -> List[Dict[str, Any]]:
    """可选简历清单（id + 展示名 + 来源 JD），按名字排序。"""
    facts = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    names = _display_names()
    out = []
    for cid in facts:
        name = names.get(cid) or cid
        jd = cid.split('_')[1] if cid.startswith('cand_') and len(cid.split('_')) > 1 else ''
        if search:
            needle = search.lower()
            if needle not in cid.lower() and needle not in str(name).lower() and needle not in jd.lower():
                continue
        out.append({'cv': cid, 'name': name, 'jd': jd,
                    'has_interview': (CV_INTERVIEW / f'{cid}.yaml').is_file()})
    out.sort(key=lambda x: (x['jd'], str(x['name'])))
    return out[:limit]


def _fact(facts: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    v = facts.get(key)
    return v if isinstance(v, dict) and 'basis' in v else None


def _interview_answers(cid: str) -> Dict[str, Any]:
    import yaml as _yaml
    p = CV_INTERVIEW / f'{cid}.yaml'
    if not p.is_file():
        return {}
    try:
        d = _yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    except Exception:  # noqa: BLE001
        return {}
    return d.get('answers') or {}


def cv_gap_for(cv: str, jd: str = '') -> Dict[str, Any]:
    """一份简历对着 CV 模板（26 字段）的缺口。`cv` 必填，理由同 JD 侧。"""
    import re

    if not cv:
        raise ValueError('cv 不能为空：缺口是相对某一份简历才成立的')
    facts_all = json.loads(CV_FACTS.read_text(encoding='utf-8'))
    if cv not in facts_all:
        raise KeyError(cv)
    facts = facts_all[cv]
    text_p = CV_TEXT / f'{cv}.txt'
    text = text_p.read_text(encoding='utf-8') if text_p.is_file() else ''
    answers = _interview_answers(cv)
    names = _display_names()

    def basis_state(f: Optional[Dict[str, Any]]) -> str:
        b = (f or {}).get('basis')
        return {'stated': '原文', 'inferred': '推断',
                'computed': '推断', 'computed_unverified': '推断'}.get(b, '原文')

    def rx(pattern: str) -> Optional[str]:
        m = re.search(pattern, text)
        return m.group(0).strip() if m else None

    def rx_group(pattern: str) -> Optional[str]:
        m = re.search(pattern, text)
        return (m.group(1) or '').strip() if m else None

    # 每条规则返回 (state, value, why/basis 说明)
    def resolve(code: str, item: Optional[str], label: str) -> Dict[str, Any]:
        # ① 一面答案优先（CV 上没有、一面问到的）
        for k, v in answers.items():
            if isinstance(v, dict) and item and (v.get('data_item') == item):
                return {'state': '一面', 'value': v.get('value'),
                        'why': f'一面记录：{str(v.get("quote") or v.get("value"))[:40]}'}
        # ② 结构化事实
        fact_map = {
            'F.GENDER': 'gender', 'F.AGE': 'age', 'F.EDU_LEVEL': 'education_rank',
            'F.EDU_MAJOR': 'major', 'F.EDU_FULLTIME': 'full_time',
            'F.EXP_YEARS': 'years', 'F.SKILL': 'skills',
        }
        fk = fact_map.get(code)
        if fk:
            f = _fact(facts, fk)
            if f and f.get('value') not in (None, '', [], {}):
                val = f['value']
                if fk == 'skills' and isinstance(val, list):
                    val = '、'.join(str(x.get('name')) for x in val[:8] if isinstance(x, dict))
                if fk == 'education_rank':
                    val = {1: '初中', 2: '高中/中专', 3: '大专', 4: '本科', 5: '硕士'}.get(
                        int(val) if str(val).isdigit() else -1, val)
                why = f.get('quote') or ''
                return {'state': basis_state(f), 'value': val, 'why': why[:60]}
            return {'state': '缺', 'value': None, 'why': f'简历正文没读到{fk}（OCR 噪声大，不做猜测）'}
        # ③ 正文里的标题式字段（稳定的才认）
        if code == 'F.CV_FULL_NAME':
            return {'state': '原文', 'value': names.get(cv, cv),
                    'why': '展示名为本仓库伪造（basis=fabricated），简历原件姓名已脱敏'}
        if code == 'F.CV_PHONE':
            v = rx(r'\d{3}\*{4}\d{4}')
            return ({'state': '原文(脱敏)', 'value': v, 'why': '简历里电话中间四位被平台打码'}
                    if v else {'state': '缺', 'value': None, 'why': '正文没有可识别的电话'})
        if code == 'F.CV_EMAIL':
            v = rx(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
            return ({'state': '原文', 'value': v, 'why': ''} if v
                    else {'state': '缺', 'value': None, 'why': '正文里的邮箱是抽取残渣（如「eee @eee」），不认'})
        if code == 'F.WORK_LOCATION':
            v = rx_group(r'居住地[-:：]\s*([^\s|]+)')
            return ({'state': '原文', 'value': v, 'why': '正文「居住地」栏'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有「居住地」栏'})
        if code == 'F.JOB_TITLE':
            v = rx_group(r'应聘职位[:：]\s*([^\s|]+)')
            return ({'state': '原文', 'value': v, 'why': '正文「应聘职位」栏'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有「应聘职位」栏'})
        if code == 'F.SALARY':
            v = rx_group(r'(\d+)[-_](\d+)K')
            if v:
                return {'state': '原文', 'value': f'{v}-{rx_group(r"(\d+)[-_](\d+)K")}K',
                        'why': '投递文件名里的薪资区间（平台填的）'}
            v2 = rx_group(r'期望薪资[:：]\s*([^\s|]+)')
            return ({'state': '原文', 'value': v2, 'why': '正文「期望薪资」栏'} if v2
                    else {'state': '缺', 'value': None, 'why': '简历没写期望薪资'})
        if code == 'F.AVAILABILITY':
            if '随时到岗' in text or '到岗' in text and '离职' in text:
                return {'state': '原文', 'value': '随时到岗（0 周）', 'why': '正文「离职-随时到岗」'}
            return {'state': '缺', 'value': None, 'why': '正文没写离职状态/到岗时间'}
        if code == 'F.CV_INSTITUTION':
            v = rx(r'[\u4e00-\u9fa5]{2,10}(大学|学院|学校)')
            return ({'state': '原文', 'value': v, 'why': '正文院校名'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有可识别的院校名'})
        if code == 'F.CV_EMPLOYER':
            v = rx(r'[\u4e00-\u9fa5]{2,12}(有限公司|股份有限公司)')
            return ({'state': '原文', 'value': v, 'why': '正文公司名'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有可识别的公司名'})
        if code == 'F.CERTIFICATION':
            v = rx(r'(内审员|报关员|叉车|电工证|ISO ?9001|IATF|会计证)')
            return ({'state': '原文', 'value': v, 'why': '正文提到该证书'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有证书字样'})
        if code == 'F.LANGUAGE_LEVEL':
            v = rx(r'(英语|英文)[^。\n]{0,12}')
            return ({'state': '原文', 'value': v, 'why': '正文提到外语（未分档，分档要一面）'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没提到外语'})
        if code == 'F.CV_TRAININGS':
            v = rx(r'培训[^。\n]{0,14}')
            return ({'state': '原文', 'value': v, 'why': '正文提到培训'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有培训记录'})
        if code == 'F.CV_PROJECTS':
            v = rx(r'项目[^。\n]{0,14}')
            return ({'state': '原文', 'value': v, 'why': '正文提到项目'} if v
                    else {'state': '缺', 'value': None, 'why': '正文没有项目记录'})
        # ④ 需要逐段解析才能算的（简历正文被 OCR 打散，现在算不出来）
        if code in ('F.YEARS_COMPUTED', 'F.AVG_TENURE', 'F.RECENT_SEGMENTS'):
            return {'state': '缺', 'value': None,
                    'why': '要逐段起止才能算；简历正文被 OCR 打散，逐段不可靠 → 一面问或结构化重抽'}
        if code == 'F.COMMUTE':
            return {'state': '缺', 'value': None, 'why': '简历永远不写通勤意愿，必须一面问（A.4 闸门）'}
        if code == 'F.CLEARANCE':
            return {'state': '缺', 'value': None, 'why': '背调项：简历与一面都不该问，入职前核'}
        if code == 'F.EXP_DOMAIN':
            return {'state': '缺', 'value': None, 'why': '职能域简历常读不出 → 一面问'}
        return {'state': '缺', 'value': None, 'why': '模板里这个字段没有抽取规则（要补）'}

    fields = []
    for f in cv_template_fields():
        code = f['code']
        r = resolve(code, f.get('data_item'), f.get('label_zh') or '')
        fields.append({'code': code, 'section': f['section'], 'label': f.get('label_zh'),
                       'level': f.get('requirement_level'), 'data_item': f.get('data_item'),
                       'state': r['state'], 'value': r['value'], 'why': r['why'],
                       'in_judging': r['state'] in CV_IN_JUDGING})

    tally = {k: 0 for k in CV_STATES}
    for x in fields:
        tally[x['state']] = tally.get(x['state'], 0) + 1
    return {
        'cv': cv, 'jd': jd, 'name': names.get(cv, cv),
        'disclosure': '展示名为本仓库伪造（basis=fabricated）；简历原件姓名已脱敏',
        'template_fields': len(fields), 'tally': tally, 'states': list(CV_STATES),
        'in_judging': sum(1 for x in fields if x['in_judging']),
        'has_interview': (CV_INTERVIEW / f'{cv}.yaml').is_file(),
        'gaps': [{'code': x['code'], 'label': x['label'], 'why': x['why']}
                 for x in fields if x['state'] == '缺'],
        'fields': fields,
    }


# ══════════════════════════════════════════════════════════════════════
# Phase 1 · 文本档缺口：**只有客户原文**，没有引用、没有 LLM
#
# 上传一份 JD 后立刻要看到"这份稿填满了几格"。可 40 格里有 18 格原本依赖
# `jd_links` 的逐字引用（年龄/学历/年限/技能/语言/薪资/到岗/通勤/背调…），
# 这一档先用文本规则兜一遍：
#   · 兜到 → 记「原文」，并标 `needs_citation: true`（引用抽完后可能变成「缺」）
#   · 兜不到 → 记「缺」，**不写「不满足」**，也不给建议值（那是 Phase 2 的事）
# 状态只有四种：原文 / 原文·空值 / 缺 / 不适用。
# ══════════════════════════════════════════════════════════════════════

TEXT_STATES = ('原文', '原文·空值', '缺', '不适用')


ROLE_LABEL = {'staff': '员工岗', 'manager': '经理岗'}


def _clean(v: Optional[str]) -> str:
    """抽平表格的值里常带 \\x07（单元格分隔）与换行 —— 显示前清掉；只剩分隔符就等同空值。"""
    if v is None:
        return ''
    return re.sub(r'[\x00-\x1f\x7f]', '', str(v)).strip()


def _text_rx(text: str, *pats: str) -> Optional[str]:
    for pat in pats:
        m = re.search(pat, text, re.M)
        if m:
            return (m.group(0) or '').strip()
    return None


def _fallback_field(code: str, text: str) -> Optional[tuple]:
    """靠引用才稳定的那些字段，先用文本兜一遍。返回 (value, why) 或 None。"""
    if code == 'F.AGE':
        v = _text_rx(text, r'年龄[\x07:：\s]*([0-9]{2})\s*[~\-—至]\s*([0-9]{2})',
                     r'([0-9]{2})\s*[~\-—至]\s*([0-9]{2})\s*岁')
        return (v, '原文（文本兜底：年龄栏）') if v else None
    if code == 'F.GENDER':
        v = _text_rx(text, r'性别[\x07:：\s]*(男女不限|男|女)')
        return (v, '原文（文本兜底：性别栏）') if v else None
    if code == 'F.EDU_LEVEL':
        v = _text_rx(text, r'(博士|硕士|本科|大专|中专|高中)[及以]{0,2}以上')
        return (v, '原文（文本兜底：学历行）') if v else None
    if code == 'F.EDU_MAJOR':
        v = _text_rx(text, r'专业[\x07:：\s]*([^\x07\n；;]{2,60})',
                     r'([\u4e00-\u9fa5/、]{2,30}等?[\u4e00-\u9fa5]{0,6}类专业)')
        return (v, '原文（文本兜底：专业栏）') if v else None
    if code == 'F.EDU_FULLTIME':
        return ('全日制', '原文（文本兜底：出现「全日制」）') if '全日制' in text else None
    if code == 'F.EXP_YEARS':
        v = _text_rx(text, r'([0-9]+)\s*年以上[^\x07\n。；]{0,20}经验',
                     r'([0-9]+)\s*年[及以]{0,2}以上[^\x07\n。；]{0,20}')
        return (v, '原文（文本兜底：年限行）') if v else None
    if code == 'F.EXP_DOMAIN':
        m = re.search(r'([0-9]+)\s*年以上\s*([\u4e00-\u9fa5]{2,12})\s*(?:工作)?经验', text)
        return (m.group(2), '原文（文本兜底：年限行里的领域）') if m else None
    if code == 'F.SKILL':
        from scripts.talent.jd_parse import requirements_from_text
        parsed = requirements_from_text('JD', text)
        skills = parsed.get('skills') or []
        return ('、'.join(skills), '原文（文本兜底：技能词命中）') if skills else None
    if code == 'F.CERTIFICATION':
        v = _text_rx(text, r'(内审员|报关员|叉车证?|电工证|会计证|ISO\s?9001|IATF\s?16949)')
        return (v, '原文（文本兜底：出现证照字样）') if v else None
    if code == 'F.LANGUAGE_LEVEL':
        v = _text_rx(text, r'(英语|英文)[^\x07\n。；]{0,20}')
        return (v, '原文（文本兜底：外语行；分档要一面）') if v else None
    if code == 'F.COMPETENCY':
        v = _text_rx(text, r'(沟通[^\x07\n。；]{0,10}(能力|协调)|协调能力|能吃苦|抗压)')
        return (v, '原文（文本兜底：素质类字样；不可判）') if v else None
    if code == 'F.AVAILABILITY':
        v = _text_rx(text, r'随时到岗|到岗时间[\x07:：\s]*([^\x07\n。；]{1,12})')
        return (v, '原文（文本兜底：到岗字样）') if v else None
    if code == 'F.SALARY':
        v = _text_rx(text, r'([0-9]{1,2}\s*[-~]\s*[0-9]{1,2}\s*[Kk千])', r'薪资[\x07:：\s]*([^\x07\n。；]{1,20})')
        return (v, '原文（文本兜底：薪资字样；预算上限要客户确认）') if v else None
    if code == 'F.CLEARANCE':
        return ('无犯罪记录', '原文（文本兜底：出现无犯罪要求）') if '无犯罪' in text else None
    if code == 'F.JD_CONFIDENTIALITY':
        return ('保密', '原文（文本兜底：出现保密要求）') if '保密' in text else None
    return None


def text_gap_for(jd: str, text: str = '') -> Dict[str, Any]:
    """Phase 1：只看客户原文的缺口（四种状态，标出哪几格靠文本兜底）。"""
    from scripts.talent.check_template_fill import (
        PROBES, TABLE_HEADER_WORDS, _table_body, _value_after,
    )

    def _norm(x: str) -> str:  # 去空白与控制字符后比较（表格抽平件里全是 \x07）
        return re.sub(r'[\x00-\x1f\x7f]', '', str(x)).replace('\u3000', '').replace(' ', '')

    if not jd:
        raise ValueError('jd 不能为空：缺口是相对某一份 JD 才成立的')
    if not text:
        src = TALENT / 'jd_links' / '_source' / f'{jd}.txt'
        if not src.is_file():
            raise KeyError(jd)
        text = src.read_text(encoding='utf-8')
    import yaml as _yaml

    links_p = TALENT / 'jd_links' / f'{jd}.yaml'
    links: Dict[str, Any] = {}
    if links_p.is_file():
        links = _yaml.safe_load(links_p.read_text(encoding='utf-8')) or {}
    ex_p = TALENT / 'jd_extracted' / f'{jd}.yaml'
    if not links and ex_p.is_file():
        # Phase 1 上传件：没有引用文件，部门/岗位类别取自抽取件
        ex = _yaml.safe_load(ex_p.read_text(encoding='utf-8')) or {}
        from services.talent_jd_ingest import _role_type

        links = {'department': ex.get('department') or '',
                 'role_type': _role_type(ex.get('supervises')),
                 'role_basis': f"抽取件：原文「直接下属」= {ex.get('supervises')!r}"}
    role_type = (links.get('role_type') or '').strip()
    labels = _template_labels()

    fields: List[Dict[str, Any]] = []
    for f in cv_template_fields.__wrapped__() if hasattr(cv_template_fields, '__wrapped__') else _jd_template_fields():
        code = f['code']
        probe = PROBES.get(code) or {}
        state, why = '缺', ''
        value = None
        needs_citation = False

        # 条件字段不触发
        cond = f.get('conditional_on') or ''
        if f.get('requirement_level') == 'conditional' and cond.startswith('岗位类别='):
            need_mgr = '经理岗' in cond
            if role_type and ((need_mgr and '经理' not in role_type) or
                              (not need_mgr and '经理' in role_type)):
                state, why = '不适用', f'条件字段（{cond}），本 JD 判为 {role_type}'

        if state != '不适用':
            if probe.get('reqs'):
                fb = _fallback_field(code, text)
                if fb:
                    value, why = fb
                    state, needs_citation = '原文', True
                else:
                    why = '客户原文没读到；且未抽取引用，可能漏'
                    needs_citation = True
            else:
                lab = probe.get('label')
                if lab:
                    if lab in text:
                        v = _value_after(text, lab)
                        if v:
                            value, why, state = v, f'原文「{lab}：{v[:20]}」', '原文'
                        else:
                            why, state = f'原文有「{lab}」栏但值是空的', '原文·空值'
                    else:
                        why = f'原文没有「{lab}」这一栏'
                elif probe.get('derive') == 'role_type':
                    if role_type:
                        value = ROLE_LABEL.get(role_type, role_type)
                        why, state = f'原文「直接下属」栏 → {value}', '原文'
                    else:
                        why = '岗位类别未定（原文没读到「直接下属」栏）'
                elif probe.get('derive') == 'department':
                    dept = (links.get('department') or '').strip()
                    if dept:
                        value, why, state = dept, f'原文「隶属部门」栏 = {dept}', '原文'
                    else:
                        why, state = '原文「隶属部门」栏为空', '原文·空值'
                elif probe.get('derive') == 'title':
                    value, why, state = jd, '取文件名/抬头', '原文'
                else:
                    hit = False
                    for kw in probe.get('markers') or []:
                        if kw not in text:
                            continue
                        hit = True
                        if probe.get('table'):
                            body = [x for x in _table_body(text, kw) if len(x) > 4]
                            if body:
                                value, why, state = body[0][:40], f'原文「{kw}」表体 {len(body)} 行', '原文'
                            else:
                                why, state = f'原文有「{kw}」表头，表体是空的', '原文·空值'
                        else:
                            # 小标题类：引它**下面**那行内容。
                            # 引标题本身（"原文含「岗位职责」：岗位职责"）等于没引。
                            lines_l = text.splitlines()
                            idx = next((i for i, ln in enumerate(lines_l) if kw in ln), None)
                            nxt = ''
                            if idx is not None:
                                for ln2 in lines_l[idx + 1:idx + 4]:
                                    t2 = ln2.strip()
                                    if t2 and not re.match(r'^[（(]\s*\d+\s*[-~]\s*\d+', t2) \
                                            and len(_norm(t2)) > 4:
                                        nxt = t2
                                        break
                            if nxt:
                                value, why, state = nxt[:40], f'原文「{kw}」下一行：{nxt[:30]}', '原文'
                            elif idx is not None:
                                why, state = f'原文只有「{kw}」这个小标题，没有内容行', '原文·空值'
                            else:
                                why = f'客户原文没有「{kw}」这一节'
                        break
                    if not hit:
                        why = '客户原文没有这一项'

        value = _clean(value) if isinstance(value, str) else value
        if state == '原文' and (value in (None, '', [])):
            state, value = '原文·空值', None
            why = why or '原文有这一栏但值是空的'

        fields.append({
            'code': code, 'section': f['section'], 'label': labels.get(code, code),
            'level': f.get('requirement_level'), 'assessable': f.get('assessable'),
            'data_item': f.get('data_item'), 'value': value, 'state': state,
            'why': why, 'needs': ('客户补' if state in ('缺', '原文·空值') else ''),
            'evidence': [], 'in_judging': state == '原文',
            'needs_citation': needs_citation,
        })

    tally = {k: 0 for k in TEXT_STATES}
    for x in fields:
        tally[x['state']] = tally.get(x['state'], 0) + 1
    return {
        'jd': jd, 'source': 'text',
        'source_label': '仅客户原文（未抽取引用；不做推断，不填我方建议）',
        'note': ('18 个字段原本依赖逐字引用；这一档先用文本规则兜底，'
                 '兜到的记「原文」并标注，兜不到的记「缺」。'),
        'template_fields': len(fields), 'tally': tally, 'states': list(TEXT_STATES),
        'in_judging': sum(1 for x in fields if x['in_judging']),
        'blockers': [{'code': x['code'], 'label': x['label'], 'why': x['why']}
                     for x in fields if x['state'] in ('缺', '原文·空值')],
        'proposals': [],
        'fields': fields,
    }


def _jd_template_fields() -> List[Dict[str, Any]]:
    """JD 模板的 26/40 字段（带 section）。"""
    import yaml as _yaml
    doc = _yaml.safe_load(TEMPLATE.read_text(encoding='utf-8')) or {}
    return [dict(f, section=s.get('code'), section_label=s.get('label_zh'))
            for s in doc.get('sections') or [] for f in s.get('fields') or []]
