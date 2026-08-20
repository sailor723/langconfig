# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Graph Engineering Studio API.

Hosts the *code-defined* LangGraph agents in ``backend/langgraph/`` natively
inside the FastAPI process — no separate ``langgraph dev`` server is needed.
The endpoint surface mirrors the Local Studio client so the React UI can list
assistants, inspect their graph structure, create threads, and stream runs
over SSE.

Endpoints:
- POST /api/graph-studio/assistants/search       list code-defined assistants
- GET  /api/graph-studio/assistants/{id}/graph    nodes + edges (canvas spec)
- GET  /api/graph-studio/assistants/{id}/schemas  input/state/output jsonschemas
- GET  /api/graph-studio/databases                list target DBs + the active one
- GET  /api/graph-studio/databases/summary         tables + row counts + LLM business summary (lang=en|zh)
- POST /api/graph-studio/databases/select         switch the SQL tools' target DB
- POST /api/graph-studio/threads/search           list threads
- POST /api/graph-studio/threads                  create a thread
- GET  /api/graph-studio/threads/{id}/state       checkpointed thread state
- GET  /api/graph-studio/threads/{id}/runs        run history
- POST /api/graph-studio/threads/{id}/runs/stream SSE run (messages/values/updates)
- POST /api/graph-studio/threads/{id}/runs/cancel interrupt an in-flight run

Threads and run history live in memory for the process lifetime; the compiled
graphs keep their own checkpointer (thread-scoped history) + store (memory).
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph-studio", tags=["graph-studio"])

# ---------------------------------------------------------------------------
# Registry of code-defined graphs (backend/langgraph/<graph_id>.py)
# ---------------------------------------------------------------------------
# Each entry exposes a compiled graph via a module-level `agent` attribute.
# Add new entries here to surface more graphs in the studio.
_LANGGRAPH_DIR = Path(__file__).resolve().parents[2] / "langgraph"

_ASSISTANT_REGISTRY: List[Dict[str, Any]] = [
    {
        "assistant_id": "sql_agent",
        "graph_id": "sql_agent",
        "name": "SQL Agent",
        "description": "Custom SQL agent with memory (Chinook DB)",
    },
    {
        "assistant_id": "sql_agent_hitl",
        "graph_id": "sql_agent_hitl",
        "name": "SQL Agent (HITL)",
        "description": "SQL agent with human-in-the-loop query approval",
    },
    {
        "assistant_id": "neo4j_agent",
        "graph_id": "neo4j_agent",
        "name": "Neo4j Graph Agent",
        "description": "Custom Neo4j graph agent with memory (Cypher queries)",
    },
    {
        "assistant_id": "neo4j_agent_hitl",
        "graph_id": "neo4j_agent_hitl",
        "name": "Neo4j Graph Agent (HITL)",
        "description": "Neo4j graph agent with human-in-the-loop Cypher approval",
    },
]

_GRAPH_CACHE: Dict[str, Any] = {}


def _load_compiled(assistant_id: str) -> Any:
    """Import (once) the graph module for an assistant and return its compiled graph."""
    if assistant_id in _GRAPH_CACHE:
        return _GRAPH_CACHE[assistant_id]

    entry = next(
        (a for a in _ASSISTANT_REGISTRY if a["assistant_id"] == assistant_id), None
    )
    if entry is None:
        raise HTTPException(404, f"unknown assistant '{assistant_id}'")

    module_path = _LANGGRAPH_DIR / f"{entry['graph_id']}.py"
    if not module_path.exists():
        raise HTTPException(404, f"graph module '{module_path}' not found")

    # The graph modules import each other by plain name (e.g. sql_setup_db),
    # so the langgraph dir must be importable.
    if str(_LANGGRAPH_DIR) not in sys.path:
        sys.path.insert(0, str(_LANGGRAPH_DIR))

    spec = importlib.util.spec_from_file_location(entry["graph_id"], module_path)
    if spec is None or spec.loader is None:
        raise HTTPException(500, f"cannot load graph module '{module_path}'")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    compiled = getattr(module, "agent", None)
    if compiled is None:
        raise HTTPException(500, f"module '{module_path}' does not expose 'agent'")

    _GRAPH_CACHE[assistant_id] = compiled
    return compiled


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def _message_to_dict(message: Any) -> Dict[str, Any]:
    """Convert a LangChain BaseMessage into the plain dict the UI renders."""
    out: Dict[str, Any] = {
        "id": getattr(message, "id", None),
        "type": getattr(message, "type", None),
        "name": getattr(message, "name", None),
        "content": getattr(message, "content", None),
    }
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = _jsonable(tool_calls)
    # Reasoning/chain-of-thought preserved by ChatDeepSeek / ChatOllama
    # (ChatOpenAI drops it, which is why Ollama must not go through it).
    reasoning = (getattr(message, "additional_kwargs", None) or {}).get(
        "reasoning_content"
    )
    if reasoning:
        out["reasoning_content"] = reasoning
    return out


def _jsonable(value: Any) -> Any:
    """Recursively convert LangChain messages / datetimes to JSON-safe types."""
    from datetime import datetime

    from langchain_core.messages import BaseMessage

    if isinstance(value, BaseMessage):
        return _message_to_dict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _sse(event: str, data: Any) -> str:
    """Format one Server-Sent-Event payload."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ---------------------------------------------------------------------------
# Assistants
# ---------------------------------------------------------------------------
def _source_info(obj: Any) -> Dict[str, Any]:
    """Best-effort source location + text for a callable (None-safe)."""
    if obj is None:
        return {
            "module": None,
            "file": None,
            "start_line": None,
            "end_line": None,
            "code": None,
        }
    try:
        code = inspect.getsource(obj)
    except Exception:  # noqa: BLE001 - compiled/builtin callables have no source
        code = None
    try:
        module = getattr(inspect.getmodule(obj), "__name__", None)
    except Exception:  # noqa: BLE001
        module = None
    try:
        file = inspect.getsourcefile(obj)
    except Exception:  # noqa: BLE001
        file = None
    try:
        lines, lineno = inspect.getsourcelines(obj)
        start_line, end_line = lineno, lineno + len(lines) - 1
    except Exception:  # noqa: BLE001
        start_line = end_line = None
    return {
        "module": module,
        "file": file,
        "start_line": start_line,
        "end_line": end_line,
        "code": code,
    }


def _graph_node_info(node_id: str, node: Any) -> Dict[str, Any]:
    """Describe one graph node for the canvas popup: kind, source, bound tools.

    ``node`` is a langgraph ``Node`` namedtuple (id, name, data, metadata, index);
    ``data`` is typically a ``RunnableCallable`` (wraps the real function in
    ``.func``) or a ``ToolNode`` (has ``.tools``). Everything is best-effort and
    None-safe so the UI always gets a renderable payload.
    """
    # START / END markers carry no user code.
    if node_id == "__start__":
        return {"id": node_id, "data": {"name": node_id, "kind": "start"}}
    if node_id == "__end__":
        return {"id": node_id, "data": {"name": node_id, "kind": "end"}}

    data = getattr(node, "data", None)
    kind = "unknown"
    info: Dict[str, Any] = {
        "module": None,
        "file": None,
        "start_line": None,
        "end_line": None,
        "code": None,
    }
    tools: List[Dict[str, Any]] = []
    type_name = type(data).__name__

    if type_name in ("ToolNode", "StructuredToolNode"):
        # Tool runner node — surface each bound tool (name, description, source).
        # Newer langgraph exposes a `tools_by_name` dict; older versions have `.tools`.
        kind = "tool"
        tools_list = getattr(data, "tools", None)
        if tools_list is None:
            tools_list = list(getattr(data, "tools_by_name", {}).values())
        for tool in tools_list or []:
            tool_fn = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
            tools.append(
                {
                    "name": getattr(tool, "name", None),
                    "description": getattr(tool, "description", None),
                    **_source_info(tool_fn),
                }
            )
    elif type_name == "CompiledStateGraph":
        # Nested (sub)graph node — report its top-level structure instead of source.
        kind = "subgraph"
        sub = data
        try:
            sub_graph = sub.get_graph()
            info["module"] = getattr(inspect.getmodule(sub), "__name__", None)
            info["file"] = inspect.getsourcefile(sub) if sub else None
            info["code"] = (
                f"# nested graph with {len(sub_graph.nodes)} nodes / "
                f"{len(sub_graph.edges)} edges"
            )
        except Exception:  # noqa: BLE001
            info["code"] = None
    else:
        # Plain function node — RunnableCallable keeps the real fn in .func.
        fn = getattr(data, "func", None)
        if fn is None and callable(data):
            fn = data
        if fn is not None:
            kind = "function"
            info = _source_info(fn)

    return {
        "id": node_id,
        "data": {
            "name": node_id,
            "kind": kind,
            "metadata": getattr(node, "metadata", None) or None,
            **info,
            "tools": tools or None,
        },
    }


class AssistantSearchRequest(BaseModel):
    metadata: Dict[str, Any] = {}


@router.post("/assistants/search")
def list_assistants(payload: AssistantSearchRequest) -> List[Dict[str, Any]]:
    """List the code-defined assistants (optionally filtered by metadata)."""
    result = []
    for a in _ASSISTANT_REGISTRY:
        if payload.metadata and not all(a.get(k) == v for k, v in payload.metadata.items()):
            continue
        result.append(
            {
                "assistant_id": a["assistant_id"],
                "graph_id": a["graph_id"],
                "name": a["name"],
                "description": a["description"],
            }
        )
    return result


@router.get("/assistants/{assistant_id}/graph")
def get_assistant_graph(assistant_id: str) -> Dict[str, Any]:
    """Return the graph structure (nodes + edges) for the canvas.

    Each node carries best-effort metadata + source info (kind, module, file,
    line range, code, bound tools) so the canvas popup can show node details.
    """
    compiled = _load_compiled(assistant_id)
    graph = compiled.get_graph()
    nodes = [_graph_node_info(nid, graph.nodes[nid]) for nid in graph.nodes]
    edges = [
        {
            "source": e.source,
            "target": e.target,
            "conditional": bool(getattr(e, "conditional", False)),
        }
        for e in graph.edges
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/assistants/{assistant_id}/code", response_class=PlainTextResponse)
def get_assistant_code(assistant_id: str) -> str:
    """Return the full Python source of the assistant's graph module.

    Mirrors the agent editors' "View code" — the studio shows the file that
    actually defines the graph (backend/langgraph/<graph_id>.py).
    """
    entry = next(
        (a for a in _ASSISTANT_REGISTRY if a["assistant_id"] == assistant_id), None
    )
    if entry is None:
        raise HTTPException(404, f"unknown assistant '{assistant_id}'")

    module_path = _LANGGRAPH_DIR / f"{entry['graph_id']}.py"
    if not module_path.exists():
        raise HTTPException(404, f"graph module '{module_path}' not found")

    return module_path.read_text(encoding="utf-8")


@router.get("/assistants/{assistant_id}/schemas")
def get_assistant_schemas(assistant_id: str) -> Dict[str, Any]:
    """Return input/state/output jsonschemas for the assistant."""
    compiled = _load_compiled(assistant_id)
    input_schema = compiled.get_input_jsonschema()
    get_state = getattr(compiled, "get_state_jsonschema", None)
    state_schema = get_state() if callable(get_state) else input_schema
    get_output = getattr(compiled, "get_output_jsonschema", None)
    output_schema = get_output() if callable(get_output) else input_schema
    return {
        "graph_id": assistant_id,
        "input_schema": input_schema,
        "state_schema": state_schema,
        "output_schema": output_schema,
    }


# ---------------------------------------------------------------------------
# Target database switching (the DB the SQL tools query)
# ---------------------------------------------------------------------------
def _sql_setup_module() -> Any:
    """Import backend/langgraph/sql_setup_db.py (the SQL tools' module)."""
    if str(_LANGGRAPH_DIR) not in sys.path:
        sys.path.insert(0, str(_LANGGRAPH_DIR))
    import sql_setup_db

    return sql_setup_db


def _list_databases() -> List[str]:
    """List every non-template database on the Postgres server."""
    import psycopg2

    sqlmod = _sql_setup_module()
    conn = psycopg2.connect(**sqlmod._connection_params())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false ORDER BY datname"
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


@router.get("/databases")
def list_databases() -> Dict[str, Any]:
    """List the databases the tools can target, grouped by type.

    Returns both Postgres DBs (for SQL agents) and Neo4j DBs (for Neo4j
    agents), plus the currently-active target for each type. The frontend
    uses this to populate the dropdown that swaps source based on which
    assistant the user selected.
    """
    sqlmod = _sql_setup_module()
    out: Dict[str, Any] = {
        "active_sql": sqlmod.get_target_database(),
        "active_neo4j": _neo4j_setup_module().get_target_database(),
    }
    # Postgres DBs (for SQL agents)
    try:
        out["sql"] = _list_databases()
    except Exception as exc:  # noqa: BLE001 - don't fail the whole call
        out["sql"] = []
        out["sql_error"] = str(exc)
    # Neo4j DBs (for Neo4j agents)
    try:
        out["neo4j"] = [d["name"] for d in _neo4j_setup_module()._list_neo4j_databases()]
    except Exception as exc:  # noqa: BLE001
        out["neo4j"] = []
        out["neo4j_error"] = str(exc)
    return out


def _neo4j_setup_module() -> Any:
    """Import backend/langgraph/neo4j_setup_db.py (the Neo4j tools' module).

    Mirrors _sql_setup_module() above. The langgraph dir must be on
    sys.path so the cross-module `from llm import ...` chain resolves when
    neo4j_setup_db is loaded.
    """
    if str(_LANGGRAPH_DIR) not in sys.path:
        sys.path.insert(0, str(_LANGGRAPH_DIR))
    import neo4j_setup_db

    return neo4j_setup_db


class SelectDatabaseRequest(BaseModel):
    database: str
    type: Literal["sql", "neo4j"] = "sql"  # default to SQL for backwards compat


@router.post("/databases/select")
def select_database(payload: SelectDatabaseRequest) -> Dict[str, Any]:
    """Point the tools at another database (runtime only, no .env edit).

    `type` selects which set of tools to retarget (sql / neo4j). The change
    lasts for the process lifetime and resets to the .env value on backend
    restart.
    """
    if payload.type == "neo4j":
        available = [d["name"] for d in _neo4j_setup_module()._list_neo4j_databases()]
        if payload.database not in available:
            raise HTTPException(404, f"unknown neo4j database '{payload.database}'")
        neo4jmod = _neo4j_setup_module()
        neo4jmod.set_target_database(payload.database)
        return {"active_neo4j": payload.database, "active_sql": _sql_setup_module().get_target_database()}

    # Default: SQL
    try:
        available = _list_databases()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"cannot list databases: {exc}")
    if payload.database not in available:
        raise HTTPException(404, f"unknown database '{payload.database}'")
    sqlmod = _sql_setup_module()
    sqlmod.set_target_database(payload.database)
    return {"active_sql": payload.database, "active_neo4j": _neo4j_setup_module().get_target_database()}


# LLM business summaries are cached per (database, language); schemas change
# rarely, so regenerating on every request would just waste tokens.
_BUSINESS_SUMMARY_CACHE: Dict[Tuple[str, str], str] = {}

# Cached ER / network payloads, keyed on the introspection input only — language
# changes don't trigger a re-introspection. Same lifetime as the business
# summary cache: process-local, reset on backend restart.
_ER_DIAGRAM_CACHE: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
_NEO4J_NETWORK_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


async def _business_summary(dbname: str, tables: List[Dict[str, Any]], lang: str) -> Optional[str]:
    """Describe the database in business terms (<=3 lines) via the LLM.

    Best-effort: any failure (missing API key, network, model error) yields
    None so the UI can fall back to the raw table counts. The inventory
    (table -> row count -> columns) is compact enough for a small model call.

    The model is resolved from the ``models`` settings document's
    ``default_model`` (the same setting the rest of the app uses — see
    Settings -> Models -> default model). This makes the summary follow the
    team's chosen LLM instead of a hardcoded ``deepseek-chat``. Falls back
    to ``deepseek-chat`` when no default is configured.
    """
    key = (dbname, lang)
    if key in _BUSINESS_SUMMARY_CACHE:
        return _BUSINESS_SUMMARY_CACHE[key]

    # Resolve the configured default model (Settings -> Models -> default
    # model) so the summary follows the team's chosen LLM. Falls back to
    # DEFAULT_MODEL (deepseek-chat) when the settings document is empty or
    # the settings engine is unavailable (pre-migration DB / import error).
    from services.agent_utils import DEFAULT_MODEL, resolve_model

    model_name = DEFAULT_MODEL
    try:
        from core.settings import runtime_get
        model_name = runtime_get("models", "default_model") or DEFAULT_MODEL
    except Exception:
        pass
    max_tokens = 1024  # the inventory is small; cap the summary call

    lines = [f"Database: {dbname}"]
    for t in tables:
        cols = ", ".join(t["columns"]) if t["columns"] else "-"
        rows = "?" if t["rows"] is None else f"{t['rows']:,}"
        lines.append(f"- {t['name']} ({rows} rows): {cols}")
    inventory = "\n".join(lines)

    language_note = "回答必须使用中文。" if lang.startswith("zh") else "Respond in English."
    prompt = (
        "You are a data analyst. Write a concise BUSINESS summary of the database below:\n"
        f"{inventory}\n\n"
        "Describe what business domain or processes the data covers and any interesting "
        f"scale signals. Keep it to AT MOST 3 short lines, plain text, no markdown. {language_note}"
    )

    try:
        model = await resolve_model(
            model_name, 0.0, max_tokens, {"model": model_name}
        )
        response = await model.ainvoke(
            [
                {"role": "system", "content": "You are a helpful data analyst."},
                {"role": "user", "content": prompt},
            ]
        )
        summary = (response.content or "").strip()
    except Exception as exc:  # noqa: BLE001 - LLM failures are non-fatal
        logger.warning(f"[graph-studio] business summary failed for '{dbname}' "
                       f"(model={model_name}): {exc}")
        return None

    if not summary:
        return None
    _BUSINESS_SUMMARY_CACHE[key] = summary
    return summary


def _er_diagram_payload(dbname: str, schema: str) -> Optional[Dict[str, Any]]:
    """Introspect any Postgres database and return tables + columns + FKs.

    The payload is what the frontend needs to render an ER diagram:

        {
            "schema": "public",
            "tables": [
                {
                    "name": "album",
                    "row_count": 347,    # null if COUNT(*) failed
                    "columns": [
                        {"name": "id", "type": "integer",
                         "nullable": false, "pk": True},
                        ...
                    ],
                },
                ...
            ],
            "foreign_keys": [
                {
                    "from_table": "album", "from_column": "artist_id",
                    "to_table": "artist", "to_column": "id",
                    "constraint_name": "fk_album_artist_id",
                    "on_update": "NO ACTION", "on_delete": "NO ACTION",
                },
                ...
            ],
        }

    Generic: works on any Postgres DB the user connects to. No schema-specific
    (chinook, etc.) logic.

    Returns None if the connection fails or any introspection step raises.
    Callers should omit the field from the response rather than 500.

    Cross-schema FKs (rare) are filtered out and logged at DEBUG; the diagram
    stays coherent and the log line is the only clue for the curious.
    """
    cache_key = (dbname, schema)
    if cache_key in _ER_DIAGRAM_CACHE:
        return _ER_DIAGRAM_CACHE[cache_key]

    payload: Dict[str, Any] = {
        "schema": schema,
        "tables": [],
        "foreign_keys": [],
    }

    try:
        sqlmod = _sql_setup_module()
    except Exception as exc:
        logger.warning(
            f"[graph-studio] ER diagram: cannot import sql_setup_db: {exc}"
        )
        _ER_DIAGRAM_CACHE[cache_key] = None
        return None

    try:
        import psycopg2
        from psycopg2 import sql as _pg_sql
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(**sqlmod._connection_params())
    except Exception as exc:
        logger.warning(
            f"[graph-studio] ER diagram connect failed for '{dbname}' "
            f"(schema={schema}): {exc}"
        )
        _ER_DIAGRAM_CACHE[cache_key] = None
        return None

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. List base tables in the schema (skip views).
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (schema,),
            )
            table_names = [r["table_name"] for r in cur.fetchall()]
            if not table_names:
                # Schema exists but is empty — still cache the empty payload
                # so we don't keep poking the DB.
                _ER_DIAGRAM_CACHE[cache_key] = payload
                return payload

            # 2. Per-table columns with PK flag. PK detection uses pg_index /
            # pg_attribute (the source of truth) joined back to column names;
            # information_schema has no is_primary_key column on its own.
            # Single query for all tables — much faster than N round trips.
            cur.execute(
                """
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    EXISTS (
                        SELECT 1
                        FROM pg_index i
                        JOIN pg_attribute a
                          ON a.attrelid = i.indrelid
                         AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = (
                            SELECT c2.oid
                            FROM pg_class c2
                            JOIN pg_namespace n ON n.oid = c2.relnamespace
                            WHERE c2.relname = c.table_name
                              AND n.nspname = c.table_schema
                        )
                          AND i.indisprimary
                          AND a.attname = c.column_name
                    ) AS is_pk
                FROM information_schema.columns c
                WHERE c.table_schema = %s AND c.table_name = ANY(%s)
                ORDER BY c.table_name, c.ordinal_position
                """,
                (schema, table_names),
            )

            table_columns: Dict[str, List[Dict[str, Any]]] = {
                name: [] for name in table_names
            }
            for r in cur.fetchall():
                table_columns[r["table_name"]].append(
                    {
                        "name": r["column_name"],
                        "type": r["data_type"],
                        "nullable": r["is_nullable"] == "YES",
                        "pk": bool(r["is_pk"]),
                    }
                )

            # 3. Per-table row counts. COUNT(*) is fine for dev databases
            # (chinook is ~15k rows total). For larger DBs we'd swap in
            # pg_stat_user_tables.n_live_tup estimates; deferred until the
            # perf actually matters.
            table_rows: Dict[str, Optional[int]] = {}
            for name in table_names:
                try:
                    cur.execute(
                        _pg_sql.SQL("SELECT count(*) FROM {}.{}").format(
                            _pg_sql.Identifier(schema),
                            _pg_sql.Identifier(name),
                        )
                    )
                    table_rows[name] = int(cur.fetchone()[0])
                except Exception as exc:
                    # One bad table (e.g. permissions) must not sink the diagram.
                    logger.debug(
                        f"[graph-studio] count(*) failed for {schema}.{name}: {exc}"
                    )
                    table_rows[name] = None

            # 4. Foreign keys across all tables in the schema.
            # information_schema already gives us everything we need;
            # no pg_* joins required.
            cur.execute(
                """
                SELECT
                    tc.table_name           AS from_table,
                    kcu.column_name         AS from_column,
                    ccu.table_name          AS to_table,
                    ccu.column_name         AS to_column,
                    tc.constraint_name      AS constraint_name,
                    rc.update_rule          AS on_update,
                    rc.delete_rule          AS on_delete
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                  ON tc.constraint_name     = rc.constraint_name
                 AND tc.constraint_schema   = rc.constraint_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON rc.unique_constraint_name = ccu.constraint_name
                 AND rc.constraint_schema = ccu.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema    = %s
                ORDER BY tc.table_name, kcu.column_name
                """,
                (schema,),
            )

            fks: List[Dict[str, Any]] = []
            valid_tables = set(table_names)
            for r in cur.fetchall():
                # Skip FKs that touch tables outside the requested schema.
                # Cross-schema FKs are technically valid but visually noisy
                # in the diagram; log at DEBUG for the curious.
                if r["from_table"] not in valid_tables:
                    logger.debug(
                        f"[graph-studio] skipping FK {r['constraint_name']}: "
                        f"from_table '{r['from_table']}' not in schema"
                    )
                    continue
                fks.append(
                    {
                        "from_table": r["from_table"],
                        "from_column": r["from_column"],
                        "to_table": r["to_table"],
                        "to_column": r["to_column"],
                        "constraint_name": r["constraint_name"],
                        "on_update": r["on_update"],
                        "on_delete": r["on_delete"],
                    }
                )

            payload["tables"] = [
                {
                    "name": n,
                    "row_count": table_rows.get(n),
                    "columns": table_columns.get(n, []),
                }
                for n in table_names
            ]
            payload["foreign_keys"] = fks
    except Exception as exc:
        # Generic catch-all: any failure here must not break the existing
        # database_summary response. Cache None so we don't keep retrying
        # the same broken DB on every language switch.
        logger.warning(
            f"[graph-studio] ER diagram introspection failed for '{dbname}' "
            f"(schema={schema}): {exc}"
        )
        _ER_DIAGRAM_CACHE[cache_key] = None
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _ER_DIAGRAM_CACHE[cache_key] = payload
    return payload


@router.get("/databases/summary")
async def database_summary(
    lang: str = "en",
    schema: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize the *active* target database for the canvas header.

    Lists every table of the database the SQL tools are currently pointed
    at (defaulting to the first non-empty schema when `schema` is omitted),
    plus exact row counts (small dev databases; count(*) is fine).
    A `summary` field holds an LLM-written business description (<=3 lines)
    in the requested language (`lang` = en | zh). The response changes as
    the user switches databases, so the header stays in sync with the
    studio's Database dropdown.

    The response also carries an `er_diagram` field with the per-table
    columns and foreign keys needed to render an ER diagram in the canvas
    schema view. `schema` defaults to the first non-empty schema in the
    target DB (usually `public`) for users on DBs that organize tables
    across multiple schemas.
    """
    import psycopg2
    from psycopg2 import sql

    sqlmod = _sql_setup_module()
    dbname = sqlmod.get_target_database()
    try:
        conn = psycopg2.connect(**sqlmod._connection_params())
    except Exception as exc:  # noqa: BLE001 - surface connection errors
        raise HTTPException(500, f"cannot connect to database '{dbname}': {exc}")

    tables: List[Dict[str, Any]] = []
    resolved_schema: Optional[str] = schema
    try:
        with conn.cursor() as cur:
            # If the caller didn't pin a schema, pick the first one that
            # has any user-visible table. Fall back to 'public' when none
            # are found so the original behavior is preserved for empty
            # databases.
            if not resolved_schema:
                cur.execute(
                    """
                    SELECT table_schema
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND table_type = 'BASE TABLE'
                    GROUP BY table_schema
                    ORDER BY table_schema
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                resolved_schema = row[0] if row else "public"

            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (resolved_schema,),
            )
            for (name,) in cur.fetchall():
                try:
                    cur.execute(
                        sql.SQL("SELECT count(*) FROM {}.{}").format(
                            sql.Identifier(resolved_schema), sql.Identifier(name)
                        )
                    )
                    rows = cur.fetchone()[0]
                except Exception:  # noqa: BLE001 - one bad table must not sink the summary
                    rows = None
                # Column names feed the LLM so it can infer the business purpose.
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY ordinal_position LIMIT 12",
                    (resolved_schema, name),
                )
                columns = [row[0] for row in cur.fetchall()]
                tables.append({"name": name, "rows": rows, "columns": columns})
    finally:
        conn.close()

    # ER diagram payload — reuses the connection-pool-free helper. Opens its
    # own short-lived connection because the `conn` above was closed in the
    # finally block. Four small queries against information_schema / pg_index.
    er_diagram = _er_diagram_payload(dbname, resolved_schema or "public")

    return {
        "database": dbname,
        "type": "sql",
        "schema": resolved_schema,
        "table_count": len(tables),
        "row_count": sum(t["rows"] for t in tables if t["rows"] is not None),
        "tables": [{"name": t["name"], "rows": t["rows"]} for t in tables],
        "summary": await _business_summary(dbname, tables, lang),
        "er_diagram": er_diagram,
    }


# ---------------------------------------------------------------------------
# Neo4j summary — mirror of the SQL summary for graph databases.
# Same shape so the UI can render either kind with one renderer.
# ---------------------------------------------------------------------------
_NEO4J_SUMMARY_CACHE: Dict[Tuple[str, str], str] = {}


async def _neo4j_business_summary(dbname: str, inventory: str, lang: str) -> Optional[str]:
    """Describe the Neo4j graph in business terms (<=3 lines) via the LLM.

    Best-effort: returns None on any failure so the UI can fall back to the
    raw label/rel counts. The inventory is a small text block (labels +
    relationship types + node/edge counts) which is well within a 1K
    token call. Reuses the same model resolution as the SQL summary
    (Settings -> Models -> default model).
    """
    key = (dbname, lang)
    if key in _NEO4J_SUMMARY_CACHE:
        return _NEO4J_SUMMARY_CACHE[key]

    from services.agent_utils import DEFAULT_MODEL, resolve_model

    model_name = DEFAULT_MODEL
    try:
        from core.settings import runtime_get
        model_name = runtime_get("models", "default_model") or DEFAULT_MODEL
    except Exception:
        pass
    max_tokens = 1024

    language_note = "回答必须使用中文。" if lang.startswith("zh") else "Respond in English."
    prompt = (
        "You are a data analyst. Write a concise BUSINESS summary of the graph database below:\n"
        f"{inventory}\n\n"
        "Describe what business domain or processes the graph covers and any interesting "
        f"scale signals. Keep it to AT MOST 3 short lines, plain text, no markdown. {language_note}"
    )

    try:
        model = await resolve_model(
            model_name, 0.0, max_tokens, {"model": model_name}
        )
        response = await model.ainvoke(
            [
                {"role": "system", "content": "You are a helpful data analyst."},
                {"role": "user", "content": prompt},
            ]
        )
        summary = (response.content or "").strip()
    except Exception as exc:  # noqa: BLE001 - LLM failures are non-fatal
        logger.warning(f"[graph-studio] neo4j business summary failed for '{dbname}' "
                       f"(model={model_name}): {exc}")
        return None

    if not summary:
        return None
    _NEO4J_SUMMARY_CACHE[key] = summary
    return summary


def _neo4j_network_payload(dbname: str) -> Optional[Dict[str, Any]]:
    """Introspect any Neo4j database and return label nodes + rel-type edges.

    The payload is what the frontend needs to render a network diagram:

        {
            "label_nodes": [
                {"name": "Person", "count": 50,
                 "properties": ["name", "born"]},
                ...
            ],
            "rel_edges": [
                {"type": "ACTED_IN", "from_label": "Person",
                 "to_label": "Movie", "count": 30},
                ...
            ],
        }

    Generic: works on any Neo4j DB. No label-name whitelist.

    Property keys per label are pulled via pure-Cypher aggregation (no APOC
    dependency, works on any Neo4j version). Rel-type edges group by
    (from_label, type, to_label) — the unit the diagram renders.

    Returns None on any failure; callers omit the field.
    """
    if dbname in _NEO4J_NETWORK_CACHE:
        return _NEO4J_NETWORK_CACHE[dbname]

    payload: Dict[str, Any] = {"label_nodes": [], "rel_edges": []}

    try:
        neo4jmod = _neo4j_setup_module()
    except Exception as exc:
        logger.warning(
            f"[graph-studio] Neo4j network: cannot import neo4j_setup_db: {exc}"
        )
        _NEO4J_NETWORK_CACHE[dbname] = None
        return None

    try:
        drv = neo4jmod._driver()
    except Exception as exc:
        logger.warning(
            f"[graph-studio] Neo4j network connect failed for '{dbname}': {exc}"
        )
        _NEO4J_NETWORK_CACHE[dbname] = None
        return None

    try:
        with drv.session(database=dbname) as s:
            # 1. Per-label node counts.
            label_rows = s.run(
                """
                MATCH (n)
                WITH labels(n)[0] AS label, count(*) AS n
                RETURN label, n
                ORDER BY n DESC
                """
            ).data()
            valid_labels = {r["label"] for r in label_rows if r["label"]}

            # 2. Per-label property keys (distinct, no cap).
            prop_rows = s.run(
                """
                MATCH (n)
                WITH labels(n)[0] AS label, keys(n) AS ks
                WITH label, ks
                UNWIND ks AS k
                WITH label, collect(DISTINCT k) AS props
                RETURN label, props
                """
            ).data()
            props_by_label = {r["label"]: r["props"] for r in prop_rows}

            payload["label_nodes"] = [
                {
                    "name": r["label"],
                    "count": r["n"],
                    "properties": props_by_label.get(r["label"], []),
                }
                for r in label_rows
                if r["label"]
            ]

            # 3. Per-rel-type edges grouped by (from_label, type, to_label).
            # LIMIT 500 keeps response size bounded for very dense graphs.
            rel_rows = s.run(
                """
                MATCH (a)-[r]->(b)
                WITH labels(a)[0] AS from_label,
                     type(r)     AS rel_type,
                     labels(b)[0] AS to_label,
                     count(*)    AS n
                RETURN from_label, rel_type, to_label, n
                ORDER BY n DESC
                LIMIT 500
                """
            ).data()
            for r in rel_rows:
                # Defensive: skip edges that reference a label that didn't
                # appear in the label scan (could happen on inconsistent
                # graphs where a node has zero labels).
                if r["from_label"] not in valid_labels:
                    continue
                if r["to_label"] not in valid_labels:
                    continue
                payload["rel_edges"].append(
                    {
                        "type": r["rel_type"],
                        "from_label": r["from_label"],
                        "to_label": r["to_label"],
                        "count": r["n"],
                    }
                )
    except Exception as exc:
        logger.warning(
            f"[graph-studio] Neo4j network introspection failed for "
            f"'{dbname}': {exc}"
        )
        _NEO4J_NETWORK_CACHE[dbname] = None
        return None

    _NEO4J_NETWORK_CACHE[dbname] = payload
    return payload


@router.get("/databases/neo4j-summary")
async def neo4j_database_summary(lang: str = "en") -> Dict[str, Any]:
    """Summarize the *active* target Neo4j database for the canvas header.

    Lists every node label + relationship type of the database the Neo4j
    tools are currently pointed at, plus exact node/edge counts (small dev
    databases; count(*) is fine). A `summary` field holds an LLM-written
    business description (<=3 lines) in the requested language
    (`lang` = en | zh). The response changes as the user switches
    databases, so the header stays in sync with the studio's DB dropdown.
    """
    neo4jmod = _neo4j_setup_module()
    dbname = neo4jmod.get_target_database()
    try:
        drv = neo4jmod._driver()
    except Exception as exc:  # noqa: BLE001 - surface connection errors
        raise HTTPException(500, f"cannot connect to neo4j: {exc}")

    labels: List[Dict[str, Any]] = []
    rels: List[Dict[str, Any]] = []
    total_nodes = 0
    total_edges = 0
    try:
        with drv.session(database=dbname) as s:
            label_rows = s.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n "
                "ORDER BY n DESC"
            ).data()
            for r in label_rows:
                labels.append({"name": r["label"], "nodes": r["n"]})
                total_nodes += r["n"] or 0
            rel_rows = s.run(
                "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n "
                "ORDER BY n DESC"
            ).data()
            for r in rel_rows:
                rels.append({"name": r["rel"], "edges": r["n"]})
                total_edges += r["n"] or 0
    except Exception as exc:  # noqa: BLE001 - keep going so the header still renders
        logger.warning(f"[graph-studio] neo4j summary query failed for '{dbname}': {exc}")
        raise HTTPException(500, f"neo4j query failed for '{dbname}': {exc}")

    # Build the inventory text the LLM reads (compact, well under 1K tokens).
    inv_lines = [f"Graph database: {dbname}"]
    inv_lines.append(f"Total: {total_nodes:,} nodes, {total_edges:,} edges")
    if labels:
        inv_lines.append("\nNode labels:")
        for lab in labels[:30]:
            inv_lines.append(f"  - {lab['name']}  ({lab['nodes']:,})")
    if rels:
        inv_lines.append("\nRelationship types:")
        for r in rels[:30]:
            inv_lines.append(f"  - :{r['name']}  ({r['edges']:,})")
    inventory = "\n".join(inv_lines)

    return {
        "database": dbname,
        "type": "neo4j",
        "node_count": total_nodes,
        "edge_count": total_edges,
        "labels": [{"name": l["name"], "nodes": l["nodes"]} for l in labels],
        "rels": [{"name": r["name"], "edges": r["edges"]} for r in rels],
        "summary": await _neo4j_business_summary(dbname, inventory, lang),
        "network_diagram": _neo4j_network_payload(dbname),
    }


# ---------------------------------------------------------------------------
# Threads (in-memory registry for the studio session)
# ---------------------------------------------------------------------------
# Threads and runs live in memory for the process lifetime. The compiled
# graphs keep their own checkpointer (thread-scoped history) + store (memory).
_THREADS: Dict[str, Dict[str, Any]] = {}
_RUNS: Dict[str, List[Dict[str, Any]]] = {}
# Per-thread cancellation flags: an in-flight SSE run checks the flag between
# events and stops at the next boundary when the user hits "interrupt".
_CANCEL_EVENTS: Dict[str, asyncio.Event] = {}


def _thread_out(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "thread_id": t["thread_id"],
        "assistant_id": t["assistant_id"],
        "created_at": t["created_at"],
        "status": t["status"],
        "metadata": {"graph_id": t["graph_id"], "assistant_id": t["assistant_id"]},
    }


class ThreadSearchRequest(BaseModel):
    metadata: Dict[str, Any] = {}


@router.post("/threads/search")
def list_threads(payload: ThreadSearchRequest) -> List[Dict[str, Any]]:
    """List threads (newest first), optionally filtered by metadata (e.g. graph_id)."""
    graph_id = payload.metadata.get("graph_id")
    result = []
    for t in _THREADS.values():
        if graph_id is not None and t.get("graph_id") != graph_id:
            continue
        result.append(_thread_out(t))
    return sorted(result, key=lambda t: t["created_at"], reverse=True)


class ThreadCreateRequest(BaseModel):
    assistant_id: str
    metadata: Dict[str, Any] = {}


@router.post("/threads")
def create_thread(payload: ThreadCreateRequest) -> Dict[str, Any]:
    """Create a studio thread bound to an assistant's graph."""
    entry = next(
        (a for a in _ASSISTANT_REGISTRY if a["assistant_id"] == payload.assistant_id),
        None,
    )
    if entry is None:
        raise HTTPException(404, f"unknown assistant '{payload.assistant_id}'")
    graph_id = payload.metadata.get("graph_id") or entry["graph_id"]
    thread_id = uuid.uuid4().hex
    record = {
        "thread_id": thread_id,
        "assistant_id": payload.assistant_id,
        "graph_id": graph_id,
        "created_at": _now(),
        "status": "idle",
    }
    _THREADS[thread_id] = record
    _RUNS[thread_id] = []
    return _thread_out(record)


@router.get("/threads/{thread_id}/state")
async def get_thread_state(thread_id: str) -> Dict[str, Any]:
    """Return the checkpointed state of a thread (values, next, interrupts…)."""
    record = _THREADS.get(thread_id)
    if record is None:
        raise HTTPException(404, f"unknown thread '{thread_id}'")

    compiled = _load_compiled(record["assistant_id"])
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snap = await compiled.aget_state(config)
    except Exception:
        snap = None

    if snap is None or not getattr(snap, "values", None):
        return {
            "values": {},
            "next": [],
            "tasks": [],
            "interrupts": [],
            "metadata": {"thread_id": thread_id},
            "checkpoint_id": None,
            "created_at": record["created_at"],
        }

    tasks = []
    for t in getattr(snap, "tasks", None) or []:
        task: Dict[str, Any] = {"name": getattr(t, "name", None)}
        interrupts = getattr(t, "interrupts", None)
        if interrupts:
            task["interrupts"] = _jsonable(interrupts)
        tasks.append(task)

    return {
        "values": _jsonable(snap.values),
        "next": list(getattr(snap, "next", None) or []),
        "tasks": tasks,
        "interrupts": _jsonable(getattr(snap, "interrupts", None) or []),
        "metadata": dict(getattr(snap, "metadata", None) or {}),
        "checkpoint_id": getattr(snap, "checkpoint_id", None),
        "created_at": getattr(snap, "created_at", None) or record["created_at"],
    }


@router.get("/threads/{thread_id}/runs")
def list_runs(thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """List run history for a thread (newest first)."""
    if thread_id not in _THREADS:
        raise HTTPException(404, f"unknown thread '{thread_id}'")
    runs = _RUNS.get(thread_id, [])
    return sorted(runs, key=lambda r: r["updated_at"], reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Streaming run (SSE)
# ---------------------------------------------------------------------------
class StreamRunRequest(BaseModel):
    assistant_id: str
    input: Dict[str, Any] = {}
    stream_mode: List[str] = ["messages", "values", "updates"]


def _accumulate_chunk(
    partial: Dict[str, Dict[str, Any]], chunk: Any
) -> Optional[Dict[str, Any]]:
    """Aggregate one streamed message chunk into the partial-message cache.

    Content chunks are concatenated; ``tool_call_chunks`` are merged by index
    (name/args/id fragments). Returns the aggregated message dict, or None if
    the chunk carries no id. Internal keys (``_tool_parts``) are stripped.
    """
    mid = getattr(chunk, "id", None)
    if not mid:
        return None

    prev = partial.get(mid)
    if prev is None:
        prev = {
            "id": mid,
            "type": getattr(chunk, "type", "ai") or "ai",
            "name": getattr(chunk, "name", None) or None,
            "content": "",
            "_tool_parts": {},
        }
        partial[mid] = prev

    content = getattr(chunk, "content", None)
    if content:
        prev["content"] += content if isinstance(content, str) else str(content)

    # Streaming reasoning tokens arrive as deltas in additional_kwargs
    # (ChatOllama maps Ollama's `message.thinking` -> reasoning_content).
    reasoning = (getattr(chunk, "additional_kwargs", None) or {}).get(
        "reasoning_content"
    )
    if reasoning:
        prev["reasoning_content"] = prev.get("reasoning_content", "") + reasoning

    for tcc in getattr(chunk, "tool_call_chunks", None) or []:
        idx = tcc.get("index")
        parts = prev["_tool_parts"].setdefault(idx, {"name": "", "args": "", "id": ""})
        if tcc.get("name"):
            parts["name"] += tcc["name"]
        if tcc.get("args"):
            parts["args"] += tcc["args"]
        if tcc.get("id"):
            parts["id"] += tcc["id"]

    if prev["_tool_parts"]:
        calls = []
        for idx in sorted(prev["_tool_parts"]):
            p = prev["_tool_parts"][idx]
            try:
                args = json.loads(p["args"]) if p["args"] else {}
            except Exception:
                args = {}
            calls.append(
                {
                    "name": p["name"],
                    "args": args,
                    "id": p["id"] or f"call_{uuid.uuid4().hex[:12]}",
                    "type": "tool_call",
                }
            )
        prev["tool_calls"] = calls
    else:
        prev.pop("tool_calls", None)

    return {k: v for k, v in prev.items() if not k.startswith("_")}


def _clean_partials(partial: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip internal aggregation keys (``_tool_parts``) and empty shells
    (messages a provider opened but never filled) before emitting."""
    out = []
    for m in partial.values():
        if not m.get("content") and not m.get("tool_calls") and not m.get("reasoning_content"):
            continue
        out.append({k: v for k, v in m.items() if not k.startswith("_")})
    return out


class _RunCancelled(Exception):
    """Raised inside the SSE generator when the user interrupts a run."""


async def _run_event_gen(
    compiled: Any,
    config: Dict[str, Any],
    payload: StreamRunRequest,
    record: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Stream a run over SSE: messages/partial, values, updates (+ error)."""
    run_id = uuid.uuid4().hex
    started = _now()
    run = {
        "run_id": run_id,
        "thread_id": record["thread_id"],
        "assistant_id": payload.assistant_id,
        "status": "running",
        "created_at": started,
        "updated_at": started,
        "kwargs": {"input": payload.input},
    }
    _RUNS.setdefault(record["thread_id"], []).append(run)
    record["status"] = "running"

    # Arm the cancellation flag for this thread (reused across runs).
    cancel_event = _CANCEL_EVENTS.setdefault(record["thread_id"], asyncio.Event())
    cancel_event.clear()

    partial_messages: Dict[str, Dict[str, Any]] = {}
    try:
        async for event in compiled.astream(
            payload.input, config=config, stream_mode=payload.stream_mode
        ):
            # Stop at the next event boundary when the user hit "interrupt".
            if cancel_event.is_set():
                raise _RunCancelled()
            if isinstance(event, tuple):
                # With a LIST of stream modes langgraph yields (mode, payload);
                # a bare (chunk, metadata) tuple is the single-mode messages shape.
                mode, data = event
                if not isinstance(mode, str):
                    # single-mode messages: event = (AIMessageChunk, metadata)
                    _accumulate_chunk(partial_messages, mode)
                    yield _sse("messages/partial", _clean_partials(partial_messages))
                elif mode == "messages":
                    chunk = data[0]
                    _accumulate_chunk(partial_messages, chunk)
                    yield _sse("messages/partial", _clean_partials(partial_messages))
                elif mode == "values":
                    yield _sse("values", _jsonable(data))
                elif mode == "updates":
                    yield _sse("updates", _jsonable(data))
            elif isinstance(event, dict) and event:
                if "messages" in event:
                    # values mode: full state snapshot (messages synced by UI)
                    yield _sse("values", _jsonable(event))
                else:
                    # updates mode: {node_name: state_delta}
                    yield _sse("updates", _jsonable(event))
        run["status"] = "completed"
        record["status"] = "completed"
    except _RunCancelled:
        run["status"] = "cancelled"
        record["status"] = "cancelled"
        yield _sse("error", {"message": "Run cancelled by user"})
    except Exception as exc:  # noqa: BLE001 - surface any graph error to the client
        run["status"] = "error"
        run["error"] = str(exc)
        record["status"] = "error"
        yield _sse("error", {"message": str(exc)})
    finally:
        run["updated_at"] = _now()
        _CANCEL_EVENTS.pop(record["thread_id"], None)


@router.post("/threads/{thread_id}/runs/stream")
async def stream_run(thread_id: str, payload: StreamRunRequest) -> StreamingResponse:
    """Start a run and stream live events (SSE)."""
    record = _THREADS.get(thread_id)
    if record is None:
        raise HTTPException(404, f"unknown thread '{thread_id}'")

    compiled = _load_compiled(payload.assistant_id)
    config = {"configurable": {"thread_id": thread_id}}
    return StreamingResponse(
        _run_event_gen(compiled, config, payload, record),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/threads/{thread_id}/runs/cancel")
def cancel_run(thread_id: str) -> Dict[str, Any]:
    """Ask an in-flight run on a thread to stop at the next event boundary.

    The run is not killed mid-step — the SSE generator checks the flag between
    events, so the user gets a clean "Run cancelled" event and the graph
    checkpointer is left in a consistent state.
    """
    if thread_id not in _THREADS:
        raise HTTPException(404, f"unknown thread '{thread_id}'")
    event = _CANCEL_EVENTS.get(thread_id)
    if event is not None:
        event.set()
    return {"thread_id": thread_id, "cancelled": True}
