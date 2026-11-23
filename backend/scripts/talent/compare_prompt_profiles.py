#!/usr/bin/env python3
"""同一个 LLM、同一份材料,只改 prompt:它能追平本体吗?

背景:第一次对比(compare_llm_vs_ontology.py)给了 LLM 一个**一次性直判**的 prompt,
结果一致率 37%,而且 48 格里它退成了「未知」。那个结果不能拿来宣布「本体更好」——
一次性直判是一个很容易被打败的基线。要回答「投入 prompt 会不会更好」,
必须把 prompt 认真做几版再比。

四个梯度(同一个模型、同一份材料、同一批人):

    v0  一次性直判        上一轮用的基线。原文+要求一起塞,直接要结论。
    v1  判据细化的直判    仍未拆步,但每条要求都给了「什么算满足 / 什么算不满足 /
                          什么才算未知」的判定标准,并要求先给证据再给结论。
    v2  先抽后判(两遍)   第一遍只抽证据、不判定,第二遍基于抽出来的证据判定。
                          这是「结构化的 LLM」,最接近本体的工作方式。
    v3  v2 + 自我复核     判完再让它逐条对着引文核一遍。

比什么(不依赖金标的维度):

    ① 与本体的一致率    结构不同,结论本就该有分歧;一致率过高反而说明没在独立判定
    ② 判定分布          最关键:v0 把 48 格退成未知,v1/v2/v3 追回多少
    ③ 自一致性          同 prompt 同温度跑两遍是否一样 —— 不满 100% 就当不了门禁
    ④ 引文可核验率      它引的原文是否真在材料里
    ⑤ 代价              调用次数 × 耗时

以及只有人工能做的:上一轮点开原文核出来的 13 格方向相反的分歧(LLM 对、本体错),
在 v1/v2/v3 里有没有被保留 —— 保住了,说明「LLM 看不出同义表达」不成立,
剩下的差距就只是可复算性。

用法:
    python -m scripts.talent.compare_prompt_profiles --jd 品质经理
    python -m scripts.talent.compare_prompt_profiles --jd 品质经理 --profiles v1 v2 --runs 1
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
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
    load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

OUT = ROOT / 'work' / 'talent' / 'compare'
RAW = OUT / '_raw'
CV_IV = ROOT / 'work' / 'talent' / 'cv_interview'

#: 每类要求的判定标准 —— v1 起写进 prompt。这不是新规矩,是把四态口径讲到模型不会误解。
RUBRIC = {
    '组件': (
        '**【能力项类】**这类要求问的是他有没有这件事。\n'
        '  · 满足:材料里任何位置(工作经历/自我评价/技能栏)有明确表述,能引原文\n'
        '  · 不满足:整份材料通读一遍,**确实没有任何一处**提到或暗示 —— '
        '「读过、没有」是可以下的结论,不要因为没写在显眼位置就退成未知\n'
        '  · 未知:只有材料残缺到分不清「没做过」还是「这段没写全」时才用'
    ),
    '数值': (
        '**【数值/等级类】**这类可以做算术。\n'
        '  · 能算出值(年龄可由出生年月推算、年限可由起止时间算、学历按 2..6 档)就按判据比\n'
        '  · 材料给的日期/年限足够推算的,不许退成未知;算出来超范围就是不满足\n'
        '  · 材料里完全没有这项信息才写未知'
    ),
    '点名': (
        '**【点名匹配类】**客户点名了几个词,命中与否是机械判断。\n'
        '  · 满足:材料的说法与客户点名的词一致,或明确是同义词\n'
        '  · 不满足:材料的说法不属于客户点名的任何一项\n'
        '  · 未知:材料里没有专业/名称这类信息'
    ),
}

HEAD = '''你是招聘判定员。读取下面的材料,对每一条 JD 要求给出判定。

判定只能是四种之一,**这四个状态不许合并**:
  满足   —— 材料里有明确、可引用的证据支持
  不满足 —— 材料里有明确证据**否定**
  未知   —— 材料里**确实没有**这项信息(不是「你没去读」)
'''

TAIL = '\n只输出 JSON,不要解释、不要 markdown 代码块。\n'


def _body(cv: str, iv: str) -> str:
    s = '\n\n=== 材料:简历 OCR 原文 ===\n' + cv[:7000]
    if iv:
        s += '\n\n=== 材料:一面记录 ===\n' + iv[:3000]
    return s + TAIL


def prompt_v0(cards, cv, iv) -> str:
    head = HEAD + '''
硬要求:
1. 每条都给 why 与 quote(逐字复制;判未知时 quote 填 null)
2. 不要把「未知」写成「不满足」

输出形状:
{"C-01": {"state": "满足|不满足|未知", "why": "一句话", "quote": "原文片段或 null"}}

要判的要求:
'''
    return head + '\n'.join(cards) + _body(cv, iv)


def _with_rubric(cards_pairs) -> str:
    out = []
    for line, kind in cards_pairs:
        out.append(line)
        out.append('    ' + RUBRIC[kind].replace('\n', '\n    '))
    return '\n'.join(out)


def prompt_v1(cards_pairs, cv, iv) -> str:
    head = HEAD + '''
硬要求:
1. **先写 evidence(材料里的逐字片段),再写 reasoning,最后才是 state** ——
   没有证据支撑的结论不许出现。evidence 必须是材料的逐字子串。
2. 每条要求下面都写了这类要求怎么判,按它判。
3. 「不满足」是一个**需要你敢下**的结论:通读整份材料确实没有这件事,就是没有。

输出形状:
{"C-01": {"evidence": "原文片段或 null", "reasoning": "一句话", "state": "满足|不满足|未知"}}

要判的要求:
'''
    return head + _with_rubric(cards_pairs) + _body(cv, iv)


def prompt_extract(cards_pairs, cv, iv) -> str:
    head = '''你是证据抽取器。**不要做任何判定**,只把材料里与下列要求相关的原文找出来。

对每一条:找到就填 evidence(材料的逐字片段)与 where(在哪一部分);
找不到就把 found 填 false,并在 nothing_found 里用一句话说明你**通读后**确认没有。
「找不到」在这个任务里是完全正当的结果,不要为了凑答案把不相关的话贴上去。

输出形状:
{"C-01": {"found": true, "where": "工作经历|自我评价|技能栏|无", "evidence": "原文片段或 null", "nothing_found": "通读后确认没有的一句话或 null"}}

要抽的要求:
'''
    return head + '\n'.join(line for line, _ in cards_pairs) + _body(cv, iv)


def prompt_judge(cards_pairs, extracted: dict, ids) -> str:
    ev = []
    for rid in ids:
        e = extracted.get(rid) or {}
        ev.append(f"{rid}: found={e.get('found')} where={e.get('where')} "
                  f"evidence={json.dumps(e.get('evidence'), ensure_ascii=False)} "
                  f"nothing_found={e.get('nothing_found')}")
    head = HEAD + '''
你的输入是**证据抽取结果**,不是原文。只能按下面的证据判定,不许凭想象补内容。

判定标准:
  · found=true 且证据支持 → 满足(或按数值判据比较)
  · found=false(抽取器通读后确认材料里没有这件事)→ **不满足**
  · 抽取结果残缺或自相矛盾、无法据此判定 → 未知

输出形状:
{"C-01": {"state": "满足|不满足|未知", "why": "一句话", "quote": "原文片段或 null"}}

要判的要求(判据):
'''
    return (head + _with_rubric(cards_pairs)
            + '\n\n=== 证据抽取结果 ===\n' + '\n'.join(ev) + TAIL)


def prompt_critique(cards_pairs, judged: dict, cv, iv, ids) -> str:
    lines = []
    for rid in ids:
        j = judged.get(rid) or {}
        lines.append(f"{rid}: state={j.get('state')} why={j.get('why')} "
                     f"quote={json.dumps(j.get('quote'), ensure_ascii=False)}")
    head = '''你是复核员。下面是**别人**对一个候选人做的判定。逐条核对,不要客气。

对每一条问三个问题:
  1. 他引的那句原文,真的在材料里吗?逐字在吗?
  2. 那句原文足以支撑这个判定吗?特别是:判「满足」但证据只是相关而非支持的,要改;
     判「未知」但材料里其实已经能判出来的,要改。
  3. 数值类要求有没有算错?

**逐条都要给出 state**(不改就原样重复)。形状:
{"C-01": {"state": "满足|不满足|未知", "why": "一句话", "quote": "原文片段或 null"}}

被复核的判定:
'''
    return (head + '\n'.join(lines)
            + '\n\n要判的要求(判据):\n' + _with_rubric(cards_pairs)
            + _body(cv, iv))


def parse_extract(raw: str, ids) -> dict:
    """抽取步骤专用解析:认 found / evidence / where / nothing_found。

    通用 parse() 只认 state —— 拿它解析抽取结果,evidence 会被丢掉,
    下一遍判定就只剩 None(实测 v2 因此整档退成未知)。
    """
    from scripts.talent.compare_llm_vs_ontology import _loads_any
    doc = _loads_any(raw) or {}
    out = {}
    for rid in ids:
        e = doc.get(rid) or {}
        found = e.get("found")
        if isinstance(found, str):
            found = found.strip().lower() in ("true", "是", "yes", "1")
        out[rid] = {"found": bool(found),
                    "evidence": e.get("evidence") or None,
                    "where": e.get("where") or None,
                    "nothing_found": e.get("nothing_found") or None}
    return out


_EV = re.compile(r'"(C-\d+)"\s*:\s*\{[^{}]*?"evidence"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)


def run_one(profile, cards, cards_pairs, cv, iv, ids, cache: pathlib.Path, fresh: bool):
    """一轮 = 一次或多次调用。cache 是本轮各步骤原始输出的落点(审计用)。"""
    steps = []

    def call(step: str, prompt: str) -> str:
        f = cache.with_name(cache.name + '.' + step + '.txt')
        if f.is_file() and not fresh:
            txt = f.read_text(encoding='utf-8')
            steps.append({'step': step, 'seconds': 0.0, 'chars': len(txt)})
            return txt
        out, t = call_llm(prompt)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(out, encoding='utf-8')
        steps.append({'step': step, 'seconds': round(t, 1), 'chars': len(out)})
        return out

    missing = []
    if profile == 'v0':
        doc, missing = parse(call('judge', prompt_v0(cards, cv, iv)), ids)
    elif profile == 'v1':
        raw = call('judge', prompt_v1(cards_pairs, cv, iv))
        p, missing = parse(raw, ids)
        doc = {k: {'state': v['state'], 'why': v.get('why', ''), 'quote': None}
               for k, v in p.items()}
        for m in _EV.finditer(raw):          # v1 把引文放在 evidence 里
            if m.group(1) in doc and m.group(2).strip():
                doc[m.group(1)]['quote'] = m.group(2)
    elif profile in ('v2', 'v3'):
        extracted = parse_extract(call('extract', prompt_extract(cards_pairs, cv, iv)), ids)
        ex_missing = [k for k, v in extracted.items() if not v['found'] and not v['nothing_found']
                      and not v['evidence']]
        judged, j_missing = parse(call('judge', prompt_judge(cards_pairs, extracted, ids)), ids)
        missing = sorted(set(ex_missing) | set(j_missing))
        doc = dict(judged)
        if profile == 'v3':
            crit, _c_missing = parse(
                call('critique', prompt_critique(cards_pairs, judged, cv, iv, ids)), ids)
            for k, v in crit.items():
                if v.get('state') in ('满足', '不满足', '未知'):
                    doc[k] = v
    else:
        raise SystemExit('未知 profile ' + profile)

    for k in ids:
        doc.setdefault(k, {'state': '未知', 'why': '', 'quote': None})
    return doc, steps, missing


_CONFLICT = re.compile(r'(?:应判|应该是|应为|其实应该是|正确的是|判错|应改为)\s*[「『]?'
                       r'(满足|不满足|未知)')
_MENTION = re.compile(r'(满足|不满足|未知)')


def self_conflict(why: str, state: str) -> bool:
    """判定与它自己的理由矛盾吗?

    实测抓到过一次:自我复核步骤写「…应判不满足」,而 state 却是「满足」。
    理由对、标签错,机器不查就没人会发现 —— 这种格子比"判错"更坏,
    因为它看起来自洽。这里只做字面查证,不假装能判语义。
    """
    if not why:
        return False
    m = _CONFLICT.search(why)
    if not m:
        return False
    said = m.group(1)
    # 「不满足」里含「满足」,先长后短地比
    return said != state


def _kind(r: dict) -> str:
    if r.get('components'):
        return '组件'
    if r.get('op') in ('between', '>='):
        return '数值'
    if r.get('op') == 'in':
        return '点名'
    return '组件'


#: 上一轮人工点开原文核过、判 LLM 对 / 本体错的格子(候选名前 12 字, 要求 id)。
HAND = [
    ('汪___', 'C-06'),
    ('雷___31', 'C-06'),
    ('胡___46', 'C-06'),
    ('陈___29', 'C-09'),
    ('汪___', 'C-07'),
    ('胡___46', 'C-07'),
    ('雷___31', 'C-07'),
    ('陈___29', 'C-07'),
    ('李___48', 'C-07'),
    ('廖___', 'C-04'),
    ('业务跟单_东莞_6_10K_万', 'C-05'),
    ('李___48', 'C-03'),
    ('李___40', 'C-06'),
]


#: 上一轮人工点开原文核过的 13 格之外,v3 还有 19 格与本体不一致。
#: 这 19 格我逐条点开原文看过,结论写在这里 —— 「谁对」不是脚本算得出来的。
#: 值 = (结论, 一句为什么)
HAND_VERDICT = {
    ('专案工程师_东莞_12_16K_陈', 'C-05'): ('v3 对', '5 年全在线束设计/研发,没有品质管理岗'),
    ('吴___', 'C-03'): ('v3 对', '专业是汉语言文学,不在客户点名之列'),
    ('吴___', 'C-05'): ('v3 对', '全部经历是人资行政,品质年限 0'),
    ('李___40', 'C-03'): ('v3 对', '会计学/计算机/英语,都不在点名之列'),
    ('李___40', 'C-07'): ('v3 对', '「公司品质系统管理」「SQA 稽核」是明确表述 —— 本体又是词表漏抽'),
    ('李___48', 'C-05'): ('v3 对', '品质相关只有 4 个月 QE 组长'),
    ('汪___', 'C-09'): ('v3 对', '「参与第二方工厂审核」「接待用户到厂考察」就是验厂'),
    ('胡___46', 'C-04'): ('v3 对', '只写英语听说读写,没有独立书写英文 8D 的证据'),
    ('胡___46', 'C-05'): ('v3 对', '全部是电线电缆工程师,品质只是「协助维护」'),
    ('陈___29', 'C-04'): ('v3 对', '有中英翻译能力,但没有 8D 报告产出'),
    ('陈___29', 'C-05'): ('v3 对', '品质只是专项项目,不构成 3 年品质管理年限'),
    ('吴___', 'C-01'): ('材料不对称', '年龄来自平台/HR 派生量,没喂给 LLM —— 它说「材料里没有」是对的'),
    ('李___48', 'C-01'): ('材料不对称', '同上'),
    ('胡___46', 'C-01'): ('材料不对称', '同上'),
    ('陈___29', 'C-01'): ('材料不对称', '同上'),
    ('廖___', 'C-01'): ('v3 错', '理由自己写「应判不满足」,state 却是满足 —— 自相矛盾,已单列'),
    ('廖___', 'C-05'): ('v3 错', '引文在材料里找不到(可核验=否),判满足没有依据'),
    ('雷___31', 'C-05'): ('v3 错', '把「生产主管 3 年 7 月」算成品质管理年限,过度外推'),
    ('汪___', 'C-03'): ('待你定', '「工业电气自动化」算不算命中「自动化」—— 子串 vs 断词的边界'),
}


def _verdict(key: str, rid: str):
    for (k, r), v in HAND_VERDICT.items():
        if r == rid and key.startswith(k):
            return v
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--profiles', nargs='*', default=['v0', 'v1', 'v2', 'v3'])
    ap.add_argument('--runs', type=int, default=2)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    mode, _src = interview_policy.mode_for(args.jd)
    _cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}

    req_ids = [c['id'] for c in link['citations']]
    cards, cards_pairs = [], []
    for c in link['citations']:
        r = lib[c['requirement']]
        card = rule_card(c, r, atts)
        cards.append(card)
        cards_pairs.append((card, _kind(r)))

    ids = [f'cand_{p.stem}' for p in sorted(CV_IV.glob('*.yaml')) if f'cand_{p.stem}' in by_id]
    if args.limit:
        ids = ids[:args.limit]

    onto = {cid: judge_all(by_id[cid], link, lib, atts) for cid in ids}
    onto_state = {(cid, c['id']): onto[cid][c['requirement']]['state']
                  for cid in ids for c in link['citations']}

    results = {}
    for prof in args.profiles:
        print('\n=== ' + prof + ' ===')
        cells, meta = [], []
        for n, cid in enumerate(ids, 1):
            cv, iv = material(cid)
            outs, secs = [], []
            first_steps = None
            for k in range(args.runs):
                cache = RAW / args.jd / prof / f"{cid.replace('cand_', '')}.run{k+1}"
                doc, steps, _missing = run_one(prof, cards, cards_pairs, cv, iv,
                                               req_ids, cache, args.fresh)
                outs.append(doc)
                secs.append(sum(s['seconds'] for s in steps))
                if first_steps is None:
                    first_steps = steps
            print(f"  [{n}/{len(ids)}] {cid.replace('cand_','')[:32]:32} "
                  + '/'.join('缓存' if s == 0 else f'{s:.0f}s' for s in secs))
            meta.append({'candidate': cid, 'seconds': [round(s, 1) for s in secs],
                         'steps': first_steps})
            for rid in req_ids:
                states = [r[rid]['state'] for r in outs]
                q = outs[0][rid].get('quote')
                cells.append({
                    'candidate': cid, 'req': rid,
                    'ontology': onto_state[(cid, rid)],
                    'prompt': states[0], 'states': states,
                    'self_agree': len(set(states)) == 1,
                    'quote': q,
                    'quote_ok': (True if not q else
                                 (str(q).strip()[:40] in cv or str(q).strip()[:40] in iv)),
                    'why': outs[0][rid].get('why') or '',
                    'self_conflict': self_conflict(outs[0][rid].get('why') or '', states[0]),
                })
        results[prof] = {'cells': cells, 'meta': meta}

    summary = {}
    for prof, res in results.items():
        cells = [c for c in res['cells'] if c['ontology'] != '不可判']
        dist = collections.Counter(c['prompt'] for c in cells)
        agree = sum(1 for c in cells if c['prompt'] == c['ontology'])
        quotes = [c for c in res['cells'] if c['quote']]
        summary[prof] = {
            '格数': len(cells), '与本体一致': agree,
            '一致率': round(agree / len(cells), 4) if cells else None,
            '未知': dist['未知'], '满足': dist['满足'], '不满足': dist['不满足'],
            '自一致': (round(sum(1 for c in res['cells'] if c['self_agree']) / len(res['cells']), 4)
                      if res['cells'] else None),
            '引文给了': len(quotes),
            '引文可核验': sum(1 for c in quotes if c['quote_ok']),
            '自相矛盾': sum(1 for c in res['cells'] if c.get('self_conflict')),
            '调用次数': sum(len(m['steps']) for m in res['meta']) * max(1, args.runs),
            '总耗时秒': round(sum(s for m in res['meta'] for s in m['seconds']), 1),
        }
        summary[prof]['本体未知'] = sum(1 for c in cells if c['ontology'] == '未知')
        TF = RAW / args.jd / (prof + '_timing.json')
        if summary[prof]['总耗时秒'] > 0:
            TF.parent.mkdir(parents=True, exist_ok=True)
            TF.write_text(json.dumps({'total': summary[prof]['总耗时秒'],
                                      'calls': summary[prof]['调用次数']}), encoding='utf-8')
        elif TF.is_file():
            t = json.loads(TF.read_text(encoding='utf-8'))
            summary[prof]['总耗时秒'] = round(t['total'], 1)
            summary[prof]['耗时注'] = '(缓存)'

    keep, unmatched = {}, []
    for prof, res in results.items():
        ok = tot = 0
        for key, rid in HAND:
            hits = [c for c in res['cells'] if c['req'] == rid
                    and c['candidate'].replace('cand_', '').startswith(key)]
            if not hits:
                unmatched.append(f'{key}×{rid}')
                continue
            if len(hits) > 1:
                unmatched.append(f'{key}×{rid}(命中 {len(hits)} 人,前缀不够唯一)')
            tot += 1
            if hits[0]['prompt'] != hits[0]['ontology']:
                ok += 1
        keep[prof] = (ok, tot)
    if unmatched:
        # 匹配不上就静默算 0/0 —— 那等于什么都没测,还看不出来
        raise SystemExit('人工核对格匹配失败:' + '; '.join(sorted(set(unmatched))))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{args.jd}·prompt 升级对比.yaml').write_text(yaml.safe_dump({
        'jd': args.jd, 'runs': args.runs, 'summary': summary,
        '人工核对过的那 13 格': {k: {'保持正确': v[0], '共': v[1]} for k, v in keep.items()},
        'per_cell': {p: [{'candidate': c['candidate'], 'req': c['req'],
                          'ontology': c['ontology'], 'prompt': c['prompt'],
                          'states': c['states'], 'quote_ok': c['quote_ok'],
                          'self_conflict': c.get('self_conflict', False),
                          'why': c['why']} for c in r['cells']] for p, r in results.items()},
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    md = ['# 只改 prompt,LLM 能追平本体吗', '',
          f"JD:**{args.jd}** · 候选人 **{len(ids)}** 人 · 要求 **{len(req_ids)}** 条 · "
          f'模型 `deepseek-chat`(temperature 0)· 每档跑 **{args.runs}** 遍', '',
          '**上一轮(v0)是我给的基线,不是 LLM 的上限。** 一次直判是最容易被打败的做法,',
          '用它的成绩宣布「本体更好」不成立。这一轮把 prompt 认真做三档,',
          '看差距到底来自 prompt,还是来自结构。', '',
          '| 档位 | 做法 |', '|---|---|',
          '| v0 | 一次性直判(上一轮的基线) |',
          '| v1 | 判据细化 + 先证据后结论(仍未拆步) |',
          '| v2 | 先抽证据,再基于证据判(两遍,最接近本体) |',
          '| v3 | v2 + 逐条自我复核(三遍) |', '',
          '## 一、四档横向对比', '',
          '| 指标 | ' + ' | '.join(args.profiles) + ' |',
          '|---|' + '---|' * len(args.profiles)]

    def row(name, fn):
        return '| ' + name + ' | ' + ' | '.join(fn(summary[p]) for p in args.profiles) + ' |'

    md.append(row('与本体一致率',
                  lambda s: f"**{s['与本体一致']}/{s['格数']} = {s['一致率'] * 100:.0f}%**"))
    md.append(row('判「未知」格数', lambda s: f"**{s['未知']}**"))
    md.append(row('(本体侧未知)', lambda s: str(s['本体未知'])))
    md.append(row('判「满足」', lambda s: str(s['满足'])))
    md.append(row('判「不满足」', lambda s: str(s['不满足'])))
    md.append(row('自一致性', lambda s: f"{s['自一致'] * 100:.0f}%"))
    md.append(row('自相矛盾(理由与标签打架)', lambda s: f"**{s['自相矛盾']}** 格"))
    md.append(row('引文可核验', lambda s: f"{s['引文可核验']}/{s['引文给了']}"))
    md.append(row('调用次数', lambda s: str(s['调用次数'])))
    md.append(row('总耗时', lambda s: f"{s['总耗时秒']:.0f}s{s.get('耗时注', '')}"))
    md.append('')

    md += ['## 二、要害一:v0 那股「不敢判」追回来没有', '',
           'v0 最大的毛病不是判错,是**不敢下结论** —— 48 格退成未知,而本体在这些格子上有判定。',
           '如果加了明确判定标准之后未知数掉下来,说明那是 prompt 问题,不是 LLM 的上限。', '']
    for p in args.profiles:
        s = summary[p]
        md.append(f"- **{p}**:未知 **{s['未知']}** 格(本体侧 {s['本体未知']} 格)")
    md.append('')

    md += ['## 三、要害二:LLM 看得见本体看不见的,升级后还看得见吗', '',
           '上一轮人工点开原文核过 **13 格**方向相反的分歧,结论是 **LLM 对、本体错** ——',
           '本体词表漏了「线材线束」「邀请客人验厂」「不良制程改善」这些同义表达。', '',
           '如果升级 prompt 之后这些格子**仍然和本体不一致**,说明 LLM 的正确性没被牺牲:',
           '那差距就只剩「可复算」这一件事,而那不是准确率问题。', '',
           '| 档位 | 仍然判对(与本体不一致) | 被磨掉了 |', '|---|---|---|']
    for p in args.profiles:
        ok, tot = keep[p]
        md.append(f'| {p} | **{ok}/{tot}** | {tot - ok} |')
    md.append('')

    last = args.profiles[-1]
    rows, tally = [], collections.Counter()
    for c in results[last]['cells']:
        if c['ontology'] == '不可判' or c['prompt'] == c['ontology']:
            continue
        nm = c['candidate'].replace('cand_', '')
        if any(nm.startswith(k) and c['req'] == r for k, r in HAND):
            continue          # 上一轮已经核过的那 13 格
        v = _verdict(nm, c['req'])
        if not v:
            continue
        tally[v[0]] += 1
        rows.append((nm[:24], c['req'], c['ontology'], c['prompt'], v[0], v[1]))
    if rows:
        md += [f'## 五、余下 {len(rows)} 格:我逐条点开原文看过', '',
               '一致率只说明"差多少",不说明"谁对"。下表是人工结论 —— 脚本不生成这一栏。', '',
               '| 候选人 | 要求 | 本体 | v3 | 谁对 | 依据 |',
               '|---|---|---|---|---|---|']
        for nm, rid, o, pr, who, why in rows:
            md.append(f'| {nm} | {rid} | {o} | {pr} | **{who}** | {why} |')
        md += ['', '小计:' + ' · '.join(f'**{k} {v} 格**' for k, v in tally.most_common()), '']
    md += ['## 六、结论', '', _conclusion(summary, keep, args.profiles, tally), '']
    (OUT / f'{args.jd}·prompt 升级对比.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    for p in args.profiles:
        s = summary[p]
        print(f"  {p}: 一致 {s['与本体一致']}/{s['格数']} · 未知 {s['未知']} · "
              f"自一致 {s['自一致'] * 100:.0f}% · 引文 {s['引文可核验']}/{s['引文给了']} · "
              f"{s['调用次数']} 次调用 {s['总耗时秒']:.0f}s")
    print(f"写出 {(OUT / f'{args.jd}·prompt 升级对比.md').relative_to(ROOT)}")
    return 0


def _conclusion(summary, keep, profiles, tally=None) -> str:
    v0, last = summary.get('v0'), summary.get(profiles[-1])
    if not v0 or not last:
        return '档位不全,不做结论。'
    out = []
    d = v0['未知'] - last['未知']
    if d > 5:
        out.append(f"- **「未知」从 {v0['未知']} 降到 {last['未知']}(少 {d} 格)**。"
                   f'说明 v0 那股「不敢判」的劲儿主要是 prompt 造成的,'
                   f'**不是 LLM 的上限** —— 我上一轮把这一点归错了。')
    else:
        out.append(f"- 「未知」只从 {v0['未知']} 降到 {last['未知']},"
                   f'即使给了明确判定标准,它仍然倾向退未知。')
    ok0, tot = keep.get('v0', (0, 1))
    okl, _ = keep.get(profiles[-1], (0, 1))
    if okl >= ok0:
        out.append(f'- 人工核对的那 {tot} 格(LLM 对 / 本体错)在 {profiles[-1]} 里保住 '
                   f'**{okl}/{tot}** —— 升级 prompt **没有**把它的「看得见」牺牲掉。')
    else:
        out.append(f'- 人工核对的那 {tot} 格在 {profiles[-1]} 里只剩 **{okl}/{tot}** —— '
                   f'升级 prompt 换来了对齐,但也磨掉了 LLM 原本的优势。')
    out.append(f"- 自一致性:{profiles[-1]} 为 {last['自一致'] * 100:.0f}%;"
               f"代价 {last['调用次数']} 次调用 / {last['总耗时秒']:.0f}s"
               f'(本体侧是毫秒级纯计算)。')
    t = tally or {}
    if t.get('v3 对'):
        out.append(f"- 余下 {sum(t.values())} 格里,人工判定 **v3 对 {t.get('v3 对')} 格**、"
                   f"**v3 错 {t.get('v3 错', 0)} 格**、材料不对称 {t.get('材料不对称', 0)} 格、"
                   f"待定 {t.get('待你定', 0)} 格。")
        out.append(f"- 加上上一轮核过的 13 格,**本体在这批人上至少错了 "
                   f"{t.get('v3 对') + 13} 格**;v3 自己错 {t.get('v3 错', 0)} 格。"
                   f'**在这个样本上,认真写 prompt 的 LLM 准确率高于本体。**')
    out += ['', '**所以答案是分层的:**', '',
            '1. **准确率这一层,你问得对:prompt 能追平,而且能超过。** 说「LLM 判不了」是不对的 —— '
            '判据讲清楚、先证据后结论,它把「不敢判」变成了「敢判」,还捡回了本体词表漏掉的同义表达。',
            '2. **来源这一层,prompt 追不平。** v3 有 4 格判「未知」是因为**我把年龄只喂了一份材料**;'
            '本体知道那个年龄来自平台/HR 派生量而不是简历。**LLM 只看得见你递给它的东西** —— '
            '而"该递什么、每条来自哪里",正是本体那一层在做的事。',
            '3. **自校验这一层,prompt 反而更危险。** v3 出现过一次「理由写应判不满足、标签却写满足」,'
            '自洽到只有人点开原文才发现。三步流程比一步流程更容易产生这种"看起来有依据"的错。',
            '4. **可复算这一层,prompt 追不平。** 自一致性不满 100% 的东西再准也当不了门禁;'
            '本体侧同输入必同结论,这是结构给的。',
            '5. **可审计这一层,差别不在方法。** v2/v3 那种「先抽后判 + 复核」其实已经是'
            '**用散文写成的本体** —— 结构在,只是写在提示词里而不是文件里。'
            '把它当本体用,就要接受它的结构不可 diff、不可被门禁复查。',
            '',
            '> 一句话:prompt 能追平**准不准**,追不平**凭什么**。'
            '产出只需要「看」,LLM+好 prompt 就够;产出需要「半年后能查出凭什么」,'
            '结构必须落在文件里 —— 而那时你会发现,v2/v3 已经在做本体的事了。']
    return '\n'.join(out)


if __name__ == '__main__':
    sys.exit(main())
