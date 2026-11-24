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


def _load(name: str, key: str | None = None):
    doc = yaml.safe_load((TALENT / name).read_text(encoding='utf-8')) or {}
    return doc[key] if key else doc


def build() -> dict:
    cat = _load('component_catalog.yaml', 'components')
    lib = _load('requirement_library.yaml', 'requirements')
    fs = _load('field_schema.yaml')
    fields = fs['fields'] if isinstance(fs.get('fields'), list) else list(fs['fields'].values())
    sec = fs.get('sections') or {}

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
            'id': c['id'], 'label': c['label'], 'kind': c.get('kind'),
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
                'id': f['id'], 'label': f.get('label'), 'dimension': f.get('dimension'),
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
                          'fields': sorted(v, key=lambda x: str(x['id']))}
                         for code, v in sorted(by_sec.items())],
        }

    # ④ 覆盖与缺口（必须显式列出）
    role_missing = [c['id'] for c in cat if not c.get('evidence_role')]
    req_unused = sorted(r['id'] for r in lib if r['id'] not in req2jd)
    comp_unused = sorted(c['id'] for c in cat if c['id'] not in comp2req)
    unassessable = sorted(r['id'] for r in lib if not r.get('assessable'))

    return {
        '_doc': ('标准目录。数字全部由 scripts/talent/build_catalog.py 现算，'
                 '不手写；--check 可判断是否过期。'),
        'generated_from': 'scripts/talent/build_catalog.py',
        'categories': categories,
        'requirements': [{
            'id': r['id'], 'name': r.get('name'), 'dimension': r.get('dimension'),
            'kind': r.get('kind'), 'data_class': r.get('data_class'),
            'assessable': bool(r.get('assessable')),
            'components': list(r.get('components') or []),
            'attribute': r.get('attribute'), 'op': r.get('op'),
            'jds': sorted(req2jd.get(r['id'], ())),
        } for r in sorted(lib, key=lambda x: x['id'])],
        'jd_template': tpl('jd'),
        'cv_template': tpl('cv'),
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
    A(f'> 分类 **{cov["categories"]}** · 组件 **{cov["components"]}** · 要求 **{cov["requirements"]}**'
      f' · 字段 **{cov["fields"]}**（JD 模板 {d["jd_template"]["field_count"]} / '
      f'CV 模板 {d["cv_template"]["field_count"]}）。')
    A('')
    A('## 先说缺口（要清理的就是这几张清单）')
    A('')
    A('| 缺口 | 数量 | 影响 |')
    A('|---|---|---|')
    A(f'| 组件**没标证据档** | **{len(cov["components_evidence_role_missing"])}** | 能力「满足」里有多少只是自述，答不出来 |')
    A(f'| 要求**没有被任何 JD 引用** | **{len(cov["requirements_unused"])}** | 标准建了没人用，要留还是删 |')
    A(f'| 组件**没有被任何要求挂** | **{len(cov["components_unused"])}** | 抽得出、判不到 |')
    A(f'| 要求**不可判**（assessable=false） | **{len(cov["requirements_unassessable"])}** | 对所有人一样，不能拿来淘汰人 |')
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
    A('## 三、JD 模板（职务说明书）')
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
    A('## 四、CV 模板（候选人档案）')
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
    A('## 五、要求清单（码 / 维度 / 类别 / 可判 / 被几个 JD 用）')
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
    print(f'  JD 模板 {d["jd_template"]["field_count"]} 字段 · CV 模板 {d["cv_template"]["field_count"]} 字段')
    return 0


if __name__ == '__main__':
    sys.exit(main())
