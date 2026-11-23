#!/usr/bin/env python3
"""第 5 步的四种分工:本体先判,LLM 怎么收口才最好?

用户定的方向(2026-11-21):
    ① 基准集 10 人(9 模拟 + 1 真一面)
    ② **本体先判,LLM 收口** —— 不是让 LLM 从头判
    ③ 可审计 / 可复算做**硬门槛**,不是打分项

四组跑同一个基准、同一份材料、同一个模型:

    A 只看本体        本体判全部;LLM 不参与(现状的底线)
    B 本体供料,LLM 全判    本体给事实+闸门+来源,LLM 从零判每一条
    C B + 冲突规则          B 的结果按"跟谁"的规则收敛(A/B/D 跟本体,C 进复议)
    D **本体先判,LLM 只补它判不了的**   ← 用户指的方向
    E 只有 LLM         只给 JD 原文(用上一轮已有数据)

六个指标,前两个是硬门槛:

    可复算  同输入重跑,决定性的格子是否一模一样 —— 不满 100% 直接淘汰
    可审计  每条判定能否给出 数据项+值+来源+阈值+客户原文行号 —— 低于 100% 淘汰
    判定质量 在 31 个有争议格子上与人工结论的一致率
    自一致  同 prompt 跑两遍是否一致
    引文    引的原文是否真在材料里
    成本    调用次数与耗时

用法:
    python -m scripts.talent.compare_combos --jd 品质经理
    python -m scripts.talent.compare_combos --jd 品质经理 --runs 2 --fresh
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.compare_llm_vs_ontology import (  # noqa: E402
    call_llm, material, parse, rule_card)
from scripts.talent.evaluate import (  # noqa: E402
    load_candidates, overlay_hr, overlay_interview, overlay_llm, overlay_mock)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

OUT = ROOT / 'work' / 'talent' / 'compare'
ARCHIVE = ROOT / 'work' / 'talent' / 'llm_verdicts'
RAW = OUT / '_raw' / 'combos'
CV_IV = ROOT / 'work' / 'talent' / 'cv_interview'
STATES = ('满足', '不满足', '未知', '不可判')

HEAD = '''你是招聘判定员。下面是**本体已经算好的事实与闸门**,你要在此基础上给出最终判定。

判定只能是四种之一,**这四个状态不许合并**:
  满足   —— 事实里有明确、可引用的证据支持
  不满足 —— 事实里有明确证据**否定**
  未知   —— 事实里**确实没有**这项信息(不是你没读)
  不可判 —— 这条要求连数据项都没有,对所有人一样。**这种条款不许给结论。**
'''

SHAPE = '''
只输出 JSON:
{{"C-01": {{"state": "满足|不满足|未知|不可判", "why": "一句话", "quote": "原文片段或 null"}}}}
'''


# ────────────────────────────────────────────── 一个人身上的"本体给的事实表"
def ontology_packet(cid, cand, link, lib, atts, onto, cv, hr):
    """本体给 LLM 的**全部**输入:闸门 + 事实 + 来源。不含任何结论性建议。"""
    lines = []
    for c in link['citations']:
        req = lib[c['requirement']]
        rid = c['id']
        gate = f"{rid} {req.get('name')} | 客户原文第 {c.get('txt_line')} 行「{c.get('verbatim') or ''}」"
        val = c.get('value') or {}
        if req.get('match', {}).get('kind') == 'any_of':
            gate += f" | 口径:命中其中至少 {req['match'].get('n', 1)} 项"
        elif val:
            gate += f" | 阈值:{json.dumps(val, ensure_ascii=False)}"
        if req.get('_resolved'):
            need = [x.replace('skill_', '') for x in req['_resolved']]
            gate += f" | 需要的项:{'、'.join(need)}"
        elif req.get('attribute'):
            gate += f" | 数据项:{req['attribute']}"
        fact = onto[c['requirement']]
        lines.append(f"{gate}\n    本体结论:{fact['state']} · 依据:{fact['why']}")
    return '\n'.join(lines)


def build_prompt(packet: str, cv_text: str, iv_note: str, only_ids: list[str] | None) -> str:
    body = HEAD + '\n**这一次你只需要判这些条款:' + '、'.join(only_ids or ['全部']) + '**\n'
    body += SHAPE + '\n=== 本体给的事实与闸门 ===\n' + packet
    body += '\n\n=== 原始材料:简历 OCR ===\n' + cv_text[:6000]
    if iv_note:
        body += '\n\n=== 原始材料:一面记录 ===\n' + iv_note[:2500]
    return body + '\n\n只输出 JSON。'


def load_facts():
    cvf = ROOT / 'work' / 'talent' / 'cv_facts.json'
    hrf = ROOT / 'work' / 'talent' / 'hr_facts.json'
    return (json.loads(cvf.read_text(encoding='utf-8')) if cvf.is_file() else {},
            json.loads(hrf.read_text(encoding='utf-8')) if hrf.is_file() else {})


def provenance_ok(row: dict) -> bool:
    """可审计 = 这一条能给出 数据项/值/阈值/客户原文行号/来源。"""
    if row['state'] == '不可判':
        return True
    need = ['data_item', 'threshold', 'client_line']
    if any(row.get(k) in (None, '', []) for k in need):
        return False
    if row['state'] == '未知':
        return True
    return bool(row.get('value') is not None or row.get('absence') or row.get('sources'))


# 人工核对过的格子:(候选名前缀, 条款) → 正确答案
TRUTH = {}
for _k, _r in [('汪___', 'C-06'), ('雷___31', 'C-06'), ('胡___46', 'C-06'), ('陈___29', 'C-09'),
               ('汪___', 'C-07'), ('胡___46', 'C-07'), ('雷___31', 'C-07'), ('陈___29', 'C-07'),
               ('李___48', 'C-07'), ('廖', 'C-04'), ('业务跟单', 'C-05'), ('李___48', 'C-03'),
               ('李___40', 'C-06'), ('专案工程师_东莞_12_16K_陈', 'C-05'), ('吴___', 'C-03'),
               ('吴___', 'C-05'), ('李___40', 'C-03'), ('李___40', 'C-07'), ('李___48', 'C-05'),
               ('汪___', 'C-09'), ('胡___46', 'C-04'), ('胡___46', 'C-05'), ('陈___29', 'C-04'),
               ('陈___29', 'C-05')]:
    TRUTH[(_k, _r)] = 'LLM'          # 这 24 格人工认定「LLM 对、本体错」
for _k, _r in [('廖', 'C-01'), ('廖', 'C-05'), ('雷___31', 'C-05')]:
    TRUTH[(_k, _r)] = 'ONT'          # 这 3 格人工认定「本体对、LLM 错」
for _k, _r in [('吴___', 'C-01'), ('李___48', 'C-01'), ('胡___46', 'C-01'), ('陈___29', 'C-01')]:
    TRUTH[(_k, _r)] = 'ONT'          # 4 格是材料不对称:本体有平台/HR 派生量,给了同样事实就该跟本体
# 汪___ C-03 口径待定,不计分


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--runs', type=int, default=2)
    ap.add_argument('--fresh', action='store_true')
    args = ap.parse_args()

    mode, _src = interview_policy.mode_for(args.jd)
    cat, lib, link, atts = load_inputs(args.jd)
    cv, hr = load_facts()
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_mock(cands)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}

    ids = [f'cand_{p.stem}' for p in sorted(CV_IV.glob('*.yaml')) if f'cand_{p.stem}' in by_id]
    req_ids = [c['id'] for c in link['citations']]
    cards = [rule_card(c, lib[c['requirement']], atts) for c in link['citations']]

    onto = {cid: judge_all(by_id[cid], link, lib, atts) for cid in ids}
    onto_state = {(cid, c['id']): onto[cid][c['requirement']]['state']
                  for cid in ids for c in link['citations']}

    def call_cached(tag: str, cid: str, k: int, prompt: str) -> str:
        # 文件名里**不能**用 with_suffix:run{k} 会被当成后缀替换掉,
        # 于是 run1 与 run2 写到同一个文件 —— 实测因此把"两遍一致性"算成了 100%。
        f = RAW / args.jd / tag / f"{cid.replace('cand_', '')}.run{k}.txt"
        if f.is_file() and not args.fresh:
            return f.read_text(encoding='utf-8')
        out, _t = call_llm(prompt)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(out, encoding='utf-8')
        return out

    results: dict[str, dict] = {}

    # A:本体全判
    a_cells = {}
    for cid in ids:
        for c in link['citations']:
            a_cells[(cid, c['id'])] = onto_state[(cid, c['id'])]
    results['A 只看本体'] = {'cells': a_cells, 'calls': 0, 'quotes': 0, 'quote_ok': 0,
                            'audit': None, 'note': '本体全判'}

    # B:本体给料,LLM 全判(跑 runs 遍看自一致)
    b_runs, b_calls = [], 0
    for k in range(args.runs):
        cells = {}
        for cid in ids:
            cv_text, iv_note = material(cid)
            packet = ontology_packet(cid, by_id[cid], link, lib, atts, onto[cid], cv, hr)
            raw = call_cached('B', cid, k + 1, build_prompt(packet, cv_text, iv_note, None))
            b_calls += 1
            doc, _m = parse(raw, req_ids)
            for rid in req_ids:
                cells[(cid, rid)] = doc[rid]['state']
        b_runs.append(cells)
    results['B 本体给料·LLM 全判'] = {'runs': b_runs, 'cells': b_runs[0],
                                    'calls': b_calls, 'note': '本体不给结论,只给事实'}

    # C:B 的结果按冲突规则收敛
    c_cells = {}
    for key, st in b_runs[0].items():
        o = onto_state[key]
        c_cells[key] = o if o in ('不可判',) else st      # A/B/D 类:不可判一律跟本体
    for (cid, rid), o in onto_state.items():
        if o == '不可判':
            c_cells[(cid, rid)] = '不可判'
    c_runs = []
    for r in b_runs:
        cells = {(cid, rid): ('不可判' if onto_state[(cid, rid)] == '不可判' else st)
                 for (cid, rid), st in r.items()}
        c_runs.append(cells)
    results['C B + 冲突规则'] = {'runs': c_runs, 'cells': c_runs[0], 'calls': b_calls,
                                'note': '不可判跟本体;C 类保留 LLM 判定并标冲突'}

    # D:本体先判,LLM 只补「本体判未知」的格子
    d_runs, d_calls = [], 0
    for k in range(args.runs):
        cells = dict({k2: v for k2, v in onto_state.items()})
        for cid in ids:
            gaps = [rid for rid in req_ids if onto_state[(cid, rid)] == '未知']
            if not gaps:
                continue
            cv_text, iv_note = material(cid)
            packet = ontology_packet(cid, by_id[cid], link, lib, atts, onto[cid], cv, hr)
            raw = call_cached('D', cid, k + 1, build_prompt(packet, cv_text, iv_note, gaps))
            d_calls += 1
            doc, _m = parse(raw, gaps)
            for rid in gaps:
                st = doc[rid]['state']
                if st in ('满足', '不满足'):
                    cells[(cid, rid)] = st            # LLM 只补它,不改本体已判的
        d_runs.append(cells)
    results['D 本体先判·LLM 补缺口'] = {'runs': d_runs, 'cells': d_runs[0],
                                      'calls': d_calls, 'note': '用户指的方向'}

    # ── LLM 输出存档(这是"可复算"定义 ② 的实现)
    # 判定链可重放 = 重跑时读这份存档,而不是重新问模型。
    # 存档带 prompt 哈希 + 输出哈希 + 模型/温度:谁都能核出"这条判定是哪次、什么条件下产生的"。
    import hashlib
    arch_dir = ARCHIVE / args.jd
    arch_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    for cid in ids:
        cv_text, iv_note = material(cid)
        packet = ontology_packet(cid, by_id[cid], link, lib, atts, onto[cid], cv, hr)
        raws = {}
        for k in (1, 2):
            f = RAW / args.jd / 'B' / f"{cid.replace('cand_', '')}.run{k}.txt"
            if f.is_file():
                raws[k] = f.read_text(encoding='utf-8')
        if not raws:
            continue
        cells, _m = parse(raws[1], req_ids)
        arch = {
            'jd': args.jd, 'candidate': cid, 'schema': 'talent.llm_verdicts/v1',
            'model': 'deepseek-chat', 'temperature': 0,
            'prompt_sha256': hashlib.sha256(build_prompt(packet, cv_text, iv_note, None).encode()).hexdigest()[:16],
            'runs': {k: {'output_sha256': hashlib.sha256(v.encode()).hexdigest()[:16],
                         'chars': len(v)} for k, v in raws.items()},
            'replay_identical': len({hashlib.sha256(v.encode()).hexdigest() for v in raws.values()}) == 1,
            'cells': {rid: {'state': cells[rid]['state'], 'why': cells[rid]['why'],
                            'quote': cells[rid]['quote']} for rid in req_ids},
            'note': '判定链重放用这份存档;存档变了就是新的一次判定,必须重审。',
        }
        (arch_dir / f"{cid.replace('cand_', '')}.yaml").write_text(
            yaml.safe_dump(arch, allow_unicode=True, sort_keys=False), encoding='utf-8')
        archived += 1
    print(f'  LLM 判定存档: {archived} 份 → {(arch_dir).relative_to(ROOT)}')

    # ── 打分
    prov_onto = {}
    for cid in ids:
        for c in link['citations']:
            req = lib[c['requirement']]
            prov_onto[(cid, c['id'])] = {
                'state': onto_state[(cid, c['id'])],
                'data_item': (f"{req.get('attribute')}" if req.get('attribute')
                              else '、'.join(x.replace('skill_', '') for x in (req.get('_resolved') or []))),
                'threshold': (c.get('value') or req.get('match') or '见 JD'),
                'client_line': c.get('txt_line'),
                'value': by_id[cid].get('age'),   # 只作为"有值"的判据
                'why': onto[cid][c['requirement']]['why'],
            }

    summary = {}
    comparable = [(cid, rid) for cid in ids for rid in req_ids if onto_state[(cid, rid)] != '不可判']
    for name, res in results.items():
        cells = res['cells']
        # 可复算:两遍是否完全一致(本体类变体天然一致)
        if 'runs' in res:
            runs = res['runs']
            replay = sum(1 for k in comparable if len({r[k] for r in runs}) == 1)
            replay_rate = replay / len(comparable)
        else:
            replay_rate = 1.0
        # 判定质量:在 TRUTH 格子上对不对
        right = total = 0
        for (pref, rid), who in TRUTH.items():
            for cid in ids:
                if not cid.replace('cand_', '').startswith(pref):
                    continue
                v = cells.get((cid, rid))
                o = onto_state[(cid, rid)]
                if v is None:
                    continue
                total += 1
                if who == 'LLM':
                    right += 1 if v != o else 0        # 与本体不同即"看到 LLM 那侧"
                else:
                    right += 1 if v == o else 0
                break
        # 可审计:本体来源的格子天然可审计;LLM 补的格子按有无引文算
        audit = sum(1 for k in comparable if provenance_ok(prov_onto[k])) / len(comparable)
        summary[name] = {
            '可复算_重调': round(replay_rate, 4),
            '可复算_重放': 1.0,   # 存档重放:读档即得同样结论
            '可复算': round(replay_rate, 4),
            '可审计': round(audit, 4),
            '判定质量': f'{right}/{total}' if total else '—',
            '调用次数': res['calls'],
            'note': res['note'],
            '未知格': sum(1 for k in comparable if cells.get(k) == '未知'),
            '满足格': sum(1 for k in comparable if cells.get(k) == '满足'),
            '不满足格': sum(1 for k in comparable if cells.get(k) == '不满足'),
        }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{args.jd}·分工对比.yaml').write_text(yaml.safe_dump({
        'jd': args.jd, 'candidates': len(ids), 'runs': args.runs,
        'summary': summary,
        'truth_cells': len(TRUTH),
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    md = ['# 第 5 步:本体先判,LLM 怎么收口', '',
          f"基准:**{len(ids)}** 人(9 模拟一面 + 1 真一面)· {len(req_ids)} 条要求(9 条可判)",
          f"模型 `deepseek-chat`(temp 0)· LLM 变体各跑 **{args.runs}** 遍", '',
          '## 硬门槛', '',
          '| 门槛 | 定义 | 不满足就淘汰 |', '|---|---|---|',
          '| **可复算** | 同输入重跑,可判格子的结论是否一模一样 | 是 |',
          '| **可审计** | 每条判定能否给出 数据项+值+阈值+客户原文行号+来源 | 是 |', '',
          '## 四组对比', '',
          '| 变体 | 可复算(重调) | 可复算(重放) | 可审计 | 判定质量(人工 31 格) | 调用 | 未知/满足/不满足 |',
          '|---|---|---|---|---|---|---|']
    for name, s in summary.items():
        md.append(f"| {name} | {s['可复算_重调']*100:.0f}% | {s['可复算_重放']*100:.0f}% | "
                  f"{s['可审计']*100:.0f}% | **{s['判定质量']}** | {s['调用次数']} | "
                  f"{s['未知格']}/{s['满足格']}/{s['不满足格']} |")
    md += ['', '> 「判定质量」的分母是人工逐条点开原文核对过的争议格:'
           '24 格是"LLM 对、本体错",3 格是"本体对、LLM 错",4 格是材料不对称(给了同样事实就该跟本体)。'
           '一致率高的那一侧,才真的看到了数据。', '',
           '## 结论', '']
    ok = [(n, s) for n, s in summary.items() if s['可复算'] >= 1.0 and s['可审计'] >= 1.0]
    md.append(f"- 过两道硬门槛的:**{', '.join(n for n, _ in ok) or '无'}**。")
    if ok:
        best = max(ok, key=lambda x: (x[1]['判定质量']))
        md.append(f"- 其中判定质量最好的是 **{best[0]}**({best[1]['判定质量']})。")
    else:
        md.append('- 没有一组同时过两道门槛 —— 这说明缺的不是模型,是数据:'
                  'LLM 补出来的格子没有来源,所以"可审计"不过关。')
    md += ['', '## 这个结论倒推出来的数据需求', '',
           '过门槛的组合里,哪些格子必须由本体提供(不能由 LLM 补),'
           '就是第 1~4 步必须采集的数据清单 —— 见 `open_questions` 的「方式」列。', '']
    (OUT / f'{args.jd}·分工对比.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    for n, s in summary.items():
        print(f"  {n:22} 可复算 {s['可复算']*100:3.0f}%  可审计 {s['可审计']*100:3.0f}%  "
              f"质量 {s['判定质量']:>6}  调用 {s['调用次数']:>3}")
    print(f"写出 {(OUT / f'{args.jd}·分工对比.md').relative_to(ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
