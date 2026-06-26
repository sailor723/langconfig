#!/usr/bin/env python3
"""
Phase 9 / Step J — graphindex_chat agent.

A single-agent DeepAgent (no subagents) that uses the same 4 graphindex
tools as `query_agent.py` but is tuned for chat-style interaction:
  - No router/loader/answerer subagent delegation (too heavy for chat)
  - LLM main agent decides which tools to call directly
  - Reuses the MemorySaver checkpointer for multi-turn continuity
  - Same project_id default (1)
  - Uses `graphindex_*` @tool wrappers from `phase9/graphindex_tools.py`
    (same ones as `query_agent.py`, so the behavior is consistent)

Why a separate agent from `query_agent.py`?

  - `query_agent.py` is the **research** mode (3 subagents, more expensive,
    better for one-shot deep questions with citations)
  - `graphindex_chat` is the **chat** mode (1 main agent, cheaper, better
    for multi-turn conversational queries)

Both share the same `graphindex_*` tools, so the LLM can pick primary +
supporting docs the same way; only the orchestration differs.

CLI modes:

  python phase9/build_graphindex_chat_agent.py --answer "Nike revenue 2023"
  python phase9/build_graphindex_chat_agent.py --chat
  python phase9/build_graphindex_chat_agent.py --show-agent

Programmatic use:

  from phase9.build_graphindex_chat_agent import get_graphindex_chat_agent
  agent = get_graphindex_chat_agent(project_id=1)
  result = agent.invoke({"messages": [{"role": "user", "content": "..."}]},
                          config={"configurable": {"thread_id": "..."}})

Per rules.md: no truncation, no chunking, no embeddings; deepseek-chat
for the main LLM. Catalog stays in Neo4j; the LLM only sees the doc list
on demand via list_docs_tool / fetch_catalog_tool.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

# Reuse the 4 graphindex @tool wrappers
from graphindex_tools import (  # noqa: E402
    fetch_catalog_tool,
    list_docs_tool,
    load_multi_doc_tool,
    read_doc_tool,
)

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
# Default LLM is deepseek-chat (user choice in step 4). Kept as default
# but the backend API endpoint can override per-request in step K.
DEFAULT_MODEL = "minimax-m3"


SYSTEM_PROMPT = """You are **graphindex_chat** — a conversational research
assistant for the user's project documents.

You have 4 tools:

  - list_docs_tool(project_id)             — list available doc names
  - fetch_catalog_tool(project_id)         — full catalog (name + about)
  - read_doc_tool(name, project_id)        — read a single doc's full text
  - load_multi_doc_tool(primary, supporting, project_id)
                                            — one-shot: load primary + supporting

Workflow:

  1. If unsure what docs exist, call list_docs_tool first (cheap).
  2. To answer a question, call load_multi_doc_tool with a primary doc
     name and 0-3 supporting doc names (different domains). This returns
     the combined context.
  3. Synthesize the final answer from the loaded context. Cite the
     document name and page when relevant.

If the user asks something unrelated to the project documents, say so
politely. Don't make up document names — always check the catalog.

Keep replies concise but cite your sources. Output language matches the
query.
"""


def build_graphindex_chat_agent(
    project_id: int = 1,
    model_name: str = DEFAULT_MODEL,
    checkpointer: bool = True,
):
    """Construct the graphindex_chat DeepAgent (single agent, 4 tools).

    Args:
        project_id: The project to scope catalog/doc reads to. Default 1.
        model_name: LLM to use. Default is deepseek-chat (per step 4).
        checkpointer: Whether to use MemorySaver for multi-turn continuity.

    Returns:
        A CompiledStateGraph (LangGraph). Call `.invoke({"messages": [...]})`.
    """
    from deepagents import create_deep_agent

    if not MINIMAX_API_KEY:
        raise RuntimeError("MINIMAX_API_KEY not set in .env")

    from langchain.chat_models import init_chat_model
    model = init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=0.0,
        max_tokens=8192,
    )

    # Project-scoped system prompt
    scoped_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Current project_id: {project_id}. Always pass project_id={project_id} "
        f"to the tools. To discover what's in the project, call "
        f"list_docs_tool(project_id={project_id}) first."
    )

    kwargs = dict(
        model=model,
        system_prompt=scoped_prompt,
        tools=[
            list_docs_tool,
            fetch_catalog_tool,
            read_doc_tool,
            load_multi_doc_tool,
        ],
    )
    if checkpointer:
        kwargs["checkpointer"] = MemorySaver()

    agent = create_deep_agent(**kwargs)
    # Stash project_id so CLI/REPL can read it back
    agent._graphindex_chat_project_id = project_id
    return agent


@lru_cache(maxsize=4)
def get_graphindex_chat_agent(project_id: int = 1):
    """Module-level singleton — lazy init, reused across CLI invocations.

    Cache up to 4 agents keyed by project_id so a project switch doesn't
    rebuild.
    """
    return build_graphindex_chat_agent(project_id=project_id)


# --- CLI plumbing (matches query_deep.py style) ---------------------------

HELP_TEXT = """\
Phase 9 / graphindex_chat agent — single-agent DeepAgent for chat.

Modes:
  --answer "Q"   one-shot: route + load + synthesize (sync)
  --chat          interactive REPL with multi-turn thread_id
  --show-agent    print the agent's tool inventory and exit

Examples:
  python phase9/build_graphindex_chat_agent.py --answer "Nike revenue 2023"
  python phase9/build_graphindex_chat_agent.py --answer "苏格拉底思想"
  python phase9/build_graphindex_chat_agent.py --chat

The REPL keeps the same thread_id across turns, so MemorySaver gives us
session continuity (catalog and prior context cached).
"""


def _print_turn_footer(elapsed: float, in_tok: int, out_tok: int,
                       cache_read: int) -> None:
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
    if "<think>" in answer and "</think>" in answer:
        return answer.split("</think>", 1)[1].strip()
    return answer


def cmd_answer(query: str, project_id: int = 1) -> int:
    agent = get_graphindex_chat_agent(project_id=project_id)
    t0 = time.time()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": f"graphindex-chat-p{project_id}"}},
    )
    elapsed = time.time() - t0
    answer = _strip_think(result["messages"][-1].content)
    in_tok, out_tok, cache_read = _extract_usage(result)

    print(f"\nQuery: {query!r}  (project_id={project_id})")
    print(f"\n🤖 {answer}")
    _print_turn_footer(elapsed, in_tok, out_tok, cache_read)
    return 0


def cmd_show_agent(project_id: int = 1) -> int:
    agent = get_graphindex_chat_agent(project_id=project_id)
    print("Agent nodes (LangGraph state graph):")
    try:
        for node in agent.get_graph().nodes:
            print(f"  - {node}")
    except Exception as e:
        print(f"  (could not introspect: {e})")
    print(f"\nTool inventory: 4 tools")
    print(f"  - list_docs_tool")
    print(f"  - fetch_catalog_tool")
    print(f"  - read_doc_tool")
    print(f"  - load_multi_doc_tool")
    print(f"Subagents: 0 (single agent, no subagent delegation)")
    print(f"Checkpointer: MemorySaver (in-memory, single-process)")
    print(f"Project ID: {project_id}")
    return 0


def cmd_chat(project_id: int = 1) -> int:
    agent = get_graphindex_chat_agent(project_id=project_id)
    thread_id = f"graphindex-chat-repl-p{project_id}"
    cfg = {"configurable": {"thread_id": thread_id}}

    print(f"\n{'='*60}")
    print(f"Phase 9 / graphindex_chat REPL — thread_id={thread_id}")
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
            cmd_show_agent(project_id=project_id)
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


# --- CLI entry point ------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="graphindex_chat agent — Phase 9 / Step J",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    parser.add_argument("--answer", help="one-shot: route + load + synthesize (sync)")
    parser.add_argument("--chat", action="store_true", help="interactive REPL")
    parser.add_argument("--show-agent", action="store_true",
                        help="print the agent's tool inventory and exit")
    parser.add_argument("--project-id", type=int, default=1,
                        help="project ID to scope doc reads (default 1)")
    args = parser.parse_args(argv)

    if args.show_agent:
        return cmd_show_agent(project_id=args.project_id)
    if args.answer:
        return cmd_answer(args.answer, project_id=args.project_id)
    if args.chat:
        return cmd_chat(project_id=args.project_id)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())