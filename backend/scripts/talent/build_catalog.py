#!/usr/bin/env python3
"""生成**标准目录**：分类 → 组件，再 JD 模板 / CV 模板。

## 为什么需要它

标准散在三份 YAML 里（`component_catalog` / `requirement_library` / `field_schema`），
字段、要求、组件之间是**互相引用**的，但没有任何地方能一眼看到：

  · 22 个分类里每个分类挂哪些组件、每个组件**证据档**标没标、简历里命中多少人；
  · 某条要求挂了哪些组件、被几个 JD 引用；
  · JD 模板 66 个字段 / CV 模板 31 个字段分别落在哪个区段、出现人次多少。

所以这里只做一件事：**把已有的标准摊开**，并把"没人用它"和"没标证据档"显式列出来 ——
那些正是要清理的清单，藏起来就等于没有。

## 一份数据，两种呈现

    work/talent/catalog.json   给界面读（体积小、结构稳定）
    work/talent/CATALOG.md     给人读（侧栏「目录」层）

数字**只在 build_catalog 里算一次**，md 与 json 共用同一份 —— 手写的数两天后一定是假的。

用法:
    python -m scripts.talent.build_catalog            # 生成 json + md
    python -m scripts.talent.build_catalog --check    # 只校验是否过期（门禁用）
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TALENT = ROOT / 'work' / 'talent'
DEST_JSON = TALENT / 'catalog.json'
DEST_MD = TALENT / 'CATALOG.md'


def _labels_en() -> dict:
    """英文显示名(侧挂文件)。标准 YAML 一个字节都不动 —— 判定读的是那些。"""
    p = TALENT / 'labels_en.yaml'
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding='utf-8')) or {}


def _load(name: str, key: str | None = None):
    doc = yaml.safe_load((TALENT / name).read_text(encoding='utf-8')) or {}
    return doc[key] if key else doc


# 公司标准模板：**公司口径**，不是从客户 10 份 JD 统计出来的。
# 客户模板（field_schema）是"实际长什么样"；标准模板是"应该长什么样"。
STD_DIR = TALENT / 'templates'
STD_FILES = {'jd': 'standard_jd_template.yaml', 'cv': 'standard_cv_template.yaml'}


def _load_std() -> dict:
    out: dict = {}
    for which, name in STD_FILES.items():
        p = STD_DIR / name
        if not p.is_file():
            out[which] = {'_missing': name}
            continue
        out[which] = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    return out


def _std_rows(doc: dict) -> list[dict]:
    rows = [dict(f, section=s.get('code'), section_label=s.get('label_zh'),
                 section_label_en=s.get('label_en'))
            for s in doc.get('sections') or [] for f in (s.get('fields') or [])]
    return rows


def build() -> dict:
    cat = _load('component_catalog.yaml', 'components')
    lib = _load('requirement_library.yaml', 'requirements')
    fs = _load('field_schema.yaml')
    fields = fs['fields'] if isinstance(fs.get('fields'), list) else list(fs['fields'].values())
    sec = fs.get('sections') or {}
    en = _labels_en()
    en_c, en_f, en_r = en.get('components') or {}, en.get('fields') or {}, en.get('requirements') or {}
    en_sec = en.get('sections') or {}

    # ① 引用关系：要求 → 组件；JD → 要求（只读 jd_links，不重算）
    reqs = {r['id']: r for r in lib}
    jd_files = sorted(p.stem for p in (TALENT / 'jd_links').glob('*.yaml'))
    req2jd: dict[str, set] = collections.defaultdict(set)
    comp2req: dict[str, set] = collections.defaultdict(set)
    jd_cites: dict[str, int] = {}
    for jd in jd_files:
        d = _load(f'jd_links/{jd}.yaml')
        cites = d.get('citations') or []
        jd_cites[jd] = len(cites)
        for c in cites:
            rid = c.get('requirement')
            req2jd[rid].add(jd)
            for comp in (reqs.get(rid, {}).get('components') or []):
                comp2req[comp].add(rid)
    def jds_of(comp: str) -> list[str]:
        return sorted({j for r in comp2req.get(comp, ()) for j in req2jd.get(r, ())})

    # ② 分类 → 组件
    cats: dict[str, list] = collections.defaultdict(list)
    for c in cat:
        cats[c['category']].append({
            'id': c['id'], 'label': c['label'], 'label_en': en_c.get(c['id']), 'kind': c.get('kind'),
            'evidence_role': c.get('evidence_role') or None,
            'cv_count': c.get('cv_count'),
            'requirements': sorted(comp2req.get(c['id'], ())),
            'jds': jds_of(c['id']),
            'evidence_note': c.get('evidence_note') or None,
        })
    categories = [{'name': k, 'components': sorted(v, key=lambda x: x['label'])}
                  for k, v in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    # ③ 模板
    def tpl(which: str) -> dict:
        rows = [f for f in fields if f.get(which)]
        by_sec: dict[str, list] = collections.defaultdict(list)
        for f in rows:
            blk = f[which]
            by_sec[blk.get('section') or '—'].append({
                'id': f['id'], 'label': f.get('label'),
                'label_en': en_f.get(f['id']), 'dimension': f.get('dimension'),
                'scale': f.get('scale'), 'unit': f.get('unit'),
                'presence': blk.get('presence'), 'required': blk.get('required'),
                'prop': blk.get('prop'), 'compare': f.get('compare'),
                'note': f.get('note') or None,
            })
        labels = (sec.get(which) or {})
        return {
            'name': (fs.get('templates', {}).get(which) or {}).get('name'),
            'rule': (fs.get('templates', {}).get(which) or {}).get('rule'),
            'field_count': len(rows),
            'sections': [{'code': code, 'label': labels.get(code) or code,
                          'label_en': (en_sec.get(which) or {}).get(code),
                          'fields': sorted(v, key=lambda x: str(x['id']))}
                         for code, v in sorted(by_sec.items())],
        }

    # ④ 覆盖与缺口（必须显式列出）
    role_missing = [c['id'] for c in cat if not c.get('evidence_role')]
    req_unused = sorted(r['id'] for r in lib if r['id'] not in req2jd)
    comp_unused = sorted(c['id'] for c in cat if c['id'] not in comp2req)
    unassessable = sorted(r['id'] for r in lib if not r.get('assessable'))

    # ⑤ 公司标准模板 + 要求覆盖（每条可判要求必须落到两个模板的某个字段上）
    std_in = _load_std()
    std: dict = {}
    for which, doc in std_in.items():
        rows = _std_rows(doc)
        std[which] = {
            'name': None,
            '_doc': None,
            'version': doc.get('version'),
            'principles': doc.get('principles') or [],
            'dropped': doc.get('dropped') or [],
            'field_count_target': doc.get('field_count_target'),
            'field_count': len(rows),
            'sections': [{
                'code': s.get('code'), 'label_zh': s.get('label_zh'), 'label_en': s.get('label_en'),
                'fields': [{
                    'code': f.get('code'), 'label_zh': f.get('label_zh'),
                    'label_en': f.get('label_en'), 'dimension': f.get('dimension'),
                    'data_item': f.get('data_item'), 'assessable': f.get('assessable'),
                    'threshold_shape': f.get('threshold_shape'),
                    'value_shape': f.get('value_shape'),
                    'evidence_required': f.get('evidence_required'),
                    'missing_means': f.get('missing_means'),
                    'requirement_level': f.get('requirement_level'),
                    'conditional_on': f.get('conditional_on'),
                    'source_requirement': f.get('source_requirement') or [],
                    'origin': f.get('origin'), 'compare': f.get('compare'),
                    'new_in_standard': bool(f.get('new_in_standard')),
                    'in_field_schema': bool(f.get('in_field_schema')),
                    'cross_side': bool(f.get('cross_side')),
                    'prop': f.get('prop'),
                    'note': f.get('note'),
                } for f in s.get('fields') or []],
            } for s in doc.get('sections') or []],
        }
        lv = collections.Counter(r.get('requirement_level') for r in rows)
        std[which]['levels'] = {k: lv.get(k, 0) for k in ('required', 'conditional', 'optional')}
        std[which]['assess'] = dict(collections.Counter(r.get('assessable') for r in rows))
        std[which]['new_fields'] = [r['code'] for r in rows
                                    if r.get('new_in_standard') and not r.get('cross_side')]
        std[which]['cross_side_fields'] = [r['code'] for r in rows if r.get('cross_side')]

    cv_items = {r.get('data_item') for r in _std_rows(std_in['cv'])}
    jd_items = {r.get('data_item') for r in _std_rows(std_in['jd'])}
    req_cov = []
    for r in lib:
        if not r.get('assessable'):
            continue
        item = r.get('attribute')
        if r.get('components'):
            ok = 'skill_*' in cv_items and 'skill_*' in jd_items
            where = 'skill_*'
        else:
            ok = item in cv_items and item in jd_items
            where = item
        req_cov.append({'requirement': r['id'], 'data_item': where,
                        'in_cv_template': ok, 'in_jd_template': ok})
    std_cov = {
        'requirements_assessable': len(req_cov),
        'requirements_uncovered': [x['requirement'] for x in req_cov if not x['in_cv_template']],
        'requirements': req_cov,
        'jd_fields': len(_std_rows(std_in['jd'])), 'cv_fields': len(_std_rows(std_in['cv'])),
        'jd_target': std_in['jd'].get('field_count_target'),
        'cv_target': std_in['cv'].get('field_count_target'),
    }

    return {
        '_doc': ('标准目录。数字全部由 scripts/talent/build_catalog.py 现算，'
                 '不手写；--check 可判断是否过期。'),
        'generated_from': 'scripts/talent/build_catalog.py',
        'categories': categories,
        'requirements': [{
            'id': r['id'], 'name': r.get('name'), 'name_en': en_r.get(r['id']),
            'dimension': r.get('dimension'),
            'kind': r.get('kind'), 'data_class': r.get('data_class'),
            'assessable': bool(r.get('assessable')),
            'components': list(r.get('components') or []),
            'attribute': r.get('attribute'), 'op': r.get('op'),
            'jds': sorted(req2jd.get(r['id'], ())),
        } for r in sorted(lib, key=lambda x: x['id'])],
        'jd_template': tpl('jd'),
        'cv_template': tpl('cv'),
        'standard_templates': std,
        'standard_coverage': std_cov,
        'coverage': {
            'categories': len(categories),
            'components': len(cat), 'requirements': len(lib), 'fields': len(fields),
            'components_with_evidence_role': len(cat) - len(role_missing),
            'components_evidence_role_missing': role_missing,
            'requirements_used_by_jds': len(reqs) - len(req_unused),
            'requirements_unused': req_unused,
            'components_unused': comp_unused,
            'requirements_unassessable': unassessable,
            'jds': {jd: {'citations': jd_cites.get(jd, 0)} for jd in jd_files},
        },
    }


def render(d: dict) -> str:
    cov = d['coverage']
    L: list[str] = []
    A = L.append
    A('# 标准目录 · 分类 / 组件 / JD 模板 / CV 模板')
    A('')
    A('> 数字由 `scripts/talent/build_catalog.py` 从三份 YAML 与五份 `jd_links` 现算，不手写。')
    std = d['standard_templates']; sc = d['standard_coverage']
    A(f'> 分类 **{cov["categories"]}** · 组件 **{cov["components"]}** · 要求 **{cov["requirements"]}**'
      f' · 标准模板 **JD {sc["jd_fields"]} / CV {sc["cv_fields"]}** 字段'
      f'（客户实际字段 JD {d["jd_template"]["field_count"]} / CV {d["cv_template"]["field_count"]}）。')
    A('')
    A('两套模板是**两件事**：`templates/standard_*` 是公司标准（应该长什么样，字段取自 '
      '`field_schema`、按这家公司实务取舍，并支撑本体推理）；'
      '`field_schema` 是客户实际（10 份 JD / 270 份简历里真长什么样）。')
    A('')
    A('> **缺口不在这份目录里**：某份 JD「还缺哪几格」是下一阶段的事 —— 在 Talent 左栏选一份 JD，'
      '打开「0 JD · 原文与缺口」看（`jd_draft/` 与 `template_fill/` 是它的原料）。'
      '标准目录只负责"标准长什么样"。')
    A('')
    A('## 目录自身的完整性（这里不看 JD/CV 缺口，那是下一层）')
    A('')
    A('| 缺口 | 数量 | 影响 |')
    A('|---|---|---|')
    A(f'| 组件**没标证据档** | **{len(cov["components_evidence_role_missing"])}** | 能力「满足」里有多少只是自述，答不出来 |')
    A(f'| 要求**没有被任何 JD 引用** | **{len(cov["requirements_unused"])}** | 标准建了没人用，要留还是删 |')
    A(f'| 组件**没有被任何要求挂** | **{len(cov["components_unused"])}** | 抽得出、判不到 |')
    A(f'| 要求**不可判**（assessable=false） | **{len(cov["requirements_unassessable"])}** | 对所有人一样，不能拿来淘汰人 |')
    A(f'| 可判要求**没落到标准模板** | **{len(sc["requirements_uncovered"])}** | 判不了：JD 提了要求，简历侧没有落脚字段 |')
    A('')
    A('## 一、分类与组件')
    A('')
    for c in d['categories']:
        A(f'### {c["name"]}（{len(c["components"])}）')
        A('')
        A('| 组件 | 标签 | kind | 证据档 | 简历命中 | 挂几条要求 | 被几个 JD 用 |')
        A('|---|---|---|---|---|---|---|')
        for x in c['components']:
            A(f'| `{x["id"]}` | {x["label"]} | {x["kind"] or "—"} | '
              f'**{x["evidence_role"] or "未声明"}** | {x["cv_count"] if x["cv_count"] is not None else "—"} | '
              f'{len(x["requirements"])} | {len(x["jds"])} |')
        A('')
    A('## 二、组件反查（哪个组件被哪条要求、哪个 JD 用到）')
    A('')
    A('| 组件 | 要求 | JD |')
    A('|---|---|---|')
    used = [x for c in d['categories'] for x in c['components'] if x['requirements'] or x['jds']]
    for x in sorted(used, key=lambda y: (-len(y['jds']), -len(y['requirements']), y['label'])):
        A(f'| `{x["id"]}` {x["label"]} | '
          f'{("、".join(r.replace("REQ-", "") for r in x["requirements"])) or "—"} | '
          f'{("、".join(x["jds"])) or "—"} |')
    A('')
    for which, title, sub in (
            ('jd', '三、标准 JD 模板（公司标准 · 40 字段）', '职务说明书应该长什么样'),
            ('cv', '四、标准 CV 模板（公司标准 · 26 字段）', '候选人档案应该长什么样')):
        t = std[which]
        lv = t['levels']
        A(f'## {title}')
        A('')
        A(f'{sub}。共 **{t["field_count"]}** 字段'
          f'（必需 {lv["required"]} / 条件 {lv["conditional"]} / 可选 {lv["optional"]}）'
          f'· 目标 {t["field_count_target"]} 字段。')
        A('')
        A('> 生成器：`scripts/talent/build_templates.py`。原则：' +
          ' / '.join(t['principles']) + '。字段 id 与中文名取自 `field_schema`，'
          '每个字段上方的注释写清了"这家公司为什么需要它"与出现次数；'
          f'没进模板的 **{len(t["dropped"])}** 条在文件末尾 `dropped` 里逐条交代去处。')
        A('')
        A('| 段 | 段名 | 字段数 |')
        A('|---|---|---|')
        for s2 in t['sections']:
            A(f'| {s2["code"]} | {s2["label_zh"]} | {len(s2["fields"])} |')
        A('')
        for s2 in t['sections']:
            A(f'### {s2["code"]} · {s2["label_zh"]}（{len(s2["fields"])}）')
            A('')
            if which == 'jd':
                A('| 字段 | 名称 | 层级 | 判定 | 数据项 | 门槛形状 | 证据 | 缺了算 | 要求 |')
                A('|---|---|---|---|---|---|---|---|---|')
                for f2 in s2['fields']:
                    A(f'| `{f2["code"]}`{" 🆕" if f2["new_in_standard"] else ""} | {f2["label_zh"]} | '
                      f'{f2["requirement_level"]} | {f2["assessable"]} | {f2["data_item"] or "—"} | '
                      f'{f2["threshold_shape"] or "—"} | {f2["evidence_required"] or "—"} | '
                      f'{f2["missing_means"] or "—"} | '
                      f'{("、".join(r.replace("REQ-", "") for r in f2["source_requirement"])) or "—"} |')
            else:
                A('| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 来源 |')
                A('|---|---|---|---|---|---|---|---|---|')
                for f2 in s2['fields']:
                    A(f'| `{f2["code"]}`{" 🆕" if f2["new_in_standard"] else ""} | {f2["label_zh"]} | '
                      f'{f2["requirement_level"]} | {f2["assessable"]} | {f2["data_item"] or "—"} | '
                      f'{f2["value_shape"] or "—"} | {f2["evidence_required"] or "—"} | '
                      f'{f2["missing_means"] or "—"} | '
                      f'{("、".join(r.replace("REQ-", "") for r in f2["source_requirement"])) or "—"} |')
            A('')
        newf = t['new_fields']
        if newf:
            A(f'标准新增（`field_schema` 里还没有）：{"、".join(f"`{x}`" for x in newf)}')
            A('')
    A('## 五、客户实际字段 · JD（10 份 JD 里真长什么样）')
    A('')
    t = d['jd_template']
    A(f'共 **{t["field_count"]}** 个字段。规则：{t["rule"]}')
    A('')
    for s in t['sections']:
        A(f'### {s["code"]} · {s["label"]}（{len(s["fields"])}）')
        A('')
        A('| 字段 | 名称 | 维度 | 出现 | 必填 | 说明 |')
        A('|---|---|---|---|---|---|')
        for f in s['fields']:
            note = (f['note'] or '').replace('\n', ' ')[:60]
            A(f'| `{f["id"]}` | {f["label"]} | {f["dimension"] or "—"} | '
              f'{f["presence"] if f["presence"] is not None else "—"} | '
              f'{"是" if f["required"] else "—"} | {note or "—"} |')
        A('')
    A('## 六、客户实际字段 · CV（270 份简历里真长什么样）')
    A('')
    t = d['cv_template']
    A(f'共 **{t["field_count"]}** 个字段。规则：{t["rule"]}')
    A('')
    for s in t['sections']:
        A(f'### {s["code"]} · {s["label"]}（{len(s["fields"])}）')
        A('')
        A('| 字段 | 名称 | 维度 | 出现 | 落哪个属性 | 两侧可比 | 说明 |')
        A('|---|---|---|---|---|---|---|')
        for f in s['fields']:
            note = (f['note'] or '').replace('\n', ' ')[:56]
            A(f'| `{f["id"]}` | {f["label"]} | {f["dimension"] or "—"} | '
              f'{f["presence"] if f["presence"] is not None else "—"} | '
              f'{f["prop"] or "—"} | {f["compare"] or "—"} | {note or "—"} |')
        A('')
    A('## 七、要求清单（码 / 维度 / 类别 / 可判 / 被几个 JD 用）')
    A('')
    A('| 码 | 名称 | 维度 | kind | 类别 | 可判 | 挂组件 | JD |')
    A('|---|---|---|---|---|---|---|---|')
    for r in d['requirements']:
        A(f'| `{r["id"].replace("REQ-", "")}` | {r["name"] or "—"} | {r["dimension"] or "—"} | '
          f'{r["kind"] or "—"} | {r["data_class"] or "—"} | {"✅" if r["assessable"] else "—"} | '
          f'{len(r["components"])} | {len(r["jds"])} |')
    A('')
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验是否最新（门禁用）')
    args = ap.parse_args()
    d = json.loads(json.dumps(build(), ensure_ascii=False))
    js = json.dumps(d, ensure_ascii=False, indent=1) + '\n'
    md = render(d)
    if args.check:
        ok = (DEST_JSON.is_file() and DEST_JSON.read_text(encoding='utf-8') == js
              and DEST_MD.is_file() and DEST_MD.read_text(encoding='utf-8').strip() == md.strip())
        print('catalog 是最新的' if ok else 'catalog 已过期 —— 重跑 build_catalog')
        return 0 if ok else 1
    DEST_JSON.write_text(js, encoding='utf-8')
    DEST_MD.write_text(md, encoding='utf-8')
    cov = d['coverage']
    print(f'写出 {DEST_JSON.relative_to(ROOT)} · {DEST_MD.relative_to(ROOT)}')
    print(f'  分类 {cov["categories"]} · 组件 {cov["components"]}'
          f'（证据档已标 {cov["components_with_evidence_role"]}）'
          f' · 要求 {cov["requirements"]}（被引用 {cov["requirements_used_by_jds"]}）')
    sc = d['standard_coverage']
    print(f'  标准模板 JD {sc["jd_fields"]} / CV {sc["cv_fields"]} 字段'
          f' · 可判要求 {sc["requirements_assessable"]} 条（未覆盖 {len(sc["requirements_uncovered"])}）')
    print(f'  客户实际字段 JD {d["jd_template"]["field_count"]} / CV {d["cv_template"]["field_count"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
