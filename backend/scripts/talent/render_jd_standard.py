#!/usr/bin/env python3
"""把定稿草稿（`jd_draft/<JD>.draft.json`）渲染成**标准 40 格定稿**：`jd_docs/<JD>.定稿(标准40格).md`。

## 为什么要有这一份

`jd_docs/<JD>.定稿.md` 是按**旧的 field_schema（49 格）**渲染的，里面还带着页数、核准/审核/制订
这些我们已经从标准模板里删掉的字段。而"所有 JD 用同一份版式"是这一阶段的口径 ——
所以定稿必须按**标准模板 40 格**出。

## 三类来源，逐行标清

| 来源 | 含义 | 能不能进判定 |
|---|---|---|
| 客户原文 | 引用或原文直取（带引用 id / 原文行） | ✅ |
| HR 侧 | 我方 HR 提的闸门取值 | ✅ |
| **AI 模拟** | 客户没给、由 AI 按公司实务模拟（`basis: mock`） | ❌ 客户确认前不进判定 |
| 不适用 | 条件字段在本岗位类别下不触发 | — |

**AI 模拟必须逐条标出来**（这是用户 2026-11-24 明确接受的做法：先 mock 全，再等客户确认）。
一份看不出哪几格是模拟的定稿，等于把假设当事实发出去。

用法:
    python -m scripts.talent.render_jd_standard --jd 品质经理
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
DRAFT_DIR = TALENT / 'jd_draft'
OUT = TALENT / 'jd_docs'

MOCK = '我方建议·待确认'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    args = ap.parse_args()
    jd = args.jd
    d = json.loads((DRAFT_DIR / f'{jd}.draft.json').read_text(encoding='utf-8'))
    rows = d['rows']
    t = d['tally']

    def src(r: dict) -> str:
        if r['state'] in ('客户原文', 'HR 侧'):
            return r['state']
        if r['state'] == MOCK:
            return '**AI 模拟**'
        if r['state'] == '原文·空值':
            return '原文·空值'
        if r['state'] == '不适用':
            return '不适用'
        return r['state']

    mock = [r for r in rows if r['state'] == MOCK]
    judge = [r for r in rows if r['state'] in ('客户原文', 'HR 侧')]
    L: list[str] = []
    A = L.append
    A(f'# {jd} · 岗位说明书（定稿 · 标准 40 格）')
    A('')
    A(f'> 版式：`templates/standard_jd_template.yaml`（{d["fields"]} 格，所有 JD 共用同一份）。')
    A(f'> 来源分三类：**客户原文 {t["客户原文"]}** · **HR 侧 {t["HR 侧"]}** · '
      f'**AI 模拟 {t[MOCK]}**（客户确认前不进判定） · 不适用 {t["不适用"]}。')
    A('> AI 模拟的每一格都在下面逐行标出，也可以看文末「AI 模拟清单」一节。')
    A('')
    A(f'**能进判定的 {len(judge)}/{d["fields"]} 格**；'
      f'AI 模拟 {len(mock)} 格等客户/HR 确认。')
    A('')
    A('## 40 格逐行')
    A('')
    A('| 段 | 字段 | 名称 | 层级 | 值 | 来源 | 依据 / 待谁确认 |')
    A('|---|---|---|---|---|---|---|')
    for r in rows:
        v = r.get('value')
        v = str(v).replace('\n', ' ').replace('|', '/') if v is not None else '—'
        if len(v) > 150:
            v = v[:150] + '…'
        note = '；'.join(r.get('evidence') or []) or (r.get('why') or '—')
        if r['state'] == MOCK and r.get('needs'):
            note = f"{note}｜待 {r['needs']}"
        note = note.replace('|', '/')[:180]
        A(f"| {r['section']} | `{r['code']}` | {r['label']} | {r['level']} | {v} | {src(r)} | {note} |")
    A('')
    if mock:
        A('## AI 模拟清单（客户确认前不进判定）')
        A('')
        A('| 段 | 字段 | 名称 | 模拟值 | 为什么这么模拟 | 待谁确认 |')
        A('|---|---|---|---|---|---|')
        for r in mock:
            v = str(r.get('value') or '').replace('|', '/')[:70]
            why = (r.get('why') or '').replace('|', '/')[:90]
            A(f"| {r['section']} | `{r['code']}` | {r['label']} | {v or '—'} | {why} | "
              f"{(r.get('needs') or '—')} |")
        A('')
    A('---')
    A('')
    A('> 定稿口径：客户原文与 HR 侧可以进判定；**AI 模拟必须换成客户真实口径后**才能进判定。')
    A(f'> 生成：`scripts/talent/render_jd_standard.py --jd {jd}`（草稿见 `jd_draft/{jd}.fill.yaml`）。')
    A('')
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f'{jd}.定稿(标准40格).md'
    p.write_text('\n'.join(L), encoding='utf-8')
    print(f'{jd}: {d["fields"]} 格 · 客户原文 {t["客户原文"]} / HR {t["HR 侧"]} / '
          f'AI 模拟 {t[MOCK]} / 不适用 {t["不适用"]} → {p.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
