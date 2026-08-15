"""
Seed built-in tools into the custom_tools table.

Architecture (Phase 4 of the native -> DB tool refactor):
    Built-in tools live in PostgreSQL exactly like custom tools. Each row is
    a ``python_function`` tool whose ``implementation_config.code`` is a
    *fully self-contained* snippet: the tool's implementation plus every
    module-level helper it references, copied out of tools/native_impl.py at
    seed time. Agents compile and run tools straight from the DB at runtime —
    nothing imports tools/native_tools.py or tools/native_impl.py at call
    time (the legacy ``load_native_tools`` loader has been removed).

    The seed source tools/native_impl.py exists only so the seeder can embed
    verbatim implementations (no transcription drift) and derive the exact
    input schemas from the real tool objects.

Run (from backend/):
    uv run python scripts/seeds/seed_builtin_tools.py

Idempotent: existing rows are left untouched (user edits are preserved).
Use ``--refresh`` to overwrite seeded rows with fresh metadata.
"""

import argparse
import ast
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Load the project-root .env (DATABASE_URL etc.) before db.database is
# imported, mirroring how the FastAPI app boots (config.py -> load_dotenv).
from dotenv import load_dotenv

load_dotenv(BACKEND_DIR.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_builtin_tools")

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
    "read_image": ("Read Image (OCR)", "filesystem", None),
    "write_file": ("Write File", "filesystem", None),
    "edit_file": ("Edit File", "filesystem", None),
    "glob": ("Glob", "filesystem", None),
    "grep": ("Grep", "filesystem", None),
    "delete_file": ("Delete File", "filesystem", None),
    "rename_file": ("Rename File", "filesystem", None),
    "move_file": ("Move File", "filesystem", None),
    "mkdir": ("Create Directory", "filesystem", None),
    "bash": ("Bash Shell", "shell", None),
    "reasoning_chain": ("Reasoning Chain", "reasoning", None),
    "task": ("Task (Subagent)", "delegation", None),
    "save_analysis_result": ("Save Analysis Result", "data_analysis", None),
    "gen_pptx": ("Generate PPTX", "presentation", None),
    "create_skill": ("Create Skill", "skills", None),
    "skill": ("Read Skill", "skills", None),
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
    "graphindex_ingest": ("GraphIndex - Ingest File", "retrieval", None),
    "graphindex_rebuild_one": ("GraphIndex - Rebuild One Document", "retrieval", None),
    "graphindex_rebuild_project": ("GraphIndex - Rebuild Project", "retrieval", None),
    "graphindex_show": ("GraphIndex - Show Document", "retrieval", None),
    "sqlite_execute": ("SQLite Execute", "data", None),
    "sqlite_load_csv": ("SQLite Load CSV", "data", None),
    "python_execute": ("Python Execute", "data", None),
    "save_document": ("Save Document", "document", None),
}

# Display category -> DSH-style definition category (core/tools/definition.py).
# Categories not listed fall back to "custom".
_DEFINITION_CATEGORY = {
    "web": "web",
    "filesystem": "filesystem",
    "reasoning": "reasoning",
    "skills": "skills",
    "database": "database",
    "delegation": "agents",
    "agent_management": "agents",
    "data_analysis": "analysis",
    "data": "analysis",
    "presentation": "presentation",
    "retrieval": "graph",
    "document": "document",
    "shell": "shell",
}


# StructuredTool wrapper names in tools/native_impl.py that carry richer
# input schemas (per-arg descriptions) than the bare plain functions they
# wrap. The seeder uses them for schema derivation; the embedded row code
# still runs the underlying plain function.
_TOOL_WRAPPER_OVERRIDE = {
    "doc_index_list": "_doc_index_list_tool",
    "doc_index_structure": "_doc_index_structure_tool",
    "doc_index_pages": "_doc_index_pages_tool",
    "graphindex_search": "_graphindex_search_tool",
    "graphindex_load": "_graphindex_load_tool",
    "graphindex_list_docs": "_graphindex_list_docs_tool",
    "graphindex_multi_doc_load": "_graphindex_multi_doc_load_tool",
}

# ---------------------------------------------------------------------------
# Self-contained code generation
# ---------------------------------------------------------------------------
# Built-in rows no longer delegate to tools/native_tools.py at call time (that
# loader is being removed). Instead the seeder embeds the tool's implementation
# plus every module-level helper it references — copied verbatim out of
# tools/native_impl.py — into the row's ``code``, exactly like a custom tool.

_TAVILY_GUARD = '''try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
'''

# Tools whose implementation lives in a stable sibling module (not part of the
# native_tools removal); their row code delegates to that module directly.
_IMPORTED_TOOL_TEMPLATE = '''from tools.presentation_tools import {name}


async def _run_tool(**kwargs) -> str:
    """{desc}"""
    return str(await {name}.ainvoke({{**kwargs}}))
'''

_SOURCE_CACHE: dict = {}


def _native_impl_source() -> str:
    """Read tools/native_impl.py once (the seed source for embedded code)."""
    src = _SOURCE_CACHE.get("native_impl")
    if src is None:
        src = BACKEND_DIR.joinpath("tools", "native_impl.py").read_text(encoding="utf-8")
        _SOURCE_CACHE["native_impl"] = src
    return src


def _collect_module_layout(src: str) -> tuple[dict, list]:
    """Index module-level defs and imports of the seed-source file."""
    tree = ast.parse(src)
    defs = {}
    import_nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = []
            for alias in node.names:
                if isinstance(node, ast.Import):
                    bound.append(alias.asname or alias.name.split(".")[0])
                else:
                    bound.append(alias.asname or alias.name)
            import_nodes.append((node, bound))
    return defs, import_nodes


def _referenced_names(node: ast.AST) -> set:
    """All loaded names (incl. ``global`` declarations) referenced by a node."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def _from_function_func(assign_node: ast.AST):
    """The plain function behind ``X = StructuredTool.from_function(func=Y, ...)``."""
    value = getattr(assign_node, "value", None)
    if not isinstance(value, ast.Call):
        return None
    for kw in value.keywords:
        if kw.arg == "func" and isinstance(kw.value, ast.Name):
            return kw.value.id
    if value.args and isinstance(value.args[0], ast.Name):
        return value.args[0].id
    return None


def _strip_decorators(source_segment: str) -> str:
    """Drop ``@tool`` decorator lines so the embedded def is a plain function."""
    lines = source_segment.splitlines()
    while lines and lines[0].lstrip().startswith("@"):
        lines.pop(0)
    return "\n".join(lines)


def _build_self_contained_code(tool_name: str, description: str) -> tuple:
    """Return ``(code, function_name)`` for a fully self-contained built-in row.

    The snippet defines the tool's implementation function plus every
    module-level helper it transitively references (verbatim from
    tools/native_impl.py) and the imports those helpers need, so the row can
    be compiled by ToolFactory at runtime without importing native_tools.py.
    """
    src = _native_impl_source()
    defs, import_nodes = _collect_module_layout(src)

    # Resolve the plain-function entry for this tool.
    entry = tool_name
    entry_node = defs.get(tool_name)
    if isinstance(entry_node, ast.Assign):
        inner = _from_function_func(entry_node)
        if inner and inner in defs:
            entry, entry_node = inner, defs[inner]

    if entry_node is None:
        # Imported tool (gen_pptx) — its stable module stays in the repo, so
        # the row delegates to it like any custom tool may import a backend
        # module.
        return _IMPORTED_TOOL_TEMPLATE.format(name=tool_name, desc=_sanitize(description)), "_run_tool"

    # BFS over module-level helper dependencies (transitive closure).
    needed = set()
    ref_names = set()
    needs_logger = False
    needs_tavily = False
    queue = [entry]
    while queue:
        name = queue.pop()
        if name in needed:
            continue
        if name in ("logger",):
            needs_logger = True
            needed.add(name)
            continue
        if name in ("TAVILY_AVAILABLE", "TavilySearchResults"):
            needs_tavily = True
            needed.add(name)
            continue
        node = defs.get(name)
        if node is None:
            continue
        needed.add(name)
        names = _referenced_names(node)
        ref_names |= names
        for sub in names:
            if sub in defs or sub in ("logger", "TAVILY_AVAILABLE", "TavilySearchResults"):
                if sub not in needed:
                    queue.append(sub)

    # Imports whose bound names are referenced anywhere in the closure.
    needed_imports = [
        ast.get_source_segment(src, node)
        for node, bound in import_nodes
        if any(b in ref_names for b in bound)
    ]

    parts = []
    if needed_imports:
        parts.append("# --- imports ---")
        parts.extend(needed_imports)
    if needs_logger:
        parts.append("# --- logger ---")
        parts.append("import logging")
        parts.append('logger = logging.getLogger("langconfig.builtin_tool")')
    if needs_tavily:
        parts.append("# --- tavily guard ---")
        parts.append(_TAVILY_GUARD.rstrip())
    for node in sorted(
        (defs[n] for n in needed if n not in ("logger", "TAVILY_AVAILABLE", "TavilySearchResults")),
        key=lambda n: n.lineno,
    ):
        segment = ast.get_source_segment(src, node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = _strip_decorators(segment)
        parts.append(segment)
    code = "\n\n".join(parts)
    # Fail fast at seed time if the embedded snippet is not valid Python.
    compile(code, f"<seed:{tool_name}>", "exec")
    return code, entry


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


def _build_row(tool_name: str, tool_obj, meta: tuple, order: int = 500) -> dict:
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
        # First NON-EMPTY line of the docstring (docstrings often start with a
        # blank line, which would otherwise produce an empty description and
        # fall back to the useless "Built-in tool: X" placeholder).
        _doc_lines = [ln.strip() for ln in (getattr(tool_obj, "__doc__", "") or "").splitlines() if ln.strip()]
        description = _doc_lines[0] if _doc_lines else ""
        properties, required = _schema_from_signature(tool_obj)
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

    # Self-contained implementation: the tool + its module-level helpers,
    # embedded verbatim so runtime compiles it straight from the DB row.
    code, function_name = _build_self_contained_code(tool_name, description)

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
            "function_name": function_name,
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
        # DSH-style declarative definition (docs/tools-refactor.md §3).
        "definition": {
            "category": _DEFINITION_CATEGORY.get(category, "custom"),
            "order": order,
            "section": None,
            "is_concurrency_safe": True,
            "output_schema": None,
            "guard": {"approval": False, "confirmation": False},
            "presentation": (
                {"requires_api_key": requires_api_key}
                if requires_api_key else {}
            ),
        },
    }


def main(refresh: bool = False) -> int:
    """Upsert all seedable built-in tools into custom_tools."""
    from models.custom_tool import CustomTool
    from db.database import SessionLocal
    import tools.native_impl as native_impl

    seed_names = list(SEEDABLE_TOOL_META)
    seed_index = 0
    logger.info(f"Seeding {len(seed_names)} built-in tools (self-contained code embedded in rows)")

    # Capture each tool's real LLM-facing description + args schema from the
    # concrete tool object in the seed source (single source of truth). Where
    # a StructuredTool wrapper exists it carries richer per-arg descriptions.
    rows_by_name = {}
    for name in seed_names:
        try:
            tool_obj = getattr(native_impl, _TOOL_WRAPPER_OVERRIDE.get(name, name))
        except Exception as exc:  # pragma: no cover — defensive
            logger.error(f"  x Failed to resolve '{name}' in tools/native_impl.py: {exc}")
            continue
        meta = SEEDABLE_TOOL_META.get(name, (name, "misc", None))
        try:
            rows_by_name[name] = _build_row(name, tool_obj, meta, order=seed_index)
            seed_index += 1
        except Exception as exc:  # pragma: no cover — defensive
            logger.error(f"  x Failed to build '{name}': {exc}")
            continue

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
