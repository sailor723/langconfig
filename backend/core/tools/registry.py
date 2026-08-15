# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DB-backed tool registry (DSH ``ctx.tools`` analog, Phase B of
docs/tools-refactor.md).

The registry is the single surface for tool *definitions* and *ordering*:

- DB rows (``custom_tools``: built-in + custom) carry a ``ToolDefinition``
  (category, order, timeout, guards, output schema, presentation);
- the 9 legacy-only harness tools (injected state / Playwright / TODO / VFS)
  get synthesized definitions so the merged list is uniform;
- ``list_definitions()`` merges both, ordered by ``definition.order``;
- ``resolve_for_agent()`` returns the ordered tool ids an agent config selects
  (native + cli + custom + memory/rag), which the prompt assembler (Phase D)
  and Code-Mode SDK generator (Phase C) will consume.

``RUN_CODE_NAME`` is reserved for the Code-Mode ``run_code`` transport.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.tools.definition import ToolDefinition

logger = logging.getLogger(__name__)

# Reserved for Code Mode (Phase C): a tool with this name can never be
# registered or shadowed.
RUN_CODE_NAME = "run_code"

# Legacy-only tool ids -> (category, prompt order). These tools cannot be
# seeded (injected agent state / Playwright / harness helpers) and live in
# tools/native_tools.py; the registry gives them uniform definitions.
_LEGACY_DEFINITIONS: Dict[str, tuple] = {
    "browser": ("web", 10),
    "think_tool": ("reasoning", 20),
    "memory_store": ("memory", 30),
    "memory_recall": ("memory", 31),
    "write_todos": ("todo", 40),
    "read_todos": ("todo", 41),
}


def _custom_tool_scope_filter(project_id: Optional[int]):
    """Reusable project-scope filter for custom_tools (global/same-project/
    builtin/public only — mirrors ToolLoader.load_custom)."""
    from sqlalchemy import or_
    from models.custom_tool import CustomTool

    if project_id is None:
        return or_(
            CustomTool.project_id.is_(None),
            CustomTool.is_builtin.is_(True),
            CustomTool.is_public.is_(True),
        )
    return or_(
        CustomTool.project_id.is_(None),
        CustomTool.project_id == project_id,
        CustomTool.is_builtin.is_(True),
        CustomTool.is_public.is_(True),
    )


class ToolRegistry:
    """Single surface for tool definitions + ordering (DB + legacy merged)."""

    def list_definitions(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Every tool the platform can offer, ordered by definition.order.

        Each entry: {tool_id, name, description, category, order,
        requires_api_key, definition (ToolDefinition metadata)}.
        """
        entries: List[Dict[str, Any]] = []

        # Legacy-only tools (always present — they are module-level).
        try:
            from tools.native_tools import get_tool_registry

            for t in get_tool_registry():
                category, order = _LEGACY_DEFINITIONS.get(
                    t["id"], (t.get("category") or "custom", 500)
                )
                entries.append({
                    "tool_id": t["id"],
                    "name": t.get("name", t["id"]),
                    "description": t.get("description", ""),
                    "category": category,
                    "order": order,
                    "requires_api_key": t.get("requires_api_key"),
                    "definition": ToolDefinition(
                        category=category,
                        order=order,
                        presentation={"requires_api_key": t.get("requires_api_key")} if t.get("requires_api_key") else {},
                    ).to_metadata(),
                })
        except Exception as exc:  # noqa: BLE001 — registry must never crash
            logger.warning(f"tool registry: legacy definitions unavailable: {exc}")

        # DB rows (built-in + custom, project-scoped).
        for row in self._db_rows(project_id):
            definition = ToolDefinition.from_row(row.definition)
            entries.append({
                "tool_id": row.tool_id,
                "name": row.name or row.tool_id.replace("_", " ").title(),
                "description": (row.description or "")[:200],
                "category": definition.category,
                "order": definition.order,
                "requires_api_key": getattr(row, "requires_api_key", None),
                "definition": definition.to_metadata(),
            })

        entries.sort(key=lambda e: e["order"])
        return entries

    def definition_for(self, tool_id: str, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """One tool's definition metadata (None when unknown)."""
        for entry in self.list_definitions(project_id):
            if entry["tool_id"] == tool_id:
                return entry
        return None

    def resolve_for_agent(
        self,
        agent_config: Dict[str, Any],
        project_id: Optional[int] = None,
    ) -> List[str]:
        """The ordered tool ids an agent config selects.

        Combines native + cli + custom tool lists (aliases resolved via
        TOOL_NAME_MAP) plus memory/RAG tools when enabled, then orders by
        definition.order (unknown names get order 500). Deduplicated, order
        preserved.
        """
        from tools.native_tools import TOOL_NAME_MAP

        canonical = {
            TOOL_NAME_MAP.get(n, n) for n in (
                *(agent_config.get("native_tools") or []),
                *(agent_config.get("cli_tools") or []),
                *(agent_config.get("custom_tools") or []),
            )
        }
        if agent_config.get("enable_memory"):
            canonical.update({"memory_store", "memory_recall"})
        if agent_config.get("enable_rag"):
            canonical.add("search_rag")

        order_map = {
            e["tool_id"]: e["order"] for e in self.list_definitions(project_id)
        }
        return sorted(canonical, key=lambda n: order_map.get(n, 500))

    @staticmethod
    def _db_rows(project_id: Optional[int]) -> List[Any]:
        try:
            from db.database import SessionLocal
            from models.custom_tool import CustomTool

            db = SessionLocal()
            try:
                return db.query(CustomTool).filter(_custom_tool_scope_filter(project_id)).all()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 — DB unavailable → legacy-only
            logger.warning(f"tool registry: DB rows unavailable: {exc}")
            return []


_registry: Optional[ToolRegistry] = None


def get_tool_registry_service() -> ToolRegistry:
    """Process-wide ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
