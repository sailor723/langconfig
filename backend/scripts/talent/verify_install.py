#!/usr/bin/env python3
"""**装完/更新后自检**：这台机器能不能像我这台一样跑 talent 的整条链。

## 为什么要有它

同事的流程是「git pull → seed in → 起服务」，但 talent 的链跨三种东西：

    ① 仓库里的文件（标准 YAML / 模板 / 产物 / mock 数据）  ← git 负责
    ② 数据库里的行（五个 agent、120 个 skill、settings）    ← seed 负责
    ③ 本机归档（cv_text / llm_verdicts / talent_db）        ← **不是必须**，缺了要能说清缺什么

一次说清"哪一层没到位、该怎么补"，比让他去翻门禁的红字快得多。

用法（在 backend 目录）:
    .venv/bin/python -m scripts.talent.verify_install            # 只查文件层（不连库）
    .venv/bin/python -m scripts.talent.verify_install --online   # 额外查服务与 agent/skill
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'

#: 缺一条链就断的文件（缺了必须报，不是"可选"）
REQUIRED = [
    'templates/standard_jd_template.yaml',
    'templates/standard_cv_template.yaml',
    'field_schema.yaml', 'component_catalog.yaml', 'requirement_library.yaml',
    'labels_en.yaml', 'company_profile.yaml', 'fake_names.yaml',
    'cv_facts.json', 'hr_facts.json', 'cv_quality.json', 'priority_catalog.yaml',
    'interview_policy.yaml', 'catalog.json', 'CATALOG.md', 'OVERVIEW.md', 'flow.svg',
]
#: 每份 JD 都要有的（按 jd_links 里的 JD 名去核）
PER_JD = [
    ('jd_links/{jd}.yaml', '引用文件'),
    ('jd_links/_source/{jd}.txt', '客户原文'),
    ('jd_draft/{jd}.draft.json', '定稿草稿'),
    ('jd_draft/{jd}.fill.yaml', '填充稿'),
    ('jd_docs/{jd}.定稿(标准40格).md', '标准 40 格定稿'),
]
#: 缺了不影响跑，但要如实说（第 3/5 步的部分产物或重算能力）
OPTIONAL_HINT = [
    ('cv_text', '270 份简历正文：只有在**重新抽取**简历事实时才需要；clone 里没有是正常的'),
    ('llm_verdicts', '重放实验归档：教程第 13 步的数字只有做过实验的机器能重算（门禁会打 NOT RUN）'),
    ('cv_draft', '大模型原始输出：可追溯用，不影响判定'),
]


def _jds() -> list[str]:
    p = TALENT / 'jd_links'
    return sorted(x.stem for x in p.glob('*.yaml')) if p.is_dir() else []


def check_files() -> int:
    bad = 0
    print('① 文件层（仓库负责）')
    for rel in REQUIRED:
        ok = (TALENT / rel).is_file()
        print(f"   {'✔' if ok else '✘'} {rel}")
        bad += 0 if ok else 1
    jds = _jds()
    print(f'   · 找到 {len(jds)} 份 JD：{"、".join(jds) or "（没有）"}')
    for jd in jds:
        for tpl, label in PER_JD:
            rel = tpl.format(jd=jd)
            ok = (TALENT / rel).is_file()
            if not ok:
                print(f"   ✘ {jd} 缺{label}：{rel}")
                bad += 1
    print()
    print('② 本机归档（非必须，缺了要知道缺什么）')
    for d, why in OPTIONAL_HINT:
        have = (TALENT / d).is_dir()
        print(f"   {'✔' if have else '·'} {d}/ —— {why}")
    return bad


def check_templates() -> int:
    print()
    print('③ 模板与定稿一致性（可现算）')
    bad = 0
    try:
        sys.path.insert(0, str(ROOT / 'backend'))
        from services.talent_gap import default_jd, gap_for
        dj = default_jd()
        g = gap_for(dj)
        print(f'   ✔ 默认 JD = {dj} · 缺口口径 {g["source"]} · 能判 {g["in_judging"]}/{g["template_fields"]}')
    except Exception as exc:                                        # noqa: BLE001
        print(f'   ✘ 缺口算不出来：{type(exc).__name__}: {exc}')
        bad += 1
    return bad


def check_online(base: str) -> int:
    print()
    print(f'④ 服务层（{base}）')
    bad = 0
    try:
        with urllib.request.urlopen(f'{base}/api/talent/docs', timeout=8) as r:
            d = json.loads(r.read().decode('utf-8'))
        print(f'   ✔ /api/talent/docs · 默认 JD = {d.get("default_jd")} · JD {len(d.get("jds") or [])} 份')
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f'   ✘ 连不上或返回异常：{exc} —— 先起服务（bash start.sh）')
        return bad + 1
    try:
        with urllib.request.urlopen(f'{base}/api/skills?limit=500', timeout=8) as r:
            raw = json.loads(r.read().decode('utf-8'))
        rows = raw if isinstance(raw, list) else (raw.get('data') or raw.get('skills') or [])
        ids = {str(x.get('skill_id') or x.get('id')) for x in rows}
        need = {'talent-jd-draft', 'talent-jd-final', 'talent-cv-shortlist',
                'talent-interview', 'talent-final-pick'}
        miss = sorted(need - ids)
        print(f"   {'✔' if not miss else '✘'} talent 技能 {'全在' if not miss else '缺：' + '、'.join(miss)}"
              f"（共 {len(ids)} 个技能）")
        if miss:
            print('      → 先跑 seed：backend/.venv/bin/python scripts/seeds/in/seed_all.py')
            bad += 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f'   ✘ 技能清单读不到：{exc}')
        bad += 1
    try:
        with urllib.request.urlopen(f'{base}/api/deepagents/?public_only=false', timeout=8) as r:
            raw = json.loads(r.read().decode('utf-8'))
        rows = raw if isinstance(raw, list) else (raw.get('data') or raw.get('agents') or [])
        names = [str(x.get('name')) for x in rows]
        talent = [n for n in names if n.startswith('Talent · ')]
        hint = (' → 跑 seed_all.py（服务在跑时会连它们一起注册）'
                ' 或 backend/.venv/bin/python scripts/seeds/in/seed_talent_agents.py --apply')
        print(f"   {'✔' if talent else '✘'} Talent agent {len(talent)} 个"
              + ('' if talent else hint))
        for n in sorted(talent):
            print(f'      · {n}')
        bad += 0 if talent else 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f'   ✘ agent 清单读不到：{exc}')
        bad += 1
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--online', action='store_true', help='额外查服务、技能、agent')
    ap.add_argument('--base', default='http://127.0.0.1:8765')
    args = ap.parse_args()
    bad = check_files() + check_templates()
    if args.online:
        bad += check_online(args.base)
    print()
    if bad:
        print(f'自检：{bad} 项没到位（上面 ✘ 的那几行就是要补的）')
        return 1
    print('自检：全通过 —— 这台机器可以按 OVERVIEW 的流程跑 talent。'
          + ('' if args.online else '（加 --online 再查服务与 agent）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
