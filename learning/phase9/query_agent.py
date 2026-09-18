#!/usr/bin/env python3
"""
Phase 9 / Step A2 — DeepAgent factory for query-side routing.

Builds a `create_deep_agent(...)` with three subagents:

  router    — picks primary + supporting docs via fetch_catalog_tool
  loader    — loads multi-doc context via read_doc_tool / load_multi_doc_tool
  answerer  — synthesizes the answer with citations

The main agent has the same tool set and decides which subagent to delegate
to. With MemorySaver checkpointer, multi-turn REPL gets cache hits and
session continuity.

Per rules.md: this is a thin layer over `deepagents.create_deep_agent`. We
rely on its built-in middleware (TodoList, Summarization, SubAgent,
Filesystem). We do NOT reimplement those.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from graphindex_tools import ALL_TOOLS  # noqa: E402

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"


# --- Subagent definitions -------------------------------------------------

ROUTER_SYSTEM = """You are the router subagent. Given a user query, decide
which document is the best match.

Use `fetch_catalog_tool(project_id=1)` to read the catalog. Then pick ONE
primary document and OPTIONALLY 0-3 supporting documents from DIFFERENT
domains (different semantic areas that add complementary context).

Reply with a JSON object on a single line, NO commentary, NO markdown:

{{"primary": "<exact doc name>", "primary_domain": "<short_domain_tag>",
  "primary_confidence": <0.0-1.0>,
  "supporting": [{{"name": "<doc>", "reason": "<why it adds context>"}}],
  "reasoning": "<one short sentence>"}}

Rules:
- Use lowercase snake_case for primary_domain (max 30 chars)
- supporting must use exact doc names from the catalog
- If NONE of the documents are relevant, reply: {{"primary": null,
  "primary_domain": null, "primary_confidence": 0.0, "supporting": [],
  "reasoning": "<why>"}}
- Do NOT call any other tools."""

LOADER_SYSTEM = """You are the loader subagent. Given a primary document
name and an optional list of supporting names, load their content into a
single context string.

Use `load_multi_doc_tool(primary=<primary>, supporting=[<names>])` to get
the combined text. Then return that text verbatim — do NOT summarize, do
NOT add commentary. Your job is to fetch and pass through.

If the tool errors out, return the error string and explain."""

ANSWERER_SYSTEM = """You are the answerer subagent. Given a user query and
already-loaded document context (provided by the loader subagent or main
agent), synthesize a final answer.

Rules:
1. Use ONLY the supplied documents. If the answer is not present, say so.
2. Cite document number and page, e.g. "(Document 1, page 3)".
3. When multiple documents are provided, weave them together — note where
   they agree, disagree, or complement each other.
4. If supporting documents don't add relevant context, ignore them and
   answer from the primary.
5. Be concise but thorough. Output in the same language as the query."""


def build_query_agent(model_name: str = MODEL, checkpointer: bool = True):
    """Construct the query-side DeepAgent with router/loader/answerer subagents.

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

    main_system = (
        "You are a multi-document research assistant. The user asks a "
        "question; you must (1) route to the best document, (2) load its "
        "content (plus any cross-domain supporting docs), and (3) "
        "synthesize a final answer with citations.\n\n"
        "Available tools:\n"
        "  - fetch_catalog_tool: read the doc catalog (cheap)\n"
        "  - read_doc_tool: read a single doc\n"
        "  - load_multi_doc_tool: load primary + supporting in one call\n"
        "  - list_docs_tool: list all doc names\n\n"
        "Recommended workflow (use the TodoList automatically):\n"
        "  1. Call fetch_catalog_tool to see what's available\n"
        "  2. Decide primary + supporting (delegate to `router` subagent if helpful)\n"
        "  3. Call load_multi_doc_tool to get the combined context\n"
        "  4. Synthesize the answer with citations\n\n"
        "Delegate to subagents when their specialty applies:\n"
        "  - router: pick primary + supporting\n"
        "  - loader: load multi-doc context\n"
        "  - answerer: synthesize final answer\n\n"
        "Always cite which document(s) and page numbers support each claim."
    )

    subagents = [
        {
            "name": "router",
            "description": (
                "Pick the best primary document and 0-3 supporting documents "
                "for a user query. Use the catalog. Returns JSON."
            ),
            "system_prompt": ROUTER_SYSTEM,
        },
        {
            "name": "loader",
            "description": (
                "Load primary + supporting documents into a single context "
                "string using load_multi_doc_tool. Returns the raw text."
            ),
            "system_prompt": LOADER_SYSTEM,
        },
        {
            "name": "answerer",
            "description": (
                "Synthesize a final answer with citations from already-loaded "
                "document context. Output language matches the query."
            ),
            "system_prompt": ANSWERER_SYSTEM,
        },
    ]

    kwargs = dict(
        model=model,
        system_prompt=main_system,
        tools=list(ALL_TOOLS),
        subagents=subagents,
    )
    if checkpointer:
        kwargs["checkpointer"] = MemorySaver()

    return create_deep_agent(**kwargs)


@lru_cache(maxsize=1)
def get_query_agent():
    """Module-level singleton — lazy init, reused across CLI invocations."""
    return build_query_agent()


# --- Smoke test ----------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python phase9/query_agent.py <query text>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    agent = get_query_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "phase9-smoke"}},
    )
    print("\n=== FINAL ANSWER ===\n")
    print(result["messages"][-1].content)