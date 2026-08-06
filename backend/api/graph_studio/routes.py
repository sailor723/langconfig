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
- POST /api/graph-studio/threads/search           list threads
- POST /api/graph-studio/threads                  create a thread
- GET  /api/graph-studio/threads/{id}/state       checkpointed thread state
- GET  /api/graph-studio/threads/{id}/runs        run history
- POST /api/graph-studio/threads/{id}/runs/stream SSE run (messages/values/updates)

Threads and run history live in memory for the process lifetime; the compiled
graphs keep their own checkpointer (thread-scoped history) + store (memory).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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
    """Return the graph structure (nodes + edges) for the canvas."""
    compiled = _load_compiled(assistant_id)
    graph = compiled.get_graph()
    nodes = [{"id": nid, "data": {"name": nid}} for nid in graph.nodes]
    edges = [
        {
            "source": e.source,
            "target": e.target,
            "conditional": bool(getattr(e, "conditional", False)),
        }
        for e in graph.edges
    ]
    return {"nodes": nodes, "edges": edges}


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
# Threads (in-memory registry for the studio session)
# ---------------------------------------------------------------------------
_THREADS: Dict[str, Dict[str, Any]] = {}
_RUNS: Dict[str, List[Dict[str, Any]]] = {}


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
        if not m.get("content") and not m.get("tool_calls"):
            continue
        out.append({k: v for k, v in m.items() if not k.startswith("_")})
    return out


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

    partial_messages: Dict[str, Dict[str, Any]] = {}
    try:
        async for event in compiled.astream(
            payload.input, config=config, stream_mode=payload.stream_mode
        ):
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
    except Exception as exc:  # noqa: BLE001 - surface any graph error to the client
        run["status"] = "error"
        run["error"] = str(exc)
        record["status"] = "error"
        yield _sse("error", {"message": str(exc)})
    finally:
        run["updated_at"] = _now()


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
