#!/usr/bin/env python3
"""
Phase 9 / Step C — DeepAgent factory for build-side (ingest + enrich).

The legacy build_graphindex.py uses raw llm.invoke + manual orchestration.
This module exposes a parallel deepagent-based path with 3 subagents:

  ingest_checker — SHA-256 hash + filesystem/Neo4j dedup
  enricher       — generate about / supports / out_of_scope / few_shot
  writer         — copy file + upsert Neo4j node + set content_sha256

The deepagent's built-in TodoList + SubAgent middleware handles step
ordering automatically (LLM decides which tool/subagent to call next).
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from buildindex_tools import ALL_TOOLS  # noqa: E402

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"


INGEST_CHECKER_SYSTEM = """You are the ingest_checker subagent. Given a file
path, your job is to:

1. Compute its SHA-256 hash via `sha256_of_file_tool`.
2. Search the filesystem via `scan_filesystem_for_dupe_tool`.
3. Search Neo4j via `scan_neo4j_for_dupe_tool`.

Reply with a single JSON object:
{{"content_hash": "<hex>", "short_hash": "<first 8 chars>", "fs_dupes": [<paths>], "neo_dupes": [<doc names>], "verdict": "new|fs_dupe|neo_dupe"}}

Rules:
- "new" means neither filesystem nor Neo4j has the file
- "fs_dupe" means a file with the same sha256 already exists on disk
- "neo_dupe" means a Neo4j node has the same content_sha256
- Do NOT load any documents, do NOT call any other tools
- Do NOT add commentary, markdown, or extra text outside the JSON"""


ENRICHER_SYSTEM = """You are the enricher subagent. Given a file path and
the list of other documents in the project, your job is to produce routing
metadata for this document.

Steps:
1. Call `read_doc_tool(file_path=<path>, max_chars=6000)` to get the doc text.
2. Call `get_graphindex_metadata_tool(file_path=<path>)` for any extra context.
3. Call `list_other_doc_names_tool()` to know the other docs.
4. Generate the enrichment JSON.

Reply with a single JSON object on one line:
{{"about": "<150-300 char description>", "supports": [<5-11 query strings>], "out_of_scope": [<exact doc names from the list above>], "few_shot": [{{"query": "...", "answer_hint": "..."}}]}}

CRITICAL rules:
- "about" must describe what the document covers, not what it contains
- "supports" are the natural-language queries this doc can answer
- "out_of_scope" entries MUST be exact doc names from the list above —
  each name on its own, no "and" / "see" / "or" / grouping
- "few_shot" should have 2-4 example Q/A pairs
- Be concise, routing-oriented, conservative (don't invent topics)
- Do NOT add commentary, markdown, or extra text outside the JSON"""


WRITER_SYSTEM = """You are the writer subagent. Given a file path, a
hash prefix, and an enrichment payload, your job is to:

1. Call `copy_to_project_dir_tool(source_path=<file>, short_hash=<8 chars>)`.
2. Call `upsert_doc_to_neo4j_tool(name=<new path basename>, file_path=<new path>, ...)`.

Reply with a single line of JSON:
{{"copied_to": "<new path>", "neo4j": "OK"}}

Do NOT call any other tools. Do NOT add commentary."""


def build_build_agent(model_name: str = MODEL, checkpointer: bool = True):
    """Construct the build-side DeepAgent."""
    from deepagents import create_deep_agent
    from langchain.chat_models import init_chat_model

    if not MINIMAX_API_KEY:
        raise RuntimeError("MINIMAX_API_KEY not set in .env")

    model = init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=0.0,
        max_tokens=8192,
    )

    main_system = (
        "You are a build-side agent for a multi-document knowledge base.\n"
        "You ingest new files into a Neo4j-backed graphindex, ensuring "
        "SHA-256 dedup and LLM-generated routing metadata.\n\n"
        "Workflow (the TodoList middleware tracks this automatically):\n"
        "  1. Delegate to `ingest_checker` to compute hash + check dedup\n"
        "  2. If `verdict == new`, delegate to `enricher` to generate metadata\n"
        "  3. Delegate to `writer` to copy file + upsert Neo4j node\n\n"
        "Available tools:\n"
        "  - sha256_of_file_tool: hash a file\n"
        "  - scan_filesystem_for_dupe_tool: check fs for duplicate\n"
        "  - scan_neo4j_for_dupe_tool: check Neo4j for duplicate\n"
        "  - read_doc_tool: read doc content (for enrichment)\n"
        "  - get_graphindex_metadata_tool: TOC / search_terms / preview\n"
        "  - list_other_doc_names_tool: get other doc names\n"
        "  - copy_to_project_dir_tool: copy file with hash prefix\n"
        "  - upsert_doc_to_neo4j_tool: write Neo4j node with enrichment\n"
        "  - set_content_sha256_tool: set content_sha256 on existing node\n\n"
        "Subagents:\n"
        "  - ingest_checker: hash + dedup check\n"
        "  - enricher:       LLM-generated routing metadata\n"
        "  - writer:         copy + upsert\n\n"
        "If `verdict` is fs_dupe or neo_dupe, skip enricher and writer — "
        "just report the existing path/name and exit."
    )

    subagents = [
        {"name": "ingest_checker",
         "description": "Compute SHA-256 and check filesystem + Neo4j for duplicate content.",
         "system_prompt": INGEST_CHECKER_SYSTEM},
        {"name": "enricher",
         "description": "Generate routing metadata (about / supports / out_of_scope / few_shot) for one document.",
         "system_prompt": ENRICHER_SYSTEM},
        {"name": "writer",
         "description": "Copy the file into project_1/ with hash prefix and upsert the Neo4j node.",
         "system_prompt": WRITER_SYSTEM},
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
def get_build_agent():
    return build_build_agent()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python phase9/build_agent.py <file_path>")
        sys.exit(1)
    file_path = " ".join(sys.argv[1:])
    agent = get_build_agent()
    result = agent.invoke(
        {"messages": [{"role": "user",
                       "content": f"Ingest this file: {file_path}"}]},
        config={"configurable": {"thread_id": "phase9-build-smoke"}},
    )
    print("\n=== FINAL RESULT ===\n")
    print(result["messages"][-1].content)