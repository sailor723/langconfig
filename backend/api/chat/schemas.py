# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Pydantic schemas for the chat API.

Moved out of api/chat/routes.py so the sub-router modules (session, messages,
context, documents) can import their models without a circular dependency on
the parent module. Re-exported by routes.py to keep
`from api.chat.routes import <Model>` working for existing callers.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StartChatRequest(BaseModel):
    """Request to start a new chat session."""
    agent_id: int
    user_id: Optional[int] = None


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # 'user' or 'assistant'
    content: str


class SendMessageRequest(BaseModel):
    """Request to send a message in a chat session."""
    session_id: str
    message: str
    project_id: Optional[int] = Field(
        None,
        description=(
            "The project this chat session is bound to. The Phase 9 chat "
            "agent queries this project's Neo4j catalog. When omitted, the "
            "backend falls back to the agent template's project_id, then "
            "to 1 (system project) — which usually causes the agent to "
            "see an empty catalog. KB chat panels (DocChatPanel) should "
            "always set this to the active project so the chat uses the "
            "right docs."
        ),
    )
    scope: Optional[List[str]] = Field(
        None,
        description=(
            "Optional doc scope. None / 'all' / [] → agent considers all docs. "
            "[doc1, doc2, ...] → only these docs (by exact name). "
            "When set, the chat agent is given a `scope` field that the "
            "graphindex_chat tools will enforce (out-of-scope reads return "
            "SCOPE_ERROR; in-scope docs are the only ones visible)."
        ),
    )


class ChatResponse(BaseModel):
    """Response from the agent."""
    session_id: str
    message: str
    tool_calls: List[Dict[str, Any]] = []
    subagent_activity: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}


class ChatSessionResponse(BaseModel):
    """Response with chat session details."""
    session_id: str
    agent_id: int
    agent_name: str
    is_active: bool
    message_count: int
    created_at: str
    updated_at: str


class ChatHistoryResponse(BaseModel):
    """Response with chat history."""
    session_id: str
    messages: List[ChatMessage]
    metrics: Dict[str, Any]


class ContextPreviewResponse(BaseModel):
    messages: List[Dict[str, Any]]
    total_count: int
    token_count: int
    strategy_used: str
    breakdown: Dict[str, int]  # banked, recent, semantic counts


class SessionDocumentResponse(BaseModel):
    """Response model for session document"""
    id: int
    session_id: str
    filename: str
    original_filename: str
    file_size: int
    mime_type: Optional[str]
    document_type: str
    indexing_status: str
    uploaded_at: datetime
    message_index: Optional[int]
    indexed_chunks_count: Optional[int]

    class Config:
        from_attributes = True
