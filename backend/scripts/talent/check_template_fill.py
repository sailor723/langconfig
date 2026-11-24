#!/usr/bin/env python3
"""拿 5 份客户 JD 去**试填**公司标准模板（40 字段）—— 看这套模板在真实客户稿上够不够用。

## 这一步要回答什么

标准模板只在纸面上成立不算数。真正的问题是：

  · 客户那 5 份 JD 里，40 个字段**实际能填出几个**？剩下的是"客户没写"还是"我们模板多要了"？
  · 哪些字段 **5 份全空** —— 这些正是标准模板的价值（客户从来不写，但我们判定要用）；
  · 哪些字段**客户给了标签却没给值**（例如「直接上司」后面是空白）—— 那不是"没这项要求"，
    是"原文写了但是空的"，补的优先级最高；
  · HR 侧那 5 条闸门（到岗/薪资/平均在职/近5年/通勤），5 份 JD 里有几份有数据？

## 判定口径（四种，不许合并）

| 状态 | 含义 |
|---|---|
| `原文` | 客户 JD 里**读得到**（有引用，或原文里有对应栏目且不为空） |
| `原文·空值` | 原文**有这一栏但值是空的**（如「直接上司＿＿」）→ 最该补 |
| `HR 侧` | 客户 JD 没有，由我方 HR 提出（`origin: hr` 的引用） |
| `缺` | 两边都没有 → 定稿时我方才填，或标「不可判」 |
| `不适用` | 条件字段在本岗位类别下不触发（经理岗字段用在员工岗上） |

**不合并的理由**：「原文·空值」与「缺」的处置完全不同 —— 前者是客户漏填，后者是我方要补的
标准项；把两种都写成"没数据"，补的时候就会漏掉客户已经划了框的那一格。

## 输入

    work/talent/templates/standard_jd_template.yaml   标准模板（40 字段）
    work/talent/jd_links/<JD>.yaml                    客户 JD → 原子要求（含逐字引用）
    work/talent/jd_links/_source/<JD>.txt             客户原文（textutil 抽平的 Word 表）

## 产物

    work/talent/template_fill/<JD>.md      每份 JD 的试填表（逐字段：状态 + 依据）
    work/talent/template_fill/_index.md    5 份汇总 + 5/5 全缺清单 + 标签空值清单
    work/talent/template_fill/fill.json    同一份数据给界面/门禁用

用法:
    python -m scripts.talent.check_template_fill            # 重新试填
    python -m scripts.talent.check_template_fill --check     # 只校验是否最新（门禁用）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
TEMPLATE = TALENT / 'templates' / 'standard_jd_template.yaml'
LINKS = TALENT / 'jd_links'
OUT = TALENT / 'template_fill'
JSON = OUT / 'fill.json'
INDEX = OUT / '_index.md'

S_ORIG, S_ORIG_EMPTY, S_HR, S_MISS, S_NA = '原文', '原文·空值', 'HR 侧', '缺', '不适用'

# 字段 → 怎么在客户原文里找。
#   reqs      : 客户 JD 的某条要求直接支撑它（走 jd_links 的引用）
#   markers   : 原文里出现这些词（说明客户写了这一栏）
#   label     : 有栏目名但值是空 → 判「原文·空值」（"直接上司＿＿"）
#   derive    : 由 jd_links 的结构字段推（role_type / department）
#   hr_only   : 客户 JD 不会有，只能由我方 HR 提（有 hr 引用才算有）
PROBES: dict[str, dict] = {
    'F.JOB_TITLE': {'derive': 'title'},
    'F.MGMT_CATEGORY': {'derive': 'role_type'},
    'F.DEPARTMENT': {'derive': 'department'},
    'F.REPORTS_TO': {'label': '直接上司'},
    'F.SUPERVISES': {'label': '直接下属'},
    'F.JD_JOB_GRADE': {'markers': ['职级', '岗位等级']},
    'F.JD_JOB_PURPOSE': {'markers': ['岗位目的', '职务目的', '工作目标', '岗位使命']},
    'F.JD_SUCCESS_CRITERIA': {'markers': ['KPI', '考核指标', '绩效指标', '成功指标']},
    'F.AGE': {'reqs': ['REQ-A-AGE-RANGE']},
    'F.GENDER': {'reqs': ['REQ-A-GENDER']},
    'F.EDU_LEVEL': {'reqs': ['REQ-B-EDU-LEVEL']},
    'F.EDU_MAJOR': {'reqs': ['REQ-B-MAJOR']},
    'F.EDU_FULLTIME': {'reqs': ['REQ-B-FULL-TIME']},
    'F.EXP_YEARS': {'reqs': ['REQ-C-YEARS-DOMAIN']},
    'F.EXP_DOMAIN': {'reqs': ['REQ-C-YEARS-DOMAIN', 'REQ-D-HARNESS-DOMAIN']},
    'F.SKILL': {'reqs': ['REQ-D-.*']},
    'F.CERTIFICATION': {'reqs': ['REQ-F-.*']},
    'F.LANGUAGE_LEVEL': {'reqs': ['REQ-H-LANG-EN']},
    'F.COMPETENCY': {'reqs': ['REQ-E-.*']},
    'F.JD_DUTY_ITEMS': {'markers': ['岗位职责', '工作职责', '主要职责', '职责范围', '工作内容',
                                    '工作事项', '工作任务', '工作范围']},
    'F.DECISION_AUTHORITY': {'markers': ['决策权限', '审批权限', '签核']},
    'F.BUDGET_OWNERSHIP': {'markers': ['预算', '成本责任']},
    'F.CROSS_DEPT': {'markers': ['跨部门', '接口']},
    # 这两项在客户稿里常是**表头写了、表体空着**：算「原文·空值」而不是「原文」
    'F.JD_ACTIVITY_TEXT': {'markers': ['事务表述', '作业明细', '工作内容明细'], 'table': True},
    'F.JD_ACTIVITY_FREQ': {'markers': ['频次', '事务表述', '作业明细'], 'table': True},
    'F.SHIFT': {'markers': ['班制', '两班', '三班', '常白班', '轮班']},
    'F.JD_ENVIRONMENT': {'markers': ['工作环境', '噪音', '粉尘', '温度']},
    'F.JD_PHYSICAL_DEMAND': {'markers': ['体力', '站立', '搬运']},
    'F.JD_PPE': {'markers': ['劳保', '防护用品', '护目镜']},
    'F.JD_WORK_LOCATION': {'markers': ['工作地点', '上班地点', '厂区']},
    'F.JD_HEADCOUNT': {'markers': ['编制', '招聘人数', '需求人数']},
    'F.AVAILABILITY': {'reqs': ['REQ-HR-NOTICE'], 'hr_only': True},
    'F.SALARY': {'reqs': ['REQ-HR-SALARY'], 'hr_only': True},
    'F.AVG_TENURE': {'reqs': ['REQ-HR-TENURE'], 'hr_only': True},
    'F.RECENT_SEGMENTS': {'reqs': ['REQ-HR-STABILITY'], 'hr_only': True},
    'F.COMMUTE': {'reqs': ['REQ-HR-COMMUTE'], 'hr_only': True},
    'F.JD_HIRING_REASON': {'markers': ['招聘原因', '新增职位', '替补']},
    'F.CLEARANCE': {'reqs': ['REQ-G-NO-CRIMINAL-RECORD']},
    'F.JD_CONFIDENTIALITY': {'reqs': ['REQ-G-CONFIDENTIALITY']},
    'F.JD_CONTRACT_TYPE': {'markers': ['用工类型', '合同类型', '全职']},
}

# 条件字段不触发的判据：本仓库 5 份 JD 全是员工岗（role_type=staff）
NA_RULES = {'岗位类别=经理岗': ('manager',)}


def load_template() -> list[dict]:
    doc = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8')) or {}
    rows = []
    for s in doc.get('sections') or []:
        for f in s.get('fields') or []:
            rows.append(dict(f, _sec=s.get('code'), _sec_label=s.get('label_zh')))
    return rows


def _value_after(text: str, label: str) -> str:
    """「直接上司＿＿直接下属」这种抽平的表格行：取标签之后、下一个标签之前的文字。"""
    i = text.find(label)
    if i < 0:
        return ''
    rest = text[i + len(label):]
    # 抬头行里下一个标签通常是另一栏；在 12 字以内找切点，找不到就取到行尾
    cut = re.search(r'(职务名称|隶属部门|直接上司|直接下属|任职资格|岗位职责|事务表述)',
                    rest[:40])
    seg = rest[:cut.start()] if cut else rest.splitlines()[0] if rest else ''
    return seg.strip(' 　:：\t')


TABLE_HEADER_WORDS = {'序号', '内容', '每日', '每周', '每月', '偶发', '备注', '频次', '时长',
                      '关联表单', '操作标准流程', 'AI可否替代', '其它事项', '类别', '项目',
                      '事务名称', '工作事项'}


def _table_body(source: str, marker: str, limit: int = 24) -> list[str]:
    """表头之后到下一节之前的非空行（滤掉表头词）。用来判断"表头写了、表体空着"。"""
    i = source.find(marker)
    if i < 0:
        return []
    tail = source[i + len(marker):].splitlines()[1:1 + limit]
    body = []
    for ln in tail:
        t = ln.strip()
        if not t or t in TABLE_HEADER_WORDS:
            continue
        if re.fullmatch(r'[（(].*[)）]', t) and len(t) < 12:   # 如「（5-8条）」
            continue
        body.append(t)
    return body


def classify(row: dict, links: dict, source: str, cits: list[dict]) -> tuple[str, str]:
    """返回 (状态, 依据)。依据要能追到引用 id / 原文行 / 结构字段，一句话说不清就是没依据。"""
    code = row['code']
    probe = PROBES.get(code)
    lvl = row.get('requirement_level')
    role = (links.get('role_type') or '').strip()

    # 条件字段：本岗位类别不触发 → 不适用
    cond = row.get('conditional_on') or ''
    if lvl == 'conditional' and cond in NA_RULES and role not in NA_RULES[cond]:
        return S_NA, f'条件字段（{cond}），本 JD 是 {role or "未知"}'

    if probe is None:
        return S_MISS, '模板里这个字段没有试填规则（要补 PROBES）'

    # ① 客户/HR 引用直接支撑
    pats = probe.get('reqs') or []
    hit_client, hit_hr = [], []
    for c in cits:
        rid = c.get('requirement') or ''
        if not any(re.fullmatch(p, rid) for p in pats):
            continue
        (hit_hr if (c.get('origin') == 'hr') else hit_client).append(c)
    if hit_client:
        c = hit_client[0]
        more = f' 等 {len(hit_client)} 条' if len(hit_client) > 1 else ''
        return S_ORIG, f'{c.get("id")}「{(c.get("verbatim") or "")[:26]}」{more}'
    if hit_hr:
        c = hit_hr[0]
        return S_HR, f'{c.get("id")}（HR 提出）「{(c.get("verbatim") or "")[:26]}」'
    if probe.get('hr_only'):
        # 客户稿里没有；先看原文有没有写（客户偶尔会写薪资区间）
        for kw in probe.get('markers') or []:
            if kw in source:
                return S_ORIG, f'客户原文含「{kw}」'
        return S_MISS, '客户 JD 与 HR 都没给（HR 闸门缺数据）'

    # ② 结构字段（role_type / department / title）
    d = probe.get('derive')
    if d == 'role_type':
        if not role:
            return S_MISS, 'role_type 缺失'
        basis = (links.get('role_basis') or '').split('\n')[0][:40]
        flag = '' if links.get('role_confirmed') else '（原文判据已记录，尚未签字）'
        return S_ORIG, f'role_type={role}（{basis}）{flag}'
    if d == 'department':
        dept = (links.get('department') or '').strip()
        return (S_ORIG, f'department={dept}') if dept else (S_ORIG_EMPTY, '隶属部门栏为空')
    if d == 'title':
        return S_ORIG, f'客户抬头「{links.get("jd")}」（{links.get("source_file")}）'

    # ③ 有栏目名：值空 → 原文·空值（最该补）；有值 → 原文
    lab = probe.get('label')
    if lab:
        if lab not in source:
            return S_MISS, f'原文没有「{lab}」这一栏'
        val = _value_after(source, lab)
        if not val or val in ('；', '，'):
            return S_ORIG_EMPTY, f'原文有「{lab}」栏但值是空的'
        return S_ORIG, f'原文「{lab}：{val[:20]}」'

    # ④ 关键词（表头型字段要看表体是不是空的）
    for kw in probe.get('markers') or []:
        if kw not in source:
            continue
        if probe.get('table'):
            body = _table_body(source, kw)
            if not body:
                return S_ORIG_EMPTY, f'原文有「{kw}」表头，但表体是空的'
            return S_ORIG, f'原文「{kw}」表体 {len(body)} 行，如「{body[0][:22]}」'
        line = next((ln.strip() for ln in source.splitlines() if kw in ln), '')
        return S_ORIG, f'原文含「{kw}」：{line[:26]}'
    return S_MISS, '客户原文没有这一项'


def run() -> dict:
    rows = load_template()
    jds = []
    for p in sorted(LINKS.glob('*.yaml')):
        d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        # 只覆盖"有逐字引用"的客户 JD。Phase 1 上传件（status: text-only）没有引用，
        # 它的覆盖度由 services/talent_gap.text_gap_for 算，不进这份试填表。
        if d.get('status') == 'text-only' or not (d.get('citations') or []):
            continue
        name = d.get('jd') or p.stem
        src_rel = d.get('source_text') or ''
        src_path = ROOT / src_rel if src_rel else None
        source = src_path.read_text(encoding='utf-8') if src_path and src_path.is_file() else ''
        cits = d.get('citations') or []
        cells = []
        for r in rows:
            state, why = classify(r, d, source, cits)
            cells.append({'code': r['code'], 'section': r['_sec'], 'state': state, 'why': why,
                          'level': r.get('requirement_level'), 'assessable': r.get('assessable'),
                          'data_item': r.get('data_item')})
        jds.append({'jd': name, 'role_type': d.get('role_type'),
                    'department': d.get('department'), 'citations': len(cits),
                    'source_lines': len(source.splitlines()) if source else 0,
                    'cells': cells})

    # 汇总：每个字段 5 份里的状态分布
    per_field = []
    for r in rows:
        states = [next(c['state'] for c in j['cells'] if c['code'] == r['code']) for j in jds]
        per_field.append({'code': r['code'], 'label': r['label_zh'], 'section': r['_sec'],
                          'level': r.get('requirement_level'),
                          'assessable': r.get('assessable'), 'states': states,
                          'orig': states.count(S_ORIG), 'orig_empty': states.count(S_ORIG_EMPTY),
                          'hr': states.count(S_HR), 'miss': states.count(S_MISS),
                          'na': states.count(S_NA)})
    tally = {k: 0 for k in (S_ORIG, S_ORIG_EMPTY, S_HR, S_MISS, S_NA)}
    for j in jds:
        for c in j['cells']:
            tally[c['state']] += 1
    return {'_doc': '5 份客户 JD 试填标准模板的结果（scripts/talent/check_template_fill.py 现算）',
            'template_fields': len(rows), 'jds': jds, 'per_field': per_field, 'tally': tally}


def render(d: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    n = d['template_fields']
    for j in d['jds']:
        L = [f"# {j['jd']} · 标准模板试填（{n} 字段）", '',
             f"> 客户原文 {j['source_lines']} 行 · 引用 {j['citations']} 条 · "
             f"岗位类别 `{j['role_type']}` · 部门 {j['department'] or '（空）'}", '',
             '| 状态 | 数量 | 含义 |', '|---|---|---|']
        cnt = {k: 0 for k in (S_ORIG, S_ORIG_EMPTY, S_HR, S_MISS, S_NA)}
        for c in j['cells']:
            cnt[c['state']] += 1
        meaning = {S_ORIG: '客户原文读得到', S_ORIG_EMPTY: '原文有栏目但值是空的（最该补）',
                   S_HR: '客户没写，我方 HR 提的', S_MISS: '两边都没有（定稿需补/标不可判）',
                   S_NA: '本岗位类别不触发'}
        for k, v in cnt.items():
            L.append(f'| {k} | {v} | {meaning[k]} |')
        L += ['', '| 段 | 字段 | 层级 | 判定 | 状态 | 依据 |', '|---|---|---|---|---|---|']
        for c in j['cells']:
            L.append(f"| {c['section']} | `{c['code']}` | {c['level']} | {c['assessable']} | "
                     f"**{c['state']}** | {c['why']} |")
        L.append('')
        out[j['jd']] = '\n'.join(L)

    t = d['tally']
    tot = sum(t.values())
    I = ['# 标准模板 × 5 份客户 JD：试填汇总', '',
         f'> 模板 **{n}** 字段 × **{len(d["jds"])}** 份京东 = **{tot}** 格，'
         '由 `scripts/talent/check_template_fill.py` 现算，不手写。', '',
         '| 状态 | 格数 | 占 |', '|---|---|---|']
    for k, v in t.items():
        I.append(f'| {k} | **{v}** | {v * 100 / tot:.1f}% |')
    I += ['', '## 一、每份 JD 的填空情况', '',
          '| JD | 岗位类别 | 引用 | 原文 | 原文·空值 | HR 侧 | 缺 | 不适用 |', '|---|---|---|---|---|---|---|---|']
    for j in d['jds']:
        cnt = {k: 0 for k in (S_ORIG, S_ORIG_EMPTY, S_HR, S_MISS, S_NA)}
        for c in j['cells']:
            cnt[c['state']] += 1
        I.append(f"| {j['jd']} | {j['role_type']} | {j['citations']} | {cnt[S_ORIG]} | "
                 f"{cnt[S_ORIG_EMPTY]} | {cnt[S_HR]} | {cnt[S_MISS]} | {cnt[S_NA]} |")

    def never_filled(p):
        return p['orig'] == 0 and p['orig_empty'] == 0 and p['hr'] == 0

    all_miss = [p for p in d['per_field'] if never_filled(p) and p['na'] == 0]
    na_only = [p for p in d['per_field'] if never_filled(p) and p['na'] > 0]
    I += ['', '## 二、5 份 JD **全都填不出来**的字段（这就是标准模板的价值）', '',
          f'共 **{len(all_miss)}** 个。客户从来不写，但定稿/管理要用 —— 由我方按标准补齐：', '',
          '| 段 | 字段 | 名称 | 层级 | 判定 | 数据项 |', '|---|---|---|---|---|---|']
    for p in all_miss:
        I.append(f"| {p['section']} | `{p['code']}` | {p['label']} | {p['level']} | "
                 f"{p['assessable']} | — |")
    if na_only:
        I += ['', f'另有 **{len(na_only)}** 个条件字段在这 5 份京东里没触发（都是经理岗字段，'
                  '而 5 份京东按原文「直接下属无」全判员工岗）：' +
                  '、'.join(f"`{p['code']}`" for p in na_only)]

    empty = [p for p in d['per_field'] if p['orig_empty']]
    I += ['', '## 三、客户**写了栏目却留空**的字段（补的优先级最高）', '',
          '| 段 | 字段 | 名称 | 几份空 | 说明 |', '|---|---|---|---|---|']
    for p in empty:
        I.append(f"| {p['section']} | `{p['code']}` | {p['label']} | {p['orig_empty']}/5 | "
                 f"{'、'.join(j['jd'] for j in d['jds'] if next(c for c in j['cells'] if c['code'] == p['code'])['state'] == S_ORIG_EMPTY)} |")
    if not empty:
        I.append('| — | — | — | 0/5 | 没有这种情况 |')

    hr_fields = [p for p in d['per_field'] if p['hr'] or p['code'] in
                 ('F.AVAILABILITY', 'F.SALARY', 'F.AVG_TENURE', 'F.RECENT_SEGMENTS', 'F.COMMUTE')]
    I += ['', '## 四、HR 侧 5 条闸门：5 份 JD 里各有几份有数据', '', '| 字段 | 名称 | HR 侧有 | 缺 |', '|---|---|---|---|']
    for p in hr_fields:
        I.append(f"| `{p['code']}` | {p['label']} | {p['hr']}/5 | {p['miss']}/5 |")
    I.append('')
    return {'index': '\n'.join(I), **out}


def write(d: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    docs = render(d)
    for name, text in docs.items():
        p = INDEX if name == 'index' else OUT / f'{name}.md'
        p.write_text(text, encoding='utf-8')
    JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def snapshot() -> str:
    """--check 用：只比较 JSON（md 由同一个 JSON 渲染，不会单独漂）。"""
    d = run()
    return json.dumps(d, ensure_ascii=False, indent=1) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验是否最新（门禁用）')
    args = ap.parse_args()
    d = run()
    js = json.dumps(d, ensure_ascii=False, indent=1) + '\n'
    if args.check:
        same = JSON.is_file() and JSON.read_text(encoding='utf-8') == js
        print('试填结果是最新的' if same else '试填结果已过期 —— 重跑 check_template_fill')
        return 0 if same else 1
    write(d)
    t = d['tally']
    tot = sum(t.values())
    print(f'{len(d["jds"])} 份 JD × {d["template_fields"]} 字段 = {tot} 格')
    for k, v in t.items():
        print(f'  {k:8s} {v:4d} 格  {v * 100 / tot:5.1f}%')
    empty = [p for p in d['per_field'] if p['orig_empty']]
    never = [p for p in d['per_field'] if p['orig'] == 0 and p['orig_empty'] == 0 and p['hr'] == 0]
    all_miss = [p for p in never if p['na'] == 0]
    print(f'  写了栏目却留空 {len(empty)} 个字段 · 5 份全填不出 {len(all_miss)} 个字段'
          f'（另有 {len(never) - len(all_miss)} 个条件字段本批未触发）')
    print(f'→ {OUT.relative_to(ROOT)}/（_index.md + {len(d["jds"])} 份 + fill.json）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
