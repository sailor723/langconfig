#!/usr/bin/env python3
"""
End-to-end test: prove MiniMax prompt cache works through dv_chat's REPL.

Strategy:
  1. Boot dv_chat's REPL programmatically (don't go through stdin)
  2. Ask question Q1 — should be cold start
  3. Ask question Q2 (different) — should miss cache (system ends same, then new user msg)
  4. Ask Q1 again — should HIT cache (system identical + user msg identical)
  5. Print the cache_read numbers
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

# Import dv_chat as a module (works in REPL too)
import importlib.util
spec = importlib.util.spec_from_file_location("dv_chat", str(REPO_ROOT / "phase9" / "dv_chat.py"))
dv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dv)

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage


def ask(llm, system_msg, question, history, label):
    user_content = dv._build_user_message(question, history[-dv.HISTORY_TURNS:])
    t0 = time.time()
    resp = llm.invoke([system_msg, HumanMessage(content=user_content)])
    elapsed = time.time() - t0
    answer = resp.content
    usage = resp.usage_metadata or {}
    details = usage.get("input_token_details", {}) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    cache_read = int(details.get("cache_read", 0) or 0)
    pct = 100 * cache_read / in_tok if in_tok else 0
    print(f"  [{label}] in={in_tok:>6,}  cache_read={cache_read:>6,}  ({pct:5.1f}%)  "
          f"out={out_tok:>4,}  {elapsed:5.1f}s  q={question[:50]!r}")
    return {"q": question, "a": answer, "cache_read": cache_read, "in_tok": in_tok,
            "out_tok": out_tok, "elapsed": elapsed}


def main() -> int:
    print("📖 Loading system prompt (Nike 10-K) ...")
    full_text, page_count = dv._extract_text(dv.Path(dv.DEFAULT_DOC))
    system_content = dv._build_system_prompt(Path(dv.DEFAULT_DOC).stem, full_text)
    system_msg = dv.SystemMessage(content=system_content)
    print(f"   system prompt: {len(system_content):,} chars, {page_count} pages")

    llm = dv._make_llm()
    history = []

    print(f"\n=== Trial sequence ===")
    r1 = ask(llm, system_msg, "What was Nike's total revenue in fiscal 2023?", history, "T1 (cold)  ")
    history.append(r1)

    r2 = ask(llm, system_msg, "List Nike's main brands.", history, "T2 (warm)  ")
    history.append(r2)

    # Repeat T1's question — should now hit cache
    r3 = ask(llm, system_msg, "What was Nike's total revenue in fiscal 2023?", history, "T3 (re-T1) ")
    history.append(r3)

    # Repeat T2's question
    r4 = ask(llm, system_msg, "List Nike's main brands.", history, "T4 (re-T2) ")
    history.append(r4)

    print(f"\n=== Verdict ===")
    print(f"  T1 (cold):   cache_read = {r1['cache_read']:>6,} / {r1['in_tok']:,} ({100*r1['cache_read']/r1['in_tok']:.1f}%)  latency {r1['elapsed']:.2f}s")
    print(f"  T2 (new):    cache_read = {r2['cache_read']:>6,} / {r2['in_tok']:,} ({100*r2['cache_read']/r2['in_tok']:.1f}%)  latency {r2['elapsed']:.2f}s")
    print(f"  T3 (=T1):    cache_read = {r3['cache_read']:>6,} / {r3['in_tok']:,} ({100*r3['cache_read']/r3['in_tok']:.1f}%)  latency {r3['elapsed']:.2f}s  <-- should be high")
    print(f"  T4 (=T2):    cache_read = {r4['cache_read']:>6,} / {r4['in_tok']:,} ({100*r4['cache_read']/r4['in_tok']:.1f}%)  latency {r4['elapsed']:.2f}s  <-- should be high")

    if r3["cache_read"] > r1["cache_read"] and r4["cache_read"] > r2["cache_read"]:
        print(f"\n  ✓ Cache works in REPL — repeating questions hit the prompt cache")
    else:
        print(f"\n  ✗ Cache did not improve on repeat — investigate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
