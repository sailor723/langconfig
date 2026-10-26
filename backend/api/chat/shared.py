# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Helpers shared by the chat sub-router modules.

Moved out of api/chat/routes.py so the session and messages sub-routers can
share the same agent cache without a circular dependency on the parent module.
"""
import logging
from typing import Any, Dict, Optional

from services.chat_session_manager import get_session_manager

logger = logging.getLogger(__name__)

# Legacy: Will be removed after migration to session manager
active_agents: Dict[str, Any] = {}


def get_cached_agent(session_id: str, agent_id: Optional[int] = None, agent_version: Optional[str] = None) -> Optional[Any]:
    """Get cached agent instance using session manager.

    If agent_id and agent_version are provided, they're included in the cache key
    so that updates to the agent's config invalidate the cache.
    """
    manager = get_session_manager()
    agent = manager.get_agent(session_id, agent_id, agent_version)
    if agent:
        return agent
    # Fallback to legacy cache (uses composite key when agent_id+version provided)
    if agent_id is not None:
        legacy_key = f"{session_id}:{agent_id}"
        if agent_version is not None:
            legacy_key = f"{legacy_key}:{agent_version}"
    else:
        legacy_key = session_id
    return active_agents.get(legacy_key)


def cache_agent(session_id: str, agent_instance: Any, agent_id: Optional[int] = None, agent_version: Optional[str] = None):
    """Cache agent instance using session manager.

    If agent_id and agent_version are provided, they're included in the cache key
    so that updates to the agent's config invalidate the cache.
    """
    manager = get_session_manager()
    manager.cache_agent(session_id, agent_instance, agent_id, agent_version)
    # Also update legacy cache for compatibility (with same composite key)
    if agent_id is not None:
        legacy_key = f"{session_id}:{agent_id}"
        if agent_version is not None:
            legacy_key = f"{legacy_key}:{agent_version}"
    else:
        legacy_key = session_id
    active_agents[legacy_key] = agent_instance

def load_session_for_caller(db, session_id: str):
    """The conversation, or 404.

    Answering 404 rather than 403 for someone else's conversation is deliberate: 403
    would confirm that the id exists, and these ids are handed around (URLs, copied
    chat links, logs). A miss and a denial must look the same.

    Used by every route that resolves a session from the URL. Centralised because a
    per-endpoint check is exactly the thing that gets forgotten in the next endpoint
    someone adds.
    """
    from fastapi import HTTPException
    from models.deep_agent import ChatSession
    from services import workspace_scope

    session = (
        db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    )
    if session is None or not workspace_scope.same_owner(session, db, column="user_id"):
        raise HTTPException(status_code=404, detail="Session not found")
    return session
