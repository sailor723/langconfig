#!/usr/bin/env python3
"""
Phase 9 / agent_chat — DeepAgent-powered chat with two-LLM routing.

Uses the ``deepagents`` library (``create_deep_agent``) with:
  - **Gemma4** (local Ollama) for doc routing
  - **Minimax M3** (API) for answer synthesis

The agent tools live in :mod:`tools`. This module wires them together
into a DeepAgent REPL (or single-query mode).

Usage:
    uv run python -m learning.phase9.legacy.agent_chat --project-id 1
    uv run python -m learning.phase9.legacy.agent_chat --query "tesla strategy" --project-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent

from learning.phase9.legacy.tools import make_tools


SYSTEM_PROMPT = """You are a research analyst assistant. Your workflow:

1. **list_docs** — See what documents are available.
2. **query_docs** — Find which documents match the user's question.
3. **read_doc** — Read the full text of matched documents.
4. **answer** — Synthesize a final answer from the documents.

Always use citations like (Document N, Filename) to reference sources.
If the user asks a question that requires information from documents,
use the tools above rather than guessing.

If no documents match, tell the user honestly."""


def build_agent(project_id: int):
    """Create and return the DeepAgent instance."""
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    model = init_chat_model(
        model=os.getenv("GRAPHINDEX_MODEL", "minimax-m3"),
        model_provider="openai",
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.2,
        max_tokens=int(os.getenv("GRAPHINDEX_ANSWER_MAX_TOKENS", "8192")),
    )

    agent = create_deep_agent(
        model=model,
        tools=make_tools(project_id),
        system_prompt=SYSTEM_PROMPT,
    )
    return agent


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_single(agent, query: str) -> None:
    """Run a single query and stream the reply."""
    print(f"\nQuery: {query}\n")
    print("─" * 60)

    async def _stream():
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=query)]},
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", "")
                if isinstance(chunk, str):
                    print(chunk, end="", flush=True)
                elif hasattr(chunk, "content"):
                    print(chunk.content, end="", flush=True)
            elif kind == "on_tool_start":
                print(f"\n  🛠 {event.get('name', '?')}... ", end="", flush=True)
            elif kind == "on_tool_end":
                print("✓", flush=True)

        print("\n" + "─" * 60)

    asyncio.run(_stream())


def _run_repl(agent) -> None:
    """Interactive REPL with conversation history."""
    print("\nDeepAgent Chat — type 'exit' to quit, '!reset' to clear history\n")
    import readline  # nicer line editing

    messages: list = []

    while True:
        try:
            raw = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw.lower() in ("exit", "quit"):
            break
        if raw.lower() == "!reset":
            messages.clear()
            print("Conversation reset.")
            continue

        print(f"\nQuery: {raw}\n")
        print("─" * 60)

        async def _stream():
            nonlocal messages
            messages.append(HumanMessage(content=raw))
            async for event in agent.astream_events(
                {"messages": messages},
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", "")
                    if isinstance(chunk, str):
                        print(chunk, end="", flush=True)
                    elif hasattr(chunk, "content"):
                        print(chunk.content, end="", flush=True)
                elif kind == "on_tool_start":
                    print(f"\n  🛠 {event.get('name', '?')}... ", end="", flush=True)
                elif kind == "on_tool_end":
                    print("✓", flush=True)
                elif kind == "on_chain_end":
                    data = event.get("data", {})
                    output = data.get("output", {})
                    if isinstance(output, dict) and "messages" in output:
                        messages = output["messages"]

            print("\n" + "─" * 60)

        asyncio.run(_stream())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / agent_chat — DeepAgent-powered document chat",
    )
    parser.add_argument("--query", metavar="TEXT",
                        help="Single query (non-interactive)")
    parser.add_argument("--project-id", type=int,
                        default=int(os.getenv("GRAPHINDEX_DEFAULT_PROJECT_ID", "1")),
                        help="Neo4j project id")
    args = parser.parse_args()

    project_id = args.project_id
    print(f"🔌 Neo4j: {os.getenv('NEO4J_URL', 'http://localhost:7474')}")
    print(f"🤖 Agent: {os.getenv('GRAPHINDEX_MODEL', 'minimax-m3')} "
          f"(routing: {os.getenv('GRAPHINDEX_ROUTING_MODEL', 'gemma4')})")

    agent = build_agent(project_id=project_id)

    if args.query:
        _run_single(agent, args.query)
    else:
        _run_repl(agent)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
