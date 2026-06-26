"""
Register 4 graphindex build actions as custom tools (so they get pencil
icons in the Studio UI and can be dragged into workflows).

Each tool is a thin wrapper that calls the corresponding function in
`backend/tools/native_tools.py` (which in turn calls `cmd_*` from
`learning/phase9/graphindex_build_python.py`).

Tools registered:
  1. studio_ingest            (calls graphindex_ingest)
  2. studio_rebuild_one       (calls graphindex_rebuild_one)
  3. studio_rebuild_project   (calls graphindex_rebuild_project)
  4. studio_show              (calls graphindex_show)

After registration, the user can:
  - See the tools in /api/custom-tools with pencil icons
  - Drag them onto a Studio canvas as TOOL_NODEs
  - Create workflows like: START → studio_ingest → END (or chain them)

Run:
  python backend/create_graphindex_workflow_tools.py
"""
import asyncio
import sys

import httpx

BASE = "http://localhost:8765"


# ----------------------------------------------------------------------------
# 1. studio_ingest
# ----------------------------------------------------------------------------
STUDIO_INGEST_CODE = '''def studio_ingest(file_path: str, project_id: int = 0) -> str:
    """Ingest a new file into the graphindex (DB-backed workflow tool).

    Thin wrapper around tools.native_tools.graphindex_ingest.

    Args:
        file_path: Absolute path to the file to ingest.
        project_id: Project ID (0 = current project).

    Returns:
        Build report from cmd_ingest.
    """
    from tools.native_tools import graphindex_ingest
    return graphindex_ingest(file_path, project_id=project_id or None)
'''


# ----------------------------------------------------------------------------
# 2. studio_rebuild_one
# ----------------------------------------------------------------------------
STUDIO_REBUILD_ONE_CODE = '''def studio_rebuild_one(name: str, project_id: int = 0) -> str:
    """Re-enrich ONE document in the graphindex (DB-backed workflow tool).

    Thin wrapper around tools.native_tools.graphindex_rebuild_one.

    Args:
        name: Exact document filename (e.g. "nke-10k-2023.pdf").
        project_id: Project ID (0 = current project).

    Returns:
        Build report from cmd_rebuild_one.
    """
    from tools.native_tools import graphindex_rebuild_one
    return graphindex_rebuild_one(name, project_id=project_id or None)
'''


# ----------------------------------------------------------------------------
# 3. studio_rebuild_project
# ----------------------------------------------------------------------------
STUDIO_REBUILD_PROJECT_CODE = '''def studio_rebuild_project(project_id: int = 0) -> str:
    """Re-enrich EVERY document in the project (DB-backed workflow tool).

    Thin wrapper around tools.native_tools.graphindex_rebuild_project.

    WARNING: slow! 1 LLM call per document (~15s each).

    Args:
        project_id: Project ID (0 = current project).

    Returns:
        Build report from cmd_rebuild_project.
    """
    from tools.native_tools import graphindex_rebuild_project
    return graphindex_rebuild_project(project_id=project_id or None)
'''


# ----------------------------------------------------------------------------
# 4. studio_show
# ----------------------------------------------------------------------------
STUDIO_SHOW_CODE = '''def studio_show(name: str, project_id: int = 0) -> str:
    """Show a document's metadata from the graphindex (DB-backed workflow tool).

    Thin wrapper around tools.native_tools.graphindex_show.

    Args:
        name: Exact document filename (e.g. "nke-10k-2023.pdf").
        project_id: Project ID (0 = current project).

    Returns:
        Document metadata (about, supports, out_of_scope, file_path).
    """
    from tools.native_tools import graphindex_show
    return graphindex_show(name, project_id=project_id or None)
'''


# ----------------------------------------------------------------------------
# Tool definitions
# ----------------------------------------------------------------------------

TOOLS = [
    {
        "tool_id": "studio_ingest",
        "name": "Studio Ingest (graphindex)",
        "description": "Ingest a new file into the graphindex. Wraps graphindex_ingest. (DB-backed, editable in Studio).",
        "code": STUDIO_INGEST_CODE,
        "function_name": "studio_ingest",
        "args_schema": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to ingest",
            },
            "project_id": {
                "type": "integer",
                "description": "Project ID (default: 0 = current project)",
                "default": 0,
            },
        },
        "required": ["file_path"],
        "category": "graphindex_build",
        "tags": ["graphindex", "build", "ingest", "studio"],
    },
    {
        "tool_id": "studio_rebuild_one",
        "name": "Studio Rebuild One (graphindex)",
        "description": "Re-enrich ONE document in the graphindex. Wraps graphindex_rebuild_one. (DB-backed, editable in Studio).",
        "code": STUDIO_REBUILD_ONE_CODE,
        "function_name": "studio_rebuild_one",
        "args_schema": {
            "name": {
                "type": "string",
                "description": "Exact document filename (e.g. nke-10k-2023.pdf)",
            },
            "project_id": {
                "type": "integer",
                "description": "Project ID (default: 0 = current project)",
                "default": 0,
            },
        },
        "required": ["name"],
        "category": "graphindex_build",
        "tags": ["graphindex", "build", "rebuild", "studio"],
    },
    {
        "tool_id": "studio_rebuild_project",
        "name": "Studio Rebuild Project (graphindex)",
        "description": "Re-enrich EVERY document in the project. Slow (~15s per doc). Wraps graphindex_rebuild_project. (DB-backed, editable in Studio).",
        "code": STUDIO_REBUILD_PROJECT_CODE,
        "function_name": "studio_rebuild_project",
        "args_schema": {
            "project_id": {
                "type": "integer",
                "description": "Project ID (default: 0 = current project)",
                "default": 0,
            },
        },
        "required": [],
        "category": "graphindex_build",
        "tags": ["graphindex", "build", "rebuild", "studio", "slow"],
    },
    {
        "tool_id": "studio_show",
        "name": "Studio Show Document (graphindex)",
        "description": "Show a document's metadata from the graphindex. Wraps graphindex_show. (DB-backed, editable in Studio).",
        "code": STUDIO_SHOW_CODE,
        "function_name": "studio_show",
        "args_schema": {
            "name": {
                "type": "string",
                "description": "Exact document filename (e.g. nke-10k-2023.pdf)",
            },
            "project_id": {
                "type": "integer",
                "description": "Project ID (default: 0 = current project)",
                "default": 0,
            },
        },
        "required": ["name"],
        "category": "graphindex_build",
        "tags": ["graphindex", "build", "show", "studio"],
    },
]


async def register_tool(client: httpx.AsyncClient, tool_def: dict) -> dict:
    payload = {
        "tool_id": tool_def["tool_id"],
        "name": tool_def["name"],
        "description": tool_def["description"],
        "tool_type": "python_function",
        "implementation_config": {
            "function_name": tool_def["function_name"],
            "code": tool_def["code"],
            "args_schema": tool_def["args_schema"],
        },
        "input_schema": {
            "type": "object",
            "properties": tool_def["args_schema"],
            "required": tool_def["required"],
        },
        "output_format": "string",
        "is_advanced_mode": True,
        "category": tool_def["category"],
        "tags": tool_def["tags"],
    }
    resp = await client.post(f"{BASE}/api/custom-tools", json=payload)
    if resp.status_code in (200, 201):
        data = resp.json()
        return {"ok": True, "id": data.get("id"), "tool_id": data.get("tool_id")}
    elif resp.status_code == 400 and "already exists" in resp.text.lower():
        return {"ok": True, "id": "existing", "tool_id": tool_def["tool_id"], "note": "already exists"}
    else:
        return {"ok": False, "status": resp.status_code, "text": resp.text[:200]}


async def main() -> int:
    print("🛠  Registering 4 graphindex build custom tools...\n")
    async with httpx.AsyncClient() as client:
        for tool_def in TOOLS:
            result = await register_tool(client, tool_def)
            if result["ok"]:
                note = result.get("note", "")
                print(f"  ✓ {result['tool_id']:30s} id={result['id']} {note}")
            else:
                print(f"  ✗ {tool_def['tool_id']:30s} status={result['status']} {result['text']}")
                return 1

    print()
    print("  All 4 tools registered. Now in your browser:")
    print("  1. Hard-refresh the Studio Tools page (Cmd+Shift+R)")
    print("  2. Filter to 'graphindex_build' category — you should see 4 tools")
    print("  3. Each has a pencil icon (hover over the card) → click to edit code")
    print("  4. Drag them onto a canvas to build a workflow")
    print()
    print("  Suggested workflow patterns:")
    print("    Simple:   START → studio_show → END           (verify a doc)")
    print("    Rebuild:  START → studio_rebuild_one → studio_show → END")
    print("    Ingest:   START → studio_ingest → studio_show → END")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
