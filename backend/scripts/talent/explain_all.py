#!/usr/bin/env python3
"""把**所有 JD** 的判定说明重生成一遍。

为什么需要它:同一个人可能同时出现在两份 JD 的面试名单里(实测:陈___5年 同时在
`品质经理` 与 `业务跟单`)。这时只重生成一份 JD 的判定说明,另一份里这个人的说明
立刻变成"输入已变,必须重生成" —— 门禁红得没道理,却是真的。

一次电话改了共享的一面数据,就该把所有受影响 JD 的说明一起刷新。

用法:
    python -m scripts.talent.explain_all
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

VERDICTS = ROOT / 'work' / 'talent' / 'verdicts'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'


def main() -> int:
    jds = sorted(p.name for p in VERDICTS.iterdir() if p.is_dir()) if VERDICTS.is_dir() else []
    if not jds:
        print('还没有任何判定说明目录')
        return 0
    failed = 0
    for jd in jds:
        lst = SHORTLIST / f'{jd}.面试名单.yaml'
        if not lst.is_file():
            print(f'  {jd}: 没有面试名单,跳过')
            continue
        proc = subprocess.run([sys.executable, '-m', 'scripts.talent.explain_rejection',
                               '--jd', jd, '--shortlist'],
                              cwd=str(BACKEND), capture_output=True, text=True)
        tail = ((proc.stdout or '') + (proc.stderr or '')).strip().splitlines()
        print(f'  {jd}: {tail[-1] if tail else "(无输出)"}')
        if proc.returncode != 0:
            failed += 1
    print(f'\n刷新 {len(jds)} 份 JD 的判定说明' + (f' · {failed} 份失败' if failed else ' · 全部成功'))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
