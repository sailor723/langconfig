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
    uv run python scripts/seeds/in/seed_builtin_tools.py

Idempotent: existing rows are left untouched (user edits are preserved).
Use ``--refresh`` to overwrite seeded rows with fresh metadata.
"""

import argparse
import ast
import logging
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, IN_DIR, OUT_DIR, REPO, SEEDS  # noqa: E402

BACKEND_DIR = BACKEND

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
    "ontology_gate_doc": ("Ontology Gate Doc (what a gate checks, from its source)", "ontology", None),
    "ontology_start_pack": ("Ontology Start Pack (profile facts, doors, docs — one call)", "ontology", None),
    "save_analysis_result": ("Save Analysis Result", "data_analysis", None),
    "gen_dashboard": ("Generate Dashboard", "data_analysis", None),
    "gen_pptx": ("Generate PPTX", "presentation", None),
    "gen_html_deck": ("Generate HTML Deck", "presentation", None),
    "gen_pdf_deck": ("Generate PDF Deck", "presentation", None),
    "doc_to_slides_outline": ("Document to Slides Outline", "presentation", None),
    "doc_to_deck": ("Document to Deck (HTML+PPTX)", "presentation", None),
    "list_deck_templates": ("List Deck Templates", "presentation", None),
    "create_skill": ("Create Skill", "skills", None),
    "skill": ("Read Skill", "skills", None),
    "update_skill": ("Update Skill", "skills", None),
    "delete_skill": ("Delete Skill", "skills", None),
    "create_agent": ("Create Agent (deep or normal)", "agent_management", None),
    "update_agent": ("Update Agent Config", "agent_management", None),
    "test_agent": ("Test Agent (probe run)", "agent_management", None),
    "sync_skills": ("Sync Skills (disk → DB)", "agent_management", None),
    # legacy id kept so existing agent configs still resolve
    "create_deepagent": ("Create DeepAgent", "agent_management", None),
    "search_skills": ("Search Skills (empty query = list all)", "platform", None),
    "pg_list_projects": ("PG - List Projects", "platform", None),
    "pg_list_documents": ("PG - List Documents", "platform", None),
    "neo4j_list_docs": ("Neo4j - List Documents", "retrieval", None),
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
    # Embedding retrieval (the semantic-search tutorial's steps 3-5 as tools).
    # Both halves live here on purpose: the document-QA agent (id 278) is the one
    # place retrieval is taught, so "nothing is indexed yet" must be fixable from
    # the same agent that reports it. `scripts/rag_index.py` remains the terminal
    # path (it prints the chunk-count report), the tool is the in-conversation one.
    "rag_search": ("RAG - Search Documents", "retrieval", None),
    "rag_index": ("RAG - Index Documents", "retrieval", None),
    # Excel/CSV → PostgreSQL, the in-conversation form of scripts/load_workbook_to_postgres.py
    # and scripts/review_db_constraints.py. `pg_*` tools are bound to the platform database,
    # so without these an agent could only build a database by shelling out.
    "list_files": ("List Files (workspace directory)", "filesystem", None),
    "db_plan_from_file": ("DB - Plan from Excel/CSV (read-only proposal)", "database", None),
    "db_build_from_file": ("DB - Build from Excel/CSV (writes; needs confirm)", "database", None),
    "db_review": ("DB - Review Schema + Build PK/FK", "database", None),
    "db_query_agent": ("DB - Query Any Database (SELECT, you write the SQL)", "database", None),
    "db_verify_against_file": ("DB - Verify against Excel/CSV", "database", None),
    "db_rename_column": ("DB - Rename a misnamed column (plan, then confirm)", "database", None),
    # 招聘流水线:交付前回检(只读,把 JD 的事实重算一遍并与报告对账)
    "talent_verify_jd_report": ("Talent - Verify JD Report (交付前回检)", "database", None),
    "python_execute": ("Python Execute", "data", None),
    # Wrapped LangGraph agents (backend/langgraph/*.py) exposed as selectable
    # native tools. Invocation is delegated to langgraph.tool_adapters so the
    # hand-built pipelines (schema -> generate -> check -> execute) stay in one
    # place. Available to both normal agents and DeepAgents via native_tools.
    # 名字要说清是哪一个：这两个都是"查库"，区别是**谁写 SQL**。
    #   db_query_agent            = 直连 psycopg2，agent 给 SQL（快、便宜、可批量）
    #   db_query_langgraph  = LangGraph 流水线，agent 给自然语言（自己取 schema、写并自检 SQL）
    "db_query_langgraph": ("DB - Query with LangGraph (ask in natural language)", "database", None),
    "neo4j_agent_tool": ("Neo4j Graph Agent", "database", None),
}

#: Renamed tools: ``old_id -> (successor_id, reason)``.
#:
#: A rename is not an invention: agents saved with the old ``tool_id`` keep working (the alias still
#: exists in native_impl), but the picker should stop offering a name that does not say what the tool
#: is. The row survives with ``is_deprecated`` + ``superseded_by``, exactly like the ``pg_*`` retirements.
#: 退役表：``tool_id -> (successor_id or "", reason)``。
#: 改名只是退役的一种：接任者可以是一个新工具，也可以是「Settings 界面」或「本体流水线」这种非工具的东西，
#: 那时 successor 留空、理由里写清去处。seeding 会写 is_deprecated / deprecated_reason（有接任者就写 superseded_by）。
RENAMED_TOOLS: dict[str, tuple[str, str]] = {
    "pg_list_skills": (
        "search_skills",
        "并入 search_skills：列表与搜索是同一张表的同一个问题，空 query 即列表（so 一个工具两种用法）",
    ),
    "db_list_databases": (
        "db_describe",
        "并进 db_describe：`db_describe()` 不传库名就是列这台服务器上的库，两个入口做的是同一类发现",
    ),
    "pg_list_agents": (
        "",
        "退役：让 agent 去看别的 agent 是开发者的活，Settings → Agents 里有界面；22 个 agent 各少一个永不调用的工具",
    ),
    "pg_get_agent": (
        "",
        "退役：同上（读一个 agent 的完整配置属于开发者界面，不是 agent 能力）",
    ),
    "pg_list_custom_tools": (
        "",
        "退役：同上（工具清单在 Settings → Tools 里看）",
    ),
    "neo4j_agent_advanced_tool": (
        "neo4j_agent_tool",
        "退役：与 SQL 侧的 advanced_sql_agent_tool 同性质（休眠的 planner 变体）；经典版 neo4j_agent_tool 已覆盖同类问题",
    ),
    "neo4j_query": (
        "neo4j_agent_tool",
        "退役：0 个 agent 绑定、0 次调用；裸 Cypher 的逃生口由 neo4j_agent_tool 的自然语言流水线替代",
    ),
    "neo4j_get_doc": ("", "退役：0 个 agent 绑定、0 次调用（文档元数据由 neo4j_list_docs 一次取回）"),
    "neo4j_upsert_doc": ("", "退役：0 个 agent 绑定、0 次调用（写入路径由知识库同步流程承担）"),
    "neo4j_delete_doc": ("", "退役：0 个 agent 绑定、0 次调用（删除是运维动作，不该是 agent 能力）"),
    "sqlite_execute": (
        "db_query_agent",
        "退役：23 个 agent 绑着、真实调用 0；SQLite 是遗留演示路径，Postgres 是本平台唯一数据层（case-12 已迁到 db_build_from_file + db_query_agent）",
    ),
    "sqlite_load_csv": (
        "db_build_from_file",
        "退役：同上 —— 把 CSV 变成可查的数据，正确路径是 db_build_from_file（类型推断、建库标记、可 recreate）",
    ),
}
# Renames are applied once and the old row is DELETED, not kept as a deprecated alias: the two
# query tools are `db_query_agent` (you write the SQL) and `db_query_langgraph` (natural language),
# and a third name that means "one of those" is exactly the confusion the rename removed.

# Display category -> DSH-style definition category (core/tools/definition.py).
# Categories not listed fall back to "custom".
_DEFINITION_CATEGORY = {
    "web": "web",
    "filesystem": "filesystem",
    "reasoning": "reasoning",
    "skills": "skills",
    "database": "database",
    # 读的是「平台自身」的表：agent 模板、项目、技能、文档、工具 —— 不是一个业务库。
    # 混在 database 里，每个 agent 选工具时都要在一半无关条目里挑。
    "platform": "platform",
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
    # array/object used to be flattened to string here, which made every
    # list-typed tool argument (agent tools, todos, …) arrive as CSV text. The
    # builder understands list/dict now, so keep the real type.
    return stype if stype in ("string", "integer", "number", "boolean", "array", "object") else "string"


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
                    renamed = RENAMED_TOOLS.get(name)
                    if renamed:
                        row.is_deprecated = True
                        row.superseded_by = renamed[0] or None
                        row.deprecated_reason = renamed[1]
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
