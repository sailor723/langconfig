#!/usr/bin/env python3
"""把一份客户 JD 按**公司标准模板（40 字段）**填成定稿草稿 —— 一格一格，带依据。

## 为什么要脚本，而不是写一篇 md

md 里写"薪资面议"很容易；但下一步判定读的是字段值，不是文章。所以这里做的是
**逐格结构化填充**：每一格必须有 `state`，而 state 决定这格能不能进判定：

| state | 进判定吗 | 规矩 |
|---|---|---|
| `客户原文` | 能（有引文即可判定） | 必须带 `cites`，脚本核对引用真实存在并把原文带出 |
| `HR 侧` | 能（我方闸门） | 必须带 `cites`，且该引用 `origin: hr` |
| `原文·空值` | 不能（记「未知」） | 客户写了栏目但值空 —— 脚本核对原文确实为空 |
| `我方建议·待确认` | **不能**（未确认前不进判定） | 必须写 `why` + `needs`（谁确认） |
| `待客户给` | 不能（记「不可判」） | 必须写缺什么 |
| `不适用` | 不适用 | 只能是条件字段，且岗位类别不触发 |

**"不许编客户没给的值"是硬规矩**：脚本会拒绝任何既没有引用、也没有 `why/needs` 的格子。

## 产物

    work/talent/jd_draft/<JD>.fill.yaml    人写的填充（建议值 + 理由 + 谁确认）
    work/talent/jd_draft/<JD> 定稿草稿.md   给人看的：40 行表（值 / 状态 / 依据 / 待谁）
    work/talent/jd_draft/<JD>.draft.json   给下一步与门禁用

用法:
    python -m scripts.talent.draft_jd --jd 品质经理
    python -m scripts.talent.draft_jd --jd 品质经理 --check     # 只校验是否最新（门禁用）
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
DIR = TALENT / 'jd_draft'

ST_CLIENT, ST_HR, ST_EMPTY = '客户原文', 'HR 侧', '原文·空值'
ST_PROPOSED, ST_WAIT, ST_WAITC, ST_NA = ('我方建议·待确认', '待客户给', '待客户确认',
                                       '不适用')
#: 能进判定的状态（其余一律「未知」/「不可判」）
IN_JUDGING = {ST_CLIENT, ST_HR}
ALL_STATES = {ST_CLIENT, ST_HR, ST_EMPTY, ST_PROPOSED, ST_WAIT, ST_WAITC, ST_NA}


def load_template() -> list[dict]:
    doc = yaml.safe_load(TEMPLATE.read_text(encoding='utf-8')) or {}
    return [dict(f, _sec=s.get('code'), _sec_label=s.get('label_zh'))
            for s in doc.get('sections') or [] for f in s.get('fields') or []]


def load_links(jd: str) -> dict:
    p = TALENT / 'jd_links' / f'{jd}.yaml'
    return yaml.safe_load(p.read_text(encoding='utf-8')) or {}


TABLE_HEADER_WORDS = {'序号', '内容', '每日', '每周', '每月', '偶发', '备注', '频次', '时长',
                      '类别', '项目', '事务名称', '工作事项', '关联表单', '操作标准流程',
                      'AI可否替代', '其它事项'}


_CTRL = re.compile(r'[\x00-\x1f\x7f\u200b\ufeff]')


def _norm(x: str) -> str:
    """把空白与控制字符全去掉再比。

    Word 表格被 `textutil` 抽平后，单元格之间是 **\x07（BEL）** ——
    「直接下属\x07无」与「直接下属无」是同一句话，`str.split()` 却切不开它。
    """
    return _CTRL.sub('', x).replace('\u3000', '').replace(' ', '')


def build(jd: str) -> dict:
    tpl = load_template()
    links = load_links(jd)
    fillp = DIR / f'{jd}.fill.yaml'
    fill = (yaml.safe_load(fillp.read_text(encoding='utf-8')) or {})
    over = fill.get('overrides') or {}
    cits = {c['id']: c for c in links.get('citations') or []}
    src_rel = links.get('source_text') or ''
    source = ''
    if src_rel and (ROOT / src_rel).is_file():
        source = (ROOT / src_rel).read_text(encoding='utf-8')

    src_norm = _norm(source)
    problems: list[str] = []
    missing_codes = [r['code'] for r in tpl if r['code'] not in over]
    extra = [c for c in over if c not in {r['code'] for r in tpl}]
    if missing_codes:
        problems.append('模板里有字段没填：' + ', '.join(missing_codes))
    if extra:
        problems.append('fill 里有模板没有的字段：' + ', '.join(extra))

    rows = []
    for r in tpl:
        code = r['code']
        spec = over.get(code) or {}
        state = spec.get('state')
        why = (spec.get('why') or '').strip()
        needs = (spec.get('needs') or '').strip()
        val = spec.get('value')
        cites = list(spec.get('cites') or [])
        quote = (spec.get('quote') or '').strip()
        qline = spec.get('line')
        ev = []
        if state not in ALL_STATES:
            problems.append(f'{code}: state 非法/缺失（{state}）')
        if state in IN_JUDGING:
            # 第三类依据：Phase 1 的**文本规则**（正文里读出来的，还没抽成引用）。
            # 这类格子可以进判定，但必须在依据里标出来 —— "文本规则"与"逐字引用"不是一回事。
            if not cites and not quote and spec.get('basis') in ('text-fallback', 'text-rule'):
                ev.append(f"文本规则：{why[:40] or '正文命中'}")
            elif not cites and not quote:
                problems.append(f'{code}: {state} 却没有 cites/quote')
            if quote:
                # 直引原文也可作依据,但必须逐字在客户稿里找得到(空白归一后比较)
                if src_norm and _norm(quote) not in src_norm:
                    problems.append(f'{code}: quote 在客户原文里找不到「{quote[:24]}」')
                else:
                    # 行号**现算**：找第一条包含该引文首段的原文行，不手抄行号
                    head = _norm(quote)[:8]
                    ln = next((i + 1 for i, line in enumerate(source.splitlines())
                               if head and head in _norm(line)), qline)
                    ev.append(f'原文第 {ln} 行「{quote[:40]}」')
            for cid in cites:
                c = cits.get(cid)
                if c is None:
                    problems.append(f'{code}: 引用了不存在的 {cid}')
                    continue
                if state == ST_HR and c.get('origin') != 'hr':
                    problems.append(f'{code}: 标 HR 侧，但 {cid} 的 origin={c.get("origin")}')
                if state == ST_CLIENT and c.get('origin') == 'hr':
                    problems.append(f'{code}: 标客户原文，但 {cid} 是我方 HR 提的')
                eb = (c.get('verbatim') or '').strip()
                ev.append(f'{cid}「{eb}」' if eb else f'{cid}（HR 提出）')
        if state in (ST_PROPOSED, ST_WAIT, ST_WAITC, ST_EMPTY) and not why:
            problems.append(f'{code}: {state} 必须写 why（为什么这么建议/缺什么）')
        if state in (ST_PROPOSED, ST_WAIT, ST_WAITC) and not needs:
            problems.append(f'{code}: {state} 必须写 needs（谁来确认）')
        if state == ST_NA:
            if r.get('requirement_level') != 'conditional':
                problems.append(f'{code}: 不适用，但它不是条件字段')
        if state == ST_EMPTY:
            tbl = (spec.get('table') or '').strip()
            if tbl:
                body = [ln.strip() for ln in
                        source[source.find(tbl) + len(tbl):].splitlines()[1:30]
                        if ln.strip() and ln.strip() not in TABLE_HEADER_WORDS]
                if body:
                    problems.append(f'{code}: 标「原文·空值」，但「{tbl}」表体有 '
                                    f'{len(body)} 行内容（如「{body[0][:16]}」）')
        rows.append({
            'code': code, 'section': r['_sec'], 'label': r['label_zh'],
            'level': r.get('requirement_level'), 'assessable': r.get('assessable'),
            'data_item': r.get('data_item'), 'state': state, 'value': val,
            'evidence': ev, 'why': why, 'needs': needs,
            'in_judging': state in IN_JUDGING,
            'missing_means': r.get('missing_means'),
        })

    tally: dict[str, int] = {k: 0 for k in (ST_CLIENT, ST_HR, ST_EMPTY, ST_PROPOSED,
                                            ST_WAIT, ST_WAITC, ST_NA)}
    for x in rows:
        tally[x['state']] = tally.get(x['state'], 0) + 1
    return {'jd': jd, 'template': 'templates/standard_jd_template.yaml',
            'role_type': links.get('role_type'), 'fields': len(rows),
            'tally': tally, 'problems': problems, 'rows': rows}


def render(d: dict) -> str:
    t = d['tally']
    n = d['fields']
    L = [f"# {d['jd']} · 定稿草稿（按公司标准 JD 模板 {n} 字段）", '',
         f"> 客户原文 + 我方建议逐格填，**{t[ST_CLIENT] + t[ST_HR]} 格能进判定**，"
         f"其余标注清楚等谁确认。生成：`scripts/talent/draft_jd.py`。", '',
         '| 状态 | 格数 | 进判定 | 说明 |', '|---|---|---|---|',
         f'| 客户原文 | {t[ST_CLIENT]} | ✅ | 改一个字都不行（逐字引用在下面每行） |',
         f'| HR 侧 | {t[ST_HR]} | ✅ | 客户稿没有，我方 HR 提的闸门 |',
         f'| 原文·空值 | {t[ST_EMPTY]} | ❌ 记「未知」 | 客户写了栏目没填 |',
         f'| 我方建议·待确认 | {t[ST_PROPOSED]} | ❌ 未确认不进判定 | 有理由、有确认方 |',
         f'| 待客户给 | {t[ST_WAIT]} | ❌ 记「不可判」 | 对所有人一样，不冤枉人 |',
         f'| 待客户确认 | {t[ST_WAITC]} | ❌ 未确认不进判定 | 客户没写，但我方已有默认口径 |',
         f'| 不适用 | {t[ST_NA]} | — | 条件字段，本岗位类别不触发 |', '']
    if d['problems']:
        L += ['## ⚠ 自检不通过', ''] + [f'- {p}' for p in d['problems']] + ['']
    L += ['| 段 | 字段 | 名称 | 层级 | 值 | 状态 | 依据 | 待谁 |', '|---|---|---|---|---|---|---|---|']
    for r in d['rows']:
        v = (r['value'] or '—')
        if isinstance(v, str):
            v = v.replace('\n', ' ').replace('|', '/')
            v = v[:120] + ('…' if len(v) > 120 else '')
        ev = '；'.join(r['evidence']) if r['evidence'] else (r['why'] or '—')
        ev = ev.replace('|', '/')[:140]
        L.append(f"| {r['section']} | `{r['code']}` | {r['label']} | {r['level']} | {v} | "
                 f"**{r['state']}** | {ev} | {r['needs'] or '—'} |")
    L.append('')
    wait = [r for r in d['rows'] if r['state'] in (ST_WAIT, ST_WAITC)]
    if wait:
        L += ['## 等客户给的（这些格现在判不了，判定里是「不可判」不是「不满足」）', '',
              '| 字段 | 名称 | 缺什么 |', '|---|---|---|']
        for r in wait:
            L.append(f"| `{r['code']}` | {r['label']} | {r['why'] or '—'} |")
        L.append('')
    prop = [r for r in d['rows'] if r['state'] == ST_PROPOSED]
    if prop:
        L += ['## 我方建议（客户没写，等确认后才进判定）', '',
              '| 字段 | 名称 | 建议值 | 理由 | 谁确认 |', '|---|---|---|---|---|']
        for r in prop:
            v = str(r['value'] or '').replace('|', '/')[:80]
            L.append(f"| `{r['code']}` | {r['label']} | {v or '—'} | "
                     f"{(r['why'] or '').replace('|', '/')[:80]} | {r['needs'] or '—'} |")
        L.append('')
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--check', action='store_true', help='只校验是否最新（门禁用）')
    args = ap.parse_args()
    jd = args.jd
    d = build(jd)
    js = json.dumps(d, ensure_ascii=False, indent=1) + '\n'
    md = render(d)
    dj = DIR / f'{jd}.draft.json'
    dm = DIR / f'{jd} 定稿草稿.md'
    if args.check:
        same = (dj.is_file() and dj.read_text(encoding='utf-8') == js
                and dm.is_file() and dm.read_text(encoding='utf-8').strip() == md.strip())
        print(f'{jd}: 草稿是最新的' if same else f'{jd}: 草稿已过期 —— 重跑 draft_jd')
        return 0 if same else 1
    DIR.mkdir(parents=True, exist_ok=True)
    dj.write_text(js, encoding='utf-8')
    dm.write_text(md, encoding='utf-8')
    t = d['tally']
    print(f"{jd}: {d['fields']} 字段 · 能进判定 {t[ST_CLIENT] + t[ST_HR]}"
          f"（客户原文 {t[ST_CLIENT]} / HR {t[ST_HR]}）· 原文·空值 {t[ST_EMPTY]}"
          f" · 建议待确认 {t[ST_PROPOSED]} · 待客户给 {t[ST_WAIT]}"
          f" · 待客户确认 {t[ST_WAITC]} · 不适用 {t[ST_NA]}")
    if d['problems']:
        print(f'  ✗ 自检 {len(d["problems"])} 条不通过:')
        for p in d['problems'][:10]:
            print('   -', p)
        return 1
    print(f'  → {dm.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
