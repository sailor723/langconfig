"""
API endpoints for the native tool registry.

Exposes the metadata of all built-in tools (from tools/native_tools.py) so the
frontend can render tool pickers in the agent editor and Studio node config
panel without hardcoded lists.
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from tools.native_tools import get_tool_registry, load_native_tools

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/registry")
async def get_registry() -> List[Dict[str, Any]]:
    """
    Get the full native tool registry with metadata for UI display.

    Returns a list of tool metadata dictionaries. Each entry contains:
      - id: unique tool identifier (e.g., "tavily_search")
      - name: human-readable name
      - description: short description
      - category: grouping key (web, filesystem, memory, reasoning, delegation)
      - requires_api_key: env var name of the required API key, or null

    The frontend should group these by `category` and render a checkbox
    (or selection control) for each tool.
    """
    return get_tool_registry()


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
    if registry_entry is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found in registry")

    # Resolve the actual tool object so we can extract its LLM-facing
    # description and argument schema.
    try:
        tools = load_native_tools([tool_id])
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
