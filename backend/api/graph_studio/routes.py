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
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

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
    """List the databases the SQL tools can target, plus the active one."""
    try:
        databases = _list_databases()
    except Exception as exc:  # noqa: BLE001 - surface connection errors
        raise HTTPException(500, f"cannot list databases: {exc}")
    sqlmod = _sql_setup_module()
    return {"databases": databases, "active": sqlmod.get_target_database()}


class SelectDatabaseRequest(BaseModel):
    database: str


@router.post("/databases/select")
def select_database(payload: SelectDatabaseRequest) -> Dict[str, Any]:
    """Point the SQL tools at another database (runtime only, no .env edit).

    The next run uses the new target; the change lasts for the process
    lifetime and resets to the .env value on backend restart.
    """
    try:
        databases = _list_databases()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"cannot list databases: {exc}")
    if payload.database not in databases:
        raise HTTPException(404, f"unknown database '{payload.database}'")

    sqlmod = _sql_setup_module()
    sqlmod.set_target_database(payload.database)
    return {"databases": databases, "active": payload.database}


# LLM business summaries are cached per (database, language); schemas change
# rarely, so regenerating on every request would just waste tokens.
_BUSINESS_SUMMARY_CACHE: Dict[Tuple[str, str], str] = {}


def _business_summary(dbname: str, tables: List[Dict[str, Any]], lang: str) -> Optional[str]:
    """Describe the database in business terms (<=3 lines) via the LLM.

    Best-effort: any failure (missing API key, network, model error) yields
    None so the UI can fall back to the raw table counts. The inventory
    (table -> row count -> columns) is compact enough for a small model call.
    """
    key = (dbname, lang)
    if key in _BUSINESS_SUMMARY_CACHE:
        return _BUSINESS_SUMMARY_CACHE[key]

    from langchain.chat_models import init_chat_model

    model = init_chat_model(
        "deepseek-chat",
        model_provider="deepseek",
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        temperature=0,
    )

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
        response = model.invoke(
            [
                {"role": "system", "content": "You are a helpful data analyst."},
                {"role": "user", "content": prompt},
            ]
        )
        summary = (response.content or "").strip()
    except Exception as exc:  # noqa: BLE001 - LLM failures are non-fatal
        print(f"[graph-studio] business summary failed for '{dbname}': {exc}")
        return None

    if not summary:
        return None
    _BUSINESS_SUMMARY_CACHE[key] = summary
    return summary


@router.get("/databases/summary")
def database_summary(lang: str = "en") -> Dict[str, Any]:
    """Summarize the *active* target database for the canvas header.

    Lists every public table of the database the SQL tools are currently
    pointed at, plus exact row counts (small dev databases; count(*) is fine).
    A `summary` field holds an LLM-written business description (<=3 lines)
    in the requested language (`lang` = en | zh). The response changes as the
    user switches databases, so the header stays in sync with the studio's
    Database dropdown.
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
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            for (name,) in cur.fetchall():
                try:
                    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name)))
                    rows = cur.fetchone()[0]
                except Exception:  # noqa: BLE001 - one bad table must not sink the summary
                    rows = None
                # Column names feed the LLM so it can infer the business purpose.
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position LIMIT 12",
                    (name,),
                )
                columns = [row[0] for row in cur.fetchall()]
                tables.append({"name": name, "rows": rows, "columns": columns})
    finally:
        conn.close()

    return {
        "database": dbname,
        "table_count": len(tables),
        "row_count": sum(t["rows"] for t in tables if t["rows"] is not None),
        "tables": [{"name": t["name"], "rows": t["rows"]} for t in tables],
        "summary": _business_summary(dbname, tables, lang),
    }


# ---------------------------------------------------------------------------
# Threads (in-memory registry for the studio session)
# ---------------------------------------------------------------------------
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
