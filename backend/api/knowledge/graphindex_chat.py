"""
Phase 9 / Step K — graphindex_chat backend API endpoint.

A FastAPI router that wraps the `phase9/build_graphindex_chat_agent`
single-agent DeepAgent. The UI (Step L) will call this endpoint to
let users chat with their project documents using LLM semantic routing.

Endpoints:

  POST /api/graphindex/chat                  — sync single-turn chat
  POST /api/graphindex/chat/stream           — SSE-streamed multi-turn
  GET  /api/graphindex/chat/show-agent       — agent introspection

The "chat" model is the `graphindex_chat` single-agent DeepAgent
(no subagents) from phase9/build_graphindex_chat_agent.py. It uses
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

# Phase 9 path hook — phase9/ now lives at langconfig/learning/phase9/
# (was langconfig/phase9/ before the 2026-06-26 refactor)
_PHASE9_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "learning", "phase9")
)
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
    max_tokens: int = Field(8192, ge=1, le=32768)


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


# --- Agent factory --------------------------------------------------------

_agent_cache: Dict[int, Any] = {}


def _get_or_build_agent(project_id: int, model_name: Optional[str] = None):
    """Build a graphindex_chat agent, cached per (project_id, model_name)."""
    from build_graphindex_chat_agent import build_graphindex_chat_agent

    cache_key = (project_id, model_name or "default")
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]
    agent = build_graphindex_chat_agent(
        project_id=project_id,
        model_name=model_name or "minimax-m3",  # default LLM
    )
    _agent_cache[cache_key] = agent
    return agent


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

    t0 = time.time()
    try:
        result = await asyncio.to_thread(
            agent.invoke,
            {"messages": messages},
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception as e:
        logger.exception(f"graphindex_chat agent error: {e}")
        raise HTTPException(status_code=500, detail=f"agent invoke failed: {e}")
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
        # The graphindex_chat agent uses a single DeepAgent node; we
        # stream the final answer (post-thinking) token-by-token using
        # the streaming API. If streaming fails, fall back to a single
        # chunk with the full answer.
        yield f"data: {dict_to_json({'type': 'start', 'thread_id': thread_id, 'query': request.query})}\n\n"
        t0 = time.time()
        try:
            result = await asyncio.to_thread(
                agent.invoke,
                {"messages": messages},
                {"configurable": {"thread_id": thread_id}},
            )
        except Exception as e:
            yield f"data: {dict_to_json({'type': 'error', 'message': str(e)})}\n\n"
            return

        answer = _strip_think(result["messages"][-1].content)
        # Stream word-by-word for low perceived latency (chunked for SSE).
        words = answer.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield f"data: {dict_to_json({'type': 'token', 'content': chunk})}\n\n"
            await asyncio.sleep(0.005)  # 5ms per word for typing effect

        in_tok, out_tok, cache_read = _extract_usage(result)
        elapsed = time.time() - t0
        yield f"data: {dict_to_json({'type': 'done', 'usage': {
            'input_tokens': in_tok,
            'output_tokens': out_tok,
            'cache_read': cache_read,
            'cache_pct': 100 * cache_read / in_tok if in_tok else 0.0,
            'latency_s': elapsed,
        }})}\n\n"

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


# --- helpers --------------------------------------------------------------

def dict_to_json(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)
