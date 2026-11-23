#!/usr/bin/env python3
"""把一份 JD 的 CV 定稿全部重渲染一遍。

第 4 步(代拟)之后必须逐份重渲染,否则档案上的值还是旧的 —— 而"逐份"意味着
39 次命令行。跑一次代拟要记得紧跟 39 条命令,是人都会漏。

用法:
    python -m scripts.talent.render_all_cv --jd 品质经理
    python -m scripts.talent.render_all_cv --all
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
INTERVIEW = ROOT / 'work' / 'talent' / 'cv_interview'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    jds = ([p.stem.replace('.面试名单', '') for p in sorted(SHORTLIST.glob('*.面试名单.yaml'))]
           if args.all else ([args.jd] if args.jd else []))
    if not jds:
        ap.error('给 --jd <JD> 或 --all')

    made = failed = 0
    for jd in jds:
        lst = SHORTLIST / f'{jd}.面试名单.yaml'
        ids = []
        if lst.is_file():
            doc = yaml.safe_load(lst.read_text(encoding='utf-8')) or {}
            ids = [c for c in (doc.get('selected') or [])
                   if (INTERVIEW / f"{str(c).replace('cand_', '')}.yaml").is_file()]
        if not ids and args.jd:
            # 面试名单没了就退回"有档案的全渲染",总比一份都不出好
            ids = [f"cand_{p.stem}" for p in INTERVIEW.glob('*.yaml')]
        for cid in ids:
            proc = subprocess.run([sys.executable, '-m', 'scripts.talent.render_cv_final',
                                   '--id', str(cid)],
                                  cwd=str(BACKEND), capture_output=True, text=True)
            if proc.returncode == 0:
                made += 1
            else:
                failed += 1
                print(f'  ✗ {str(cid).replace("cand_", "")[:34]} '
                      f'{(proc.stderr or "").strip().splitlines()[-1:] or ""}')
        print(f'  {jd}: {len(ids)} 份 → 成功 {made} · 失败 {failed}')
    print(f'\n重渲染 {made} 份定稿' + (f' · {failed} 份失败' if failed else ' · 全部成功'))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
