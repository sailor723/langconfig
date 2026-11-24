#!/usr/bin/env python3
"""生成**标准目录（Phase 0 · 标准定义层）**：分类 → 组件 → 要求 → 标准 JD / CV 模板。

## 这一层只管"标准长什么样"

标准目录**不对应任何具体的 JD 或简历**。打开它，看到的是：

  · 22 个能力分类、54 个组件（每个组件标了 `evidence_role`：硬证据还是自述）；
  · 61 条要求（哪条可判、挂哪些组件、属于哪个数据项）—— 但**不显示"被哪份 JD 引用"**，
    因为引用关系属于具体某一份 JD 的事（下一层才谈）；
  · **标准 JD 模板 40 字段 / 标准 CV 模板 26 字段**：所有 JD 共用同一份版式。

不出现：任何客户 JD 名字、任何一份简历、任何"缺口"。那些在下面几层：

    Phase 0  标准定义      ← 本文件（CATALOG.md / catalog.json）
    Phase 1  客户 JD 原文   jd_links/_source/<JD>.txt
    Phase 2  这份 JD 的缺口  Talent「0 JD · 原文与缺口」面板（jd_draft/ / template_fill/）
    Phase 3  某份简历的缺口  （未接界面）

## 一份数据，两种呈现

    work/talent/catalog.json   给界面读（体积小、结构稳定）
    work/talent/CATALOG.md     给人读（侧栏「标准目录」层）

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

STD_DIR = TALENT / 'templates'
STD_FILES = {'jd': 'standard_jd_template.yaml', 'cv': 'standard_cv_template.yaml'}


def _labels_en() -> dict:
    """英文显示名(侧挂文件)。标准 YAML 一个字节都不动 —— 判定读的是那些。"""
    p = TALENT / 'labels_en.yaml'
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding='utf-8')) or {}


def _load(name: str, key: str | None = None):
    doc = yaml.safe_load((TALENT / name).read_text(encoding='utf-8')) or {}
    return doc[key] if key else doc


def _load_std() -> dict:
    out: dict = {}
    for which, name in STD_FILES.items():
        p = STD_DIR / name
        out[which] = (yaml.safe_load(p.read_text(encoding='utf-8')) or {}) if p.is_file() else {}
    return out


def _std_rows(doc: dict) -> list[dict]:
    return [dict(f, section=s.get('code'), section_label=s.get('label_zh'),
                 section_label_en=s.get('label_en'))
            for s in doc.get('sections') or [] for f in (s.get('fields') or [])]


def build() -> dict:
    cat = _load('component_catalog.yaml', 'components')
    lib = _load('requirement_library.yaml', 'requirements')
    en = _labels_en()
    en_c, en_r = en.get('components') or {}, en.get('requirements') or {}

    # ① 组件 ↔ 要求：只从 requirement_library 推（**不读 jd_links** —— 那属于具体 JD 的事）
    comp2req: dict[str, set] = collections.defaultdict(set)
    for r in lib:
        for comp in (r.get('components') or []):
            comp2req[comp].add(r['id'])

    # ② 分类 → 组件
    cats: dict[str, list] = collections.defaultdict(list)
    for c in cat:
        cats[c['category']].append({
            'id': c['id'], 'label': c['label'], 'label_en': en_c.get(c['id']), 'kind': c.get('kind'),
            'evidence_role': c.get('evidence_role') or None,
            'requirements': sorted(comp2req.get(c['id'], ())),
            'evidence_note': c.get('evidence_note') or None,
        })
    categories = [{'name': k, 'components': sorted(v, key=lambda x: x['label'])}
                  for k, v in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    # ③ 标准模板（JD 40 / CV 26）—— 所有 JD 共用同一份版式
    std_in = _load_std()
    std: dict = {}
    for which, doc in std_in.items():
        rows = _std_rows(doc)
        std[which] = {
            'version': doc.get('version'),
            'principles': doc.get('principles') or [],
            'dropped': doc.get('dropped') or [],
            'field_count_target': doc.get('field_count_target'),
            'field_count': len(rows),
            'levels': {k: sum(1 for r in rows if r.get('requirement_level') == k)
                       for k in ('required', 'conditional', 'optional')},
            'assess': dict(collections.Counter(r.get('assessable') for r in rows)),
            'new_fields': [r['code'] for r in rows
                           if r.get('new_in_standard') and not r.get('cross_side')],
            'cross_side_fields': [r['code'] for r in rows if r.get('cross_side')],
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
                    'prop': f.get('prop'), 'note': f.get('note'),
                } for f in s.get('fields') or []],
            } for s in doc.get('sections') or []],
        }

    # ④ 可判要求 → 模板落脚字段（每条可判要求两个模板都得有地方读）
    cv_items = {r.get('data_item') for r in _std_rows(std_in['cv'])}
    jd_items = {r.get('data_item') for r in _std_rows(std_in['jd'])}
    req_cov = []
    for r in lib:
        if not r.get('assessable'):
            continue
        item = 'skill_*' if r.get('components') else r.get('attribute')
        req_cov.append({'requirement': r['id'], 'data_item': item,
                        'in_cv_template': item in cv_items, 'in_jd_template': item in jd_items})
    std_cov = {
        'requirements_assessable': len(req_cov),
        'requirements_uncovered': [x['requirement'] for x in req_cov if not x['in_cv_template']],
        'requirements': req_cov,
        'jd_fields': len(_std_rows(std_in['jd'])), 'cv_fields': len(_std_rows(std_in['cv'])),
        'jd_target': std_in['jd'].get('field_count_target'),
        'cv_target': std_in['cv'].get('field_count_target'),
    }

    # ⑤ 目录自身的完整性（只讲标准层，不涉及具体 JD/简历）
    role_missing = [c['id'] for c in cat if not c.get('evidence_role')]
    comp_unused = sorted(c['id'] for c in cat if c['id'] not in comp2req)
    unassessable = sorted(r['id'] for r in lib if not r.get('assessable'))

    return {
        '_doc': ('标准目录 · Phase 0（标准定义层）。不对应任何具体 JD 或简历：'
                 '分类 / 组件 / 要求 / 标准 JD 模板（所有 JD 共用同一版式）/ 标准 CV 模板。'
                 '数字全部由 scripts/talent/build_catalog.py 现算，不手写；--check 可判断是否过期。'),
        'generated_from': 'scripts/talent/build_catalog.py',
        'phase': 'phase0-standard-definition',
        'layout_rule': ('所有 JD 共用同一份 40 字段版式（standard_templates.jd）；'
                        '所有简历共用同一份 26 字段版式（standard_templates.cv）。'
                        '具体某份 JD 的取值与缺口属于下一层，不在本目录里。'),
        'categories': categories,
        'requirements': [{
            'id': r['id'], 'name': r.get('name'), 'name_en': en_r.get(r['id']),
            'dimension': r.get('dimension'),
            'kind': r.get('kind'), 'data_class': r.get('data_class'),
            'assessable': bool(r.get('assessable')),
            'components': list(r.get('components') or []),
            'attribute': r.get('attribute'), 'op': r.get('op'),
        } for r in sorted(lib, key=lambda x: x['id'])],
        'standard_templates': std,
        'standard_coverage': std_cov,
        'coverage': {
            'phase': 'phase0',
            'categories': len(categories),
            'components': len(cat), 'requirements': len(lib),
            'components_with_evidence_role': len(cat) - len(role_missing),
            'components_evidence_role_missing': role_missing,
            'components_unused': comp_unused,
            'requirements_unassessable': unassessable,
        },
    }


def render(d: dict) -> str:
    cov, sc = d['coverage'], d['standard_coverage']
    std = d['standard_templates']
    L: list[str] = []
    A = L.append
    A('# 标准目录 · Phase 0（标准定义层）')
    A('')
    A('> 这一层**不对应任何具体 JD 或简历**：只有分类、组件、要求，以及公司标准的 JD / CV 模板。')
    A('> 数字由 `scripts/talent/build_catalog.py` 现算，不手写。')
    A('')
    A(f'> 分类 **{cov["categories"]}** · 组件 **{cov["components"]}** · 要求 **{cov["requirements"]}**'
      f' · 标准 JD 模板 **{sc["jd_fields"]}** 字段 · 标准 CV 模板 **{sc["cv_fields"]}** 字段')
    A('')
    A(f'> **版式统一**：{d["layout_rule"]}')
    A('')
    A('## 目录自身的完整性')
    A('')
    A('| 检查 | 数量 | 影响 |')
    A('|---|---|---|')
    A(f'| 组件**没标证据档** | **{len(cov["components_evidence_role_missing"])}** | 能力「满足」里有多少只是自述，答不出来 |')
    A(f'| 组件**没有被任何要求挂** | **{len(cov["components_unused"])}** | 抽得出、判不到 |')
    A(f'| 要求**不可判**（assessable=false） | **{len(cov["requirements_unassessable"])}** | 对所有人一样，不能拿来淘汰人 |')
    A(f'| 可判要求**没落到标准模板** | **{len(sc["requirements_uncovered"])}** | 判不了：要求提了，模板里没有落脚字段 |')
    A('')
    A('## 一、分类与组件')
    A('')
    for c in d['categories']:
        A(f'### {c["name"]}（{len(c["components"])}）')
        A('')
        A('| 组件 | 标签 | kind | 证据档 | 挂几条要求 |')
        A('|---|---|---|---|---|')
        for x in c['components']:
            A(f'| `{x["id"]}` | {x["label"]} | {x["kind"] or "—"} | '
              f'**{x["evidence_role"] or "未声明"}** | {len(x["requirements"])} |')
        A('')
    A('## 二、组件 → 要求反查')
    A('')
    A('| 组件 | 要求 |')
    A('|---|---|')
    used = [x for c in d['categories'] for x in c['components'] if x['requirements']]
    for x in sorted(used, key=lambda y: (-len(y['requirements']), y['label'])):
        A(f'| `{x["id"]}` {x["label"]} | '
          f'{("、".join(r.replace("REQ-", "") for r in x["requirements"])) or "—"} |')
    A('')
    for which, tpl, title, sub in (
            ('jd', std['jd'], '三、标准 JD 模板（所有 JD 共用同一版式）', '职务说明书'),
            ('cv', std['cv'], '四、标准 CV 模板（所有简历共用同一版式）', '候选人档案')):
        lv = tpl['levels']
        A(f'## {title}')
        A('')
        A(f'{sub}。共 **{tpl["field_count"]}** 字段'
          f'（必需 {lv["required"]} / 条件 {lv["conditional"]} / 可选 {lv["optional"]}）'
          f'· 目标 {tpl["field_count_target"]} 字段。')
        A('')
        A('> 生成器：`scripts/talent/build_templates.py`。原则：' + ' / '.join(tpl['principles']) +
          '。字段 id 与中文名取自 `field_schema`，每个字段上方的注释写清了"这家公司为什么需要它"'
          f'与出现次数；没进模板的 **{len(tpl["dropped"])}** 条在文件末尾 `dropped` 里逐条交代去处。')
        A('')
        A('| 段 | 段名 | 字段数 |')
        A('|---|---|---|')
        for s2 in tpl['sections']:
            A(f'| {s2["code"]} | {s2["label_zh"]} | {len(s2["fields"])} |')
        A('')
        for s2 in tpl['sections']:
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
                A('| 字段 | 名称 | 层级 | 判定 | 数据项 | 值形状 | 证据 | 缺了算 | 要求 |')
                A('|---|---|---|---|---|---|---|---|---|')
                for f2 in s2['fields']:
                    A(f'| `{f2["code"]}`{" 🆕" if f2["new_in_standard"] else ""} | {f2["label_zh"]} | '
                      f'{f2["requirement_level"]} | {f2["assessable"]} | {f2["data_item"] or "—"} | '
                      f'{f2["value_shape"] or "—"} | {f2["evidence_required"] or "—"} | '
                      f'{f2["missing_means"] or "—"} | '
                      f'{("、".join(r.replace("REQ-", "") for r in f2["source_requirement"])) or "—"} |')
            A('')
        if tpl['new_fields']:
            A(f'标准新增（`field_schema` 里还没有）：{"、".join(f"`{x}`" for x in tpl["new_fields"])}')
            A('')
    A('## 五、要求清单')
    A('')
    A('| 码 | 名称 | 维度 | kind | 类别 | 可判 | 挂组件 |')
    A('|---|---|---|---|---|---|---|')
    for r in d['requirements']:
        A(f'| `{r["id"].replace("REQ-", "")}` | {r["name"] or "—"} | {r["dimension"] or "—"} | '
          f'{r["kind"] or "—"} | {r["data_class"] or "—"} | {"✅" if r["assessable"] else "—"} | '
          f'{len(r["components"])} |')
    A('')
    A('---')
    A('')
    A('下一层（不在这份目录里）：客户 JD 原文 → 这份 JD 的缺口 → 某份简历的缺口。'
      '缺口在 Talent 左栏「0 JD · 原文与缺口」看，原料是 `jd_draft/` 与 `template_fill/`。')
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
    cov, sc = d['coverage'], d['standard_coverage']
    print(f'写出 {DEST_JSON.relative_to(ROOT)} · {DEST_MD.relative_to(ROOT)}')
    print(f'  Phase 0 · 分类 {cov["categories"]} · 组件 {cov["components"]}'
          f'（证据档已标 {cov["components_with_evidence_role"]}）· 要求 {cov["requirements"]}')
    print(f'  标准 JD 模板 {sc["jd_fields"]} 字段 · 标准 CV 模板 {sc["cv_fields"]} 字段'
          f' · 可判要求 {sc["requirements_assessable"]} 条（未覆盖 {len(sc["requirements_uncovered"])}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
