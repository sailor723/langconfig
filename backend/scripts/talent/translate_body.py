#!/usr/bin/env python3
"""把 `talent_steps` 七张章节页的**正文**逐块翻成中文，保留行内代码与强调。

## 为什么不是"改 i18n 表"

`translate_page()` 是按**原文字串**做替换的，适用于标题这类连续文本。
正文里到处是行内标签（`<code>:Candidate</code>`、`<strong>candidates exist</strong>`），
整段原文在 HTML 里根本不是一个连续串 —— 塞进 i18n 表也一条都命中不了
（这正是 retail 那 52 条"看着完整、其实从没生效"的老问题）。

所以正文用这个脚本直接改文件：每个被翻译的块拆成
`文本段 + {n}（行内标签） + 文本段 …`，翻译只替换文本段，行内标签与它的内容原样保留。

## 用法

    python -m scripts.talent.translate_body --page 1 --map tutorials/step1.zh.json
    python -m scripts.talent.translate_body --page 1 --list      # 只打印待译模板

模板里的 `{n}` 就是行内标签的占位（n 从 0 起，按出现顺序）。产物写回原文件。
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'backend' / 'features' / 'ontology' / 'profiles' / 'talent_steps' / 'tutorial'

#: 要处理的块级标签（正文段落、列表项、小标题、标签行）
BLOCK = re.compile(r'<(p|li|h2|h3|summary)([^>]*)>(.*?)</\1>', re.S)
LABEL = re.compile(r'<div class="label">(.*?)</div>', re.S)


def visible(inner: str) -> str:
    """块的可见文本(去标签、压空白) —— 用作翻译表的键。"""
    txt = re.sub(r'<[^>]+>', ' ', inner)
    txt = htmlmod.unescape(txt)
    return re.sub(r'\s+', ' ', txt).strip()


def segments(inner: str) -> tuple[str, list[str]]:
    """把块内 HTML 拆成「带 {n} 占位的模板」+「占位对应的原始标签 HTML」。"""
    tags, out, pos = [], [], 0
    for m in re.finditer(r'<[^>]+>.*?</[^>]+>', inner, re.S):
        out.append(inner[pos:m.start()])
        out.append('{%d}' % len(tags))
        tags.append(m.group(0))
        pos = m.end()
    out.append(inner[pos:])
    text = ''.join(out)
    text = re.sub(r'\s+', ' ', text).strip()
    return text, tags


def rebuild(template: str, tags: list[str]) -> str:
    out = template
    for i, tag in enumerate(tags):
        out = out.replace('{%d}' % i, tag)
    return re.sub(r'\s+', ' ', out).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', type=int, required=True)
    ap.add_argument('--map', help='JSON: {"模板": "中文模板"}')
    ap.add_argument('--list', action='store_true', help='只打印待译模板（带占位）')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    path = BASE / f'step{args.page}.html'
    original = path.read_text(encoding='utf-8')
    table = {}
    if args.map:
        table = json.loads(pathlib.Path(args.map).read_text(encoding='utf-8'))

    blocks = [(m.start(3), m.end(3), m.group(3)) for m in BLOCK.finditer(original)]
    blocks += [(m.start(1), m.end(1), m.group(1)) for m in LABEL.finditer(original)]
    blocks.sort()

    missing, done = [], 0
    out = []
    pos = 0
    for start, end, inner in blocks:
        if start < pos:
            continue
        key = visible(inner)
        if not re.search(r'[A-Za-z]{3,}', key):
            continue                      # 纯代码/纯数字块，不译
        zh = table.get(key)
        if not zh:
            missing.append(key)
            continue
        out.append(original[pos:start])
        out.append(zh)                    # 译文自带需要的行内标签
        pos = end
        done += 1
    out.append(original[pos:])
    new = ''.join(out)

    if args.list:
        print(f'step{args.page}: {len(missing)} 块待译')
        for t in missing:
            print(json.dumps(t, ensure_ascii=False))
        return 0
    if missing:
        print(f'step{args.page}: {len(missing)} 块没有译文，**不写文件**（半翻译比不翻更难查）')
        for t in missing[:5]:
            print('   缺:', json.dumps(t, ensure_ascii=False)[:120])
        return 1
    if not args.dry:
        path.write_text(new, encoding='utf-8')
    print(f'step{args.page}: 译了 {done} 块' + ('（--dry，未写盘）' if args.dry else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
