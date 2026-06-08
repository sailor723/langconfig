"""
API endpoints for the native tool registry.

Exposes the metadata of all built-in tools (from tools/native_tools.py) so the
frontend can render tool pickers in the agent editor and Studio node config
panel without hardcoded lists.
"""

from fastapi import APIRouter
from typing import List, Dict, Any

from tools.native_tools import get_tool_registry

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
