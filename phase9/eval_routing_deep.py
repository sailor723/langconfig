#!/usr/bin/env python3
"""
Phase 9 / Step A4 — eval suite over the DeepAgent query pipeline.

Runs the same 14-query hand-labeled eval set used by eval_routing.py
against a routing-only DeepAgent (just fetch_catalog_tool + router
subagent). Compares results against the legacy string + LLM baselines.

The legacy eval_routing.py is left untouched.

Usage:
  # Run all three methods and write a comparison table
  python phase9/eval_routing_deep.py

  # Just DeepAgent
  python phase9/eval_routing_deep.py --method deep
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))

# Reuse the same hand-labeled eval set + base helpers from legacy eval
from eval_routing import (  # noqa: E402
    EVAL_QUERIES,
    run_string_eval,
    run_llm_eval,
    summarize as summarize_results,
    render_report as render_legacy_report,
    Neo4jDocumentIndex,
    fetch_catalog,
)
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentRecord,
    choose_best_document_match,
)

# --- Routing-only DeepAgent (separate from query_agent.py's full agent) ---

ROUTING_AGENT_SYSTEM = """You are a routing agent for a multi-document knowledge base.

You have access to a `fetch_catalog_tool` that returns the full catalog
of all available documents (each with name, about, supported_queries, and
out_of_scope).

Given a user query, your ONLY job is to decide which single document best
matches the query. Reply with a single line of JSON and nothing else:

{"primary": "<exact doc name>", "primary_confidence": <0.0-1.0>, "reasoning": "<one short sentence>"}

Rules:
- "primary" must be EXACTLY one of the document names from the catalog
- Prefer a PARTIAL match with low confidence over returning null — if any
  document's about or supports is even loosely related, pick it (this is
  better for the user than saying "nothing matches")
- Only return null if EVERY document is clearly unrelated
- Do NOT load any documents, do NOT answer the user's question
- Do NOT add commentary, markdown, or extra text outside the JSON"""


def build_routing_agent():
    """A minimal DeepAgent with just fetch_catalog_tool, optimized for routing."""
    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver
    from langchain.chat_models import init_chat_model
    from graphindex_tools import fetch_catalog_tool
    from dotenv import load_dotenv
    import os

    try:
        _env = Path(__file__).resolve().parent.parent / ".env"
    except NameError:
        _env = Path(os.getcwd()) / ".env"
    load_dotenv(_env)

    model = init_chat_model(
        model="minimax-m3",
        model_provider="openai",
        api_key=os.getenv("MINIMAX_API_KEY", ""),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.0,
        max_tokens=512,
    )

    return create_deep_agent(
        model=model,
        system_prompt=ROUTING_AGENT_SYSTEM,
        tools=[fetch_catalog_tool],
        checkpointer=MemorySaver(),
    )


# --- DeepAgent run + parse -------------------------------------------------

_JSON_LINE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _parse_primary(answer: str) -> Optional[str]:
    """Extract `primary` from the DeepAgent's JSON response."""
    if "<think>" in answer and "</think>" in answer:
        answer = answer.split("</think>", 1)[1].strip()
    match = _JSON_LINE.search(answer)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    p = data.get("primary")
    return p if p else None


def run_deep_eval(queries: List[Dict[str, Any]], agent) -> List[Dict]:
    """Run the routing-only DeepAgent on each query, capturing its primary
    pick + per-turn timing/tokens."""
    results = []
    for i, q in enumerate(queries, 1):
        t0 = time.time()
        try:
            r = agent.invoke(
                {"messages": [{"role": "user", "content": q["q"]}]},
                config={"configurable": {"thread_id": f"eval-deep-{i}"}},
            )
        except Exception as e:
            print(f"  ✗ query {i} error: {e}")
            results.append({
                "query": q["q"], "category": q["category"],
                "expected_primary": q["primary"],
                "actual_primary": None, "actual_confidence": 0.0,
                "actual_supporting": [], "latency_s": 0.0,
                "cache_read": 0, "in_tokens": 0, "out_tokens": 0,
            })
            continue
        elapsed = time.time() - t0

        answer = r["messages"][-1].content if isinstance(r["messages"][-1].content, str) \
                 else str(r["messages"][-1].content)
        primary = _parse_primary(answer)

        usage = getattr(r["messages"][-1], "usage_metadata", None) or {}
        details = usage.get("input_token_details", {}) or {}
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        cache_read = int(details.get("cache_read", 0) or
                         details.get("cached_tokens", 0))

        results.append({
            "query": q["q"],
            "category": q["category"],
            "expected_primary": q["primary"],
            "actual_primary": primary,
            "actual_confidence": 1.0 if primary else 0.0,
            "actual_supporting": [],
            "latency_s": elapsed,
            "cache_read": cache_read,
            "in_tokens": in_tok,
            "out_tokens": out_tok,
        })
    return results


# --- 3-way comparison table -----------------------------------------------

def primary_hit(r: Dict) -> bool:
    exp = r["expected_primary"]
    if exp is None:
        return r["actual_primary"] is None
    return r["actual_primary"] == exp


def summarize_deep(results: List[Dict]) -> Dict:
    total = len(results)
    hits = sum(1 for r in results if primary_hit(r))
    by_cat: Dict[str, Dict] = {}
    for r in results:
        s = by_cat.setdefault(r["category"], {"n": 0, "primary_hit": 0})
        s["n"] += 1
        if primary_hit(r):
            s["primary_hit"] += 1
    latencies = [r["latency_s"] for r in results]
    cache_reads = [r["cache_read"] for r in results]
    in_toks = [r["in_tokens"] for r in results]
    return {
        "total": total,
        "primary_accuracy": hits / total if total else 0,
        "latency_mean": statistics.mean(latencies) if latencies else 0,
        "latency_max": max(latencies) if latencies else 0,
        "cache_read_mean": statistics.mean(cache_reads) if cache_reads else 0,
        "cache_pct_mean": (statistics.mean([100 * c / m for c, m in
            zip(cache_reads, in_toks) if m]) if in_toks else 0),
        "by_category": by_cat,
    }


def render_comparison(string_s: Optional[Dict], llm_s: Optional[Dict],
                      deep_s: Dict, deep_results: List[Dict]) -> str:
    lines = []
    lines.append(f"\n{'='*70}\n  DeepAgent SEMANTIC (create_deep_agent)\n{'='*70}")
    lines.append(f"  queries run:      {deep_s['total']}")
    lines.append(f"  primary accuracy: {deep_s['primary_accuracy']*100:.0f}%")
    lines.append(f"  latency mean:     {deep_s['latency_mean']:.2f}s")
    lines.append(f"  latency max:      {deep_s['latency_max']:.2f}s")
    lines.append(f"  cache_read mean:  {deep_s['cache_read_mean']:,.0f} tokens")
    lines.append(f"  cache % mean:     {deep_s['cache_pct_mean']:.1f}%")
    lines.append("")
    lines.append("  per-category:")
    for cat, s in sorted(deep_s["by_category"].items()):
        pa = s["primary_hit"] / s["n"] * 100 if s["n"] else 0
        lines.append(f"    {cat:30s}  n={s['n']}  primary={pa:3.0f}%")
    lines.append("")
    lines.append("  misroutes:")
    for r in deep_results:
        if not primary_hit(r):
            lines.append(f"    ✗ [{r['category']}] {r['query']!r}")
            lines.append(f"        expected:  {r['expected_primary']}")
            lines.append(f"        actual:    {r['actual_primary']}")

    # 3-way side-by-side
    if string_s and llm_s:
        lines.append(f"\n{'='*70}\n  THREE-WAY: string vs llm.invoke vs DeepAgent\n{'='*70}")
        cats = sorted(set(q["category"] for q in EVAL_QUERIES))
        lines.append(f"  {'category':30s}  string  llm.invoke  deepagent")
        for cat in cats:
            cs = string_s["by_category"].get(cat, {})
            cl = llm_s["by_category"].get(cat, {})
            cd = deep_s["by_category"].get(cat, {})
            n = cs.get("n", 0)
            if not n:
                continue
            ps = cs["primary_hit"] / n * 100
            pl = cl.get("primary_hit", 0) / n * 100
            pd = cd.get("primary_hit", 0) / n * 100
            lines.append(f"  {cat:30s}  {ps:3.0f}%   {pl:3.0f}%       {pd:3.0f}%")
        # overall
        ns = string_s["primary_accuracy"] * 100
        nl = llm_s["primary_accuracy"] * 100
        nd = deep_s["primary_accuracy"] * 100
        lines.append(f"  {'OVERALL':30s}  {ns:3.0f}%   {nl:3.0f}%       {nd:3.0f}%")
        lines.append("")
        lines.append(f"  latency mean: string={string_s['latency_mean']*1000:.0f}ms  "
                     f"llm.invoke={llm_s['latency_mean']:.1f}s  "
                     f"deepagent={deep_s['latency_mean']:.1f}s")
    return "\n".join(lines)


# --- Main ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 9 DeepAgent eval.")
    parser.add_argument("--method", choices=["string", "llm", "deep", "all"],
                        default="all",
                        help="Which method to run (default: all)")
    parser.add_argument("--output", metavar="FILE", default=None,
                        help="Write JSON results to FILE")
    args = parser.parse_args()

    if args.method == "all":
        methods = ["string", "llm", "deep"]
    else:
        methods = [args.method]

    print(f"🔌 Neo4j: http://localhost:7474")
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, 1)
    print(f"   catalog: {len(rows)} docs")
    print(f"\n📋 Eval set: {len(EVAL_QUERIES)} queries across "
          f"{len(set(q['category'] for q in EVAL_QUERIES))} categories")
    print(f"   methods: {', '.join(methods)}\n")

    string_results, llm_results, deep_results = [], [], []
    string_summary, llm_summary = None, None

    if "string" in methods:
        string_results = run_string_eval(EVAL_QUERIES, rows)
        string_summary = summarize_results(string_results)
        print(render_legacy_report("STRING MATCHING (legacy)", string_summary,
                                   string_results))

    if "llm" in methods:
        from route_semantic import make_llm as _make_llm
        llm = _make_llm()
        llm_results = run_llm_eval(EVAL_QUERIES, rows, llm)
        llm_summary = summarize_results(llm_results)
        print(render_legacy_report("LLM INVOKE (legacy)", llm_summary,
                                   llm_results))

    if "deep" in methods:
        print("🤖 Building routing-only DeepAgent...")
        agent = build_routing_agent()
        print("   agent ready\n")
        deep_results = run_deep_eval(EVAL_QUERIES, agent)
        deep_summary = summarize_deep(deep_results)
        print(render_comparison(string_summary, llm_summary,
                                deep_summary, deep_results))

    if args.output:
        out = {
            "queries": EVAL_QUERIES,
            "string_results": [{k: v for k, v in vars(r).items()}
                               for r in string_results],
            "llm_results": [{k: v for k, v in vars(r).items()}
                            for r in llm_results],
            "deep_results": deep_results,
        }
        with open(args.output, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\n💾 wrote {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())