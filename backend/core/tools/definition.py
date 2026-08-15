# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tool definition — the DSH ``defineTool`` analog on the compile model
(docs/tools-refactor.md §3).

Every tool row (``custom_tools``) may carry a ``definition`` JSONB describing
what the tool *is* beyond its code: category, prompt-assembly order, execution
timeout, concurrency safety, an output JSON Schema, guard config, and UI
presentation. ``ToolFactory.create_tool`` parses it and attaches it as tool
metadata; Phases B–D consume it (registry ordering, guards, prompt guidance,
Code-Mode SDK generation).

Phase A declares the surface — enforcement (timeout/guards/output schema) is
gradual.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

# Category vocabulary (mirrors DSH tool-package groupings). Free-form strings
# are allowed, but UI pickers and prompt sections key off these.
TOOL_CATEGORIES = {
    "web",          # web_search, web_fetch, tavily_search, browser
    "filesystem",   # read_file, write_file, edit_file, ls, glob, grep, vfs_*
    "database",     # pg_*, sqlite_*
    "graph",        # neo4j_*, doc_index_*, graphindex_*
    "analysis",     # python_execute, sqlite_load_csv, save_analysis_result
    "skills",       # create_skill, update_skill, delete_skill, search_skills
    "agents",       # create_deepagent, task
    "memory",       # memory_store, memory_recall
    "reasoning",    # think_tool, reasoning_chain
    "todo",         # write_todos, read_todos
    "notification", # slack/discord/wordpress
    "presentation", # gen_pptx
    "document",     # save_document (agent document library)
    "shell",        # bash (agent terminal)
    "custom",       # user-defined (default)
}


class ToolGuard(BaseModel):
    """Guard config: what must happen before/around execution (Phase B)."""

    model_config = ConfigDict(extra="forbid")

    # Requires human approval before execution (HITL). Wired in Phase B.
    approval: bool = False
    # Requires the user to confirm (lighter than approval).
    confirmation: bool = False


class ToolPresentation(BaseModel):
    """UI-facing presentation metadata."""

    model_config = ConfigDict(extra="forbid")

    icon: Optional[str] = None
    # Provider field or env var name the tool needs configured, or None.
    requires_api_key: Optional[str] = None
    hidden: bool = False


class ToolDefinition(BaseModel):
    """The declarative definition of one tool (DSH ``DefineToolOptions``)."""

    model_config = ConfigDict(extra="forbid")

    category: str = "custom"
    # Prompt-assembly order (lower = earlier). Default 500 = mid-pack.
    order: int = 500
    # Guidance-section grouping for the system prompt (Phase D); None = category.
    section: Optional[str] = None
    # Optional cooperative timeout in milliseconds (enforced Phase B).
    timeout_ms: Optional[int] = None
    # Whether the tool may join a parallel group (langchain parallel tool calls).
    is_concurrency_safe: bool = True
    # Canonical output JSON Schema — declared now, enforced gradually.
    output_schema: Optional[dict] = None
    guard: ToolGuard = ToolGuard()
    presentation: ToolPresentation = ToolPresentation()

    @classmethod
    def from_row(cls, raw: Optional[dict]) -> "ToolDefinition":
        """Parse a row's ``definition`` JSONB (None/empty → defaults).

        Invalid shapes fall back to defaults rather than breaking compilation —
        a malformed definition must never take a tool down.
        """
        if not raw:
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()

    def to_metadata(self) -> dict:
        """The definition's prompt/UI-relevant fields (attached to tool.metadata)."""
        return {
            "category": self.category,
            "order": self.order,
            "section": self.section or self.category,
            "timeout_ms": self.timeout_ms,
            "is_concurrency_safe": self.is_concurrency_safe,
            "output_schema": self.output_schema,
            "guard": self.guard.model_dump(),
            "presentation": self.presentation.model_dump(exclude_none=True),
        }
