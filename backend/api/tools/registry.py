"""
API endpoints for the tool registry.

Phase 3 of the native -> DB tool refactor: the registry is DB-primary.
Seeded built-in tools (custom_tools rows with ``is_builtin``) carry their
display metadata (name, category, requires_api_key) in the row itself and are
the source of truth; legacy-only tools that cannot be seeded (browser,
write_todos/read_todos, vfs_*, memory_*, think_tool) still
come from TOOL_REGISTRY in tools/native_tools.py so the UI pickers never lose
an option.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from tools.native_tools import get_tool_registry, load_legacy_native_tools

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _load_db_rows() -> List[Any]:
    """Load all custom_tools rows (built-in and user-defined)."""
    from db.database import SessionLocal
    from models.custom_tool import CustomTool

    db = SessionLocal()
    try:
        return db.query(CustomTool).all()
    finally:
        db.close()


@router.get("/registry")
async def get_registry() -> List[Dict[str, Any]]:
    """
    Get the full tool registry with metadata for UI display.

    Returns a list of tool metadata dictionaries. Each entry contains:
      - id: unique tool identifier (e.g., "tavily_search")
      - name: human-readable name
      - description: short description
      - category: grouping key (web, filesystem, memory, reasoning, delegation)
      - requires_api_key: env var name of the required API key, or null

    Seeded built-in tools are read from the ``custom_tools`` table (the DB is
    the source of truth for the 43 seedable tools); the remaining legacy-only
    tools (browser, write_todos/read_todos, vfs_*, memory_*,
    think_tool) come from TOOL_REGISTRY in tools/native_tools.py.
    The frontend should group these by `category` and render a checkbox
    (or selection control) for each tool.
    """
    legacy_entries = {t["id"]: t for t in get_tool_registry()}

    db_entries: List[Dict[str, Any]] = []
    db_ids = set()
    try:
        rows = _load_db_rows()
    except Exception:  # pragma: no cover — DB unavailable → legacy-only registry
        rows = []

    for row in rows:
        if not row.is_builtin:
            continue  # user custom tools stay in their own picker (custom_tool_ids)
        db_entries.append({
            "id": row.tool_id,
            "name": row.name or row.tool_id.replace("_", " ").title(),
            "description": (row.description or "")[:140],
            "category": row.category or "misc",
            "requires_api_key": row.requires_api_key,
        })
        db_ids.add(row.tool_id)

    # Legacy-only tools that cannot be seeded (special handling required)
    db_entries.extend(t for t in legacy_entries.values() if t["id"] not in db_ids)
    return db_entries


@router.get("/registry/{tool_id}/details")
async def get_tool_details(tool_id: str) -> Dict[str, Any]:
    """
    Get the full LLM-facing description and argument schema for a single tool.

    This is what the model actually sees when deciding whether/how to call
    the tool — distinct from the short ``description`` in /registry which is
    intended for human UI display.

    Returns:
        - id: tool identifier
        - name: human-readable name (from registry)
        - ui_description: short description from the registry (for display)
        - llm_description: full LLM-facing description (what reaches the model)
        - args_schema: JSON Schema of the tool's arguments (what the LLM
          must produce to call the tool)
        - category: tool category
        - requires_api_key: env var name of required API key, or null

    Used by the ToolLibrary UI to show the full LLM-facing prompt when
    the user clicks "View Prompt" on a tool card.
    """
    # Look up the short registry entry first
    registry_entry = next(
        (t for t in get_tool_registry() if t["id"] == tool_id),
        None,
    )

    # DB rows (built-in and user custom tools) are the source of truth when
    # present — they carry the authoritative LLM description + args schema.
    try:
        row = next((r for r in _load_db_rows() if r.tool_id == tool_id), None)
    except Exception:  # pragma: no cover — DB unavailable → fall back below
        row = None

    if row is not None:
        return {
            "id": tool_id,
            "name": row.name or tool_id,
            "ui_description": (row.description or "")[:140],
            "llm_description": row.description or "",
            "args_schema": row.input_schema or {"type": "object", "properties": {}},
            "category": row.category or (registry_entry or {}).get("category", "misc"),
            "requires_api_key": row.requires_api_key or (registry_entry or {}).get("requires_api_key"),
        }

    if registry_entry is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found in registry")

    # Legacy path: resolve the actual tool object for description + args.
    # Only the legacy-only tools (injected-state harness tools) still resolve
    # from code; DB-seeded built-ins are handled by the row path above.
    try:
        tools = load_legacy_native_tools([tool_id])
    except Exception as exc:  # pragma: no cover — defensive
        raise HTTPException(status_code=500, detail=f"Failed to load tool: {exc}")
    if not tools:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' could not be resolved")

    tool_obj = tools[0]
    llm_description = getattr(tool_obj, "description", "") or ""

    # StructuredTool.args is a JSON Schema dict.
    args_schema = getattr(tool_obj, "args", {}) or {}

    return {
        "id": tool_id,
        "name": registry_entry["name"],
        "ui_description": registry_entry["description"],
        "llm_description": llm_description,
        "args_schema": args_schema,
        "category": registry_entry["category"],
        "requires_api_key": registry_entry["requires_api_key"],
    }
