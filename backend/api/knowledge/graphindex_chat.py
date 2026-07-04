"""
Phase 9 / Step K — graphindex_chat backend API endpoint.

A FastAPI router that wraps the `phase9/graphindex_chat_agent`
single-agent DeepAgent. The UI (Step L) will call this endpoint to
let users chat with their project documents using LLM semantic routing.

Endpoints:

  POST /api/graphindex/chat                  — sync single-turn chat
  POST /api/graphindex/chat/stream           — SSE-streamed multi-turn
  GET  /api/graphindex/chat/show-agent       — agent introspection

The "chat" model is the `graphindex_chat` single-agent DeepAgent
(no subagents) from phase9/graphindex_chat_agent.py. It uses
the same 4 graphindex @tool wrappers as the existing
/api/rag/graphindex/answer endpoint but adds:

  - Multi-turn continuity (MemorySaver checkpointer keyed by thread_id)
  - Multi-doc loading (1 primary + 0-3 supporting from cross-domain)
  - Per-project scoping (project_id baked into system prompt)
  - Per-request model selection (model_name from request body)
  - Streaming response (SSE for low perceived latency)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

# Phase 9 path hook — add the repo root to sys.path so that
#   from learning.phase9.graphindex.agent import build_agent
# resolves correctly (was learning/phase9/ alone before the refactor).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path and os.path.isdir(_REPO_ROOT):
    sys.path.insert(0, _REPO_ROOT)
# Also keep phase9/ on the path for backward compat with any scripts
# that still do `from graphindex_chat_agent import ...`.
_PHASE9_DIR = os.path.join(_REPO_ROOT, "learning", "phase9")
if _PHASE9_DIR not in sys.path and os.path.isdir(_PHASE9_DIR):
    sys.path.insert(0, _PHASE9_DIR)

from fastapi import APIRouter, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

# Logger
import logging  # noqa: E402
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graphindex", tags=["graphindex-chat"])


# --- Pydantic schemas -----------------------------------------------------

class GraphIndexChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class GraphIndexChatRequest(BaseModel):
    query: str = Field(..., description="User's question")
    project_id: int = Field(1, description="Project to scope doc reads to")
    thread_id: Optional[str] = Field(
        None, description="Multi-turn thread id (defaults to 'graphindex-chat-{project_id}')"
    )
    history: List[GraphIndexChatMessage] = Field(
        default_factory=list, description="Prior turns in the conversation (optional)"
    )
    model: Optional[str] = Field(
        None, description="Override LLM (defaults to deepseek-chat per step 4)"
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(1_000_000, ge=1, le=1_000_000)
    scope: Optional[List[str]] = Field(
        None,
        description=(
            "Optional doc filter. None / 'all' / [] → search all docs. "
            "[doc1, doc2, ...] → only consider / read these docs (by exact name)."
        ),
    )


class GraphIndexChatUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_pct: float = 0.0
    latency_s: float = 0.0


class GraphIndexChatResponse(BaseModel):
    query: str
    answer: str
    project_id: int
    thread_id: str
    model: str
    usage: GraphIndexChatUsage
    agent: str = "graphindex_chat"
    clarification: Optional[dict] = Field(
        None,
        description=(
            "Set when the agent didn't actually answer — e.g. the user's scope "
            "didn't match any documents. The UI should show the message and let "
            "the user retry with a different scope (e.g. 'all docs')."
        ),
    )


class Neo4jDocumentItem(BaseModel):
    """A single document as it appears in the Neo4j graphindex catalog.
    Mirrors the structure the UI uses for the left sidebar so it can
    merge with /api/rag/documents (Postgres context_documents)."""
    name: str
    file_path: Optional[str] = None
    about: Optional[str] = None
    has_enrichment: bool = False
    chunk_count: Optional[int] = None
    page_count: Optional[int] = None
    context_doc_id: Optional[int] = None
    doc_index_id: Optional[str] = None
    project_id: int


class Neo4jDocumentsResponse(BaseModel):
    project_id: int
    total: int
    documents: List[Neo4jDocumentItem]


# --- Agent factory --------------------------------------------------------

_agent_cache: Dict[int, Any] = {}


def _get_or_build_agent(project_id: int, model_name: Optional[str] = None):
    """Build a graphindex_chat agent, cached per (project_id, model_name)."""
    from learning.phase9.graphindex.agent import build_agent

    cache_key = (project_id, model_name or "default")
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]
    agent = build_agent(project_id=project_id)
    _agent_cache[cache_key] = agent
    return agent


def _set_scope(scope):
    """Set the active doc scope via ContextVar. Returns a token for reset."""
    from learning.phase9.graphindex.tools import set_active_doc_scope
    return set_active_doc_scope(scope)


def _reset_scope(token) -> None:
    """Reset the active doc scope via ContextVar."""
    from learning.phase9.graphindex.tools import reset_active_doc_scope
    reset_active_doc_scope(token)


def _resolve_scope(project_id: int, scope):
    """Resolve the user's scope against the project's catalog.

    Returns a dict:
        {
            "valid":    [names in scope that match a doc in the project],
            "invalid":  [names in scope that don't match any doc],
            "all_doc_names":  [all doc names in the project, sorted]
        }

    Special cases:
        - scope is None / "all" / []  → returns {"valid": None, "invalid": [], "all_doc_names": [...]}
          (None for `valid` means "no filter" — not "all valid")
        - scope has only invalid items  → all_doc_names is populated so the caller
          can build a "did you mean..." message
        - scope has some valid + some invalid  → caller can choose to warn or silently drop

    Lazy imports to keep startup fast (this is only called when scope is set).
    """
    # Normalize: None / "all" / [] = no filter
    if scope is None or scope == "all" or (isinstance(scope, (list, tuple)) and len(scope) == 0):
        # Still fetch all doc names for the "available docs" suggestion
        from learning.phase9.graphindex.index_build import Neo4jDocumentIndex
        from learning.phase9.graphindex.route import fetch_catalog
        try:
            idx = Neo4jDocumentIndex(
                base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
                username=os.environ.get("NEO4J_USER", "neo4j"),
                password=os.environ.get("NEO4J_PASSWORD", "password"),
            )
            idx.ensure_constraints()
            rows = fetch_catalog(idx, project_id)
            all_names = sorted({r["name"] for r in rows})
        except Exception:
            all_names = []
        return {"valid": None, "invalid": [], "all_doc_names": all_names}

    # Scope is a real list — resolve it against the catalog
    from learning.phase9.graphindex.build_index import Neo4jDocumentIndex
    from learning.phase9.graphindex.route import fetch_catalog
    try:
        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        rows = fetch_catalog(idx, project_id)
        all_names_set = {r["name"] for r in rows}
        all_names = sorted(all_names_set)
    except Exception:
        # If Neo4j is down, treat as no resolution possible
        return {"valid": [], "invalid": list(scope), "all_doc_names": []}

    valid = [n for n in scope if n in all_names_set]
    invalid = [n for n in scope if n not in all_names_set]
    return {"valid": valid, "invalid": invalid, "all_doc_names": all_names}


def _strip_think(text: str) -> str:
    if "<think>" in text and "</think>" in text:
        return text.split("</think>", 1)[1].strip()
    return text


def _extract_usage(result) -> tuple[int, int, int]:
    msgs = result.get("messages", [])
    last = msgs[-1] if msgs else None
    if last is None:
        return 0, 0, 0
    usage = getattr(last, "usage_metadata", None) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return in_tok, out_tok, cache_read


# --- Endpoints ------------------------------------------------------------

@router.post("/chat", response_model=GraphIndexChatResponse)
async def graphindex_chat(request: GraphIndexChatRequest) -> GraphIndexChatResponse:
    """Single-turn chat with the graphindex_chat agent.

    For multi-turn, the client must echo back the `thread_id` from this
    response and include the prior assistant message in `history` (the
    MemorySaver checkpointer also keeps the state server-side, so a
    simple `thread_id` round-trip is enough — but passing `history`
    helps if the server restarts between turns).
    """
    try:
        agent = _get_or_build_agent(request.project_id, request.model)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"agent init failed: {e}")

    thread_id = request.thread_id or f"graphindex-chat-{request.project_id}"

    # Build messages: history first, then current user query
    messages: List[Dict[str, str]] = []
    for m in request.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": request.query})

    # Validate the scope BEFORE running the agent. If the user passed
    # a scope that matches no documents, return a clarification response
    # asking if they want to search all docs instead.
    t0 = time.time()
    resolution = _resolve_scope(request.project_id, request.scope)
    if request.scope and resolution["valid"] is not None and len(resolution["valid"]) == 0:
        elapsed = time.time() - t0
        message = (
            f"Your scope didn't match any documents in this project. "
            f"Would you like to search all {len(resolution['all_doc_names'])} documents instead?"
        )
        return GraphIndexChatResponse(
            query=request.query,
            project_id=request.project_id,
            thread_id=thread_id,
            model=request.model or "minimax-m3",
            answer=message,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read": 0,
                "cache_pct": 0.0,
                "latency_s": elapsed,
                "clarification": True,
            },
            clarification={
                "code": "scope_not_found",
                "scope_received": list(request.scope),
                "scope_invalid": resolution["invalid"],
                "available_docs": resolution["all_doc_names"][:20],
                "available_count": len(resolution["all_doc_names"]),
                "suggestion": "Remove the scope to search all documents.",
            },
        )

    # Set the active doc scope for this request. The agent's tools will
    # only see / read docs whose name is in `scope` (if provided).
    scope_token = _set_scope(request.scope)
    try:
        result = await asyncio.to_thread(
            agent.invoke,
            {"messages": messages},
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception as e:
        logger.exception(f"graphindex_chat agent error: {e}")
        raise HTTPException(status_code=500, detail=f"agent invoke failed: {e}")
    finally:
        # Always restore the previous scope, even if the agent raised.
        _reset_scope(scope_token)
    elapsed = time.time() - t0

    answer = _strip_think(result["messages"][-1].content)
    in_tok, out_tok, cache_read = _extract_usage(result)
    cache_pct = 100 * cache_read / in_tok if in_tok else 0.0

    return GraphIndexChatResponse(
        query=request.query,
        answer=answer,
        project_id=request.project_id,
        thread_id=thread_id,
        model=request.model or "minimax-m3",
        usage=GraphIndexChatUsage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read=cache_read,
            cache_pct=cache_pct,
            latency_s=elapsed,
        ),
    )


@router.post("/chat/stream")
async def graphindex_chat_stream(request: GraphIndexChatRequest):
    """Server-sent events streaming of the chat response.

    Yields SSE events of the form:
      data: {"type": "start"}
      data: {"type": "token", "content": "..."}
      data: {"type": "done", "usage": {...}}
      data: {"type": "error", "message": "..."}
    """
    try:
        agent = _get_or_build_agent(request.project_id, request.model)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"agent init failed: {e}")

    thread_id = request.thread_id or f"graphindex-chat-{request.project_id}"
    messages: List[Dict[str, str]] = []
    for m in request.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": request.query})

    async def event_generator() -> AsyncGenerator[str, None]:
        # The graphindex_chat agent uses a single DeepAgent node. We use
        # `agent.stream(..., stream_mode="values")` (NOT `agent.invoke()`)
        # so we can emit SSE events for each tool call — that way the
        # client can see what the agent is doing step by step.
        yield f"data: {dict_to_json({'type': 'start', 'thread_id': thread_id, 'query': request.query})}\n\n"
        t0 = time.time()

        # Validate the scope BEFORE running the agent. If the user passed
        # a scope that matches no documents, return a clarification event
        # asking if they want to search all docs instead.
        resolution = _resolve_scope(request.project_id, request.scope)
        if request.scope and resolution["valid"] is not None and len(resolution["valid"]) == 0:
            # All scope items are invalid — emit clarification, skip agent
            clarification_payload = {
                "type": "clarification",
                "code": "scope_not_found",
                "message": (
                    f"Your scope didn't match any documents in this project. "
                    f"Would you like to search all {len(resolution['all_doc_names'])} documents instead?"
                ),
                "scope_received": list(request.scope),
                "scope_invalid": resolution["invalid"],
                "available_docs": resolution["all_doc_names"][:20],  # cap the list
                "available_count": len(resolution["all_doc_names"]),
                "suggestion": "Remove the scope to search all documents.",
            }
            yield f"data: {dict_to_json(clarification_payload)}\n\n"
            # Also emit a token event with the message so the UI's chat
            # bubble shows it as if the LLM said it.
            yield f"data: {dict_to_json({'type': 'token', 'content': clarification_payload['message']})}\n\n"
            elapsed = time.time() - t0
            done_payload = {
                "type": "done",
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read": 0,
                    "cache_pct": 0.0,
                    "latency_s": elapsed,
                    "tool_calls": 0,
                    "clarification": True,
                },
            }
            yield f"data: {dict_to_json(done_payload)}\n\n"
            return

        # Set the active doc scope for this request. The agent's tools
        # will only see / read docs whose name is in `scope` (if provided).
        scope_token = _set_scope(request.scope)

        # Track what we've already emitted so we don't repeat events
        # (stream_mode="values" emits the full state on each step).
        emitted_tool_call_ids: set = set()
        emitted_message_indices: set = set()
        result = None
        try:
            # Run the agent ONCE via stream(); capture the final state.
            # (Earlier code re-ran via agent.invoke() to get the result —
            # that doubled the wall clock for no benefit. We now use the
            # last event's `messages` as the final state.)
            last_event = None
            prev_msg_count = 0
            for event in agent.stream(
                {"messages": messages},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="values",
            ):
                last_event = event
                msgs = event.get("messages", [])
                # Emit any new tool calls (assistant messages with tool_calls)
                for i, m in enumerate(msgs):
                    if i in emitted_message_indices:
                        continue
                    emitted_message_indices.add(i)
                    # AIMessage with tool_calls
                    tool_calls = getattr(m, "tool_calls", None) or []
                    for tc in tool_calls:
                        tc_id = tc.get("id") or f"{tc.get('name')}-{i}"
                        if tc_id in emitted_tool_call_ids:
                            continue
                        emitted_tool_call_ids.add(tc_id)
                        yield f"data: {dict_to_json({'type': 'tool_start', 'name': tc.get('name'), 'args': tc.get('args', {}), 'id': tc_id})}\n\n"
                    # ToolMessage (the result of a tool call)
                    if getattr(m, "type", "") == "tool":
                        yield f"data: {dict_to_json({'type': 'tool_end', 'name': getattr(m, 'name', ''), 'id': getattr(m, 'tool_call_id', '')})}\n\n"
                prev_msg_count = len(msgs)

            # Use the final event's `messages` as the result
            if last_event is not None:
                result = {"messages": last_event.get("messages", [])}
        except Exception as e:
            yield f"data: {dict_to_json({'type': 'error', 'message': str(e)})}\n\n"
            return
        finally:
            # Always restore the previous scope, even if the agent raised.
            _reset_scope(scope_token)

        answer = _strip_think(result["messages"][-1].content)
        # Stream word-by-word for low perceived latency (chunked for SSE).
        words = answer.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield f"data: {dict_to_json({'type': 'token', 'content': chunk})}\n\n"
            await asyncio.sleep(0.005)  # 5ms per word for typing effect

        in_tok, out_tok, cache_read = _extract_usage(result)
        elapsed = time.time() - t0
        # Build the done event payload as a dict, then serialize.
        # (Avoids a multi-line f-string with nested dict braces.)
        done_payload = {
            "type": "done",
            "usage": {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cache_read": cache_read,
                "cache_pct": 100 * cache_read / in_tok if in_tok else 0.0,
                "latency_s": elapsed,
                "tool_calls": len(emitted_tool_call_ids),
            },
        }
        yield f"data: {dict_to_json(done_payload)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )


@router.get("/chat/show-agent")
async def show_graphindex_chat_agent(project_id: int = 1):
    """Introspect the graphindex_chat agent (tool inventory, model, etc.)."""
    try:
        agent = _get_or_build_agent(project_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"agent init failed: {e}")

    return {
        "agent": "graphindex_chat",
        "project_id": project_id,
        "model": "minimax-m3",
        "subagents": 0,
        "tools": [
            "list_docs_tool",
            "fetch_catalog_tool",
            "read_doc_tool",
            "load_multi_doc_tool",
        ],
        "checkpointer": "MemorySaver",
    }


@router.get("/neo4j-documents", response_model=Neo4jDocumentsResponse)
async def list_neo4j_documents(project_id: int = 1):
    """List documents from the Neo4j graphindex catalog for a project.

    This is the **chat's view** of the project's docs — what
    `graphindex_chat` actually sees when it routes a query. It
    complements the Postgres `context_documents` table that the UI's
    left sidebar normally shows.

    Why we need this: docs can exist in Neo4j without a matching
    `context_documents` row (e.g. if the file was indexed via a
    different path, or the Postgres row was deleted). The chat can
    find them, but the UI's sidebar doesn't. To keep the chat and
    the sidebar in sync, the UI merges this list with its Postgres
    list (Neo4j wins on the `name` field — same identity as chat).

    Each item returns:
      - name: the doc's name (matches what the chat passes to its tools)
      - file_path: where the file lives on disk (for the viewer)
      - about: 1-2 sentence summary (for tooltips)
      - indexed_at: when the LLM enrichment was last updated
      - has_enrichment: True if `what_this_document_is_about` is non-empty
      - chunk_count: number of chunks in pgvector (if any)
      - page_count: number of pages in the source doc (PDF only)
    """
    try:
        # Add the phase9/ dir to sys.path so we can import the helpers
        import sys
        from pathlib import Path
        _REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
        _PHASE9_DIR = _REPO_ROOT / "learning" / "phase9"
        if str(_PHASE9_DIR) not in sys.path:
            sys.path.insert(0, str(_PHASE9_DIR))
        import importlib.util
        # Neo4jDocumentIndex lives in services/ — already on path
        from services.neo4j_document_index import Neo4jDocumentIndex

        idx = Neo4jDocumentIndex()
        # Use the existing HTTP-based list_documents API. Returns
        # full Neo4jDocumentRecord objects with all metadata fields
        # (name, file_path, about, page_count, context_doc_id, etc.)
        rows = idx.list_documents(project_id)
        items = []
        for r in rows:
            about = r.what_this_document_is_about or ""
            items.append(Neo4jDocumentItem(
                name=r.name,
                file_path=r.file_path,
                about=about,
                has_enrichment=len(about) > 10,
                chunk_count=None,  # chunks live in pgvector, not Neo4j
                page_count=int(r.page_count) if r.page_count is not None else None,
                context_doc_id=int(r.context_doc_id) if r.context_doc_id is not None else None,
                doc_index_id=r.doc_index_id,
                project_id=project_id,
            ))
        return Neo4jDocumentsResponse(
            project_id=project_id,
            total=len(items),
            documents=items,
        )
    except Exception as e:
        logger.exception(f"list_neo4j_documents failed: {e}")
        raise HTTPException(status_code=500, detail=f"neo4j list failed: {e}")


@router.get("/file")
async def serve_neo4j_file(project_id: int, name: str):
    """Stream a project's document file by name (Neo4j lookup).

    This is the file-by-name equivalent of
    `GET /api/rag/documents/{id}/file` — used by the UI's
    DocumentViewer when the user clicks a doc that exists in
    Neo4j but isn't in the Postgres context_documents table
    (so the `id`-based endpoint would 404).

    Returns the file with the appropriate Content-Type for the
    extension, similar to the id-based endpoint.
    """
    import mimetypes
    from fastapi.responses import FileResponse
    try:
        from services.neo4j_document_index import Neo4jDocumentIndex
        idx = Neo4jDocumentIndex()
        doc = idx.get_document(project_id, name)
        if not doc:
            raise HTTPException(status_code=404, detail=f"doc not found: {name}")
        if not doc.file_path:
            raise HTTPException(status_code=404, detail=f"doc has no file_path: {name}")
        fp = doc.file_path
        if not Path(fp).exists():
            raise HTTPException(status_code=404, detail=f"file missing on disk: {fp}")
        mime, _ = mimetypes.guess_type(fp)
        return FileResponse(
            path=fp,
            media_type=mime or "application/octet-stream",
            filename=name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"serve_neo4j_file failed: {e}")
        raise HTTPException(status_code=500, detail=f"file serve failed: {e}")


@router.get("/content")
async def serve_neo4j_content(project_id: int, name: str, max_chars: int = 100_000):
    """Return the text content of a project document by name.

    Mirrors `GET /api/rag/documents/{id}/content` but takes
    project_id + name so it works for Neo4j-only docs that
    have no Postgres `context_documents` row.

    Uses phase9's `_read_doc_text` to extract text (PDF via
    PyMuPDF, MD/TXT directly), capped at `max_chars` (default
    100K) so the response stays small.
    """
    try:
        import sys
        from pathlib import Path
        _REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
        _PHASE9_DIR = _REPO_ROOT / "learning" / "phase9"
        if str(_PHASE9_DIR) not in sys.path:
            sys.path.insert(0, str(_PHASE9_DIR))
        import importlib.util
        from services.neo4j_document_index import Neo4jDocumentIndex

        idx = Neo4jDocumentIndex()
        doc = idx.get_document(project_id, name)
        if not doc:
            raise HTTPException(status_code=404, detail=f"doc not found: {name}")
        if not doc.file_path or not Path(doc.file_path).exists():
            raise HTTPException(status_code=404, detail=f"file missing on disk: {doc.file_path}")

        # Load from phase9/graphindex/index_build.py
        from learning.phase9.graphindex.index_build import load_document_content
        text = load_document_content(str(doc.file_path), max_chars=max_chars)

        return {
            "doc_id": 0,  # no Postgres id
            "doc_name": name,
            "content": text,
            "char_count": len(text),
            "source": "neo4j",
            "file_path": doc.file_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"serve_neo4j_content failed: {e}")
        raise HTTPException(status_code=500, detail=f"content serve failed: {e}")


# --- helpers --------------------------------------------------------------

def dict_to_json(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)
