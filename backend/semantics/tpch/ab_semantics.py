#!/usr/bin/env python
"""ab_semantics — the same TPCH questions with and without `SEMANTICS.md`.

The point is not to prove the file helps; it is to see *where* it changes the
answer. Each question below targets one declared rule and carries the value the
database actually returns, so a wrong arm is detectable without a human reading it.

Two arms, one variable (`semantics_path`), same graph, same database, same model:

    ON   load_semantics finds `tpch/SEMANTICS.md`   -> 3 blocks in the prompt
    OFF  semantics_path points nowhere              -> 0 blocks

Usage::

    backend/.venv/bin/python backend/semantics/tpch/ab_semantics.py            # all questions
    ... --only Q3,Q4        # a subset      ... --arm off     # one arm
    ... --json /tmp/ab.json # save raw answers

Exit code is 0 always — this is an experiment, not a gate. `check_semantics.py`
is the gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BACKEND = os.path.join(REPO, "backend")

# ── Question set: one per rule, with the number the database actually holds ──
# `ok`     tokens: any one may appear (commas/spaces are normalised away)
# `bad`    tokens: their presence means the known wrong answer was produced
# `kind`   "value" (a number must appear) or "refusal" (the gap must be stated)
QUESTIONS = [
    dict(
        id="Q1", rule="rule 1 — three revenue definitions",
        q="整个数据库的总收入是多少？给出金额。",
        kind="value",
        ok=["20535072231", "21615929280", "21356596030", "205.35亿", "215.36亿"],
        bad=["1068", "106,8"],
        note="net / gross / order-header — any is correct if named",
    ),
    dict(
        id="Q2", rule="rule 5 — closed dataset has no 'current year'",
        q="今年的总收入是多少？",
        kind="refusal",
        ok=["1998", "没有", "封闭", "止于"],
        bad=["2025年总收入为", "2026年总收入为", "2025年的总收入为"],
        note="must refuse the premise and anchor to 1998-08-02",
    ),
    dict(
        id="Q3", rule="rule 3 — late delivery needs a definition",
        q="延迟交付率是多少？",
        kind="value",
        ok=["50.3", "50.4", "50.41"],
        bad=["49.5", "100.0"],
        note="ship > commit = 50.41%; on-time is 49.59%",
    ),
    dict(
        id="Q4", rule="rule 7 — order-header fan-out",
        q="1998 年订单头口径的总收入（SUM(o_totalprice)）是多少？",
        kind="value",
        ok=["1933789650", "19.33亿", "1933"],
        bad=["9703462214", "9703462213", "97.03亿"],
        note="orders alone 1.93B; joined to lineitem it inflates to 9.70B",
    ),
    dict(
        id="Q5", rule="rule 4 — supply cost lives in partsupp (control)",
        q="整个库的毛利率是多少？",
        kind="value",
        ok=["62.7", "62.71"],
        bad=["-2", "负", "12.1"],
        note="control: the FKs make this discoverable without semantics",
    ),
    dict(
        id="Q6", rule="rule 2 — ratio vs percent",
        q="加权平均折扣率是多少？",
        kind="value",
        ok=["5.00", "5.0%", "5%"],
        bad=["0.05%", "0.0500%"],
        note="A8 = 0.050003 ratio = 5.0003%; '0.05%' means the unit was lost",
    ),
    dict(
        id="Q7", rule="rule 8 — no expense accounts, no net profit / ROE",
        q="这个数据库的净利润和 ROE 是多少？",
        kind="refusal",
        ok=["没有", "无法", "缺", "不含", "算不出"],
        bad=["净利润为", "净利润是", "ROE为", "ROE 为", "roe为"],
        note="must state the gap, not invent assets or equity",
    ),
    dict(
        id="Q8", rule="rule 6 — synthetic evenness across regions",
        q="五个大区哪个经营得最好？给出结论。",
        kind="info",
        ok=["均匀", "合成", "基准", "生成", "接近", "无显著", "不能"],
        bad=[],
        note="±0.6pp spread is generator noise, not a finding",
    ),
]


def _norm(text: str) -> str:
    return re.sub(r"[\s,，]", "", text or "")


def judge(q: dict, answer: str) -> tuple[bool, str]:
    n = _norm(answer)
    hit_ok = [t for t in q["ok"] if _norm(t) in n]
    hit_bad = [t for t in q["bad"] if _norm(t) in n]
    if hit_bad:
        return False, f"hit wrong token {hit_bad[0]!r}"
    if q["kind"] == "info":
        return (bool(hit_ok), "noted the caveat" if hit_ok else "narrated a winner")
    if q["kind"] == "refusal":
        return (True, "stated the gap") if hit_ok else (False, "no gap stated")
    return (True, f"hit {hit_ok[0]!r}") if hit_ok else (False, "expected value absent")


def run_arm(question: str, semantics_on: bool) -> dict:
    """One graph run; returns the final answer plus the SQL it emitted."""
    import langgraph_semantic as G

    cfg = {"configurable": {"thread_id": f"ab-{uuid.uuid4().hex[:8]}"}}
    init = {"messages": [{"role": "user", "content": question}], "sql_database": "tpch"}
    if not semantics_on:
        init["semantics_path"] = "/nonexistent/SEMANTICS.md"

    blocks, answer = 0, ""
    for upd in G.agent.stream(init, config=cfg, stream_mode="updates"):
        for node, val in upd.items():
            if node == "load_semantics" and isinstance(val, dict):
                blocks = len(val.get("semantics") or {})
            if isinstance(val, dict):
                for m in val.get("messages") or []:
                    if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
                        answer = str(m.content)
    snap = G.agent.get_state(cfg)
    queries = [
        tc["args"].get("query", "")
        for m in snap.values.get("messages", [])
        for tc in (getattr(m, "tool_calls", None) or [])
    ]
    return {"blocks": blocks, "answer": answer, "queries": queries}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated question ids, e.g. Q1,Q4")
    ap.add_argument("--arm", choices=["on", "off", "both"], default="both")
    ap.add_argument("--json", default="", help="write the raw answers to this path")
    ap.add_argument("--repeat", type=int, default=3,
                    help="runs per cell (default 3) — a single run is not evidence")
    args = ap.parse_args()

    sys.path.insert(0, BACKEND)
    sys.path.insert(0, os.path.join(BACKEND, "langgraph"))
    os.chdir(os.path.join(BACKEND, "langgraph"))
    os.environ.setdefault("SQL_POSTGRES_DB", "chinook")

    wanted = [x.strip() for x in args.only.split(",") if x.strip()]
    qs = [q for q in QUESTIONS if not wanted or q["id"] in wanted]
    arms = {"on": True, "off": False}
    arm_keys = list(arms) if args.arm == "both" else [args.arm]

    results: list[dict] = []
    print(f"== A/B over {len(qs)} questions x {len(arm_keys)} arm(s), tpch @ :5432\n")
    for q in qs:
        row = {"id": q["id"], "rule": q["rule"], "question": q["q"], "arms": {}}
        for arm in arm_keys:
            runs = []
            for i in range(args.repeat):
                t0 = time.time()
                try:
                    r = run_arm(q["q"], arms[arm])
                except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
                    runs.append({"error": f"{type(exc).__name__}: {exc}"})
                    print(f"  {q['id']} {arm:<3} #{i + 1} ERROR {type(exc).__name__}")
                    continue
                ok, why = judge(q, r["answer"])
                runs.append({**r, "ok": ok, "why": why, "secs": round(time.time() - t0, 1)})
                mark = "PASS" if ok else "FAIL"
                print(f"  {q['id']} {arm:<3} #{i + 1} {mark} ({r['blocks']} blocks, "
                      f"{runs[-1]['secs']}s) — {why}: {r['answer'][:110].replace(chr(10), ' ')}")
            oks = [r for r in runs if r.get("ok")]
            row["arms"][arm] = {
                "runs": runs,
                "pass": len(oks),
                "n": len(runs),
                "queries": [q2 for r in runs for q2 in r.get("queries", [])],
            }
        results.append(row)

    print(f"\n== pass rate per cell (n={args.repeat} runs each; '2/3' means unstable) ==")
    print(f"{'':<4}{'rule':<44}{'OFF':<8}{'ON':<8}")
    for row in results:
        def cell(arm):
            a = row["arms"].get(arm)
            if not a:
                return "-"
            return f"{a['pass']}/{a['n']}"
        print(f"{row['id']:<4}{row['rule'][:42]:<44}{cell('off'):<8}{cell('on'):<8}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"\nraw answers -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
