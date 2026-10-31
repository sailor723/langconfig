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
deep-agent path) and returns the configured list unchanged: the stored row IS
the tool set. ``DEFAULT_NATIVE_TOOLS`` is now only the editor's pre-ticked
starting point for a new agent (``GET /api/tools/registry/defaults``).
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
    # .pdf/.docx) straight into the workspace's generated/ folder, which is what
    # the Files panel lists. (save_document was removed: it wrote the same file
    # plus an agent_documents row that no UI ever read.)
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


def resolve_native_tools(configured: Optional[List[str]]) -> List[str]:
    """The agent's native tools, exactly as configured.

    No fallback, deliberately. The set an agent runs with is what was stored —
    `[]` means no tools, not "give it the defaults". Every previous version of this
    function read an empty list as "unspecified" and filled in the universal base,
    which meant the database did not record what the user chose: an agent configured
    with nothing ran with 28 tools, and nothing anywhere said so.

    "Start a new agent with a sensible base" is a property of the EDITOR, not of the
    resolver: the picker pre-ticks ``DEFAULT_NATIVE_TOOLS`` for a new agent, so a
    user who wants the base keeps it and one who wants none unticks it — and the row
    stores whichever of those they did.
    """
    return list(configured or [])
