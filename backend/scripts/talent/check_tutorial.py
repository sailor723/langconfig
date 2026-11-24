#!/usr/bin/env python3
"""教程 v2 的门禁 —— 三件必须机器查的事，外加一条不许撒谎的规矩。

1. **数字没有过期**：`facts.json` 必须等于现场重算的结果；任何一步产物变了而没重跑，
   这里就红。教程里的数字一旦可以过期，它就从教材退化成散文。
2. **正文没有手写数字**：md 里出现的每一个阿拉伯数字，都必须能在 facts 里找到。
   找不到 = 有人手打了一个数，那个数没人负责。
3. **每一步都有反证，且反证真的变了**：`falsify` 里任何一条 `changed: false`
   都说明这个前提本来没起作用 —— 那一步的"反证"是装饰。

另外查两条结构：十四步齐全；每步都写了「这一步拒绝什么」。

用法:
    python -m scripts.talent.check_tutorial            # 红了退出码 1
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent import build_tutorial_v2 as BT  # noqa: E402
from scripts.talent import tutorial_facts as TF  # noqa: E402

COMPLAINTS: list[str] = []
PASSED = 0


def ok(label: str, cond: bool, detail: str = '') -> None:
    global PASSED
    if cond:
        PASSED += 1
    else:
        COMPLAINTS.append(f'{label} — {detail}')


def allowed_numbers(facts: dict) -> set[str]:
    """facts 里出现过的数字 + 由它们算出的百分比（模板里就是这么算的）。"""
    allowed = set(re.findall(r'\d+(?:\.\d+)?', json.dumps(facts, ensure_ascii=False)))
    s13 = facts['step13_replay']
    if s13.get('replay_rate') is not None:
        allowed.add(str(round(s13['replay_rate'] * 100)))
    if s13.get('cell_agreement') is not None:
        allowed.add(str(round(s13['cell_agreement'] * 1000) / 10).rstrip('0').rstrip('.')
                    if round(s13['cell_agreement'] * 1000) % 10 else
                    str(round(s13['cell_agreement'] * 100)))
    # 实验表里的比例也会被写成百分比
    for v in (facts['step9_division'].get('experiment') or {}).values():
        for k in ('可复算_重放', '可复算_重调'):
            if v.get(k) is not None:
                allowed.add(str(round(v[k] * 100)))
    # 允许常见整数形式的等价值（1 与 1.0 不该互判为错）
    for a in list(allowed):
        if '.' in a:
            try:
                allowed.add(str(int(float(a))))
            except ValueError:
                pass
    return allowed


def main() -> int:
    facts_path = TF.TALENT / 'tutorial' / 'facts.json'
    md_path = TF.TALENT / 'tutorial' / 'TUTORIAL_v2.md'
    if not facts_path.is_file() or not md_path.is_file():
        print('缺产物：先跑 tutorial_facts 和 build_tutorial_v2')
        return 2

    # 教程里有 40 组「重放实验」的数字，它们来自 **本机归档**（llm_verdicts/ 等，
    # 按 .gitignore 不进库：270 份大模型原始输出，进库只会让 diff 失去意义）。
    # 同事 clone 下来没有这份归档 → 重算结果必然不同，这时**不能判红**：
    # 判红会让人以为"教程坏了"，实际只是"这台机器没做过那些实验"。
    if not (TF.TALENT / 'llm_verdicts').is_dir():
        print('NOT RUN — 缺本机归档 llm_verdicts/（教程第 13 步的重放实验数字只有做过实验的机器能重算）。'
              '\n  这不是失败：clone 里本来就没有这份归档；装了它的机器会自动恢复校验。')
        return 0

    saved = json.loads(facts_path.read_text(encoding='utf-8'))
    fresh = json.loads(json.dumps(TF.collect(), ensure_ascii=False))  # 产物形态比较
    ok('facts.json 是现场重算的结果', saved == fresh,
       '产物变了但 facts 没重跑 —— 教程里的数字已经过期')

    md_on_disk = md_path.read_text(encoding='utf-8')
    ok('TUTORIAL_v2.md 与 facts 渲染结果一致', md_on_disk == BT.render(saved),
       '有人手改过 md，或者改了模板没重新生成')

    # 正文数字必须都能追到 facts
    allowed = allowed_numbers(saved)
    tokens = re.findall(r'\d+(?:\.\d+)?', md_on_disk)
    stray = sorted({t for t in tokens if t not in allowed})
    ok('正文里没有手写数字', not stray,
       f'这些数字在 facts 里找不到：{stray[:5]}')

    # 十四步齐全 + 每步都有反证与拒绝
    steps = [f'第{cn}步 · ' for cn in BT.CN[1:15]]
    missing = [s for s in steps if s not in md_on_disk]
    ok('十四步齐全', not missing, f'缺：{missing}')

    sections = re.split(r'\n## ', md_on_disk)
    step_secs = [s for s in sections if re.match(r'第[一二三四五六七八九十]+步', s)]
    ok('每步都有一段', len(step_secs) == 14, f'实际 {len(step_secs)} 段')
    no_falsify = [s.splitlines()[0] for s in step_secs if '反证' not in s]
    ok('每步都有反证', not no_falsify, f'缺反证：{no_falsify}')
    no_refuse = [s.splitlines()[0] for s in step_secs if '这一步拒绝' not in s]
    ok('每步都写了「这一步拒绝什么」', not no_refuse, f'缺：{no_refuse}')

    # 反证必须真的变
    dead = [k for k, v in saved['falsify'].items() if not v.get('changed')]
    ok('每条反证都真的改变了数字', not dead, f'这些反证不起作用：{dead}')

    # 一条硬的：一面数据里真访谈必须是 0 才允许写"演练"
    pt = saved.get('pipeline_truth') or {}
    ok('演练状态与一面记录一致',
       (pt.get('real_interview_docs') == 0) == ('演练' in md_on_disk),
       f"真访谈 {pt.get('real_interview_docs')} 份，md 的「演练」标注要对得上")

    print(f'\n{len(COMPLAINTS) + PASSED} checks · {len(COMPLAINTS)} failed'
          + ('' if COMPLAINTS else ' · green'))
    for c in COMPLAINTS:
        print(f'  [FAIL] {c}')
    return 0 if not COMPLAINTS else 1


if __name__ == '__main__':
    sys.exit(main())
