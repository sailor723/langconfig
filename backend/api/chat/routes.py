# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Chat API - DeepAgent Testing Interface

This module provides a complete chat interface for testing DeepAgents before export.

## Architecture

The chat system uses **dual storage** for conversation history:

1. **PostgreSQL JSON Column** (`chat_sessions.messages`)
   - Used for: UI display, conversation context service, session list
   - Format: `[{role, content, timestamp, banked}, ...]`
   - Must use `flag_modified()` when updating

2. **LangGraph Checkpointer** (PostgreSQL checkpoint tables)
   - Used for: Agent runtime memory, automatic compaction
   - Format: Binary-encoded LangChain BaseMessage objects
   - Automatic persistence via thread_id

## Session Lifecycle

1. **Start Session** - User opens chat → Create session, assign thread_id
2. **Active Chat** - Messages flow through both storage systems
3. **Auto-Cleanup** - Session manager removes stale sessions (1 hour TTL)
4. **End Session** - User explicitly ends → Remove from cache, cleanup checkpoints

## Memory Management

- **Agent Caching**: Session manager caches agent instances for performance
- **TTL Cleanup**: Background task removes inactive sessions every 5 minutes
- **Checkpoint Cleanup**: Deletes LangGraph state when session ends
- **Token Limits**: Guardrails config controls automatic summarization/eviction

## Health Monitoring

GET /api/chat/health - Returns session manager stats and validates consistency

## Key Features

- Token-by-token streaming (astream_events)
- Message banking (mark important messages)
- Conversation context for workflows
- Human-in-the-loop (HITL) support
- Automatic resource cleanup
"""

import logging
import sys as _sys
import os as _os
# Phase 9 integration: ensure learning/ is on sys.path so that
# ``from learning.phase9.graphindex...`` imports resolve correctly
# for downstream modules.
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in _sys.path and _os.path.isdir(_REPO_ROOT):
    _sys.path.insert(0, _REPO_ROOT)

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Pydantic schemas live in schemas.py (extracted so the sub-router modules can
# import them without a circular dependency on this module). Re-exported here
# so `from api.chat.routes import <Model>` keeps working for callers that
# referenced the models on this module.
from .schemas import (
    ChatHistoryResponse,
    ChatMessage,
    ChatResponse,
    ChatSessionResponse,
    ContextPreviewResponse,
    SendMessageRequest,
    SessionDocumentResponse,
    StartChatRequest,
)


# ── Sub-routers (split from this god-module) ──
from .session import router as _session_router
from .messages import router as _messages_router
from .context import router as _context_router
from .documents import router as _documents_router

router.include_router(_session_router)
router.include_router(_messages_router)
router.include_router(_context_router)
router.include_router(_documents_router)


def __getattr__(name: str):
    """Lazily re-export sub-module symbols.

    tests/test_chat_generated_files.py imports `list_session_generated_files`
    and scripts/test_graphindex_native_tools.py imports `_extract_file_text`
    from this module.
    """
    if name == "list_session_generated_files":
        from .documents import list_session_generated_files
        return list_session_generated_files
    if name == "_extract_file_text":
        from .documents import _extract_file_text
        return _extract_file_text
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
