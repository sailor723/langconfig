# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Chat message endpoints (sync + streaming), history/metrics and banking.

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

import json
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphInterrupt
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from core.workflows.events.emitter import ExecutionEventCallbackHandler
from db.database import AsyncSessionLocal, get_db
from models.deep_agent import ChatSession, DeepAgentConfig, DeepAgentTemplate, SessionDocument
from models.core import IndexingStatus
from services.conversation_context import ConversationContextService
from services.deepagent_factory import DeepAgentFactory

# Phase 9 / graphindex — stateful streaming filter that strips
# `<think>...</think>` and `<tool_call>...</tool_call>` XML emitted
# by Minimax M3 as raw text in model content. 22/22 tests pass.
from think_filter import ThinkFilter as StreamingFilter

from .schemas import (
    ChatHistoryResponse,
    ChatMessage,
    ChatResponse,
    SendMessageRequest,
)
from .session import resume_chat
from .shared import cache_agent, get_cached_agent

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])


def _default_agent_docs(agent, workspace_root: str) -> dict:
    """Sensible default AGENTS.md / CLAUDE.md for agents that have no
    user-authored docs in PostgreSQL.

    Every agent workspace should carry these files: MemoryMiddleware loads
    AGENTS.md into the system prompt and the Files panel lists them next to
    uploads + generated files. The defaults are stored back to the DB row so
    the Docs tab in the editor shows the same content (editable).
    """
    name = getattr(agent, "name", None) or f"Agent {getattr(agent, 'id', '')}".strip()
    description = getattr(agent, "description", None) or "An AI agent."
    agents_md = (
        f"# {name}\n\n"
        f"{description}\n\n"
        f"## Workspace\n\n"
        f"Your workspace directory is:\n\n"
        f"    {workspace_root}\n\n"
        f"- **Generated files** — save every deliverable you produce (reports, "
        f"documents, exports) into the `generated/` subfolder, e.g. via "
        f"`save_document` or file-writing tools, so the user can find them in "
        f"the Files panel.\n"
        f"- **Uploaded files** — documents the user uploads appear in the "
        f"`knowledge-base/` subfolder; read them from there when a task needs "
        f"their data.\n"
        f"- **Your instructions** — AGENTS.md (this file) and CLAUDE.md sit at "
        f"the workspace root.\n"
        f"- Keep all files inside the workspace — do not write outside it.\n\n"
        f"## Working conventions\n\n"
        f"- Before generating a file, match the format the user asked for "
        f"(Markdown, DOCX, CSV, HTML, …) and save it with a descriptive "
        f"filename inside `generated/`.\n"
        f"- After producing a deliverable, summarize what you created and "
        f"where it was saved.\n"
        f"- If a task needs data from uploaded files, read them from "
        f"`knowledge-base/` first.\n\n"
        f"## Agent docs\n\n"
        f"- This file (AGENTS.md) is loaded into your context as instructions "
        f"on every chat run.\n"
        f"- CLAUDE.md (next to this file) mirrors these instructions.\n"
    )
    claude_md = (
        f"# {name} — CLAUDE.md\n\n"
        f"Mirror of AGENTS.md — see that file in the same folder for the "
        f"agent's full operating instructions.\n\n"
        f"## Quick reference\n\n"
        f"- Workspace: `{workspace_root}`\n"
        f"- Save generated deliverables into `generated/`; user uploads appear "
        f"in `knowledge-base/`.\n"
        f"- After producing a deliverable, summarize what you created and "
        f"where it was saved.\n"
    )
    return {"AGENTS.md": agents_md, "CLAUDE.md": claude_md}


def _materialize_agent_docs(agent, workspace_root: str, db=None) -> None:
    """Write the agent's instruction docs (AGENTS.md / CLAUDE.md / …) into
    its workspace.

    ``deep_agent_templates.agent_docs`` (PostgreSQL) is the source of truth;
    the files are materialized here so MemoryMiddleware can read AGENTS.md and
    the Files panel shows the docs alongside uploads + generated files.

    Agents without authored docs get sensible defaults materialized, and (when
    a DB session is available) those defaults are stored back onto the row so
    the editor's Docs tab stays consistent.
    """
    if not workspace_root:
        return
    docs = getattr(agent, "agent_docs", None) or {}
    if not docs:
        docs = _default_agent_docs(agent, workspace_root)
        if db is not None:
            # Seed the defaults back onto the row (best-effort — a chat run
            # must never fail because persisting defaults failed).
            try:
                agent.agent_docs = docs
                db.commit()
                logger.info(
                    f"Seeded default agent docs for agent "
                    f"{getattr(agent, 'id', '?')}: {list(docs.keys())}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to persist default agent docs "
                    f"(agent {getattr(agent, 'id', '?')}): {e}"
                )
    from pathlib import Path
    root = Path(workspace_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        for name, content in docs.items():
            if not name or not isinstance(content, str):
                continue
            # basename only — keep the docs inside the workspace root
            safe_name = Path(name).name
            target = (root / safe_name).resolve()
            if not target.is_relative_to(root.resolve()):
                logger.warning(f"Skipping agent doc with unsafe name: {name!r}")
                continue
            target.write_text(content, encoding="utf-8")
        logger.info(f"Materialized {len(docs)} agent doc(s) into {root}")
    except Exception as e:
        logger.warning(f"Failed to materialize agent docs into {workspace_root}: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

def make_json_safe(obj):
    """
    Recursively convert objects to JSON-safe format.
    Filters out non-serializable items like LangGraph Command objects.
    """
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items() if not k.startswith('_')}
    elif isinstance(obj, (list, tuple)):
        return [make_json_safe(item) for item in obj]
    else:
        # Skip non-serializable objects like Command
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return None


class StreamingFilter:
    """Stateful filter to strip <think>...</think> and <tool_call>...</tool_call> tags
    and their contents from a stream of tokens.
    Also captures stripped think content for frontend streaming."""
    def __init__(self):
        self.buffer = ""
        self.in_think = False
        self.in_tool = False
        self.think_buffer = ""  # Captures stripped think content for streaming

    def feed(self, token: str) -> str:
        self.buffer += token
        output = ""
        
        while True:
            if not self.in_think and not self.in_tool:
                think_idx = self.buffer.find("<think>")
                tool_idx = self.buffer.find("<tool_call>")
                
                if think_idx != -1 and (tool_idx == -1 or think_idx < tool_idx):
                    output += self.buffer[:think_idx]
                    self.buffer = self.buffer[think_idx + len("<think>"):]
                    self.in_think = True
                    self.think_buffer = ""  # Reset think buffer on enter
                    continue
                elif tool_idx != -1 and (think_idx == -1 or tool_idx < think_idx):
                    output += self.buffer[:tool_idx]
                    self.buffer = self.buffer[tool_idx + len("<tool_call>"):]
                    self.in_tool = True
                    continue
                
                last_angle = self.buffer.rfind("<")
                if last_angle != -1:
                    suffix = self.buffer[last_angle:]
                    if "<think>".startswith(suffix) or "<tool_call>".startswith(suffix):
                        output += self.buffer[:last_angle]
                        self.buffer = suffix
                        break
                
                output += self.buffer
                self.buffer = ""
                break
            
            elif self.in_think:
                end_idx = self.buffer.find("</think>")
                if end_idx != -1:
                    self.think_buffer += self.buffer[:end_idx]
                    self.buffer = self.buffer[end_idx + len("</think>"):]
                    self.in_think = False
                    continue
                
                last_angle = self.buffer.rfind("<")
                if last_angle != -1:
                    suffix = self.buffer[last_angle:]
                    if "</think>".startswith(suffix):
                        self.think_buffer += self.buffer[:last_angle]
                        self.buffer = suffix
                        break
                
                self.think_buffer += self.buffer
                self.buffer = ""
                break
                
            elif self.in_tool:
                end_idx = self.buffer.find("</tool_call>")
                if end_idx != -1:
                    self.buffer = self.buffer[end_idx + len("</tool_call>"):]
                    self.in_tool = False
                    continue
                
                last_angle = self.buffer.rfind("<")
                if last_angle != -1:
                    suffix = self.buffer[last_angle:]
                    if "</tool_call>".startswith(suffix):
                        self.buffer = suffix
                        break
                
                self.buffer = ""
                break
                
        return output

    def finalize(self) -> str:
        if not self.in_think and not self.in_tool:
            res = self.buffer
            self.buffer = ""
            return res
        return ""


# =============================================================================
# Message Endpoints (Synchronous & Streaming)
# =============================================================================


@router.post("/message", response_model=ChatResponse)
async def send_message(
    request: SendMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Send a message and receive a complete response (non-streaming).

    Storage Flow:
    1. Append user message to session.messages (PostgreSQL JSON)
    2. Invoke agent with thread_id (LangGraph loads previous messages from checkpointer)
    3. Append assistant response to session.messages
    4. Both storages are updated atomically

    Returns:
        ChatResponse with full message content
    """
    try:
        # Get session
        session = db.query(ChatSession).filter(
            ChatSession.session_id == request.session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.is_active:
            raise HTTPException(status_code=400, detail="Session is not active")

        # Get agent
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == session.agent_id
        ).first()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Add user message to history
        from datetime import datetime
        from sqlalchemy.orm.attributes import flag_modified
        user_message_timestamp = datetime.utcnow().isoformat()
        user_message_index = len(session.messages or [])
        session.messages.append({
            "role": "user",
            "content": request.message,
            "timestamp": user_message_timestamp,
            "banked": False
        })
        flag_modified(session, "messages")

        # Get or create agent instance. Key by agent id + updated_at so edits
        # invalidate the cache consistently across all chat entry points.
        agent_version = None
        if agent.updated_at:
            agent_version = str(int(agent.updated_at.timestamp()))
        agent_instance = get_cached_agent(
            request.session_id,
            agent_id=agent.id,
            agent_version=agent_version,
        )

        if not agent_instance:
            # ── Language preference from DB settings ──
            lang_instruction = ""
            try:
                from models.settings import Settings as SettingsModel
                settings_row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
                if settings_row and settings_row.language and settings_row.language not in ("en", "en-US", "en-GB"):
                    LANG_NAMES = {"zh": "Chinese", "ja": "Japanese", "ko": "Korean",
                                  "ru": "Russian", "ar": "Arabic", "th": "Thai",
                                  "hi": "Hindi", "he": "Hebrew", "el": "Greek",
                                  "es": "Spanish", "fr": "French", "de": "German",
                                  "pt": "Portuguese", "it": "Italian", "nl": "Dutch",
                                  "zh-CN": "Chinese", "zh-TW": "Chinese (Traditional)"}
                    lang_name = LANG_NAMES.get(settings_row.language, settings_row.language)
                    lang_instruction = f"\n\n**Language**: Respond in {lang_name}."
            except Exception:
                pass  # fallback to no language instruction

            # Create agent instance via the appropriate factory.
            # Regular agents (use_deepagents=False) use AgentFactory with _create_task_tool pattern.
            # Deep agents use DeepAgentFactory with SubAgentMiddleware.
            # Fix: ensure list fields are never None to avoid "NoneType has no len()"
            _safe_config = dict(agent.config or {})
            for _list_key in ['middleware', 'subagents', 'skills', 'native_tools']:
                if _safe_config.get(_list_key) is None:
                    _safe_config[_list_key] = []
            if _safe_config.get('guardrails') is None:
                _safe_config['guardrails'] = {"input": [], "output": []}
            config = DeepAgentConfig(**_safe_config)
            if lang_instruction:
                config.system_prompt = (config.system_prompt or "") + lang_instruction

            use_deepagents = _safe_config.get("use_deepagents", True)
            # Per-agent chat workspace, anchored to the active vault (project):
            # all of this agent's files (uploads + generated output) live under
            # the resolved root (user-defined workspace_path → vault-scoped
            # outputs/projects/{id}/agents/agent_{id}/ → legacy default).
            from services.workspace_manager import get_workspace_manager
            _session_project_id = getattr(session, "project_id", None)
            _ws_mgr = get_workspace_manager()
            agent_workspace_root = str(_ws_mgr.resolve_agent_workspace(
                agent, _session_project_id,
                vault_key=_ws_mgr.project_vault_key(db, _session_project_id) or None,
                agent_key=_ws_mgr.agent_vault_key(db, agent),
            ))
            # Materialize the agent's instruction docs (AGENTS.md / CLAUDE.md…)
            # into the workspace so MemoryMiddleware + the Files panel see them.
            # Agents without authored docs get defaults seeded + materialized.
            _materialize_agent_docs(agent, agent_workspace_root, db=db)
            if not use_deepagents:
                from core.agents.factory import AgentFactory
                agent_instance, _tools, _callbacks = await AgentFactory.create_agent(
                    agent_config=_safe_config,
                    project_id=_session_project_id or 0,
                    task_id=0,
                    context="",
                    mcp_manager=None,
                    vector_store=None,
                    agent_context={"agent_id": agent.id},
                    workspace_root=agent_workspace_root,
                    agent_id=agent.id,
                )
            else:
                agent_instance, _tools, _callbacks = await DeepAgentFactory.create_deep_agent(
                    config=config,
                    project_id=_session_project_id or 0,
                    task_id=0,
                    context="",
                    mcp_manager=None,
                    vector_store=None,
                    user_message=request.message,
                    workspace_root=agent_workspace_root,
                    agent_id=agent.id,
                )
            cache_agent(
                request.session_id,
                agent_instance,
                agent_id=agent.id,
                agent_version=agent_version,
            )

        # Create new user message (checkpointer will load previous messages automatically)
        from langchain_core.messages import HumanMessage
        new_message = HumanMessage(content=request.message)

        # Invoke agent with thread_id for conversation persistence
        # The checkpointer automatically loads and saves conversation history
        result = await agent_instance.ainvoke(
            {"messages": [new_message]},
            config={"configurable": {"thread_id": session.session_id}}
        )

        # Extract response — iterate backwards for the last non-empty text.
        # When the agent uses task() to delegate, the final AIMessage may have
        # empty content (tool_calls only). We need the ToolMessage result or
        # the agent's follow-up response instead.
        response_text = ""
        if hasattr(result, "messages") and result.messages:
            for msg in reversed(result.messages):
                c = getattr(msg, "content", "")
                if c and isinstance(c, str) and c.strip():
                    response_text = c
                    break
                # Handle list content blocks
                if isinstance(c, list):
                    flat = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in c
                    )
                    if flat.strip():
                        response_text = flat
                        break
        elif isinstance(result, dict) and "messages" in result:
            for msg in reversed(result["messages"]):
                c = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                if c and isinstance(c, str) and c.strip():
                    response_text = c
                    break
                if isinstance(c, list):
                    flat = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in c
                    )
                    if flat.strip():
                        response_text = flat
                        break
        else:
            response_text = str(result)

        if not isinstance(response_text, str):
            response_text = str(response_text)

        # Add assistant message to history
        assistant_message_timestamp = datetime.utcnow().isoformat()
        assistant_message_index = len(session.messages or [])
        session.messages.append({
            "role": "assistant",
            "content": response_text,
            "timestamp": assistant_message_timestamp,
            "banked": False
        })
        flag_modified(session, "messages")

        # Update metrics
        session.metrics["total_tokens"] = session.metrics.get("total_tokens", 0) + len(request.message) + len(response_text)
        flag_modified(session, "metrics")

        # Extract tool calls from agent result messages
        tool_calls = []
        subagent_activity = []

        if isinstance(result, dict) and "messages" in result:
            for msg in result["messages"]:
                # AI messages with tool calls
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        # Detect skill name from read_file path or task subagent_type
                        skill_name = None
                        args = tc.get("args", {})
                        tool_name = tc.get("name", "unknown")
                        file_path = args.get("file_path", "") or str(args.get("path", ""))
                        if "/skills/" in str(file_path):
                            parts = file_path.split("/skills/")[1].split("/")
                            if parts:
                                skill_name = parts[0]
                        elif tool_name == "task":
                            # task() tool passes subagent name in args (subagent approach)
                            skill_name = args.get("subagent_type") or args.get("name") or None
                        tool_calls.append({
                            "tool_name": tc.get("name", "unknown"),
                            "skill_name": skill_name,
                            "arguments": args,
                            "result": "",
                            "timestamp": datetime.utcnow().isoformat(),
                            "status": "completed",
                        })
                # Tool result messages — attach to last tool call without a result
                if hasattr(msg, "type") and getattr(msg, "type", None) == "tool":
                    content = msg.content
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    for tc in reversed(tool_calls):
                        if not tc["result"]:
                            tc["result"] = str(content)[:500]
                            break

        # Save session — persist tool call names so MetricsPanel shows them
        if tool_calls:
            session.tool_calls = (session.tool_calls or []) + tool_calls
            flag_modified(session, "tool_calls")
        db.commit()
        db.refresh(session)

        # ──────────────────────────────────────────────
        # 1. Archive conversation turn (auto-save every turn)
        # 2. Extract user metadata (LLM, only when new info detected)
        # ──────────────────────────────────────────────
        try:
            from models.conversation_archive import ConversationArchive
            from models.user_profile import UserProfile

            # 1. Archive the turn
            import re
            turn_matches = re.findall(r'role["\']:\s*["\']user["\']', json.dumps(session.messages))
            turn_number = len(turn_matches)

            archive_record = ConversationArchive(
                session_id=session.session_id,
                user_id=session.user_id,
                turn_number=turn_number,
                user_message=request.message,
                agent_response=response_text,
                tool_calls=tool_calls or [],
            )
            db.add(archive_record)
            db.commit()

            # 2. Extract user metadata (LLM-based, uses DeepSeek internally)
            try:
                from core.chat.metadata_extractor import extract_metadata_from_message

                metadata = await extract_metadata_from_message(
                    request.message
                )
                if metadata and metadata.has_new_info:
                    existing = db.query(UserProfile).filter_by(
                        user_id=session.user_id
                    ).first()
                    if existing:
                        if metadata.name:
                            existing.name = metadata.name
                        if metadata.preferences:
                            all_prefs = list(set(
                                (existing.preferences or []) + metadata.preferences
                            ))
                            existing.preferences = all_prefs
                        existing.updated_at = datetime.utcnow()
                    else:
                        profile = UserProfile(
                            user_id=session.user_id,
                            name=metadata.name,
                            preferences=metadata.preferences or [],
                            metadata_snapshot=metadata.model_dump(),
                        )
                        db.add(profile)
                    db.commit()
                    logger.info(
                        f"Extracted user metadata: name={metadata.name}, "
                        f"preferences={metadata.preferences}"
                    )
            except Exception as meta_err:
                logger.warning(f"Metadata extraction failed (non-blocking): {meta_err}")

        except Exception as archive_err:
            logger.warning(f"Conversation archive failed (non-blocking): {archive_err}")

        # Store messages in vector store for semantic search (if project_id available)
        # Note: Chat sessions currently don't have project association, but we'll add it later
        project_id_for_vectorstore = (
            getattr(session, 'project_id', None)
            or (agent.project_id if hasattr(agent, 'project_id') else None)
        )
        if project_id_for_vectorstore:
            try:
                from backend.services.conversation_context import ConversationContextService
                # Use the async engine session factory — binding AsyncSession
                # to the sync engine would fail at first use and silently
                # disable vector-store persistence.
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as async_db:
                    context_service = ConversationContextService(async_db)

                    # Store user message
                    await context_service.store_message_in_vector_store(
                        session_id=session.session_id,
                        agent_template_id=session.agent_id,
                        message_index=user_message_index,
                        role="user",
                        content=request.message,
                        timestamp=user_message_timestamp,
                        project_id=project_id_for_vectorstore
                    )

                    # Store assistant message
                    await context_service.store_message_in_vector_store(
                        session_id=session.session_id,
                        agent_template_id=session.agent_id,
                        message_index=assistant_message_index,
                        role="assistant",
                        content=response_text,
                        timestamp=assistant_message_timestamp,
                        project_id=project_id_for_vectorstore
                    )
            except Exception as e:
                # Don't fail the whole request if vector storage fails
                print(f"Failed to store messages in vector store: {e}")

        logger.info(f"Processed message in session {request.session_id}")

        return ChatResponse(
            session_id=session.session_id,
            message=response_text,
            tool_calls=tool_calls,
            subagent_activity=subagent_activity,
            metrics=session.metrics
        )

    except Exception as e:
        import traceback
        logger.error(f"Error sending message: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


async def _aiter_sync(gen):
    """Wrap a sync generator as an async generator. Each iteration
    yields the next value with a tiny sleep to let the event loop
    breathe (so a long-running sync generator doesn't block other
    asyncio tasks)."""
    import asyncio
    for item in gen:
        await asyncio.sleep(0)  # yield to event loop
        yield item


# NOTE: `_generate_stream_phase9` was a planned refactor that was
# superseded by the inline Phase 9 path inside `send_message_stream`
# (which uses `astream_events` + the `StreamingFilter` defined above).
# The chat model is now wrapped with `ThinkStrippingChatModel` at build
# time (see `learning/phase9/graphindex_chat_agent.py`), so the think
# XML is stripped at the model boundary and the inline stream only
# ever sees clean content. This stub is kept for reference but is
# not called by the route.


@router.post("/message/stream")
async def send_message_stream(
    request: SendMessageRequest,
    db: Session = Depends(get_db)
):
    """Send a message and stream the response."""
    # ============================================================
    # DEBUG: log every chat request so the user can see the
    # session_id / project_id / message in the backend stdout.
    # The session_id is what threads the conversation through
    # MemorySaver; if the frontend sends a new session_id per
    # turn, the agent has no memory of the previous turn and
    # repeats the same BYD/Tesla answer.
    # ============================================================
    logger.info(
        f"[CHAT-IN] session_id={request.session_id} "
        f"project_id={request.project_id} "
        f"scope={request.scope} "
        f"msg={request.message!r}"
    )
    try:
        # Get session
        session = db.query(ChatSession).filter(
            ChatSession.session_id == request.session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.is_active:
            raise HTTPException(status_code=400, detail="Session is not active")

        # Get agent
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == session.agent_id
        ).first()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Store session_id and agent config before entering generator
        # to avoid detached session issues
        session_id = session.session_id
        # Resolve the doc scope from the request. None / "all" / [] = no filter.
        # We treat any of these as None (no filter) to keep the tool layer simple.
        scope = request.scope
        if scope is not None and (
            scope == "all" or (isinstance(scope, (list, tuple)) and len(scope) == 0)
        ):
            scope = None
        # Set the doc scope on the native tools so graphindex_search / list / load
        # filter to only the user-selected docs (deterministic, not LLM-dependent).
        from tools.native_tools import set_graphindex_doc_scope
        pid = request.project_id
        set_graphindex_doc_scope(scope, pid)
        agent_config = agent.config.copy() if agent.config else {}
        # Merge guardrails_config separately — it's a separate DB column
        if agent.guardrails_config:
            agent_config["guardrails"] = agent.guardrails_config.copy()
        agent_project_id = getattr(agent, 'project_id', None)

        async def generate_stream():
            """Generate streaming response."""
            full_response = ""
            all_context = ""
            rag_tokens_used = 0
            stream_filter = StreamingFilter()

            # Dedicated async session for the stream: keeps blocking DB work
            # off the event loop so one slow chat never stalls the whole API.
            async_db = AsyncSessionLocal()

            try:
                # Re-query session inside generator to avoid detached object issues
                from sqlalchemy.orm.attributes import flag_modified
                fresh_session = (await async_db.execute(
                    select(ChatSession).where(ChatSession.session_id == session_id)
                )).scalar_one_or_none()

                if not fresh_session:
                    logger.error(f"Session {session_id} not found in generator")
                    await async_db.close()
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
                    return

                logger.info(f"Before adding user message: total_messages={len(fresh_session.messages)}")
                fresh_session.messages.append({
                    "role": "user",
                    "content": request.message
                })
                flag_modified(fresh_session, "messages")
                await async_db.commit()  # Commit user message immediately
                await async_db.refresh(fresh_session)  # Refresh to confirm save
                logger.info(f"✓ User message saved to DB: session={session_id}, total_messages={len(fresh_session.messages)}")

                # Build agent via DeepAgentFactory (standard path)
                # Use the UI's active project if the agent doesn't have one
                project_id = agent_project_id or request.project_id
                all_context = ""

                # Check the compiled-agent cache first. Follow-up turns skip the
                # RAG/context work that only feeds compilation, making them as
                # close to a bare CLI agent.invoke() as possible.
                agent_version = None
                if agent.updated_at:
                    agent_version = str(int(agent.updated_at.timestamp()))
                agent_instance = get_cached_agent(
                    request.session_id,
                    agent_id=agent.id,
                    agent_version=agent_version,
                )

                if project_id and not agent_instance:
                    from services.context_retrieval import context_retriever
                    from services.token_counter import get_token_counter
                    token_counter = get_token_counter()

                    try:
                        project_context_package = await context_retriever.retrieve_context(
                            project_id=project_id,
                            task_description=request.message,
                            similarity_top_k=3,
                            use_hyde=False
                        )
                        project_chunks = project_context_package.get('components', {}).get('code_chunks', [])
                        project_context = "\n\n".join([chunk.get('content', '') for chunk in project_chunks])
                    except Exception as e:
                        logger.warning(f"Failed to retrieve project context: {e}")
                        project_context = ""

                    session_context = ""
                    session_docs = (await async_db.execute(
                        select(SessionDocument).where(
                            SessionDocument.session_id == request.session_id,
                            SessionDocument.indexing_status == IndexingStatus.READY,
                        )
                    )).scalars().all()

                    if session_docs:
                        try:
                            logger.info(f"Found {len(session_docs)} indexed session documents")
                            session_context_package = await context_retriever.retrieve_context(
                                project_id=project_id,
                                task_description=request.message,
                                similarity_top_k=2,
                                session_id=request.session_id,
                                use_hyde=False
                            )
                            session_chunks = session_context_package.get('components', {}).get('code_chunks', [])
                            session_context = "\n\n".join([chunk.get('content', '') for chunk in session_chunks])
                        except Exception as e:
                            logger.warning(f"Failed to retrieve session context: {e}")
                            session_context = ""

                    if project_context and session_context:
                        all_context += f"# Project Documents:\n{project_context}\n\n# Session Documents:\n{session_context}"
                    elif project_context:
                        all_context += f"# Project Documents:\n{project_context}"
                    elif session_context:
                        all_context += f"# Session Documents:\n{session_context}"

                    if all_context:
                        rag_tokens_used = token_counter.count_tokens(all_context)
                        logger.info(f"Retrieved RAG context: {rag_tokens_used} tokens")
                    # Inject companion .skill.md content if available.
                    if session_docs:
                        try:
                            _ws_mgr = get_workspace_manager()
                            _sandbox_dir = _ws_mgr.base_dir / "default"
                            for _doc in session_docs:
                                if _doc.filename.lower().endswith('.csv'):
                                    _stem = _doc.filename.rsplit('.', 1)[0]
                                    _skill_path = _sandbox_dir / f"{_stem}.skill.md"
                                    if _skill_path.exists():
                                        _text = _skill_path.read_text(encoding='utf-8')
                                        if _text.strip():
                                            all_context += (
                                                f"\n## User Data Context -- {_doc.filename}\n\n"
                                                f"The user has provided a data context / "
                                                f"interpretation guide. Use it to understand "
                                                f"column semantics, business logic, and "
                                                f"common queries:\n\n{_text}"
                                            )
                                            logger.info(
                                                f"Injected companion .skill.md for CSV: {_doc.filename}"
                                            )
                        except Exception as e:
                            logger.warning(f"Failed to inject companion .skill.md: {e}")

                if not agent_instance:
                    # Create agent via appropriate factory.
                    # Regular agents (use_deepagents=False) → AgentFactory with _create_task_tool
                    # Deep agents → DeepAgentFactory with SubAgentMiddleware
                    from services.workspace_manager import get_workspace_manager
                    _session_project_id = getattr(session, "project_id", None) or project_id
                    _ws_mgr = get_workspace_manager()
                    agent_workspace_root = str(_ws_mgr.resolve_agent_workspace(
                        agent, _session_project_id,
                        vault_key=_ws_mgr.project_vault_key(db, _session_project_id) or None,
                        agent_key=_ws_mgr.agent_vault_key(db, agent),
                    ))
                    _materialize_agent_docs(agent, agent_workspace_root, db=db)
                    use_deepagents = agent_config.get("use_deepagents", True)
                    if not use_deepagents:
                        from core.agents.factory import AgentFactory
                        agent_instance, tools, callbacks = await AgentFactory.create_agent(
                            agent_config=agent_config,
                            project_id=_session_project_id or 0,
                            task_id=0,
                            context=all_context,
                            mcp_manager=None,
                            vector_store=None,
                            agent_context={"agent_id": agent.id},
                            workspace_root=agent_workspace_root,
                            agent_id=agent.id,
                        )
                    else:
                        config = DeepAgentConfig(**agent_config)
                        agent_instance, tools, callbacks = await DeepAgentFactory.create_deep_agent(
                            config=config,
                            project_id=_session_project_id or 0,
                            task_id=0,
                            context=all_context,
                            mcp_manager=None,
                            vector_store=None,
                            user_message=request.message,
                            workspace_root=agent_workspace_root,
                            agent_id=agent.id,
                        )
                    cache_agent(
                        request.session_id,
                        agent_instance,
                        agent_id=agent.id,
                        agent_version=agent_version,
                    )

                # Fallback: if no project_id or agent couldn't be built, use graphindex agent
                if agent_instance is None:
                    try:
                        from learning.phase9.graphindex.agent import build_agent as _build_graphindex_agent
                        agent_instance = _build_graphindex_agent(project_id=project_id or 1)
                        logger.info(f"Fallback: built graphindex agent for session={session_id}")
                    except Exception as e:
                        logger.error(f"Fallback agent build failed: {e}")
                        await async_db.close()
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Failed to build agent'})}\n\n"
                        return

                # Create event handler for tracking tool calls and subagent activity
                event_handler = ExecutionEventCallbackHandler(
                    project_id=project_id or 0,
                    task_id=0,
                    workflow_id=None,  # No workflow for chat sessions
                    enable_sanitization=True,
                    save_to_db=False  # Don't persist to DB for chat sessions
                )

                # Inject file content into the message so agent sees it
                # (text is extracted during upload and stored in session.messages,
                # but LangGraph checkpointer has its own history — the agent won't
                # see the content otherwise)
                file_context = ""
                for msg in fresh_session.messages:
                    content = msg.get("content", "")
                    if msg.get("role") == "assistant" and "Content: \"" in content:
                        file_context += "\n\n" + content
                if file_context:
                    augmented_content = f"{file_context}\n\nUser question: {request.message}"
                else:
                    augmented_content = request.message

                # Create new user message (checkpointer loads previous messages)
                from langchain_core.messages import HumanMessage
                new_message = HumanMessage(content=augmented_content)

                # Use astream_events for token-by-token streaming
                tool_calls_count = 0
                collected_tool_names = []  # Track tool names for DB persistence and skill detection
                async for event in agent_instance.astream_events(
                    {"messages": [new_message]},
                    config={
                        "configurable": {"thread_id": session_id},
                        "callbacks": [event_handler],
                        "recursion_limit": 500  # Increased from default 25 for complex tool chains
                    },
                    version="v2"
                ):
                    kind = event.get("event")
                    if kind == "on_tool_start":
                        tool_calls_count += 1
                        tool_data = event.get("data", {})
                        # Tool name is in event["name"] for astream_events v2
                        tool_name = event.get("name", "unknown")
                        # Detect skill name from read_file path or task subagent_type
                        skill_name = None
                        tool_input = tool_data.get("input", {})
                        if isinstance(tool_input, dict):
                            file_path = tool_input.get("file_path", "") or str(tool_input.get("path", ""))
                            if tool_name == "task":
                                skill_name = tool_input.get("subagent_type") or tool_input.get("name") or None
                        else:
                            file_path = str(tool_input) if tool_input else ""
                        if "/skills/" in file_path:
                            parts = file_path.split("/skills/")[1].split("/")
                            if parts:
                                skill_name = parts[0]
                        # Track tool name for persistence
                        collected_tool_names.append({
                            "tool_name": tool_name,
                            "skill_name": skill_name,
                            "arguments": make_json_safe(tool_data.get("input", {})),
                            "result": "",
                            "timestamp": datetime.utcnow().isoformat(),
                            "status": "running",
                        })
                        # Filter out non-serializable objects
                        safe_data = make_json_safe(tool_data)
                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name, 'skill_name': skill_name, 'data': safe_data})}\n\n"

                    elif kind == "on_tool_end":
                        tool_data = event.get("data", {})
                        tool_name = event.get("name", "unknown")
                        # Update the running tool call with result
                        for tc in reversed(collected_tool_names):
                            if tc["tool_name"] == tool_name and tc["status"] == "running":
                                output = tool_data.get("output", "")
                                if isinstance(output, str):
                                    tc["result"] = output[:500]
                                elif isinstance(output, dict):
                                    tc["result"] = json.dumps(output)[:500]
                                tc["status"] = "completed"
                                break
                        # Filter out non-serializable objects
                        safe_data = make_json_safe(tool_data)
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': tool_name, 'data': safe_data})}\n\n"

                    # Stream custom events (LangGraph-style progress bars, status badges, etc.)
                    elif kind == "on_custom_event" or (kind == "custom_event"):
                        custom_data = event.get("data", {})
                        safe_data = make_json_safe(custom_data)
                        yield f"data: {json.dumps({'type': 'custom_event', 'data': safe_data})}\n\n"

                    # Stream LLM tokens as they're generated
                    elif kind == "on_chat_model_stream":
                        chunk_content = event.get("data", {}).get("chunk")
                        if chunk_content and hasattr(chunk_content, "content"):
                            token = chunk_content.content

                            # Ensure token is a string (handle cases where content might be a list of blocks)
                            if isinstance(token, list):
                                # Skip empty lists
                                if not token:
                                    continue
                                # Extract text from content blocks: [{'text': '...', 'type': 'text'}, ...]
                                parts = [
                                    block.get("text", "") if isinstance(block, dict) else str(block)
                                    for block in token
                                ]
                                # Join parts directly - streaming sends complete tokens
                                token = "".join(parts)
                            elif token is None:
                                continue
                            elif not isinstance(token, str):
                                token = str(token)

                            if token:
                                # Apply StreamingFilter to strip <think> and <tool_call> tags and their contents
                                # The filter captures stripped think content in think_buffer
                                filtered_token = stream_filter.feed(token)
                                
                                # Emit think content that was captured since last feed
                                think_content = stream_filter.think_buffer
                                if think_content and not stream_filter.in_think:
                                    # Think block just closed — emit all captured content
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': think_content})}\n\n"
                                    stream_filter.think_buffer = ""  # Reset after emit
                                
                                if filtered_token:
                                    full_response += filtered_token
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': filtered_token})}\n\n"

                    # Stream interrupt events (Human-in-the-Loop)
                    elif kind == "__interrupt__":
                        interrupt_data = event.get("data", {})
                        safe_data = make_json_safe(interrupt_data)
                        logger.info(f"Agent interrupted for session {session_id}: {str(safe_data)[:300]}")
                        payload = json.dumps({
                            'type': 'interrupt',
                            'session_id': session_id,
                            'data': safe_data,
                        })
                        yield f"data: {payload}\n\n"

                # After stream completes, check for pending interrupts
                interrupted = False
                try:
                    state_snapshot = await agent_instance.aget_state(
                        {"configurable": {"thread_id": session_id}}
                    )
                    if state_snapshot and hasattr(state_snapshot, 'interrupts') and state_snapshot.interrupts:
                        # Deep agent interrupts (GraphInterrupt/HumanInTheLoopMiddleware)
                        interrupt_data = state_snapshot.interrupts[0]
                        if hasattr(interrupt_data, 'value'):
                            safe_data = make_json_safe(interrupt_data.value)
                        else:
                            safe_data = make_json_safe(str(interrupt_data))
                        logger.info(f"Agent interrupted (post-stream check) for session {session_id}: {str(safe_data)[:300]}")
                        payload = json.dumps({
                            'type': 'interrupt',
                            'session_id': session_id,
                            'data': safe_data,
                        })
                        yield f"data: {payload}\n\n"
                        interrupted = True
                    elif state_snapshot and hasattr(state_snapshot, 'next') and state_snapshot.next:
                        # Normal agent interrupts (interrupt_before=["tools"])
                        # state.next contains the nodes execution is paused before, e.g. ("tools",)
                        # Extract tool_calls from the last AIMessage for interrupt data
                        next_nodes = list(state_snapshot.next)
                        logger.info(f"Agent paused before nodes: {next_nodes} for session {session_id}")
                        messages = state_snapshot.values.get("messages", [])
                        tool_calls_data = []
                        for msg in reversed(messages):
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                tool_calls_data = [
                                    {"name": tc["name"], "args": tc["args"], "id": tc.get("id", "")}
                                    for tc in msg.tool_calls
                                ]
                                break
                        safe_data = make_json_safe({
                            "next_nodes": next_nodes,
                            "tool_calls": tool_calls_data,
                        })
                        safe_data_for_interrupt = {'type': 'interrupt', 'session_id': session_id, 'data': safe_data}
                        yield f"data: {json.dumps(safe_data_for_interrupt)}\n\n"
                        interrupted = True
                except Exception as e:
                    logger.debug(f"No interrupt state available: {e}")

                # Finalize filter
                final_prose = stream_filter.finalize()
                if final_prose:
                    full_response += final_prose
                    yield f"data: {json.dumps({'type': 'chunk', 'content': final_prose})}\n\n"

                # Send completion event (skip if interrupted)
                if not interrupted:
                    yield f"data: {json.dumps({'type': 'complete', 'content': full_response})}\n\n"
                else:
                    full_response = ""  # Clear response — interrupt means no completion happened

            except GraphInterrupt as e:
                # Agent was paused for Human-in-the-Loop input
                interrupt_data = None
                if e.args and isinstance(e.args[0], tuple) and len(e.args[0]) > 0:
                    first = e.args[0][0]
                    interrupt_data = first.value if hasattr(first, 'value') else str(first)
                safe_data = make_json_safe(interrupt_data) if interrupt_data else {}
                logger.info(f"Agent interrupted for session {session_id}: {str(safe_data)[:300]}")
                payload = {'type': 'interrupt', 'session_id': session_id, 'data': safe_data}
                yield f"data: {json.dumps(payload)}\n\n"
                # Clear response — interrupt means no completion happened
                full_response = ""

            except Exception as e:
                logger.error(f"Error in stream: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            finally:
                # Always save assistant message, even if there was an error
                if full_response:
                    try:
                        # Re-query session to ensure we have a fresh, attached object
                        final_session = (await async_db.execute(
                            select(ChatSession).where(ChatSession.session_id == session_id)
                        )).scalar_one_or_none()

                        if final_session:
                            logger.info(f"Before adding assistant message: total_messages={len(final_session.messages)}")

                            final_session.messages.append({
                                "role": "assistant",
                                "content": full_response
                            })
                            flag_modified(final_session, "messages")

                            # Update metrics with RAG token tracking
                            rough_tokens = len(request.message) + len(full_response)
                            final_session.metrics["total_tokens"] = final_session.metrics.get("total_tokens", 0) + rough_tokens + rag_tokens_used
                            final_session.metrics["rag_context_tokens"] = final_session.metrics.get("rag_context_tokens", 0) + rag_tokens_used
                            final_session.metrics["tool_calls"] = final_session.metrics.get("tool_calls", 0) + tool_calls_count
                            flag_modified(final_session, "metrics")

                            # Update cost tracking columns (if they exist)
                            try:
                                final_session.rag_context_tokens = final_session.metrics.get("rag_context_tokens", 0)
                            except AttributeError:
                                pass  # Column doesn't exist yet

                            # Persist tool call names (shows skill names in MetricsPanel)
                            if collected_tool_names:
                                # Mark completed tool calls as completed
                                for tc in collected_tool_names:
                                    if tc["status"] == "running":
                                        tc["status"] = "completed"
                                final_session.tool_calls = (final_session.tool_calls or []) + collected_tool_names
                                flag_modified(final_session, "tool_calls")

                            await async_db.commit()
                            await async_db.refresh(final_session)  # Refresh to confirm save
                            logger.info(f"✓ Assistant message saved to DB: session={session_id}, total_messages={len(final_session.messages)}, rag_tokens={rag_tokens_used}")

                            # Archive conversation turn (mirrors non-streaming path at line 619)
                            try:
                                from models.conversation_archive import ConversationArchive
                                import re
                                _session_msgs_json = json.dumps(final_session.messages or [])
                                _turn_matches = re.findall(r'role["\']:\s*["\']user["\']', _session_msgs_json)
                                _turn_number = len(_turn_matches)
                                _archive = ConversationArchive(
                                    session_id=final_session.session_id,
                                    user_id=final_session.user_id,
                                    turn_number=_turn_number,
                                    user_message=request.message,
                                    agent_response=full_response,
                                    tool_calls=collected_tool_names or [],
                                )
                                async_db.add(_archive)
                                await async_db.commit()
                                logger.info(f"✓ Turn archived: session={session_id}, turn={_turn_number}")
                            except Exception as _archive_err:
                                logger.warning(f"⚠ Failed to archive turn (non-fatal): {_archive_err}")
                                await async_db.rollback()
                        else:
                            logger.error(f"❌ Session {session_id} not found when saving assistant message")
                    except Exception as save_error:
                        logger.error(f"❌ Failed to save assistant message to DB: {save_error}", exc_info=True)
                        await async_db.rollback()
                else:
                    logger.warning(f"⚠ No response generated for session={session_id}")

                # Release the stream's DB session (runs on success and error).
                await async_db.close()

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error starting stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Session Data & Metrics Endpoints
# =============================================================================


@router.get("/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the full chat history for a session.

    Loads from PostgreSQL session.messages (not from checkpointer).
    """
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return ChatHistoryResponse(
        session_id=session.session_id,
        messages=[ChatMessage(**msg) for msg in session.messages],
        metrics=session.metrics
    )


@router.get("/{session_id}/metrics")
async def get_session_metrics(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed metrics for a chat session with cost calculations."""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    total_tokens = session.metrics.get("total_tokens", 0)
    rag_tokens = session.metrics.get("rag_context_tokens", 0)

    agent = db.query(DeepAgentTemplate).filter_by(id=session.agent_id).first()
    model = "claude-sonnet-4-5-20250929"
    if agent and agent.config:
        model = agent.config.get("model", "claude-sonnet-4-5-20250929")

    MODEL_PRICING = {
        "claude-sonnet-4-5-20250929": 9.0,
        "claude-sonnet-4": 9.0,
        "claude-opus-4-20250514": 45.0,
        "claude-opus-4": 45.0,
        "claude-3-5-sonnet-20241022": 6.0,
        "claude-3-5-sonnet-20240620": 6.0,
        "claude-3-5-haiku-20241022": 1.5,
        "claude-3-opus-20240229": 37.5,
        "claude-3-sonnet-20240229": 6.0,
        "claude-3-haiku-20240307": 0.75,
        "gpt-4o-2024-11-20": 5.0,
        "gpt-4o-2024-08-06": 5.0,
        "gpt-4o-2024-05-13": 10.0,
        "gpt-4o": 7.5,
        "gpt-4o-mini-2024-07-18": 0.3,
        "gpt-4o-mini": 0.3,
        "gpt-4-turbo-2024-04-09": 15.0,
        "gpt-4-turbo": 15.0,
        "gpt-4-0125-preview": 30.0,
        "gpt-4": 30.0,
        "gpt-3.5-turbo": 1.5,
        "gemini-2.0-flash-exp": 0.0,
        "gemini-exp-1206": 0.0,
        "gemini-2.0-flash-thinking-exp-1219": 0.0,
        "gemini-2.0-flash-thinking-exp": 0.0,
        "gemini-1.5-pro-002": 2.5,
        "gemini-1.5-pro": 2.5,
        "gemini-1.5-flash-002": 0.15,
        "gemini-1.5-flash": 0.15,
        "deepseek-chat": 0.55,
        "deepseek-reasoner": 2.19,
    }

    cost_per_1m = MODEL_PRICING.get(model, 9.0)
    estimated_cost = (total_tokens / 1_000_000) * cost_per_1m

    # Calculate current context size
    context_service = ConversationContextService(db)
    context_tokens = context_service.calculate_session_tokens(session)

    # Update cost tracking if column exists (handle missing column gracefully)
    try:
        current_cost = getattr(session, 'total_cost_usd', 0.0)
        if abs(current_cost - estimated_cost) > 0.0001:
            session.total_cost_usd = estimated_cost
            db.commit()
    except AttributeError:
        # Column doesn't exist yet - migration not run
        pass

    return {
        "session_id": session.session_id,
        "metrics": {
            **session.metrics,
            "total_cost_usd": round(estimated_cost, 4),
            "rag_context_tokens": rag_tokens,
            "context_tokens": context_tokens,
            "cost_per_token": round(estimated_cost / max(total_tokens, 1), 8) if total_tokens > 0 else 0,
            "model_used": model
        },
        "tool_calls": session.tool_calls,
        "subagent_spawns": session.subagent_spawns,
        "context_operations": session.context_operations,
        "message_count": len(session.messages or []),
        "is_active": session.is_active,
        "duration_seconds": (session.updated_at - session.created_at).total_seconds()
    }


# =============================================================================
# Message Banking Endpoints (for Context Management)
# =============================================================================


@router.post("/{session_id}/approve")
async def approve_hitl(
    session_id: str,
    approval_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Handle HITL approval by resuming the interrupted agent."""
    # Redirect to resume endpoint
    return await resume_chat(
        session_id=session_id,
        resume_data=approval_data,
        db=db
    )


@router.post("/{session_id}/messages/{message_index}/bank")
async def bank_message(
    session_id: str,
    message_index: int,
    db: Session = Depends(get_db)
):
    """
    Mark a message as 'banked' (important for future context).

    Banked messages are prioritized for inclusion when loading conversation
    context into workflows, even if they're old.
    """
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.messages or message_index >= len(session.messages):
        raise HTTPException(status_code=404, detail="Message not found")

    # Mark message as banked
    from sqlalchemy.orm.attributes import flag_modified
    session.messages[message_index]["banked"] = True
    flag_modified(session, "messages")
    db.commit()

    logger.info(f"Banked message {message_index} in session {session_id}")

    return {
        "status": "success",
        "message": "Message banked successfully",
        "session_id": session_id,
        "message_index": message_index
    }


@router.delete("/{session_id}/messages/{message_index}/bank")
async def unbank_message(
    session_id: str,
    message_index: int,
    db: Session = Depends(get_db)
):
    """Unmark a banked message."""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.messages or message_index >= len(session.messages):
        raise HTTPException(status_code=404, detail="Message not found")

    # Unmark message
    from sqlalchemy.orm.attributes import flag_modified
    session.messages[message_index]["banked"] = False
    flag_modified(session, "messages")
    db.commit()

    logger.info(f"Unbanked message {message_index} in session {session_id}")

    return {
        "status": "success",
        "message": "Message unbanked successfully",
        "session_id": session_id,
        "message_index": message_index
    }
