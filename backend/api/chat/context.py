# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Chat context preview endpoint.

Split out of api/chat/routes.py. Registered on a prefix-less router included
by the parent (routes.py) under the "/api/chat" prefix.
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

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db

from .schemas import ContextPreviewResponse

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])


@router.get("/agents/{agent_template_id}/context-preview")
async def preview_context(
    agent_template_id: int,
    query: str,
    context_mode: str = "smart",
    window_size: int = 20,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Preview what context would be injected for a given query.

    This helps users understand what conversation history will be loaded
    when they run a workflow with this agent.
    """
    try:
        from backend.services.conversation_context import ConversationContextService
        from sqlalchemy.ext.asyncio import AsyncSession

        # Convert to async session
        async_db = AsyncSession(bind=db.get_bind())
        context_service = ConversationContextService(async_db)

        # Get context
        messages = await context_service.get_context_for_agent(
            agent_template_id=agent_template_id,
            current_query=query,
            context_mode=context_mode,
            window_size=window_size,
            banked_message_ids=[],
            project_id=project_id
        )

        # Convert messages to dict format for response
        message_dicts = []
        for msg in messages:
            message_dicts.append({
                "role": "user" if msg.__class__.__name__ == "HumanMessage" else "assistant",
                "content": msg.content,
                "type": msg.__class__.__name__
            })

        # Estimate token count (rough estimate: ~4 chars per token)
        total_text = "".join(msg["content"] for msg in message_dicts)
        estimated_tokens = len(total_text) // 4

        # Breakdown by source (simplified for now)
        breakdown = {
            "total": len(message_dicts),
            "banked": 0,  # Would be counted if we tracked sources
            "recent": min(len(message_dicts), window_size),
            "semantic": max(0, len(message_dicts) - window_size)
        }

        return ContextPreviewResponse(
            messages=message_dicts,
            total_count=len(message_dicts),
            token_count=estimated_tokens,
            strategy_used=context_mode,
            breakdown=breakdown
        )

    except Exception as e:
        logger.error(f"Failed to preview context: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to preview context: {str(e)}")
