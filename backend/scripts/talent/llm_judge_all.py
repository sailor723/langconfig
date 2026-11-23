#!/usr/bin/env python3
"""批量跑 LLM 判定并存档 —— 组合 C 的第一步:先把"LLM 的判定"变成可重放的证据。

为什么要有这一步:第 5 步现在是「本体先判 → LLM 收口」,但 LLM 侧只有 10 份存档
(那 10 个面过的人),剩下 150 多人只能退回纯本体。缺的不是模型,是**没跑过**。

每条判定的输入只有三样(不许塞"建议结论"):
    ① 本体给的事实与闸门:每条要求的客户原文+行号、阈值/口径、本体结论与依据
    ② 简历 OCR 原文
    ③ 一面记录(有就带)

输出 `work/talent/llm_verdicts/<JD>/<人>.yaml`:
    prompt 哈希 + 输出哈希 + 模型/温度 + 逐条四态与引文
重跑读存档 = 可复算(重放);存档变了就是新的一次判定,必须重审。

用法:
    python -m scripts.talent.llm_judge_all --jd 品质经理 --scope shortlist --workers 6
    python -m scripts.talent.llm_judge_all --jd 品质经理 --fresh
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.compare_combos import build_prompt, ontology_packet  # noqa: E402
from scripts.talent.compare_llm_vs_ontology import call_llm, material, parse  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    load_candidates, overlay_hr, overlay_interview, overlay_llm, overlay_mock)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

ARCHIVE = ROOT / 'work' / 'talent' / 'llm_verdicts'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
CV_IV = ROOT / 'work' / 'talent' / 'cv_interview'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--scope', choices=['shortlist', 'interviewed', 'all'], default='shortlist')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--fresh', action='store_true', help='已有存档也重跑')
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个(调试用)')
    args = ap.parse_args()

    mode, _src = interview_policy.mode_for(args.jd)
    cat, lib, link, atts = load_inputs(args.jd)
    cvf = ROOT / 'work' / 'talent' / 'cv_facts.json'
    hrf = ROOT / 'work' / 'talent' / 'hr_facts.json'
    cv = json.loads(cvf.read_text(encoding='utf-8')) if cvf.is_file() else {}
    hr = json.loads(hrf.read_text(encoding='utf-8')) if hrf.is_file() else {}

    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_mock(cands)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}
    req_ids = [c['id'] for c in link['citations']]

    sl = yaml.safe_load((SHORTLIST / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
    if args.scope == 'shortlist':
        ids = [c for c in (sl.get('kept') or []) if c in by_id]
    elif args.scope == 'interviewed':
        ids = [f'cand_{p.stem}' for p in sorted(CV_IV.glob('*.yaml')) if f'cand_{p.stem}' in by_id]
    else:
        ids = [c['id'] for c in cands if not c['duplicate']]

    dest = ARCHIVE / args.jd
    dest.mkdir(parents=True, exist_ok=True)
    todo = [c for c in ids if args.fresh or not (dest / f"{c.replace('cand_', '')}.yaml").is_file()]
    if args.limit:
        todo = todo[:args.limit]
    print(f'待判 {len(todo)} / 目标 {len(ids)} 人(已有存档 {len(ids) - len(todo)} 份)')

    onto_all = {cid: judge_all(by_id[cid], link, lib, atts) for cid in ids}

    def work(cid: str):
        try:
            cv_text, iv_note = material(cid)
            packet = ontology_packet(cid, by_id[cid], link, lib, atts, onto_all[cid], cv, hr)
            prompt = build_prompt(packet, cv_text, iv_note, None)
            out, _t = call_llm(prompt)
            cells, missing = parse(out, req_ids)
            if missing:
                return cid, f'解析不全: 缺 {len(missing)} 条'
            arch = {
                'jd': args.jd, 'candidate': cid, 'schema': 'talent.llm_verdicts/v1',
                'model': 'deepseek-chat', 'temperature': 0,
                'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()[:16],
                'runs': {1: {'output_sha256': hashlib.sha256(out.encode()).hexdigest()[:16],
                             'chars': len(out)}},
                'replay_identical': None,
                'cells': {rid: {'state': cells[rid]['state'], 'why': cells[rid]['why'],
                                'quote': cells[rid]['quote']} for rid in req_ids},
                'note': '判定链重放用这份存档;存档变了就是新的一次判定,必须重审。',
            }
            (dest / f"{cid.replace('cand_', '')}.yaml").write_text(
                yaml.safe_dump(arch, allow_unicode=True, sort_keys=False), encoding='utf-8')
            return cid, None
        except Exception as exc:  # noqa: BLE001
            return cid, f'{type(exc).__name__}: {exc}'[:120]

    ok, fails = 0, []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (cid, err) in enumerate(ex.map(work, todo), 1):
            if err:
                fails.append((cid, err))
            else:
                ok += 1
            if i % 20 == 0 or i == len(todo):
                print(f'  {i}/{len(todo)} 成功 {ok} 失败 {len(fails)}', flush=True)

    print(f'\n完成:新增存档 {ok} 份 → {dest.relative_to(ROOT)}')
    for cid, err in fails[:5]:
        print(f'  失败 {cid.replace("cand_", "")[:34]}: {err}')
    total = len(list(dest.glob('*.yaml')))
    print(f'该 JD 现有存档 {total} 份')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
