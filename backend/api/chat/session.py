# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Chat session lifecycle endpoints.

Split out of api/chat/routes.py (session management sub-router). Routes are
registered on a prefix-less router that the parent (routes.py) includes under
the "/api/chat" prefix.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from db.database import get_db
from models.deep_agent import ChatSession, DeepAgentTemplate
from services.chat_session_manager import get_session_manager

from .schemas import ChatSessionResponse, StartChatRequest
from .shared import active_agents, get_cached_agent

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])


@router.post("/start", response_model=ChatSessionResponse)
async def start_chat_session(
    request: StartChatRequest,
    db: Session = Depends(get_db)
):
    """
    Start a new chat session with a DeepAgent.

    Creates a session record in PostgreSQL and assigns a unique thread_id
    for LangGraph checkpoint persistence.

    Returns:
        ChatSessionResponse with session details
    """
    try:
        # Get agent
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == request.agent_id
        ).first()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Create session ID
        session_id = str(uuid.uuid4())

        # Create session record
        session = ChatSession(
            session_id=session_id,
            agent_id=agent.id,
            user_id=request.user_id,
            project_id=request.project_id,  # vault scope for the agent workspace
            messages=[],
            metrics={
                "total_tokens": 0,
                "tool_calls": 0,
                "subagent_spawns": 0
            },
            tool_calls=[],
            subagent_spawns=[],
            context_operations=[],
            is_active=True
        )

        db.add(session)
        db.commit()
        db.refresh(session)

        logger.info(f"Started chat session {session_id} for agent {agent.name}")

        return ChatSessionResponse(
            session_id=session.session_id,
            agent_id=agent.id,
            agent_name=agent.name,
            project_id=session.project_id,
            is_active=session.is_active,
            message_count=len(session.messages or []),
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Error starting chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/end")
async def end_chat_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """End a chat session and cleanup resources."""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark as inactive
    session.is_active = False
    import datetime
    session.ended_at = datetime.datetime.utcnow()
    db.commit()

    # Cleanup agent instance from cache
    manager = get_session_manager()
    removed = manager.remove_session(session_id)

    # Also remove from legacy cache (plain and composite keys)
    legacy_keys = [
        key for key in active_agents
        if key == session_id or key.startswith(f"{session_id}:")
    ]
    for key in legacy_keys:
        del active_agents[key]

    # Cleanup LangGraph checkpoints for this thread
    cleanup_success = False
    try:
        from core.workflows.checkpointing.utils import delete_thread_checkpoints
        await delete_thread_checkpoints(thread_id=session_id)
        cleanup_success = True
        logger.info(f"Cleaned up checkpoints for session {session_id}")
    except Exception as e:
        logger.warning(f"Failed to cleanup checkpoints for session {session_id}: {e}")

    logger.info(
        f"Ended chat session {session_id} "
        f"(agent_removed={removed}, checkpoints_cleaned={cleanup_success})"
    )

    return {
        "status": "success",
        "message": "Session ended",
        "agent_removed": removed,
        "checkpoints_cleaned": cleanup_success
    }


@router.get("/sessions")
async def list_chat_sessions(
    agent_id: Optional[int] = None,
    active_only: bool = True,
    limit: int = 50,  # Default to 50 most recent conversations
    db: Session = Depends(get_db)
):
    """List all chat sessions, ordered by most recently updated first."""
    query = db.query(ChatSession).join(
        DeepAgentTemplate,
        ChatSession.agent_id == DeepAgentTemplate.id
    )

    if agent_id:
        query = query.filter(ChatSession.agent_id == agent_id)

    if active_only:
        query = query.filter(ChatSession.is_active == True)

    # Order by updated_at so most recently used conversations appear first
    sessions = query.order_by(ChatSession.updated_at.desc()).limit(limit).all()

    result = []
    for session in sessions:
        # Get agent safely (might have been deleted)
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == session.agent_id
        ).first()

        # Get last message preview
        last_message_preview = None
        if session.messages and len(session.messages) > 0:
            last_msg = session.messages[-1]
            content = last_msg.get("content", "")
            # Truncate to 60 chars for preview
            last_message_preview = content[:60] + "..." if len(content) > 60 else content

        result.append({
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_name": agent.name if agent else "Unknown Agent",
            "is_active": session.is_active,
            # BUG FIX: session.messages can be None for some sessions
            # (e.g. freshly created with no messages yet, or migrated from
            # a schema that didn't set the default). Use a safe accessor.
            "message_count": len(session.messages or []),
            "last_message_preview": last_message_preview,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat()
        })

    return result


@router.get("/health")
async def get_chat_health(db: Session = Depends(get_db)):
    """
    Get health status of the chat system.

    Returns session manager statistics and validates message consistency.
    """
    manager = get_session_manager()
    stats = manager.get_stats()

    # Validate message consistency
    active_sessions = db.query(ChatSession).filter(
        ChatSession.is_active == True
    ).all()

    inconsistencies = []
    for session in active_sessions:
        db_message_count = len(session.messages) if session.messages else 0

        # Check if session is cached
        cached_agent = manager.get_agent(session.session_id)
        is_cached = cached_agent is not None

        # Basic validation
        if db_message_count == 0 and is_cached:
            inconsistencies.append({
                "session_id": session.session_id,
                "issue": "Session has cached agent but no messages in database",
                "db_messages": db_message_count,
                "is_cached": is_cached
            })

    return {
        "status": "healthy" if len(inconsistencies) == 0 else "warning",
        "session_manager": stats,
        "active_db_sessions": len(active_sessions),
        "inconsistencies": inconsistencies,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/{session_id}/recover")
async def recover_messages_from_checkpoint(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Recover messages from LangGraph checkpointer.

    If messages were lost from the database but still exist in the
    LangGraph checkpoint storage, this endpoint can retrieve and restore them.
    """
    try:
        # Check if session exists
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Query checkpoint table for this thread_id
        from sqlalchemy import text
        checkpoint_query = text("""
            SELECT checkpoint_id, checkpoint, metadata, created_at
            FROM checkpoints
            WHERE thread_id = :thread_id
            ORDER BY created_at DESC
            LIMIT 1
        """)

        result = db.execute(checkpoint_query, {"thread_id": session_id})
        checkpoint_row = result.fetchone()

        if not checkpoint_row:
            return {
                "session_id": session_id,
                "recovered": False,
                "message": "No checkpoint data found for this session",
                "db_messages": len(session.messages) if session.messages else 0
            }

        # Decode checkpoint data (it's stored as binary/pickle)
        import pickle
        try:
            checkpoint_data = pickle.loads(checkpoint_row.checkpoint)

            # Extract messages from checkpoint
            recovered_messages = []
            if 'channel_values' in checkpoint_data and 'messages' in checkpoint_data['channel_values']:
                from langchain_core.messages import BaseMessage
                for msg in checkpoint_data['channel_values']['messages']:
                    if isinstance(msg, BaseMessage):
                        recovered_messages.append({
                            "role": "assistant" if msg.type == "ai" else "user" if msg.type == "human" else msg.type,
                            "content": msg.content,
                            "timestamp": getattr(msg, 'id', None) or datetime.utcnow().isoformat()
                        })

            # Compare with DB messages
            db_message_count = len(session.messages) if session.messages else 0
            checkpoint_message_count = len(recovered_messages)

            return {
                "session_id": session_id,
                "recovered": True,
                "db_messages": db_message_count,
                "checkpoint_messages": checkpoint_message_count,
                "missing_messages": checkpoint_message_count - db_message_count,
                "recovered_data": recovered_messages,
                "checkpoint_id": checkpoint_row.checkpoint_id,
                "created_at": checkpoint_row.created_at.isoformat() if checkpoint_row.created_at else None
            }

        except Exception as decode_error:
            logger.error(f"Failed to decode checkpoint data: {decode_error}")
            return {
                "session_id": session_id,
                "recovered": False,
                "message": f"Found checkpoint but failed to decode: {str(decode_error)}",
                "db_messages": len(session.messages) if session.messages else 0
            }

    except Exception as e:
        logger.error(f"Error recovering messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/recover/restore")
async def restore_messages_from_checkpoint(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Restore messages from LangGraph checkpointer to database.

    This will overwrite the current messages in the database with
    the messages from the checkpoint.
    """
    try:
        # First recover the messages
        recovery_data = await recover_messages_from_checkpoint(session_id, db)

        if not recovery_data.get("recovered"):
            raise HTTPException(status_code=404, detail=recovery_data.get("message", "No checkpoint data found"))

        # Get session
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Restore messages
        from sqlalchemy.orm.attributes import flag_modified
        session.messages = recovery_data["recovered_data"]
        flag_modified(session, "messages")
        db.commit()

        logger.info(f"✓ Restored {len(recovery_data['recovered_data'])} messages for session {session_id}")

        return {
            "session_id": session_id,
            "restored": True,
            "message_count": len(recovery_data["recovered_data"]),
            "messages": recovery_data["recovered_data"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/resume")
async def resume_chat(
    session_id: str,
    resume_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Resume a chat session after a Human-in-the-Loop interrupt.

    The agent was paused waiting for human input. This endpoint resumes it
    using LangGraph's Command(resume=...) mechanism.
    """
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check agent exists before entering try block. Use the same composite
    # cache key as the streaming path so resumed sessions find their agent.
    agent = db.query(DeepAgentTemplate).filter(
        DeepAgentTemplate.id == session.agent_id
    ).first()
    agent_version = None
    if agent and agent.updated_at:
        agent_version = str(int(agent.updated_at.timestamp()))
    agent_instance = get_cached_agent(
        session_id,
        agent_id=session.agent_id,
        agent_version=agent_version,
    )
    if not agent_instance:
        raise HTTPException(
            status_code=400,
            detail="Agent not found for this session. Start a new chat first."
        )

    try:
        from langgraph.types import Command

        # Use DeepAgentFactory's HumanInTheLoopMiddleware pattern (always).
        # DeepAgent handles resume via {"decisions": [...]} format.
        action = resume_data.get("action", "approve")
        if isinstance(action, str):
            decisions = [{"type": action}]
        elif isinstance(action, list):
            decisions = action
        else:
            decisions = [{"type": "approve"}]
        resume_value = {"decisions": decisions}
        result = await agent_instance.ainvoke(
            Command(resume=resume_value),
            config={"configurable": {"thread_id": session_id}}
        )

        response_text = ""
        if result and "messages" in result:
            # Find the last non-empty AIMessage content
            for msg in reversed(result["messages"]):
                if hasattr(msg, "content") and msg.content:
                    response_text = msg.content
                    break

        logger.info(f"Chat resumed for session {session_id}: {response_text[:100]}")

        # Save the response to the database
        if response_text:
            try:
                saved_session = db.query(ChatSession).filter(
                    ChatSession.session_id == session_id
                ).first()
                if saved_session:
                    saved_session.messages.append({
                        "role": "assistant",
                        "content": response_text
                    })
                    flag_modified(saved_session, "messages")
                    db.commit()
                    logger.info(f"Resume response saved to session {session_id}")
            except Exception as db_err:
                logger.warning(f"Failed to save resume response: {db_err}")
                db.rollback()

        return {
            "status": "resumed",
            "session_id": session_id,
            "content": response_text,
        }

    except Exception as e:
        logger.error(f"Failed to resume session {session_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resume session: {str(e)}"
        )
