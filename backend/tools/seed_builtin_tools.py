"""
Seed built-in tools (tools/native_tools.py) into the custom_tools table.

Architecture (Phase 0 of the native -> DB tool refactor):
    Built-in tools now live in PostgreSQL exactly like custom tools. Each row
    is a ``python_function`` tool whose code is a thin wrapper that delegates
    to the legacy implementation in tools/native_tools.py at call time. Agents
    then compile and run tools uniformly from the DB via ToolFactory.

    The wrapper resolves the tool through ``load_native_tools`` (the same
    name -> implementation map the legacy loader used), so a rename of an
    implementation function never breaks a seeded row.

Run (from backend/):
    uv run python -m tools.seed_builtin_tools

Idempotent: existing rows are left untouched (user edits are preserved).
Use ``--refresh`` to overwrite seeded rows with fresh metadata.
"""

import argparse
import logging
import sys
from pathlib import Path

# Load the project-root .env (DATABASE_URL etc.) before db.database is
# imported, mirroring how the FastAPI app boots (config.py -> load_dotenv).
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_builtin_tools")

# Tools that must stay on the legacy in-module path:
#  - browser: Playwright toolkit, loaded asynchronously via a separate path
#  - write_todos / read_todos: harness middleware (Command return + injected args)
#  - vfs_*: injected state / tool_call_id args
#  - memory_*: routed to SimpleMemory by AgentFactory assembly
SKIP_TOOLS = {
    "browser",
    "write_todos",
    "read_todos",
    "vfs_ls",
    "vfs_read_file",
    "vfs_write_file",
    "memory_store",
    "memory_recall",
}

# Seed-time display metadata for the 43 seedable built-in tools:
#   {tool_id: (display_name, category, requires_api_key)}
# This is the one place the human-facing registry metadata lives in code; the
# runtime registry (GET /api/tools/registry) reads it from the seeded DB rows
# instead of TOOL_REGISTRY in tools/native_tools.py, which now only carries
# the 10 legacy-only tools that cannot be seeded.
SEEDABLE_TOOL_META = {
    "web_search": ("Web Search", "web", None),
    "tavily_search": ("Tavily Search", "web", "TAVILY_API_KEY"),
    "web_fetch": ("Web Fetch", "web", None),
    "ls": ("List Directory", "filesystem", None),
    "read_file": ("Read File", "filesystem", None),
    "write_file": ("Write File", "filesystem", None),
    "edit_file": ("Edit File", "filesystem", None),
    "glob": ("Glob", "filesystem", None),
    "grep": ("Grep", "filesystem", None),
    "reasoning_chain": ("Reasoning Chain", "reasoning", None),
    "task": ("Task (Subagent)", "delegation", None),
    "save_analysis_result": ("Save Analysis Result", "data_analysis", None),
    "gen_pptx": ("Generate PPTX", "presentation", None),
    "gen_html": ("Generate HTML Deck", "presentation", None),
    "create_skill": ("Create Skill", "skills", None),
    "update_skill": ("Update Skill", "skills", None),
    "delete_skill": ("Delete Skill", "skills", None),
    "create_deepagent": ("Create DeepAgent", "agent_management", None),
    "pg_list_tables": ("PG - List Tables", "database", None),
    "pg_describe_table": ("PG - Describe Table", "database", None),
    "pg_query": ("PG - Query (SELECT)", "database", None),
    "pg_execute": ("PG - Execute (INSERT/UPDATE/DELETE)", "database", None),
    "pg_list_agents": ("PG - List Agents", "database", None),
    "pg_get_agent": ("PG - Get Agent Config", "database", None),
    "pg_list_skills": ("PG - List Skills", "database", None),
    "search_skills": ("Search Skills", "database", None),
    "pg_list_projects": ("PG - List Projects", "database", None),
    "pg_list_documents": ("PG - List Documents", "database", None),
    "pg_list_custom_tools": ("PG - List Custom Tools", "database", None),
    "neo4j_list_docs": ("Neo4j - List Documents", "retrieval", None),
    "neo4j_get_doc": ("Neo4j - Get Document Metadata", "retrieval", None),
    "neo4j_query": ("Neo4j - Cypher Query", "retrieval", None),
    "neo4j_upsert_doc": ("Neo4j - Upsert Document", "retrieval", None),
    "neo4j_delete_doc": ("Neo4j - Delete Document", "retrieval", None),
    "doc_index_list": ("Doc Index - List Documents", "retrieval", None),
    "doc_index_structure": ("Doc Index - Get Document Structure", "retrieval", None),
    "doc_index_pages": ("Doc Index - Get Page Content", "retrieval", None),
    "graphindex_search": ("GraphIndex - Search Documents", "retrieval", None),
    "graphindex_load": ("GraphIndex - Load Document Content", "retrieval", None),
    "graphindex_list_docs": ("GraphIndex - List Documents", "retrieval", None),
    "graphindex_multi_doc_load": ("GraphIndex - Multi-Doc Load", "retrieval", None),
    "sqlite_execute": ("SQLite Execute", "data", None),
    "python_execute": ("Python Execute", "data", None),
}

# Thin wrapper executed by ToolFactory._create_python_function_tool.
# ``**kwargs`` passes the pydantic-validated args straight to the legacy
# implementation; ``ainvoke`` handles both sync and async native tools.
WRAPPER_TEMPLATE = '''async def {name}(**kwargs) -> str:
    """{desc}"""
    from tools.native_tools import load_native_tools as _load_native_tools
    _tool = _load_native_tools(["{name}"])[0]
    return str(await _tool.ainvoke({{**kwargs}}))
'''

# Used for tools that are plain functions in native_tools.py (not
# StructuredTool-wrapped, e.g. sqlite_execute / python_execute).
SYNC_WRAPPER_TEMPLATE = '''def {name}(**kwargs) -> str:
    """{desc}"""
    from tools.native_tools import load_native_tools as _load_native_tools
    _impl = _load_native_tools(["{name}"])[0]
    return str(_impl(**kwargs))
'''


def _sanitize(text: str) -> str:
    """Collapse a description into a single safe docstring line."""
    return (text or "").replace("\\", "/").replace('"', "'").replace("\n", " ")[:160]


def _simplify_type(spec: dict) -> str:
    """Reduce a JSON Schema property to a python_function-builder primitive.

    The python_function args builder only understands string/integer/number/
    boolean; unions (anyOf/oneOf) and complex types (array/object) are
    flattened to string so the pydantic model always builds successfully.
    """
    stype = spec.get("type")
    if not stype:
        # Optional[T] is emitted as {"anyOf": [{"type": ...}, {"type": "null"}]}
        for key in ("anyOf", "oneOf"):
            for sub in (spec.get(key) or []):
                if sub.get("type"):
                    stype = sub["type"]
                    break
            if stype:
                break
    stype = stype or "string"
    return stype if stype in ("string", "integer", "number", "boolean") else "string"


_PY_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _schema_from_signature(fn) -> tuple[dict, list]:
    """Build ``(properties, required)`` for a plain function from its signature."""
    import inspect

    properties = {}
    required = []
    for pname, param in inspect.signature(fn).parameters.items():
        if pname in ("self", "cls") or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        entry = {"type": "string", "description": ""}
        if param.annotation is not inspect.Parameter.empty:
            entry["type"] = _PY_TO_JSON_TYPE.get(param.annotation, "string")
        if param.default is not inspect.Parameter.empty:
            if param.default is not None:
                entry["default"] = param.default
        else:
            required.append(pname)
        properties[pname] = entry
    return properties, required


def _build_row(tool_name: str, tool_obj, meta: tuple) -> dict:
    """Build the CustomTool payload for one built-in tool.

    ``input_schema`` keeps the faithful JSON Schema (LLM-facing) while
    ``implementation_config.args_schema`` carries the flattened shape the
    python_function pydantic builder needs, including ``default`` values so
    optional params stay optional. Display metadata (name/category/
    requires_api_key) comes from ``SEEDABLE_TOOL_META`` so the runtime
    registry can read it straight from the row.

    Handles both StructuredTool instances (args from ``.args``) and plain
    functions (args derived from the signature, called directly).
    """
    display_name, category, requires_api_key = meta
    is_plain_function = not hasattr(tool_obj, "description")

    if is_plain_function:
        description = (getattr(tool_obj, "__doc__", "") or "").split("\n")[0]
        properties, required = _schema_from_signature(tool_obj)
        code = SYNC_WRAPPER_TEMPLATE.format(name=tool_name, desc=_sanitize(description))
    else:
        description = tool_obj.description
        try:
            # `.args` only exposes the properties dict — the full JSON Schema
            # (with `required`) comes from the input schema.
            full_schema = tool_obj.get_input_schema().model_json_schema()
        except Exception:  # pragma: no cover — defensive fallback
            full_schema = {}
        properties = full_schema.get("properties") or getattr(tool_obj, "args", {}) or {}
        required = full_schema.get("required", [])
        code = WRAPPER_TEMPLATE.format(name=tool_name, desc=_sanitize(description))

    input_props = {}
    impl_args = {}
    for arg_name, spec in properties.items():
        entry = {
            "type": _simplify_type(spec),
            "description": spec.get("description", ""),
        }
        if "default" in spec:
            entry["default"] = spec["default"]
        input_props[arg_name] = dict(entry)
        impl_args[arg_name] = entry

    return {
        "tool_id": tool_name,
        "name": display_name,  # human display name for the registry / UI
        "description": description or f"Built-in tool: {tool_name}",
        "tool_type": "python_function",
        "template_type": "custom",
        "implementation_config": {
            "function_name": tool_name,
            "code": code,
            "args_schema": impl_args,
        },
        "input_schema": {"type": "object", "properties": input_props, "required": required},
        "output_format": "string",
        "is_advanced_mode": True,
        "is_builtin": True,
        "created_by": "builtin-seeder",
        "category": category,
        "requires_api_key": requires_api_key,
        "tags": ["builtin", category],
    }


def main(refresh: bool = False) -> int:
    """Upsert all seedable built-in tools into custom_tools."""
    from models.custom_tool import CustomTool
    from db.database import SessionLocal
    from tools.native_tools import (
        get_available_tool_names,
        load_native_tools,
    )

    seed_names = [n for n in get_available_tool_names() if n not in SKIP_TOOLS]
    logger.info(f"Seeding {len(seed_names)} built-in tools (excluding {len(SKIP_TOOLS)} special-cased)")

    # Capture each tool's real LLM-facing description + args schema from the
    # concrete StructuredTool instance (single source of truth).
    rows_by_name = {}
    for name in seed_names:
        try:
            tools = load_native_tools([name])
        except Exception as exc:  # pragma: no cover — defensive
            logger.error(f"  x Failed to load '{name}': {exc}")
            continue
        if not tools:
            logger.warning(f"  ! No native tool for '{name}' — skipping")
            continue
        meta = SEEDABLE_TOOL_META.get(name, (name, "misc", None))
        rows_by_name[name] = _build_row(name, tools[0], meta)

    db = SessionLocal()
    try:
        created = updated = skipped = 0
        for name, payload in rows_by_name.items():
            row = db.query(CustomTool).filter(CustomTool.tool_id == name).first()
            if row is None:
                db.add(CustomTool(**payload))
                created += 1
                logger.info(f"  + {name}")
            elif row.is_builtin:
                if refresh:
                    for key, value in payload.items():
                        setattr(row, key, value)
                    updated += 1
                    logger.info(f"  ~ {name} (refreshed)")
                else:
                    skipped += 1
            else:
                skipped += 1
                logger.warning(f"  ! {name} exists as a user tool — not touched")
        db.commit()
        logger.info(f"\nDone: {created} created, {updated} refreshed, {skipped} skipped (already seeded)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed built-in tools into custom_tools")
    parser.add_argument("--refresh", action="store_true", help="Overwrite existing seeded rows")
    args = parser.parse_args()
    sys.exit(main(refresh=args.refresh))
