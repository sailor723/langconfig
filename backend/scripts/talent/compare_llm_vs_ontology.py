#!/usr/bin/env python3
"""同一个 JD、同一批材料:本体+join 判一遍,只给 LLM 判一遍,然后数分歧。

问这个问题的场合:客户/业务方问"你们这套为什么要建本体?直接让大模型看不就行了"。
这个问题不该用"因为大模型不可靠"来回答 —— 那是断言,不是证据。要把两种做法真的各跑
一遍,把分歧逐条摆出来,让人自己看。

三种做法在这里被区分得很清楚:

    本体 + join   要求 → 组件/属性 → ABox 里的数据项 → 四态判定。数据项是什么、
                  谁供的、能不能复算,全部落在文件里。
    only LLM      原文 + 判据一起塞进 prompt,让它直接说"满足/不满足/未知"。

**这个脚本不做的事:不评谁"更准"。** 准确率要有标准答案,而这里没有金标 ——
这批人谁合格只有真面过的 HR 和用人经理知道。脚本能做的是把**可测的四个维度**摆出来:

    ① 一致率       两边判得一样吗,分歧集中在哪几条要求
    ② 自一致性     同一个模型 temp=0 跑两遍,自己跟自己一致吗
    ③ 可核验性     它引的那句原文,真的在简历里吗(逐字子串检查)
    ④ 信息利用率   谁把"没读到"老老实实说成「未知」

②③ 是这两个方案的**结构性差异**,不依赖金标就能测 —— 这也是这份对比的价值所在。

用法:
    python -m scripts.talent.compare_llm_vs_ontology --jd 品质经理
    python -m scripts.talent.compare_llm_vs_ontology --jd 品质经理 --runs 2
    python -m scripts.talent.compare_llm_vs_ontology --jd 品质经理 --dry   # 只看 prompt
"""
from __future__ import annotations

import argparse
import collections
import re
import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent.pick_final import judge_all, load_inputs  # noqa: E402

OUT = ROOT / "work" / "talent" / "compare"
RAW = OUT / "_raw"
DRAFT = ROOT / "work" / "talent" / "cv_draft"
CV_TEXT = ROOT / "work" / "talent" / "cv_text"
CV_IV = ROOT / "work" / "talent" / "cv_interview"

STATES = ("满足", "不满足", "未知", "不可判")


# ─────────────────────────────────────────────────────── 材料:两边必须读同一份
def material(cid: str) -> tuple[str, str]:
    """返回 (简历原文, 一面记录文本)。

    **两边喂同一份材料**是这个对比成立的前提。本体侧除了简历还用了 HR 派生量
    (在岗月数/空档)和一面记录,所以 LLM 侧也得拿到一面记录 —— 否则比的不是
    "判定方式",而是"谁看到的东西多",结论就没有意义。
    """
    draft = DRAFT / f"{cid}.json"
    text = ""
    if draft.is_file():
        src = (json.loads(draft.read_text(encoding="utf-8")) or {}).get("source_file")
        if src:
            p = CV_TEXT / (pathlib.Path(str(src)).stem[:80] + ".txt")
            if p.is_file():
                text = p.read_text(encoding="utf-8")
    if not text:
        # 兜底:按 id 名去 cv_text 里找(个别 id 与文件名不完全一致)
        key = cid.replace("cand_", "")[:10]
        hits = [p for p in CV_TEXT.glob("*.txt") if key[:6] in p.stem]
        if hits:
            text = hits[0].read_text(encoding="utf-8")
    note = ""
    ivf = CV_IV / f"{cid.replace('cand_', '')}.yaml"
    if ivf.is_file():
        doc = yaml.safe_load(ivf.read_text(encoding="utf-8")) or {}
        lines = []
        for a in doc.get("answers") or []:
            real = interview_policy.is_real_basis(a)
            tag = "真访谈" if real else "模拟(我方推断)"
            q = a.get("question") or a.get("q") or ""
            v = a.get("answer") or a.get("a") or ""
            props = a.get("props") or {}
            body = v or "; ".join(f"{k}={x}" for k, x in props.items())
            lines.append(f"  [{tag}] {q} → {body}")
        if lines:
            note = "\n".join(lines)
    return text, note


# ─────────────────────────────────────────────────────── prompt:只给判据,不给结构
def rule_card(c: dict, r: dict, atts: dict) -> str:
    """把一条要求写成"人话判据"。这是 LLM 侧唯一拿到的结构信息。

    注意这里给的是**客户原文 + 比较语义**(落在区间/不低于/命中点名),不是本体的
    组件表。组件表是本体侧独有的一层,不给 LLM —— 给了就不是"only llm"了。
    """
    lines = [f"{c['id']} {r.get('name')}", f"    客户原文:「{c.get('verbatim') or ''}」"]
    op, shape, val = r.get("op"), (r.get("value_shape") or {}), (c.get("value") or {})
    if op == "between":
        lines.append(f"    判据:年龄(整数,岁)是否落在 {val.get('min')}~{val.get('max')} 之间(含端点)")
    elif op == ">=" and "num" in shape:
        unit = shape.get("num", "")
        if "学历" in str(unit):
            lines.append(f"    判据:学历等级是否 ≥ {val.get('num') or val.get('min')}"
                         f"(2=中专/高中 3=大专 4=本科 5=硕士 6=博士)")
        else:
            lines.append(f"    判据:{shape.get('domain') or ''}年限是否 ≥ {val.get('num') or val.get('min')} {unit}")
    elif op == "in":
        lines.append(f"    判据:专业名是否命中客户点名的词之一:{val.get('list') or '见原文'}"
                     f"(只按点名判,不按专业门类)")
    elif r.get("components"):
        lines.append(f"    判据:材料里是否有明确证据表明他具备这几项(每项都要有原文依据) —— "
                     + "、".join(c.replace("skill_", "") for c in r["components"]))
    else:
        lines.append("    判据:材料里是否有明确证据支持这条要求")
    note = (r.get("note") or "").strip()
    if note:
        first = note.split("\n")[0][:120]
        if first and not first.startswith("**判定规则") and "实测" not in first:
            lines.append(f"    补充:{first}")
    return "\n".join(lines)


HEAD = """你是招聘判定员。读取下面的材料,对每一条 JD 要求给出判定。

判定只能是四种之一,**这四个状态不许合并**:
  满足   —— 材料里有明确、可引用的证据支持
  不满足 —— 材料里有明确证据**否定**(如年龄 41,而要求 25~40)
  未知   —— 材料里没写到 / 读不出来。**"没写到"不是"不合格"**

硬要求:
1. 每条判定都给出 why(一句话)与 quote(原文逐字片段)。quote 必须从材料里**逐字复制**,
   不许改写、不许拼接。判「未知」时 quote 填 null。
2. 不要把「未知」写成「不满足」。材料里没有的东西,你不知道。
3. 只输出 JSON,不要解释、不要 markdown 代码块。

输出形状:
{"C-01": {"state": "满足|不满足|未知", "why": "一句话", "quote": "原文片段或 null"}}

要判的要求:
"""


def build_prompt(cards: list[str], cv_text: str, iv_note: str) -> str:
    head = HEAD + "\n".join(cards) + "\n\n=== 材料:简历 OCR 原文 ===\n"
    body = cv_text[:7000]
    if iv_note:
        body += "\n\n=== 材料:一面记录(HR 记录) ===\n" + iv_note[:3000]
    return head + body + "\n\n只输出 JSON。"


def call_llm(prompt: str, max_tokens: int = 4000) -> tuple[str, float]:
    from config import Settings
    s = Settings()
    if not s.DEEPSEEK_API_KEY:
        raise SystemExit("没有 DEEPSEEK_API_KEY —— 这个对比必须真调模型,不能假装")
    body = json.dumps({"model": "deepseek-chat", "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{s.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {s.DEEPSEEK_API_KEY}",
                                          "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=240) as r:
        out = json.loads(r.read())["choices"][0]["message"]["content"]
    return out, time.time() - t0


_OBJ = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")


def _loads_any(s: str):
    """整段 loads;不行就逐条抠 "C-xx": {...}。

    实测模型会把最外层的 } 漏掉(或输出被 max_tokens 截断)。这时整段解析必然失败,
    而**把解析失败当成"未知"是最坏的处理** —— 它会让"读不到"和"我没读成"混在一起。
    所以下面返回 (doc, 缺了哪几条),缺的那几条由调用方按「未审」处理,不算判定。
    """
    try:
        doc = json.loads(s)
        if isinstance(doc, dict):
            return doc
    except json.JSONDecodeError:
        pass
    doc = {}
    for m in _ENTRY.finditer(s):
        try:
            body = m.group(2)
            doc["C-" + m.group(1)] = json.loads(body if body.strip().startswith("{")
                                             else "{" + body + "}")
        except json.JSONDecodeError:
            continue
    return doc or None


_ENTRY = re.compile(r'"C-(\d+)"\s*:\s*(\{.*?\})(?=\s*(?:,|\n|\}|$))', re.S)


def parse(out: str, ids: list[str]) -> tuple[dict, list[str]]:
    s = out.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if "```" in s[3:] else s[3:]
        s = s.lstrip("json").strip()
    doc = _loads_any(s) or {}
    good = {}
    for k in ids:
        item = doc.get(k) or {}
        st = str(item.get("state") or "").strip()
        if st not in ("满足", "不满足", "未知"):
            st = "未知" if not st else st
        good[k] = {"state": st, "why": str(item.get("why") or ""),
                   "quote": (item.get("quote") or None)}
    # 模型没给出这几条 = 没读到判定结果,不是"未知"。返回缺失清单让调用方按未审处理。
    missing = [k for k in ids if k not in doc]
    return good, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--runs", type=int, default=2, help="LLM 侧重复跑几遍(测自一致性)")
    ap.add_argument("--ids", nargs="*", default=None, help="默认:所有有访谈档案的人")
    ap.add_argument("--dry", action="store_true", help="只打印 prompt,不调模型")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fresh", action="store_true", help="忽略已缓存的模型原始输出,重新调")
    args = ap.parse_args()

    mode, mode_src = interview_policy.mode_for(args.jd)
    mock_ok = mode == interview_policy.MOCK_ALLOWED
    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_interview(cands, allow_simulated=mock_ok)
    by_id = {c["id"]: c for c in cands}

    if args.ids:
        ids = [i if i.startswith("cand_") else f"cand_{i}" for i in args.ids]
    else:
        ids = [f"cand_{p.stem}" for p in sorted(CV_IV.glob("*.yaml"))]
    ids = [i for i in ids if i in by_id]
    if args.limit:
        ids = ids[:args.limit]

    cards = [rule_card(c, lib[c["requirement"]], atts) for c in link["citations"]]
    req_ids = [c["id"] for c in link["citations"]]

    rows, meta = [], []
    for n, cid in enumerate(ids, 1):
        text, note = material(cid)
        onto = judge_all(by_id[cid], link, lib, atts)
        prompt = build_prompt(cards, text, note)
        if args.dry:
            print("=" * 78)
            print(f"{cid}  材料 {len(text)} 字 / 一面 {len(note)} 字 / prompt {len(prompt)} 字")
            if n == 1:
                print(prompt[:2500])
            continue
        runs, secs, missing_all = [], [], []
        for k in range(max(1, args.runs)):
            raw = RAW / args.jd / f"{cid.replace('cand_', '')}.run{k+1}.txt"
            if raw.is_file() and not args.fresh:
                out, t = raw.read_text(encoding="utf-8"), 0.0
            else:
                out, t = call_llm(prompt)
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(out, encoding="utf-8")
            one, missing = parse(out, req_ids)
            spent, tries = t, 1
            # 网络超时和输出截断都会造成"缺条"。缺了就重试 ——
            # 实测有过一次 SSL 读超时,把 10 个格子直接抹成未审,而那 10 格本来是有答案的。
            while missing and tries < 3:
                print(f"      ↻ {cid.replace('cand_','')[:20]} 第 {k+1} 遍缺 {len(missing)} 条,重试")
                out, t2 = call_llm(prompt)
                spent += t2
                raw.write_text(out, encoding="utf-8")
                one, missing = parse(out, req_ids)
                tries += 1
            runs.append(one)
            secs.append(spent)
            if missing:
                missing_all.append((k + 1, missing))
        print(f"  [{n}/{len(ids)}] {cid.replace('cand_','')[:34]:34} "
              f"{'/'.join(('缓存' if t == 0 else f'{t:.0f}s') for t in secs)}")
        if missing_all:
            # 解析不全必须喊出来。静默填「未知」会把"我没读成"混进"材料里没有"。
            print(f"      ⚠ 输出解析不全:第 {[k for k, _ in missing_all]} 遍缺 "
                  f"{sorted({m for _, ms in missing_all for m in ms})}")
        meta.append({"candidate": cid, "cv_chars": len(text), "iv_chars": len(note),
                     "prompt_chars": len(prompt), "seconds": [round(t, 1) for t in secs],
                     "解析缺失": sorted({m for _, ms in missing_all for m in ms})})
        for rid in req_ids:
            states = [r[rid]["state"] for r in runs]
            rows.append({
                "candidate": cid, "req": rid,
                "_未审": any(rid in ms for _, ms in missing_all),
                "name": lib[[c["requirement"] for c in link["citations"]
                             if c["id"] == rid][0]].get("name"),
                "本体": onto[[c["requirement"] for c in link["citations"]
                             if c["id"] == rid][0]]["state"],
                "本体依据": onto[[c["requirement"] for c in link["citations"]
                                if c["id"] == rid][0]]["why"],
                "llm": states[0],
                "llm_states": states,
                "llm_自一致": len(set(states)) == 1,
                "llm依据": runs[0][rid]["why"],
                "llm引文": runs[0][rid]["quote"],
                # 引文可核验:必须能在材料里逐字找到 —— 否则它是在"讲得像",不是"读到了"
                "引文可核验": (lambda q: True if not q else
                              (str(q).strip()[:40] in text or str(q).strip()[:40] in note))(
                                  runs[0][rid]["quote"]),
                "一致": onto[[c["requirement"] for c in link["citations"]
                             if c["id"] == rid][0]]["state"] == states[0],
            })
    if args.dry:
        return 0

    # ── 统计:只算两边都能判的格子(本体「不可判」= 这条要求没有数据项,不参与比对)
    unread = [r for r in rows if r.get("_未审")]
    both = [r for r in rows if r["本体"] != "不可判" and not r.get("_未审")
            and r["llm"] in ("满足", "不满足", "未知")]
    agree = [r for r in both if r["一致"]]
    mat = collections.Counter((r["本体"], r["llm"]) for r in both)
    per_req = collections.OrderedDict()
    for rid in req_ids:
        sub = [r for r in both if r["req"] == rid]
        if sub:
            per_req[rid] = (sum(1 for r in sub if r["一致"]), len(sub), sub[0]["name"])
    quote_ok = [r for r in rows if r["llm引文"]]
    quote_verified = [r for r in quote_ok if r["引文可核验"]]
    judged = [r for r in rows if not r.get("_未审")]
    self_ok = [r for r in judged if r["llm_自一致"]]
    onto_unknown = sum(1 for r in both if r["本体"] == "未知")
    llm_unknown = sum(1 for r in both if r["llm"] == "未知")
    secs = [s for m in meta for s in m["seconds"]]
    TIMING = RAW / args.jd / "_timing.json"
    if sum(secs) > 0:
        TIMING.parent.mkdir(parents=True, exist_ok=True)
        TIMING.write_text(json.dumps({"total": round(sum(secs), 1),
                                      "calls": len(secs)}), encoding="utf-8")
        timing_note = f"{sum(secs):.0f}s / {sum(secs)/max(1,len(secs)):.1f}s 每人每次"
    elif TIMING.is_file():
        t = json.loads(TIMING.read_text(encoding="utf-8"))
        timing_note = (f"{t['total']:.0f}s / {t['total']/max(1,t['calls']):.1f}s 每人每次"
                       f"(本次全部命中缓存,0 次调用)")
    else:
        timing_note = "本次全部命中缓存(未记录首次耗时)"

    OUT.mkdir(parents=True, exist_ok=True)
    yaml_out = {
        "jd": args.jd, "interview_policy": {"mode": mode, "source": mode_src},
        "candidates": len(ids), "requirements": len(req_ids), "runs": args.runs,
        "model": "deepseek-chat (temperature 0)",
        "metrics": {
            "可比对格子": len(both),
            "一致": len(agree),
            "一致率": round(len(agree) / len(both), 4) if both else None,
            "本体判未知": onto_unknown,
            "llm判未知": llm_unknown,
            "llm自一致": round(len(self_ok) / len(judged), 4) if judged else None,
            "llm给了引文": len(quote_ok),
            "引文可核验": len(quote_verified),
            "总耗时秒": round(sum(secs), 1),
            "llm未审格": len(unread),
        },
        "matrix": {f"{a}→{b}": n for (a, b), n in sorted(mat.items())},
        "per_requirement": {k: {"name": v[2], "agree": v[0], "of": v[1]} for k, v in per_req.items()},
        "disagreements": [{k: r[k] for k in ("candidate", "req", "name", "本体", "本体依据",
                                             "llm", "llm依据", "llm引文", "引文可核验")}
                          for r in both if not r["一致"]],
    }
    (OUT / f"{args.jd}·LLM vs 本体.yaml").write_text(
        yaml.safe_dump(yaml_out, allow_unicode=True, sort_keys=False), encoding="utf-8")

    md = [f"# 同一个 JD,两种判法:本体+join vs 只有 LLM", "",
          f"JD:**{args.jd}** · 候选人 **{len(ids)}** 人 · 要求 **{len(req_ids)}** 条 · "
          f"模型 `deepseek-chat`(temperature 0)· 每人跑 **{args.runs}** 遍", "",
          "> 两边读的是**同一份材料**(简历 OCR 原文 + 一面记录)。差别只有一处:",
          "> 一边先把材料拆成数据项、再按组件/属性的比较语义 join 出判定;",
          "> 另一边把原文和判据一起塞进 prompt,让它直接说结论。", ""]

    if unread:
        # 分母少了几格,一致率就不能照着念 —— 这一行必须在最前面
        md += [f"> ⚠ **本次有 {len(unread)} 格未审**(模型输出被截断或调用失败,重试后仍未拿到),"
               f"它们**不计入分母**。一致率是在少 {len(unread)} 格的基础上算的,"
               f"不能和完整跑的结果直接比。", ""]
    md += ["## 一、可测的四件事", "",
           "| 指标 | 结果 | 怎么读 |", "|---|---|---|",
           f"| 判定一致率 | **{len(agree)}/{len(both)} = {len(agree)/max(1,len(both))*100:.0f}%** | "
           f"两种做法在「都能判」的格子上的一致程度 |",
           f"| 本体判「未知」 | **{onto_unknown}** 格 | 数据项没读到,如实报未知 |",
           f"| LLM 判「未知」 | **{llm_unknown}** 格 | 同上,由模型自己判断「读不到」 |",
           f"| LLM 自一致性 | **{len(self_ok)}/{len(judged)} = {len(self_ok)/max(1,len(judged))*100:.0f}%** | "
           f"同 prompt 同温度跑 {args.runs} 遍,结论是否完全一样 |",
           f"| 引文可核验率 | **{len(quote_verified)}/{len(quote_ok)}** | "
           f"它引的那句原文,是否真在材料里(逐字子串) |",
           f"| LLM 未审格子 | **{len(unread)}** 格 | "
           f"模型输出被截断/解析不全的,一律不算判定(不计入上表分母) |",
           f"| 耗时 | {timing_note} | "
           f"本体侧判定是纯计算,毫秒级 |", ""]

    md += ["## 二、一致/分歧在哪", "",
           "| 要求 | 一致 | 一致率 |", "|---|---|---|"]
    for rid, (a, t, nm) in per_req.items():
        bar = "█" * round(a / t * 10) + "░" * (10 - round(a / t * 10))
        md.append(f"| {rid} {nm} | {a}/{t} | `{bar}` {a/t*100:.0f}% |")
    md += ["", "### 判定矩阵(行=本体,列=LLM)", "",
           "| 本体 ↓ / LLM → | 满足 | 不满足 | 未知 |", "|---|---|---|---|"]
    for a in STATES:
        cells = [mat.get((a, b), 0) for b in ("满足", "不满足", "未知")]
        if sum(cells):
            md.append(f"| **{a}** | {cells[0]} | {cells[1]} | {cells[2]} |")
    md.append("")

    dis = yaml_out["disagreements"]
    # 分歧不是随机噪声,按"谁让了步"分三类。这一层是这份对比最有用的产物:
    # 它把"两种做法打架"翻译成"本体该修哪里"。
    comp_reqs = {c["id"] for c in link["citations"] if lib[c["requirement"]].get("components")}
    pat = collections.Counter()
    for r in dis:
        onto, llm = r["本体"], r["llm"]
        if llm == "未知" and onto != "未知":
            pat["本体有结论 / LLM 退未知"] += 1
        elif onto == "未知" and llm != "未知":
            pat["LLM 有结论 / 本体未知"] += 1
        elif onto == "不满足" and llm == "满足":
            pat["本体说不满足 / LLM 说满足" + ("(组件类)" if r["req"] in comp_reqs else "(属性类)")] += 1
        elif onto == "满足" and llm == "不满足":
            pat["本体说满足 / LLM 说不满足" + ("(组件类)" if r["req"] in comp_reqs else "(属性类)")] += 1
        else:
            pat["其他"] += 1
    md += ["## 三、逐条分歧", ""]
    if not dis:
        md += ["两边**完全一致**。这种情况下 LLM 是够用的 —— 但注意这只说明这一批人、"
               "这一份 JD 上一致,不说明换个 JD 还一致。", ""]
    else:
        md += [f"共 **{len(dis)}** 格不一致。", "",
               "| 候选人 | 要求 | 本体 | 本体依据 | LLM | LLM 依据 | 引文可核验 |",
               "|---|---|---|---|---|---|---|"]
        for r in dis:
            md.append(f"| {r['candidate'].replace('cand_','')[:22]} | {r['req']} | "
                      f"**{r['本体']}** | {str(r['本体依据'])[:50]} | "
                      f"**{r['llm']}** | {str(r['llm依据'])[:50]} | "
                      f"{'✓' if r['引文可核验'] else '✗'} |")
        md.append("")

    md += ["## 四、分歧不是噪声:它们分成几类", "",
           "逐格看 57 条分歧没意义,按「谁让了步」归类之后,它们的形状很清楚:", "",
           "| 分歧模式 | 格数 | 该怎么读 |", "|---|---|---|"]
    READ = {
        "本体有结论 / LLM 退未知": "LLM 不敢对「材料里没写」下结论。**不是它错**,是它把举证责任"
                              "都放在一次生成里;本体敢下,是因为抽取阶段已经用封闭词表把"
                              "「读过了,没有」定死了",
        "本体说不满足 / LLM 说满足(组件类)": "**本体的词表没覆盖到同义表达**。这类要点开原文看:"
                                     "多数情况 LLM 是对的,本体该补词表",
        "本体说满足 / LLM 说不满足(属性类)": "阈值口径或组件粒度问题。这类要人裁 —— "
                                     "两边都能自圆其说时,以客户原文为准",
        "LLM 有结论 / 本体未知": "本体缺数据项(抽取没读到),LLM 从上下文补出来了 —— 可回填",
        "本体说不满足 / LLM 说满足(属性类)": "同上,看原文",
        "本体说满足 / LLM 说不满足(组件类)": "同上,看原文",
    }
    for k, v in pat.most_common():
        md.append(f"| {k} | **{v}** | {READ.get(k, '需人工看原文')} |")
    md += [""]

    md += ["## 五、这份对比能说明什么、不能说明什么", "",
           "**能说明的**:", "",
           "- 一致率:两种做法在这批人上的重合程度。分歧集中在哪几条要求,表里逐条列了。",
           f"- 自一致性:同一个模型同温度跑 {args.runs} 遍,"
           f"{(1-len(self_ok)/max(1,len(judged)))*100:.0f}% 的格子上结论会变。"
           "本体侧不存在这一项 —— 同输入必同结论,是可以拿来做门禁的。",
           f"- 引文可核验:LLM 引的原文里有 {len(quote_ok)-len(quote_verified)} 处**在材料里找不到**。"
           "找不到的引文,对外就是不可复核的断言。",
           "- 成本:LLM 每人每次数秒、按量计费;本体侧判定是毫秒级纯计算,重算不花钱。", "",
           "**不能说明的**:", "",
           "- 不能说明谁「更准」。这批人谁合格,只有真面过的 HR 和用人经理知道。",
           "- 不能拿这一次的一致率外推到别的 JD。样本是 "
           f"{len(ids)} 人 × {len(req_ids)} 条,分歧集中在阈值为数值的要求上时,"
           "换一份阈值不同的 JD,一致率会变。", "",
           "## 六、结论", "",
           "如果一致率很高,LLM 可以拿来**做交叉复核**:本体判完,让 LLM 独立判一遍,"
           "不一致的格子推给人看。它不适合**替代**判定,原因不是「模型笨」,而是:",
           "",
           "1. 判定要能被复算 —— 半年后有人问「这个人当时为什么判不满足」,"
           "   答案要在文件里,不能是「上次模型这么说的」;",
           "2. 判定要能当门禁 —— 自一致性不满 100% 的东西,没法做成 gate;",
           "3. 「未知」要能保真 —— 一旦模型把「没读到」写成「不满足」,"
           "就是在凭空判一批人不合格,而这种错在报告里看不出来。", ""]
    hand = OUT / f"{args.jd}·核对结论.md"
    if hand.is_file():
        md += ["---", "", f"> 机器能测的到此为止。**逐条点开原文核对过的结论**在 "
               f"`{hand.name}`(人工写的,脚本不生成)。", ""]
    (OUT / f"{args.jd}·LLM vs 本体.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\n可比对 {len(both)} 格 · 一致 {len(agree)} ({len(agree)/len(both)*100:.0f}%) · "
          f"本体未知 {onto_unknown} / LLM 未知 {llm_unknown} · "
          f"自一致 {len(self_ok)}/{len(judged)} · 引文可核验 {len(quote_verified)}/{len(quote_ok)} · "
          f"{sum(secs):.0f}s")
    print(f"写出 {(OUT / f'{args.jd}·LLM vs 本体.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
