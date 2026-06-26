#!/usr/bin/env python3
"""
Phase 9 / Step A3 — CLI + REPL over the DeepAgent-based query pipeline.

The legacy code path (route_semantic.py + dv_chat.py + eval_routing.py) is
left intact. This file is the deepagent-based parallel, used like:

  # Single answer (route + load + synthesize, single LLM call graph)
  python phase9/query_deep.py --answer "Nike revenue 2023"

  # Interactive REPL with multi-turn continuity
  python phase9/query_deep.py --chat

Per rules.md: no truncation, no chunking, no embeddings; MiniMax M3 only.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langchain_core.messages import HumanMessage  # noqa: E402

from query_agent import get_query_agent  # noqa: E402

HELP_TEXT = """\
Phase 9 / Step A3 — DeepAgent-based query CLI.

Modes:
  --answer "Q"   one-shot: route + load + synthesize (sync)
  --chat          interactive REPL with multi-turn thread_id
  --show-agent    print the agent's subagent + tool inventory and exit

Examples:
  python phase9/query_deep.py --answer "Nike revenue 2023"
  python phase9/query_deep.py --answer "苏格拉底思想"
  python phase9/query_deep.py --chat

The REPL keeps the same thread_id across turns, so MemorySaver gives us
session continuity (catalog and prior context cached).
"""


def _print_turn_footer(elapsed: float, in_tok: int, out_tok: int,
                       cache_read: int) -> None:
    cum = elapsed
    cache_pct = 100 * cache_read / in_tok if in_tok else 0
    print()
    print(f"   ├─ tokens:   in={in_tok:>7,}  out={out_tok:>5,}")
    print(f"   │            cache_read={cache_read:>6,}  ({cache_pct:.1f}% cached)")
    print(f"   └─ latency:  {elapsed:5.1f}s")


def _extract_usage(result) -> tuple[int, int, int]:
    """Pull in/out/cache_read tokens from the last AIMessage in result."""
    msgs = result.get("messages", [])
    last = msgs[-1] if msgs else None
    if last is None:
        return 0, 0, 0
    usage = getattr(last, "usage_metadata", None) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return in_tok, out_tok, cache_read


def _strip_think(answer: str) -> str:
    """Drop <think>...</think> wrappers the LLM sometimes produces."""
    if "<think>" in answer and "</think>" in answer:
        return answer.split("</think>", 1)[1].strip()
    return answer


def cmd_answer(query: str) -> int:
    agent = get_query_agent()
    t0 = time.time()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "phase9-answer"}},
    )
    elapsed = time.time() - t0
    answer = _strip_think(result["messages"][-1].content)
    in_tok, out_tok, cache_read = _extract_usage(result)

    print(f"\nQuery: {query!r}")
    print(f"\n🤖 {answer}")
    _print_turn_footer(elapsed, in_tok, out_tok, cache_read)
    return 0


def cmd_show_agent() -> int:
    agent = get_query_agent()
    print("Agent nodes (LangGraph state graph):")
    try:
        for node in agent.get_graph().nodes:
            print(f"  - {node}")
    except Exception as e:
        print(f"  (could not introspect: {e})")
    print(f"\nTool inventory: 4 tools (fetch_catalog, read_doc, list_docs, load_multi_doc)")
    print(f"Subagents: 3 (router, loader, answerer)")
    print(f"Checkpointer: MemorySaver (in-memory, single-process)")
    return 0


def cmd_chat() -> int:
    agent = get_query_agent()
    thread_id = "phase9-chat"
    cfg = {"configurable": {"thread_id": thread_id}}

    print(f"\n{'='*60}")
    print(f"Phase 9 / DeepAgent REPL — thread_id={thread_id}")
    print(f"Type /quit to exit, /help for commands.\n")

    turn = 0
    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return 0

        if not raw:
            continue
        low = raw.lower()

        if low in ("/quit", "/exit", "/q"):
            print("bye.")
            return 0
        if low in ("/help", "/h"):
            print(HELP_TEXT)
            continue
        if low in ("/agent", "/show-agent"):
            cmd_show_agent()
            continue

        turn += 1
        t0 = time.time()
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": raw}]},
                config=cfg,
            )
        except Exception as e:
            print(f"  ✗ error: {e}")
            continue
        elapsed = time.time() - t0

        answer = _strip_think(result["messages"][-1].content)
        in_tok, out_tok, cache_read = _extract_usage(result)

        print(f"\n🤖 {answer}")
        _print_turn_footer(elapsed, in_tok, out_tok, cache_read)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / DeepAgent-based query CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--answer", metavar="Q", help="one-shot answer")
    group.add_argument("--chat", action="store_true", help="interactive REPL")
    group.add_argument("--show-agent", action="store_true",
                       help="print agent topology and exit")
    args = parser.parse_args()

    if not os.getenv("MINIMAX_API_KEY"):
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        return 1

    if args.answer:
        return cmd_answer(args.answer)
    if args.chat:
        return cmd_chat()
    if args.show_agent:
        return cmd_show_agent()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())