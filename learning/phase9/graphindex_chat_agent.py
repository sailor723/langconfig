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

  python phase9/graphindex_chat_agent.py --answer "Nike revenue 2023"
  python phase9/graphindex_chat_agent.py --chat
  python phase9/graphindex_chat_agent.py --show-agent

Programmatic use:

  from phase9.graphindex_chat_agent import get_graphindex_chat_agent
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
from typing import Optional

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

# Reuse the 5 graphindex @tool wrappers (4 old + 1 new: route_query_tool)
from graphindex_tools import (  # noqa: E402
    fetch_catalog_tool,
    list_docs_tool,
    load_multi_doc_tool,
    read_doc_tool,
    route_query_tool,
    set_active_doc_scope,
    reset_active_doc_scope,
)

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
# Default LLM is deepseek-chat (user choice in step 4). Kept as default
# but the backend API endpoint can override per-request in step K.
DEFAULT_MODEL = "minimax-m3"


SYSTEM_PROMPT = """You are **graphindex_chat** — a conversational research
assistant for the user's project documents.

You have 5 tools:

  - list_docs_tool(project_id)             — list available doc names (cheap)
  - fetch_catalog_tool(project_id)         — full catalog (name + about)
  - route_query_tool(query, project_id)    — pick top 1-3 matching docs
                                             for a query (LLM semantic routing;
                                             returns JSON with primary +
                                             supporting[0-3] + reasoning)
  - read_doc_tool(name, project_id)        — read a single doc's full text
  - load_multi_doc_tool(primary, supporting, project_id)
                                            — one-shot: load primary + supporting

WORKFLOW (progressive disclosure — MUST follow this order):

  1. ALWAYS call route_query_tool(query=..., project_id=1) FIRST for
     every user question. This is the LLM-semantic routing step that
     picks the best primary doc + 0-3 cross-domain supporting docs.
     It returns JSON like:
       {"primary": "<name>", "supporting": [{"name": "<name>",
         "reason": "..."}, ...], "primary_confidence": 0.0-1.0, ...}
  2. PASS those exact names to load_multi_doc_tool(primary=<primary>,
     supporting=[<names from route_query_tool.supporting>]).
  3. SYNTHESIZE the final answer from the loaded context. Cite the
     document name and page when relevant.

  - Use list_docs_tool / fetch_catalog_tool only for casual browse
    (e.g. "what docs do I have?"), not for answering a question.
  - Use read_doc_tool only as a fallback when route_query_tool isn't
    available or you need to re-read a specific doc.

If the user asks something unrelated to the project documents, say so
politely. Don't make up document names — route_query_tool is the
source of truth for "which docs match this query".

Keep replies concise but cite your sources. Output language matches the
query.
"""


def create_graphindex_chat_agent(
    project_id: Optional[int] = 1,
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

    # Project-scoped system prompt. When project_id is None (the
    # active project couldn't be determined), we tell the LLM there
    # is no project context — the LLM will then call the tools
    # without a project filter, the tools will return 0 docs, and
    # the LLM will naturally reply "no matched document found".
    # This is preferred over silently falling back to a hardcoded
    # project (e.g. project 1), which historically caused the
    # misleading "no documents in project X" message when the user
    # was actually on a different project.
    if project_id is None:
        scoped_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"No project is currently selected. The tools may return "
            f"empty results. If you can't find a relevant document, "
            f"reply honestly: 'No matched document found in the "
            f"current scope. Please select a project or upload docs.'"
        )
    else:
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
            route_query_tool,
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
def get_graphindex_chat_agent(project_id: Optional[int] = 1):
    """Module-level singleton — lazy init, reused across CLI invocations.

    Cache up to 4 agents keyed by project_id so a project switch doesn't
    rebuild.
    """
    return create_graphindex_chat_agent(project_id=project_id)


def stream_graphindex_chat(
    project_id: Optional[int],
    query: str,
    thread_id: str,
    scope=None,
) -> str:
    """Run the graphindex_chat agent (single shot) and return the final
    assistant text. Used by the langconfig backend at
    `POST /api/chat/message/stream` when the agent is a graphindex_chat
    template — we swap out the generic langconfig flow for the proven
    Phase 9 single-agent deepagent that already has the 5 graphindex
    tools + progressive-disclosure system_prompt.

    The optional `scope` argument restricts which docs the agent can see
    and read. It is carried into the tool layer via a ContextVar, so the
    LLM-facing tool signatures don't have to expose a `scope` argument
    (keeps the agent's prompt cache hot).

    Args:
        project_id: Project to scope catalog/doc reads to.
        query: User's question.
        thread_id: LangGraph checkpointer thread id (for multi-turn).
        scope: Optional doc filter.
                - None / "all" / []  → no filter, all docs visible
                - [doc1, doc2, ...]  → only these docs (by exact name)

    Returns:
        The final assistant text (after <think> stripping). Yields nothing —
        the LLM run is synchronous; if you need streaming, use the agent
        directly via `agent.stream(...)`.
    """
    agent = get_graphindex_chat_agent(project_id=project_id)
    scope_token = set_active_doc_scope(scope)
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        # Always restore the previous scope, even if the agent raised.
        reset_active_doc_scope(scope_token)
    # Last message is the assistant's final response
    last = result["messages"][-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    # Strip <think>...</think> blocks if present
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    return text


def stream_graphindex_chat_events(
    project_id: Optional[int],
    query: str,
    thread_id: str,
    scope=None,
):
    """Streaming variant: yields LangGraph events from
    `agent.stream(..., stream_mode="values")`. Each event is the state
    dict after each node runs, so the caller can:
      - yield "on_chat_model_stream" chunks as they arrive (token-by-token)
      - yield "on_tool_start" / "on_tool_end" events for tool-call tracking
      - skip <think>...</think> blocks in the assistant's final text

    The langconfig backend's `POST /api/chat/message/stream` wraps this
    generator and re-emits SSE events that match the existing
    `{type: chunk|tool_start|tool_end|done, ...}` schema.

    `scope` works the same as in `stream_graphindex_chat`:
      None / "all" / []   → all docs visible
      [doc1, doc2, ...]   → only these docs (by exact name)
    """
    agent = get_graphindex_chat_agent(project_id=project_id)
    scope_token = set_active_doc_scope(scope)
    try:
        for event in agent.stream(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="values",
        ):
            yield event
    finally:
        # Always restore the previous scope, even if the agent raised.
        reset_active_doc_scope(scope_token)


# --- CLI plumbing (matches query_deep.py style) ---------------------------

HELP_TEXT = """\
Phase 9 / graphindex_chat agent — single-agent DeepAgent for chat.

Modes:
  --answer "Q"   one-shot: route + load + synthesize (sync)
  --chat          interactive REPL with multi-turn thread_id
  --show-agent    print the agent's tool inventory and exit

Examples:
  python phase9/graphindex_chat_agent.py --answer "Nike revenue 2023"
  python phase9/graphindex_chat_agent.py --answer "苏格拉底思想"
  python phase9/graphindex_chat_agent.py --chat

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

    # Tool-call trace — shows which tools the LLM chose to use, in order.
    # This verifies the progressive-disclosure workflow: route_query_tool
    # should come first, then load_multi_doc_tool.
    print(f"\nQuery: {query!r}  (project_id={project_id})")
    print("\n── Tool calls (in order) ──")
    for i, msg in enumerate(result["messages"]):
        msg_type = getattr(msg, "type", "?")
        name = getattr(msg, "name", None) or getattr(msg, "tool_call_id", None)
        # AI messages may have tool_calls
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                args_str = str(tc.get("args", {}))
                if len(args_str) > 200:
                    args_str = args_str[:200] + "…"
                print(f"  [{i}] {tc.get('name')}({args_str})")
        elif msg_type == "tool":
            content = getattr(msg, "content", "")
            print(f"  [{i}]   → {len(content):,} chars returned")
    print("\n🤖 " + answer)
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
    print(f"\nTool inventory: 5 tools")
    print(f"  - list_docs_tool")
    print(f"  - fetch_catalog_tool")
    print(f"  - route_query_tool       (progressive disclosure — Step M)")
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

def cmd_stream_sync(query: str, project_id: int = 1) -> int:
    """Test the single-shot `stream_graphindex_chat()` wrapper."""
    print(f"\nQuery: {query!r}  (project_id={project_id})")
    print("Calling stream_graphindex_chat()...")
    t0 = time.time()
    try:
        text = stream_graphindex_chat(
            project_id=project_id,
            query=query,
            thread_id=f"stream-sync-test-p{project_id}",
        )
        elapsed = time.time() - t0
        print(f"\n🤖 {text}")
        print(f"\n  ({elapsed:.1f}s, returned {len(text):,} chars)")
        return 0
    except Exception as e:
        print(f"  ✗ error: {e}")
        return 1


def cmd_stream_events(query: str, project_id: int = 1) -> int:
    """Test the streaming `stream_graphindex_chat_events()` wrapper.

    Diffs LangGraph state updates and prints:
      - tool_start / tool_end events
      - chunk deltas (assistant text being added)
      - final state
    """
    print(f"\nQuery: {query!r}  (project_id={project_id})")
    print("Calling stream_graphindex_chat_events()...")
    t0 = time.time()
    last_text = ""
    try:
        for state in stream_graphindex_chat_events(
            project_id=project_id,
            query=query,
            thread_id=f"stream-events-test-p{project_id}",
        ):
            messages = state.get("messages", [])
            # Show only the most recent message of each interesting type
            if messages:
                last_msg = messages[-1]
                msg_type = getattr(last_msg, "type", "?")
                if msg_type == "ai":
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            print(f"  → tool call: {tc.get('name')}({list(tc.get('args', {}).keys())})")
                    else:
                        text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                        # Strip <think> blocks for the display
                        if "<think>" in text and "</think>" in text:
                            text = text.split("</think>", 1)[1].strip()
                        if text and text != last_text:
                            delta = text[len(last_text):]
                            last_text = text
                            if delta.strip():
                                print(f"  + chunk ({len(delta):,} chars): {delta[:80]!r}...")
                elif msg_type == "tool":
                    tool_name = getattr(last_msg, "name", "unknown")
                    content = getattr(last_msg, "content", "")
                    print(f"  ← tool result: {tool_name} returned {len(content or ''):,} chars")
        elapsed = time.time() - t0
        print(f"\n  ({elapsed:.1f}s, final answer: {len(last_text):,} chars)")
        return 0
    except Exception as e:
        print(f"  ✗ error: {e}")
        return 1


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
    parser.add_argument("--stream-sync", metavar="TEXT",
                        help="test stream_graphindex_chat() (single-shot wrapper)")
    parser.add_argument("--stream-events", metavar="TEXT",
                        help="test stream_graphindex_chat_events() (streaming wrapper)")
    parser.add_argument("--project-id", type=int, default=1,
                        help="project ID to scope doc reads (default 1)")
    args = parser.parse_args(argv)

    if args.show_agent:
        return cmd_show_agent(project_id=args.project_id)
    if args.answer:
        return cmd_answer(args.answer, project_id=args.project_id)
    if args.chat:
        return cmd_chat(project_id=args.project_id)
    if args.stream_sync:
        return cmd_stream_sync(args.stream_sync, project_id=args.project_id)
    if args.stream_events:
        return cmd_stream_events(args.stream_events, project_id=args.project_id)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())