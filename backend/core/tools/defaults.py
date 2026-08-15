# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Default native tools — every agent / deep agent gets a sensible base toolset
without configuration (docs/tools-audit.md, "assign defaults" request).

``DEFAULT_NATIVE_TOOLS`` is the curated universal set: reasoning, planning,
web, filesystem (with the new file-management tools), shell, on-demand skills,
and the document deliverable tool. Excluded by design (opt-in / specialized):
database & graph/RAG families, code-execution sandboxes, meta tools
(create_skill/create_deepagent), key-gated tavily/browser, and memory
(memory stays behind enable_memory).

``resolve_native_tools()`` is applied at every tool-loading choke point
(AgentFactory.create_agent, ToolLoader.load_all, load_agent_tools for the
deep-agent path): an explicitly-configured list always wins; empty/None falls
back to the defaults; ``enable_default_tools: False`` forces empty.
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
    # web
    "web_search",
    "web_fetch",
    # filesystem (deep agents get the SDK's set via middleware — deduped)
    "ls",
    "read_file",
    "read_image",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "delete_file",
    "rename_file",
    "move_file",
    "mkdir",
    # shell
    "bash",
    # skills (progressive disclosure on demand)
    "skill",
    # deliverables
    "save_document",
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
