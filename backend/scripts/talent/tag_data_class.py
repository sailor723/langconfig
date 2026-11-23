#!/usr/bin/env python3
"""给每条要求标「数据类别」—— 因为三类东西的"没有"含义完全不同。

    事实类 (fact)        年龄、学历、专业、年限、证照
                         → 有值就按阈值比;**没有值 = 未知**(他可能没填、也可能 OCR 没读到)
                         → 采集方式:证件(HR 邀约阶段就要)

    能力类 (capability)  英语、品质问题分析、品质工具、线束行业、客户验厂
                         → 有证据就按匹配口径判;**没有证据 = 未知**,不是不满足
                         → 采集方式:实测(业务现场出题)。**问不出来** ——
                           问"你懂不懂 SPC",回答永远是"懂"

    软素质 (soft)        沟通协调、抗压、稳定性
                         → 没有数据项,也没有刻度 → **不可判**,对所有人一样
                         → 要判必须先落一个可判的数据项(第 2 步的活)

这个分类不是学术分类,它决定三件事:① 没有数据时判什么状态 ② 谁去采 ③ 能不能拿它淘汰人。
之前没这个字段,代码就在 `judge_component` 里把「能力类没读到」当成了「不满足」——
实测把 148 个没在简历里写"品质问题分析"的人判成不合格。

用法:
    python -m scripts.talent.tag_data_class                     # 写入 requirement_library.yaml
    python -m scripts.talent.tag_data_class --check             # 只检查,不写
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

LIBRARY = ROOT / 'work' / 'talent' / 'requirement_library.yaml'

#: kind → 数据类别
MAP = {
    'threshold': 'fact',        # 年龄/学历/年限:有值就能比
    'enumerate': 'fact',        # 专业这类点名匹配:有值就能比
    'boolean': 'fact',
    'component': 'capability',  # 单个能力项
    'composite': 'capability',  # 多个能力项合成一条
    'unmeasurable': 'soft',     # 没有数据项
}

NOTE = {
    'fact': '没有值 → 未知(不是不满足);采集=证件/面谈',
    'capability': '没有证据 → 未知(不是不满足);采集=业务实测,问不出来',
    'soft': '没有数据项 → 不可判(对所有人一样);要判必须先落数据项',
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只报告,不写文件')
    args = ap.parse_args()

    doc = yaml.safe_load(LIBRARY.read_text(encoding='utf-8')) or {}
    reqs = doc.get('requirements') or []
    before = collections.Counter(r.get('data_class') for r in reqs)
    unknown_kind, changed = [], 0
    for r in reqs:
        cls = MAP.get(str(r.get('kind') or ''))
        if not cls:
            unknown_kind.append((r['id'], r.get('kind')))
            continue
        if r.get('data_class') != cls:
            r['data_class'] = cls
            changed += 1
        # 一致性:能力类必须有组件;软素质不许有组件
        if cls == 'capability' and not (r.get('components') or r.get('attribute')):
            print(f"  ⚠ {r['id']} 标了 capability 但没有组件")
        if cls == 'soft' and r.get('components'):
            print(f"  ⚠ {r['id']} 标了 soft 却有组件")

    after = collections.Counter(r.get('data_class') for r in reqs)
    print(f'要求 {len(reqs)} 条 · data_class 前 {dict(before)} · 后 {dict(after)} · 变更 {changed} 条')
    for cid, k in unknown_kind:
        print(f'  ⚠ {cid} 的 kind={k!r} 没有对应数据类别')

    if args.check:
        print('(--check:未写文件)')
        return 0
    if changed:
        header = (
            '# 数据类别(2026-11-21 加,由 scripts/talent/tag_data_class.py 写入)\n'
            '#   fact       有值就按阈值比;没有值 = 未知(不是不满足)。采集=证件/面谈\n'
            '#   capability 有证据就按匹配口径判;没有证据 = 未知(不是不满足)。采集=业务实测,问不出来\n'
            '#   soft       没有数据项 → 不可判(对所有人一样);要判必须先落数据项\n')
        text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        LIBRARY.write_text(header + text, encoding='utf-8')
        print(f'已写入 {LIBRARY.relative_to(ROOT)}')
    else:
        print('没有变化')
    return 0


if __name__ == '__main__':
    sys.exit(main())
