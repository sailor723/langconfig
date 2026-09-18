# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Default native tools — every agent / deep agent gets a refined base toolset
without configuration (docs/tools-audit.md).

``DEFAULT_NATIVE_TOOLS`` is the curated universal set (35 tools):

- universal base: reasoning, planning, web, filesystem (incl. file management),
  shell, on-demand skills, document deliverable
- memory (store/recall) — routed to SimpleMemory; including them enables
  memory for every agent
- database **read-only**: pg introspection + SELECT (pg_execute is NOT
  default — every agent writing the app DB is too risky)
- analysis: sqlite + python_execute (sandboxed subprocess) + save_analysis_result
- retrieval: the canonical RAG trio (graphindex_search/load, doc_index_list)

Excluded by design (opt-in): pg_execute (DB writes), browser (heavy
Playwright), neo4j graph ops + doc-index detail viewers, meta tools
(create_skill/create_deepagent/task), key-gated tavily_search, gen_pptx,
and user custom tools.

``resolve_native_tools()`` is applied at every tool-loading choke point
(AgentFactory.create_agent, ToolLoader.load_all, load_agent_tools for the
deep-agent path) and materialized into agent configs at create/update:
an explicitly-configured list always wins; empty/None falls back to the
defaults; ``enable_default_tools: False`` forces empty.
"""

from __future__ import annotations

from typing import List, Optional

DEFAULT_NATIVE_TOOLS: List[str] = [
    # reasoning
    "think_tool",
    "reasoning_chain",
    # planning
    "write_todos",
    "read_todos",
    # memory (routes to SimpleMemory; enables memory for the agent)
    "memory_store",
    "memory_recall",
    # web — web_search/web_fetch (free DDG) + tavily_search (AI-optimized,
    # key-gated: gracefully reports when TAVILY_API_KEY is unset).
    "web_search",
    "web_fetch",
    "tavily_search",
    # filesystem — the deepagents SDK provides ls/read_file/write_file/edit_file/
    # glob/grep/delete via FilesystemMiddleware (default for all agents, with
    # the format-aware backend wrap for multi-format documents). Only tools the
    # SDK lacks stay native: rename_file, move_file, mkdir.
    "rename_file",
    "move_file",
    "mkdir",
    # shell
    "bash",
    # skills (progressive disclosure on demand)
    "skill",
    # deliverables — write_file generates format-aware documents (.md/.html/
    # .pdf/.docx); save_document persists the final deliverable to the versioned
    # document library (agent_documents table + workspace copy).
    "save_document",
    # database — read-only (pg_execute stays opt-in)
    "pg_list_tables",
    "pg_describe_table",
    "pg_query",
    "pg_list_agents",
    "pg_get_agent",
    "pg_list_projects",
    # analysis / data
    "sqlite_execute",
    "sqlite_load_csv",
    "python_execute",
    "save_analysis_result",
    # retrieval (canonical RAG trio)
    "graphindex_search",
    "graphindex_load",
    "doc_index_list",
]


def resolve_native_tools(
    configured: Optional[List[str]],
    enable_default_tools: bool = True,
) -> List[str]:
    """Configured list wins; empty/None → the default tool set.

    ``enable_default_tools=False`` forces empty (specialists that must not
    receive the defaults can opt out).
    """
    if not enable_default_tools:
        return list(configured or [])
    if configured:
        return list(configured)
    return list(DEFAULT_NATIVE_TOOLS)
