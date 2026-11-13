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

import asyncio
import dataclasses
import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

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

# NOTE: the chat streaming path uses a local `StreamingFilter` class defined
# below (search for `class StreamingFilter`). An earlier version imported an
# external equivalent from `learning/phase9/think_filter.py` — that directory
# is intentionally excluded from the team-install zip (see
# `scripts/make_team_zip.sh`), so the import crashed team deployments with
# `ModuleNotFoundError: No module named 'think_filter'`. The local class is
# the authoritative implementation; we just deleted the stale import.

from .schemas import (
    ChatHistoryResponse,
    ChatMessage,
    ChatResponse,
    SendMessageRequest,
)
from .session import resume_chat
from .shared import cache_agent, get_cached_agent, load_session_for_caller

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])


#: Transport failures between this backend and the model provider. They are NOT the agent's fault and they are
#: NOT fatal: the turn can be retried, because the graph checkpoints its state per thread. Measured twice on one
#: evening: `StreamChunkTimeoutError … for 600.0s (chunks_received=28)` and `httpx.ConnectTimeout →
#: openai.APITimeoutError`. Both surfaced to the user as a bare 500 with the word "detail" in it.
_TRANSPORT_ERROR_NAMES = ("StreamChunkTimeoutError", "APITimeoutError", "ConnectTimeout", "ReadTimeout",
                          "ConnectError", "RemoteProtocolError")


def _is_transport_error(exc: BaseException) -> bool:
    """True for a link problem to the model provider (retryable), False for a bug in the graph."""
    name = type(exc).__name__
    if name in _TRANSPORT_ERROR_NAMES:
        return True
    # httpx/openai wrap the cause, and langchain wraps both: look one level down as well.
    cause = getattr(exc, "__cause__", None)
    if cause is not None and type(cause).__name__ in _TRANSPORT_ERROR_NAMES:
        return True
    text = str(exc)
    return "No streaming chunk received" in text or "Request timed out" in text


def _transport_message(exc: BaseException, attempts: int) -> str:
    """What the human is told when the link — not the agent — failed, and what to do about it."""
    return (
        f"⚠ 到模型服务的链路断了（{type(exc).__name__}），已自动重试 {attempts} 次仍未恢复。\n\n"
        "这不是 agent 的错，也不是本轮指令的问题：**已经写入的文件和数据库都在**，"
        "产物请以 workspace 的 `generated/` 与库里的表为准。\n\n"
        "处理建议：等网络稳定后，再发一句「继续」即可（会话状态在 checkpoint 里，不会从头再来）。"
    )


def _args_grow(prev: str, cur: str) -> bool:
    """True when `cur` is `prev` plus MORE of the same thing — the signature of the degenerate loop.

    Measured twice:
      1. ten `psql -c "select count(*) … trip_date < X"` calls, each the previous command with one more `-c`
         appended — growth at the END, so `cur.startswith(prev)` saw it;
      2. this turn: **78** `execute` calls of `… | grep -rn "samples" f1 f2 … fN 2>/dev/null | head -20`, where
         each call appended one more file to the MIDDLE of the command (the `2>/dev/null | head -20` tail never
         moved). Prefix test was false every time, so nothing tripped and the turn burned to the recursion limit.

    So growth means: after removing the common suffix the two strings share, the shorter is a prefix of the
    longer. That catches append-at-end (common suffix empty) and insert-in-the-middle (common suffix is the
    fixed tail) — and still says NO to `ls a` vs `ls b` (no common suffix, no prefix) and to unrelated
    commands. Plain equality must NOT trip at 3: "run the generator twice, then once more to prove
    determinism" is a legitimate pattern this same agent is asked to do (equality trips at 5).
    """
    if not prev or len(cur) <= len(prev):
        return False
    if cur.startswith(prev):
        return True
    n = 0                                            # length of the shared TAIL
    while n < len(prev) and prev[-1 - n] == cur[-1 - n]:
        n += 1
    if n == 0:
        return False
    head_prev, head_cur = prev[: len(prev) - n], cur[: len(cur) - n]
    return head_cur.startswith(head_prev) and head_cur != head_prev


def _args_signature(name: str, payload) -> str:
    """A stable fingerprint of one tool call, so a REPEATED call is detectable."""
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:                                          # noqa: BLE001
        raw = str(payload)
    return f"{name}::{hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16]}"


def _turn_is_empty(result) -> bool:
    """True when the graph ended WITHOUT an assistant answer (empty AI turn or a dangling tool message).

    Measured twice on the Mock Data Agent: the model executed tools and then returned
    `ai content=0 tool_calls=[]`. The graph treats that as "done", so the loop ends; the response extraction
    used to walk backwards and hand the last TOOL output back as the assistant's answer — the run looked
    finished, and nothing had been produced.
    """
    msgs = getattr(result, "messages", None)
    if msgs is None and isinstance(result, dict):
        msgs = result.get("messages")
    if not msgs:
        return True
    last = msgs[-1]
    role = getattr(last, "type", None) or (last.get("role") if isinstance(last, dict) else None)
    content = getattr(last, "content", None) if not isinstance(last, dict) else last.get("content")
    if isinstance(content, list):
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    has_text = isinstance(content, str) and content.strip()
    tool_calls = getattr(last, "tool_calls", None) or (last.get("tool_calls") if isinstance(last, dict) else None)
    return role == "ai" and not has_text and not tool_calls


def _resolve_recursion_limit(agent_config: Optional[dict]) -> int:
    """Turn cap for one chat invocation.

    A recursion limit bounds LangGraph supersteps (model + tool turns): it is the
    guard against a runaway tool loop, not a context-size control. Resolution
    order:

    1. the agent's own ``recursion_limit`` (so one agent can be tighter than its
       kind's default),
    2. the per-kind default from Settings → Agents (``agents.agent`` /
       ``agents.deepagent``) — the two kinds differ ~6x in steps per LLM turn,
    3. the team-wide ``analysis_recursion_limit``.

    Verified against deepagents 0.7.1: the SDK binds ``recursion_limit=9999`` on
    the compiled graph via ``.with_config``, but an invoke-time value overrides
    it (invoking with 2 raises GraphRecursionError where 3 completes).
    """
    from config import settings as _app_settings

    agent_config = agent_config or {}
    try:
        per_agent = int(agent_config.get("recursion_limit") or 0)
    except (TypeError, ValueError):
        logger.warning(
            "agent config recursion_limit=%r is not an int — using the kind default",
            agent_config.get("recursion_limit"),
        )
        per_agent = 0
    if per_agent > 0:
        return per_agent

    try:
        from models.deep_agent import default_recursion_limit

        kind_default = default_recursion_limit(
            bool(agent_config.get("use_deepagents", True))
        )
    except Exception as exc:  # settings unreadable must never break a chat
        logger.warning("could not read the agents settings defaults: %s", exc)
        kind_default = None
    if kind_default:
        return kind_default

    return _app_settings.analysis_recursion_limit


def _handoff_steps(agent_config: dict) -> dict:
    """`step key → display label` for the agent's handoff middleware ({} if none).

    The card reads "售后 → 财务" rather than "support → finance", so the labels
    the reviewer typed in the policy editor have to travel with the event.
    """
    for entry in (agent_config or {}).get("middleware") or []:
        if (isinstance(entry, dict)
                and entry.get("type") in ("handoff", "handoffs")
                and entry.get("enabled", True)):
            steps = (entry.get("config") or {}).get("steps") or {}
            return {
                str(key): str((step or {}).get("label") or key)
                for key, step in steps.items()
                if isinstance(step, dict) or step is None
            }
    return {}


def _handoff_default_step(agent_config: dict) -> str | None:
    """The step a conversation starts in — the origin of the first hop."""
    for entry in (agent_config or {}).get("middleware") or []:
        if (isinstance(entry, dict)
                and entry.get("type") in ("handoff", "handoffs")
                and entry.get("enabled", True)):
            return (entry.get("config") or {}).get("default_step")
    return None


def _default_agent_docs(agent, workspace_root: str) -> dict:
    """Sensible default AGENTS.md / CLAUDE.md for agents that have no
    user-authored docs in PostgreSQL.

    Every agent workspace should carry these files: MemoryMiddleware loads
    AGENTS.md into the system prompt and the Files panel lists them next to
    uploads + generated files. The defaults are stored back to the DB row so
    the Docs tab in the editor shows the same content (editable).

    The stored copy carries the real agent id + workspace root baked in
    (same as the system prompt identity block).
    """
    from core.agents.identity import default_agent_docs
    return default_agent_docs(agent, workspace_root)


def _materialize_agent_docs(agent, workspace_root: str, db=None) -> None:
    """Write the agent's instruction docs (AGENTS.md / CLAUDE.md / …) into
    its workspace.

    ``deep_agent_templates.agent_docs`` (PostgreSQL) is the source of truth;
    the files are materialized here so MemoryMiddleware can read AGENTS.md and
    the Files panel shows the docs alongside uploads + generated files.

    Agents without authored docs get sensible defaults materialized, and (when
    a DB session is available) those defaults are stored back onto the row so
    the editor's Docs tab stays consistent.

    Also ensures the standard workspace skeleton exists
    (upload/ + generated/ + skills/ + other/), so every agent workspace has
    the same shape from its first chat.
    """
    if not workspace_root:
        return
    try:
        from services.workspace_manager import ensure_agent_workspace_layout
        from pathlib import Path as _Path
        root = _Path(workspace_root)
        ensure_agent_workspace_layout(root)
        for sub in ("upload", "generated", "other"):
            gitkeep = root / sub / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("")
    except Exception as e:  # never fail a chat because skeleton creation failed
        logger.warning(f"Failed to ensure workspace skeleton: {e}")
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
        # Docs are stored with the real agent id + workspace root baked in at
        # creation/backfill, so the stored copy is the canonical content. The
        # baked root, however, may predate the current session's project
        # binding (creation happens project-agnostic → legacy
        # outputs/agents/agent_{id}/), so each materialized copy is re-baked
        # with THIS session's resolved workspace root — the doc analogue of
        # the system-prompt identity re-bake above.
        from core.agents.identity import refresh_doc_identity
        _agent_id = getattr(agent, "id", None)
        for name, content in docs.items():
            if not name or not isinstance(content, str):
                continue
            # basename only — keep the docs inside the workspace root
            safe_name = Path(name).name
            target = (root / safe_name).resolve()
            if not target.is_relative_to(root.resolve()):
                logger.warning(f"Skipping agent doc with unsafe name: {name!r}")
                continue
            target.write_text(
                refresh_doc_identity(content, _agent_id, str(root)),
                encoding="utf-8",
            )
        logger.info(f"Materialized {len(docs)} agent doc(s) into {root}")
    except Exception as e:
        logger.warning(f"Failed to materialize agent docs into {workspace_root}: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

def sanitize_tool_call_history(messages):
    """Ensure every ``AIMessage.tool_calls`` has its ``ToolMessage`` responses.

    A crashed/aborted run (stream timeout, client cancel, worker kill) can leave
    an ``AIMessage`` with ``tool_calls`` but no ``ToolMessage`` results in the
    checkpointed state. OpenAI-compatible APIs (DeepSeek) reject such history
    with 400: "An assistant message with 'tool_calls' must be followed by tool
    messages responding to each 'tool_call_id'". This strips orphaned tool_calls
    (keeping any text content) and drops empty orphaned tool-call messages.

    Returns the original list when nothing changed, else the cleaned list.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    msgs = list(messages)
    answered = {
        m.tool_call_id
        for m in msgs
        if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
    }
    changed = False
    out = []
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            orphaned = [tc for tc in m.tool_calls if tc.get("id") not in answered]
            if orphaned:
                kept = [tc for tc in m.tool_calls if tc.get("id") in answered]
                if kept:
                    m = m.model_copy(update={"tool_calls": kept})
                    changed = True
                elif getattr(m, "content", None):
                    m = m.model_copy(update={"tool_calls": []})
                    changed = True
                else:
                    # Empty orphaned tool-call message (a run died mid-call) → drop.
                    changed = True
                    continue
        out.append(m)
    return out if changed else messages


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
        # Messages and rich tool results are payloads, not junk: LangChain
        # messages carry theirs in `.content`, dataclasses and pydantic models
        # (e.g. deepagents' ``ExecuteResponse``) in their fields. Without this a
        # tool that returns an object serialised as ``null`` and the chat UI
        # showed an empty result for every such tool — including ``execute``.
        content = getattr(obj, "content", None)
        if isinstance(content, (str, list, dict)):
            return make_json_safe(content)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            try:
                return make_json_safe(dataclasses.asdict(obj))
            except Exception:
                pass
        model_dump = getattr(obj, "model_dump", None)
        if callable(model_dump):
            try:
                return make_json_safe(model_dump())
            except Exception:
                pass
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


def _stored_message(role: str, content: str) -> Dict[str, Any]:
    """A message as it is stored in ``chat_sessions.messages``.

    Every append site goes through here. The streaming endpoint (what the chat
    UI actually calls) used to append a bare ``{"role", "content"}`` while the
    non-streaming one stamped a timestamp, so nearly every message sent through
    the UI landed without one and the history footer rendered "Invalid Date"
    underneath it — 198 of 210 stored messages in one real database.
    """
    from datetime import datetime

    return {
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat(),
        "banked": False,
    }


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
        user_message_index = len(session.messages or [])
        _user_entry = _stored_message("user", request.message)
        user_message_timestamp = _user_entry["timestamp"]
        session.messages.append(_user_entry)
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

        # Built before the cache check: `_resolve_recursion_limit(_safe_config)` runs on
        # BOTH paths, but this used to be assigned only inside `if not agent_instance:` —
        # so the second message of a session (agent already cached) died with
        # UnboundLocalError. A live multi-turn chat found it.
        # Fix: ensure list fields are never None to avoid "NoneType has no len()"
        _safe_config = dict(agent.config or {})
        for _list_key in ['middleware', 'subagents', 'skills', 'native_tools']:
            if _safe_config.get(_list_key) is None:
                _safe_config[_list_key] = []
        if _safe_config.get('guardrails') is None:
            _safe_config['guardrails'] = {"input": [], "output": []}

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
            # Re-bake the agent's identity block on every chat so the
            # workspace path matches the SESSION's current project (not the
            # one captured at agent creation). The agent is project-agnostic;
            # the binding lives on chat_sessions.project_id. Strip the stale
            # baked-in identity, resolve the new one, splice it back in.
            _session_project_id = getattr(session, "project_id", None)
            # NOT conditional on project_id. A session with no project still has a
            # workspace — the caller's — and skipping the rebuild left the creation-time
            # path (the *first* admin's tree) in the prompt. A live chat caught it: the
            # agent said it worked for "account ID 1" while running as user 284.
            if True:
                from core.agents.identity import (
                    _strip_identity_block,
                    build_identity_system_prompt,
                    caller_block,
                )
                from services.workspace_manager import get_workspace_manager
                _ws_mgr = get_workspace_manager()
                _re_ws_root = str(_ws_mgr.resolve_agent_workspace(
                    agent, _session_project_id,
                    vault_key=_ws_mgr.project_vault_key(db, _session_project_id) or None,
                    agent_key=_ws_mgr.agent_vault_key(db, agent),
                ))
                _re_base = _strip_identity_block(
                    _safe_config.get("system_prompt", "") or ""
                )
                _safe_config["system_prompt"] = build_identity_system_prompt(
                    _re_base, agent.id, _re_ws_root, agent.agent_docs or {},
                    # Who is asking, for this turn only — the stored prompt is shared
                    # between accounts, so the person cannot live in the DB.
                    caller=caller_block(db, getattr(session, "user_id", None), session.session_id),
                )
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
            # First message of a fresh session: ask the agent to introduce
            # itself and report its workspace status so the user gets a good
            # starting view. Identity (id + workspace) is already baked into
            # the stored system prompt at creation time.
            if (session.messages or []) and len(session.messages) == 1:
                from core.agents.identity import (
                    first_chat_greeting,
                    has_workspace_status_tools,
                )
                _greeting = first_chat_greeting(
                    agent_workspace_root,
                    include_workspace_status=has_workspace_status_tools(
                        _safe_config.get("native_tools")
                    ),
                    subagents=[
                        s.get("name") for s in (_safe_config.get("subagents") or [])
                        if isinstance(s, dict) and s.get("name")
                    ],
                )
                _safe_config["system_prompt"] = (
                    (_safe_config.get("system_prompt") or "") + _greeting
                )
                config.system_prompt = (config.system_prompt or "") + _greeting
            # ── A code-defined LangGraph graph IS the agent ──────────────────
            # `config.graph_id` names a graph under backend/langgraph/. Running it
            # directly (instead of wrapping it in a tool) is what makes the middle
            # of the run visible: the same graph the Studio renders is the one the
            # chat executes. The graph carries its own checkpointer; chat history
            # still lives in Postgres, so the two are independent by design.
            _graph_id = (_safe_config.get("graph_id") or "").strip()
            if _graph_id:
                from langgraph.assigned import is_assigned, describe
                from langgraph.tool_adapters import get_graph_runnable
                if not is_assigned(_graph_id):
                    raise HTTPException(status_code=403, detail=describe(_graph_id))
                try:
                    agent_instance = get_graph_runnable(_graph_id)
                    _tools, _callbacks = [], []
                    logger.info(f"Chat bound to LangGraph graph '{_graph_id}' (agent {agent.id})")
                except KeyError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
            elif not use_deepagents:
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

        # Sanitize checkpointed history before invoking: a previous run that
        # died mid-tool-call (timeout/cancel) leaves an AIMessage.tool_calls
        # with no ToolMessage results, which OpenAI-compatible APIs reject
        # with 400. Strip orphans so the graph resumes cleanly.
        try:
            checkpointer = getattr(agent_instance, "checkpointer", None)
            if checkpointer is not None and hasattr(checkpointer, "aget_state"):
                _cfg = {"configurable": {"thread_id": session.session_id}}
                _st = await checkpointer.aget_state(_cfg)
                if _st is not None and _st.values:
                    _msgs = list(_st.values.get("messages", []) or [])
                    _cleaned = sanitize_tool_call_history(_msgs)
                    if _cleaned is not _msgs and hasattr(checkpointer, "aupdate_state"):
                        await checkpointer.aupdate_state(_cfg, {"messages": _cleaned})
                        logger.info(
                            f"Sanitized orphaned tool_calls in history for session "
                            f"{session.session_id} ({len(_msgs) - len(_cleaned)} dropped)"
                        )
        except Exception as e:
            logger.warning(f"History sanitize failed (non-fatal): {e}")

        # Keep the thread inside the context window. The provider does not summarise for us: it
        # answers 400 and the turn is lost (measured on ECS: 1,367,956 message tokens against a
        # 1,048,576 window). Shrinking the checkpointed STATE means the next turn starts small too.
        try:
            from services.thread_budget import shrink_thread as _shrink
            _compaction = await _shrink(agent_instance, session.session_id)
            if _compaction.changed:
                logger.info(f"compacted thread {session.session_id}: {_compaction.describe()}")
        except Exception as e:                                     # noqa: BLE001
            logger.warning(f"Thread compaction failed (non-fatal): {e}")

        # Invoke agent with thread_id for conversation persistence
        # The checkpointer automatically loads and saves conversation history.
        # Turn cap: the agent's own recursion_limit, else the team-wide setting.
        #
        # The agent's shell + file tools resolve their sandbox from this binding:
        # inside the harness the request identity is not visible, and without it the
        # tools fell back to the install owner — so a second account's agent worked in
        # the first account's tree. The run knows whose workspace it is; say so.
        from tools.native_impl import bind_run_root, clear_run_root
        from services import user_roots
        from services.workspace_manager import get_workspace_manager as _wsm_for_run

        # The run root is the SESSION'S AGENT WORKSPACE, not the account's whole tree. Measured: with the user
        # root bound, `read_any_file /upload/<the file the user just uploaded>` was refused with "outside the
        # allowed workspace" three times in one turn — the agent could see the file through its own file tools
        # but not through the native reader. Resolved here, outside the agent-cache branch, because a cached
        # agent (the second and later turns) never reached the code that computed it.
        _run_ws_root = None
        try:
            _wsm_run = _wsm_for_run()
            _run_ws_root = str(_wsm_run.resolve_agent_workspace(
                agent, getattr(session, "project_id", None),
                vault_key=_wsm_run.project_vault_key(db, getattr(session, "project_id", None)) or None,
                agent_key=_wsm_run.agent_vault_key(db, agent),
            ))
        except Exception as _ws_exc:                            # noqa: BLE001 — never block a turn
            logger.warning("could not resolve the run workspace: %s", _ws_exc)

        def _invoke_once(_messages):
            return agent_instance.ainvoke(
                {"messages": _messages},
                config={
                    "configurable": {"thread_id": session.session_id},
                    "recursion_limit": _resolve_recursion_limit(_safe_config),
                },
            )

        _run_root_token = bind_run_root(_run_ws_root or user_roots.root_for(getattr(session, "user_id", None)))
        try:
            try:
                result = await _invoke_once([new_message])
            except Exception as _e:                              # noqa: BLE001
                if not _is_transport_error(_e):
                    raise
                # One retry on a link failure, then a message a human can act on (this path used to return a
                # bare 500 whose `detail` was the openai exception's str()).
                logger.error("transport failure (non-streaming), retrying once: %s", _e)
                try:
                    result = await _invoke_once([new_message])
                except Exception as _e2:                         # noqa: BLE001
                    raise HTTPException(status_code=503, detail=_transport_message(_e2, 2)) from _e2
            # An EMPTY final assistant turn is a dead end, not an answer: the model ran the tools and then
            # produced nothing, and the old code returned the last tool output as if it were the reply.
            # One bounded retry turns that into progress instead of a silent stop.
            if _turn_is_empty(result):
                logger.warning("empty assistant turn for session=%s — retrying once", session.session_id)
                result = await _invoke_once([
                    new_message,
                    HumanMessage(content=(
                        "你上一步执行完工具后没有输出任何内容（空回合）。请继续：直接调用需要的工具推进"
                        "当前任务，不要说『已完成』除非产物真的存在。若已经完成，用一段话给出产物路径与检查数。"
                    )),
                ])
        finally:
            clear_run_root(_run_root_token)

        # Extract response. The LAST message decides: a turn that ended on a tool result is a turn with NO
        # answer, and saying so beats dressing a `psql` dump up as one. Only an assistant message counts; for
        # subagent/delegation turns the final AIMessage carries the summary, which is what we want anyway.
        response_text = ""
        _last = None
        _all = getattr(result, "messages", None) or (result.get("messages") if isinstance(result, dict) else None)
        if _all:
            _last = _all[-1]
        _last_role = getattr(_last, "type", None) or (_last.get("role") if isinstance(_last, dict) else None)
        _last_text = getattr(_last, "content", "") if _last is not None and not isinstance(_last, dict) else ((_last or {}).get("content") if isinstance(_last, dict) else "")
        if isinstance(_last_text, list):
            _last_text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in _last_text)
        if _last_role != "ai" or not (isinstance(_last_text, str) and _last_text.strip()):
            logger.warning("⚠ no assistant answer for session=%s (last message: %s) — reporting it as such",
                           session.session_id, _last_role)
            _hint = (getattr(_last, "content", "") if _last is not None and not isinstance(_last, dict) else "")
            _hint = _hint if isinstance(_hint, str) else ""
            response_text = (
                "⚠ 本轮没有生成回答：模型在工具执行后返回了空回合。\n\n"
                + (f"上一步的工具输出（供参考）：\n```\n{_hint[:1200]}\n```\n\n" if _hint.strip() else "")
                + "已完成的部分在 workspace 里（用文件面板看 `generated/`）。再发一句「继续」即可推进，或换一个更小的步骤。"
            )
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
        assistant_message_index = len(session.messages or [])
        _assistant_entry = _stored_message("assistant", response_text)
        assistant_message_timestamp = _assistant_entry["timestamp"]
        session.messages.append(_assistant_entry)
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
                            tc.update(clip_tool_result(content))
                            tc["status"] = derive_tool_status(content)
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


# ---------------------------------------------------------------------------
# Stopping a run
# ---------------------------------------------------------------------------
# The composer's send button becomes a stop button while a run streams. Hanging
# up the HTTP request is not enough on its own: uvicorn notices the disconnect
# between chunks, but a run sitting inside a slow tool call keeps going and the
# user is told "stopped" while the agent is still working (and still spending
# tokens). So the client also calls POST /api/chat/{session_id}/stop, which sets
# this flag; the event loop checks it after every event and breaks, closing the
# LangGraph stream with it.
_STOP_REQUESTS: set[str] = set()


def request_stop(session_id: str) -> None:
    _STOP_REQUESTS.add(session_id)


def _stop_requested(session_id: str) -> bool:
    return session_id in _STOP_REQUESTS


def clear_stop(session_id: str) -> None:
    _STOP_REQUESTS.discard(session_id)


@router.post("/{session_id}/stop")
async def stop_message_stream(session_id: str):
    """Ask the run streaming for `session_id` to stop.

    Idempotent and cheap: the flag is read by the streaming generator, which
    emits a terminal `stopped` event and returns. Anything already written to
    the transcript stays — a stopped run keeps its partial answer instead of
    losing it.
    """
    request_stop(session_id)
    logger.info(f"[CHAT-STOP] stop requested for session {session_id}")
    return {"status": "stopping", "session_id": session_id}


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

        # Persist the UI-supplied project_id onto the chat session. The
        # workspace resolver (line ~405) reads chat_sessions.project_id, not
        # request.project_id — without this persist the UI's project picker
        # has no effect on the per-agent vault path. The agent itself stays
        # project-agnostic (no FK on deep_agent_templates); the binding is
        # per-chat-session, so the same agent can run in different projects
        # across its sessions.
        if request.project_id is not None and session.project_id != request.project_id:
            session.project_id = request.project_id
            db.commit()
            db.refresh(session)

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
            clear_stop(session_id)

            # The finalizer below saves the turn from these three lists, and it
            # runs even when the stream fails before they would be created — the
            # UnboundLocalError it raised then masked the original error. Create
            # them here so every path can rely on them.
            tool_calls_count = 0
            collected_tool_names = []  # tool names for DB persistence + skill detection
            collected_subagent_spawns = []  # one entry per `task` delegation
            collected_handoffs = []  # one entry per transfer_to_* call
            full_response = ""
            reasoning_chars = 0        # characters of visible deliberation (never the answer)
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
                fresh_session.messages.append(
                    _stored_message("user", request.message)
                )
                flag_modified(fresh_session, "messages")
                await async_db.commit()  # Commit user message immediately
                await async_db.refresh(fresh_session)  # Refresh to confirm save
                logger.info(f"✓ User message saved to DB: session={session_id}, total_messages={len(fresh_session.messages)}")

                # Build agent via DeepAgentFactory (standard path)
                # Use the chat session's project binding (persisted from the
                # UI's project picker in the request handler above) as the
                # authoritative source. Falls back to request.project_id for
                # the first message of a fresh session before persistence.
                project_id = (
                    getattr(fresh_session, "project_id", None)
                    or request.project_id
                )
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
                            _sandbox_dir = _ws_mgr.user_base() / "default"
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

                # ── A code-defined LangGraph graph IS the agent (streaming path) ──
                # Same rule as the non-streaming entry point, and the same guard: only
                # graphs in langgraph/assigned.py may answer in chat. Studio runs the
                # drafts; the product runs the assigned ones.
                _graph_id = str((agent.config or {}).get("graph_id") or "").strip()
                if not agent_instance and _graph_id:
                    from langgraph.assigned import is_assigned, describe
                    from langgraph.tool_adapters import get_graph_runnable
                    if not is_assigned(_graph_id):
                        raise HTTPException(status_code=403, detail=describe(_graph_id))
                    try:
                        agent_instance = get_graph_runnable(_graph_id)
                        logger.info(
                            f"Chat (stream) bound to assigned LangGraph graph "
                            f"'{_graph_id}' (agent {agent.id})"
                        )
                    except KeyError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))

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
                    # Re-bake the identity block in the system prompt so it
                    # matches THIS session's workspace (same rule as the
                    # non-streaming entry point). The stored prompt carries
                    # the creation-time (legacy) root; without this the agent
                    # reports the wrong workspace even though the greeting
                    # below names the resolved root.
                    if True:  # see the non-streaming path: no project ≠ no workspace
                        from core.agents.identity import (
                            _strip_identity_block,
                            build_identity_system_prompt,
                            caller_block,
                        )
                        _base_prompt = _strip_identity_block(
                            agent_config.get("system_prompt") or ""
                        )
                        agent_config["system_prompt"] = build_identity_system_prompt(
                            _base_prompt,
                            agent.id,
                            agent_workspace_root,
                            agent.agent_docs or {},
                            caller=caller_block(db, getattr(fresh_session, "user_id", None), fresh_session.session_id),
                        )
                    _materialize_agent_docs(agent, agent_workspace_root, db=db)
                    # First message of a fresh session: ask the agent to
                    # introduce itself and report its workspace status (same
                    # rule as the first chat entry point).
                    if (fresh_session.messages or []) and len(fresh_session.messages) == 1:
                        from core.agents.identity import (
                            first_chat_greeting,
                            has_workspace_status_tools,
                        )
                        _greeting = first_chat_greeting(
                            agent_workspace_root,
                            include_workspace_status=has_workspace_status_tools(
                                agent_config.get("native_tools")
                            ),
                            subagents=[
                                s.get("name") for s in (agent_config.get("subagents") or [])
                                if isinstance(s, dict) and s.get("name")
                            ],
                        )
                        agent_config["system_prompt"] = (
                            (agent_config.get("system_prompt") or "") + _greeting
                        )
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

                # A paused review must be answered before the conversation moves
                # on: sending a new message into a run that is parked on an
                # interrupt would either double-run it or lose the pending call.
                try:
                    _snap = await agent_instance.aget_state(
                        {"configurable": {"thread_id": session_id}}
                    )
                    _pending = tuple(getattr(_snap, "interrupts", ()) or ())
                except Exception as _e:  # noqa: BLE001 — never block a chat on this probe
                    logger.warning(f"Pending-interrupt probe failed for {session_id}: {_e}")
                    _pending = ()
                if _pending:
                    yield f"data: {json.dumps({'type': 'interrupt', 'session_id': session_id, 'data': make_json_safe(_pending[0].value)})}\n\n"
                    await async_db.close()
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
                # Turn cap: the agent's own recursion_limit, else the team-wide
                # setting (same resolution as the non-streaming path).
                # A hop is an edge, so remember where the conversation is: the
                # first transfer starts from `default_step`, each later one from
                # wherever the previous hop landed.
                _hop_labels = _handoff_steps(agent_config)
                # Where the conversation currently stands. Each user turn is a
                # fresh request, so the counter cannot live in this function: the
                # last persisted hop is the truth across turns (a single turn may
                # hop twice, and the loop below keeps up with that).
                _hop_current = _handoff_default_step(agent_config)
                for _msg in (getattr(fresh_session, "messages", None) or []):
                    if isinstance(_msg, dict) and _msg.get("role") == "handoff" and _msg.get("to"):
                        _hop_current = _msg["to"]
                # Same binding as the non-streaming path: the tools' sandbox comes
                # from the run, because the harness does not carry the request
                # identity into tool execution.
                from tools.native_impl import bind_run_root as _bind_root, clear_run_root as _clear_root
                from services import user_roots as _user_roots
                # Bind the AGENT's workspace, not just the person's tree: `_sandbox_roots()` uses
                # the bound root to resolve RELATIVE tool paths, and an agent names its own files
                # relatively (`upload/orders.xlsx`). Measured: with the person's tree bound, that
                # path resolved against the server's cwd and was refused as "outside the allowed
                # workspace", so the agent spent a turn asking where its own upload was.
                # `agent_workspace_root` is only assigned when this turn had to CREATE the agent
                # (the reuse path skips that branch), so referencing it here raised
                # `cannot access local variable 'agent_workspace_root'` on every reused turn —
                # measured as a 500 on upload. Resolve it here instead, guarded.
                try:
                    from services.workspace_manager import get_workspace_manager as _gwm
                    _root_mgr = _gwm()
                    _root_project = getattr(fresh_session, "project_id", None) or project_id
                    _bind_target = str(_root_mgr.resolve_agent_workspace(
                        agent, _root_project,
                        vault_key=_root_mgr.project_vault_key(db, _root_project) or None,
                        agent_key=_root_mgr.agent_vault_key(db, agent),
                    ))
                except Exception as _root_exc:                  # noqa: BLE001 — never block a chat
                    logger.warning("could not resolve the agent workspace for this run: %s", _root_exc)
                    _bind_target = ""
                _run_root_token = _bind_root(
                    _bind_target
                    or _user_roots.root_for(getattr(fresh_session, "user_id", None))
                )
                try:
                    # A HEARTBEAT is the difference between "working" and "hung" from the user's chair. Measured
                    # tonight: a turn that emitted nothing for 600 s, and another that emitted nothing while it
                    # wrote a 30 KB file — both looked identical to a dead spinner. So the stream is consumed with
                    # a 5 s timeout: a quiet 5 s emits one `progress` event (elapsed, tool, chunks, tokens).
                    # Same guard as the non-streaming path, on the path the app actually uses.
                    # This has to run BEFORE the stream starts: LangGraph replays the thread, so a
                    # 1.3M-token history is already fatal by the time a token arrives. The notice is
                    # yielded, not logged only — a silent shrink looks like the agent forgetting.
                    try:
                        from services.thread_budget import shrink_thread as _shrink
                        _compaction = await _shrink(agent_instance, session_id)
                        if _compaction.changed:
                            logger.info("compacted thread %s: %s", session_id, _compaction.describe())
                            _notice = _compaction.describe()
                            yield f"data: {json.dumps({'type': 'custom_event', 'event_type': 'progress', 'message': _notice})}\n\n"
                    except Exception as _compact_exc:                  # noqa: BLE001 — never fail a turn
                        logger.warning("thread compaction failed (non-fatal): %s", _compact_exc)

                    _stream = agent_instance.astream_events(
                        {"messages": [new_message]},
                        config={
                            "configurable": {"thread_id": session_id},
                            "callbacks": [event_handler],
                            "recursion_limit": _resolve_recursion_limit(agent_config),
                        },
                        version="v2"
                    )
                    _turn_started = time.monotonic()
                    _heartbeat_s = 5.0
                    _tokens_seen = 0
                    _last_tool = ""
                    _prev_args: dict[str, str] = {}
                    _growth: dict[str, int] = {}
                    _same_calls: dict[str, int] = {}
                    _loop_stopped = False

                    # The stream is consumed by a PUMP TASK into a queue, not with `wait_for(__anext__())`.
                    # Measured (CLI probe, 22:52): cancelling the pending `__anext__()` on each 5 s timeout put
                    # the async generator into a broken state — the probe that should have completed instead got a
                    # spurious `interrupt` event and no answer. Cancelling a step of an async generator is not a
                    # "peek": it raises inside it. A queue decouples "wait for the next event" from "read it".
                    _event_q: asyncio.Queue = asyncio.Queue(maxsize=200)
                    _PUMP_DONE = object()

                    async def _pump_events():
                        try:
                            async for _ev in _stream:
                                await _event_q.put(_ev)
                            await _event_q.put(_PUMP_DONE)
                        except BaseException as _exc:              # noqa: BLE001 — forwarded to the consumer
                            await _event_q.put((_PUMP_DONE, _exc))

                    _pump_task = asyncio.create_task(_pump_events())
                    while True:
                        try:
                            _item = await asyncio.wait_for(_event_q.get(), timeout=_heartbeat_s)
                        except asyncio.TimeoutError:
                            yield f"data: {json.dumps({'type': 'progress', 'elapsed_s': int(time.monotonic() - _turn_started), 'tool': _last_tool, 'tool_calls': tool_calls_count, 'chars': len(full_response), 'tokens': _tokens_seen})}\n\n"
                            continue
                        if _item is _PUMP_DONE:
                            break
                        if isinstance(_item, tuple) and len(_item) == 2 and _item[0] is _PUMP_DONE:
                            raise _item[1]
                        event = _item
                        if _stop_requested(session_id):
                            # Break here and answer immediately: closing the
                            # LangGraph stream raises CancelledError into this
                            # generator, so anything scheduled *after* the loop
                            # (interrupt probing, filter flush) never runs.
                            logger.info(
                                f"[CHAT-STOP] stopping {session_id} after "
                                f"{len(full_response)} chars, {tool_calls_count} tool calls"
                            )
                            stopped = True
                            try:
                                await _stream.aclose()
                            except Exception as _exc:  # noqa: BLE001
                                logger.debug(f"[CHAT-STOP] stream close: {_exc}")
                            clear_stop(session_id)
                            # Keep the partial answer: stop means stop, not amnesia.
                            yield f"data: {json.dumps({'type': 'stopped', 'content': full_response, 'tool_calls': tool_calls_count})}\n\n"
                            return
                        kind = event.get("event")
                        if kind == "on_tool_start":
                            tool_calls_count += 1
                            tool_data = event.get("data", {})
                            # A REPEATED call is not progress. Measured: ten `psql -c "select count(*) …"` calls
                            # whose arguments grew by one query each, no number reported, the turn eventually lost.
                            try:
                                _sig = _args_signature(event.get("name", "?"), tool_data.get("input"))
                            except Exception:                            # noqa: BLE001
                                _sig = ""
                            _tool_nm = str(event.get("name") or "")
                            _args_txt = _sig.split("::", 1)[1] if _sig else ""
                            if _sig:
                                try:
                                    _args_json = json.dumps(tool_data.get("input"), ensure_ascii=False,
                                                            sort_keys=True)
                                except Exception:                        # noqa: BLE001
                                    _args_json = str(tool_data.get("input"))
                                _prev = _prev_args.get(_tool_nm, "")
                                if _prev and _args_grow(_prev, _args_json):
                                    _growth[_tool_nm] = _growth.get(_tool_nm, 0) + 1
                                    _same_calls[_tool_nm] = 0
                                elif _prev == _args_json:
                                    _same_calls[_tool_nm] = _same_calls.get(_tool_nm, 0) + 1
                                    _growth[_tool_nm] = 0
                                else:
                                    _growth[_tool_nm] = 0
                                    _same_calls[_tool_nm] = 0
                                _prev_args[_tool_nm] = _args_json
                                _why = ""
                                if _growth.get(_tool_nm, 0) >= 3:
                                    _why = f"参数在连续递增（第 {_growth[_tool_nm] + 1} 次比上一次更长且包含上一次）"
                                elif _same_calls.get(_tool_nm, 0) >= 5:
                                    _why = f"同一条调用已连续 {_same_calls[_tool_nm] + 1} 次完全一样"
                                if _why:
                                    _loop_stopped = True
                                    _msg = (f"⚠ 循环已中止：{_tool_nm} {_why}。上一次的输出就在上面——"
                                            "请换一种做法（一条聚合 SQL 一次算完，或分块写文件），然后发「继续」。")
                                    logger.warning("loop guard tripped: %s (%s)", _tool_nm, _why)
                                    yield f"data: {json.dumps({'type': 'error', 'message': _msg})}\n\n"
                                    try:
                                        await _stream.aclose()
                                    except Exception:                    # noqa: BLE001
                                        pass
                                    full_response = (full_response + "\n\n" + _msg).strip()
                                    break
                            _last_tool = str(event.get("name") or "")
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
                            # Delegation evidence: the Metrics panel's
                            # "subagent activity" reads this list, and until now
                            # nothing wrote it — a session that delegated to
                            # three subagents recorded zero spawns.
                            if tool_name == "task" and isinstance(tool_input, dict):
                                collected_subagent_spawns.append({
                                    "subagent": tool_input.get("subagent_type")
                                    or tool_input.get("name") or "unknown",
                                    "task": str(tool_input.get("description") or "")[:300],
                                    "status": "running",
                                    "timestamp": datetime.utcnow().isoformat(),
                                })
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

                            # A handoff moves the *speaker*: from here on the answer
                            # comes from another step, and the transcript has to say
                            # so — otherwise one reply reads as if a single agent
                            # both offered to transfer and answered as the expert.
                            from core.agents.handoff_tools import transfer_target as _tt

                            _target = _tt(str(tool_name))
                            if _target:
                                _reason = (tool_input or {}).get("reason") if isinstance(tool_input, dict) else ""
                                _from = _hop_current
                                _hop_current = _target
                                _hop = {
                                    "from_step": _from,
                                    "from_label": _hop_labels.get(_from, _from) if _from else None,
                                    "to": _target,
                                    "to_label": _hop_labels.get(_target, _target),
                                    "reason": _reason or "",
                                    "timestamp": datetime.utcnow().isoformat(),
                                }
                                collected_handoffs.append(_hop)
                                yield f"data: {json.dumps({'type': 'handoff', **_hop})}\n\n"

                        elif kind == "on_tool_end":
                            tool_data = event.get("data", {})
                            tool_name = event.get("name", "unknown")
                            # Update the running tool call with result
                            for tc in reversed(collected_tool_names):
                                if tc["tool_name"] == tool_name and tc["status"] == "running":
                                    if tool_name == "task":
                                        for spawn in reversed(collected_subagent_spawns):
                                            if spawn["status"] == "running":
                                                spawn["status"] = "completed"
                                                break
                                    output = make_json_safe(tool_data.get("output", ""))
                                    if isinstance(output, (dict, list)):
                                        output = json.dumps(output, ensure_ascii=False)
                                    tc.update(clip_tool_result(output if output is not None else ""))
                                    tc["status"] = derive_tool_status(tc["result"])
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

                                # A thinking model streams `reasoning_content` in additional_kwargs with an
                                # EMPTY `content`. Without this the user watches a spinner for two minutes and
                                # then gets nothing ("No response generated"), which is what made the build
                                # look dead. Show the deliberation as `thinking`, never as the answer.
                                _reason = ""
                                try:
                                    _ak = getattr(chunk_content, "additional_kwargs", None) or {}
                                    _reason = _ak.get("reasoning_content") or ""
                                except Exception:                        # noqa: BLE001
                                    _reason = ""
                                if _reason:
                                    reasoning_chars += len(_reason)
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': _reason})}\n\n"

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
                                        _tokens_seen += 1
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

                finally:
                    try:
                        _pump_task.cancel()                     # noqa: F821 — defined above the try
                    except Exception:                           # noqa: BLE001
                        pass
                    _clear_root(_run_root_token)

                # After stream completes, check for pending interrupts
                interrupted = False
                stopped = False
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

                # Send completion event (skip if interrupted or stopped)
                if stopped:
                    # A stopped run keeps whatever it already produced: the user
                    # asked for it to stop, not for the text to disappear.
                    logger.info(
                        f"[CHAT-STOP] stopped for {session_id} after "
                        f"{len(full_response)} chars, {tool_calls_count} tool calls"
                    )
                    yield f"data: {json.dumps({'type': 'stopped', 'content': full_response})}\n\n"
                    clear_stop(session_id)
                elif not interrupted:
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
                if _is_transport_error(e):
                    # The LINK died, not the agent. Retry the turn once (the graph checkpoints per thread), then
                    # say what actually happened instead of a bare 500 with a stack trace in `detail`.
                    logger.error("transport failure in stream: %s", e)
                    yield f"data: {json.dumps({'type': 'progress', 'note': '到模型服务的链路中断，自动重试一次'})}\n\n"
                    _recovered = False
                    try:
                        _retry_stream = agent_instance.astream_events(
                            {"messages": [new_message]},
                            config={
                                "configurable": {"thread_id": session_id},
                                "callbacks": [event_handler],
                                "recursion_limit": _resolve_recursion_limit(agent_config),
                            },
                            version="v2",
                        )
                        async for _ev in _retry_stream:
                            if _ev.get("event") == "on_chat_model_stream":
                                _chunk = _ev.get("data", {}).get("chunk")
                                _tok = getattr(_chunk, "content", "") if _chunk is not None else ""
                                if isinstance(_tok, str) and _tok.strip():
                                    full_response += _tok
                                    _recovered = True
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': _tok})}\n\n"
                        logger.info("transport retry finished for session=%s (text=%s)", session_id, _recovered)
                    except Exception as retry_exc:                 # noqa: BLE001
                        logger.error("transport retry failed for session=%s: %s", session_id, retry_exc)
                        _tmsg = _transport_message(retry_exc, 2)
                        yield f"data: {json.dumps({'type': 'error', 'message': _tmsg})}\n\n"
                        full_response = (full_response + "\n\n" + _tmsg).strip()
                else:
                    logger.error(f"Error in stream: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            finally:
                # Save the turn even when it ended in an interrupt: the run has
                # no prose yet, but the tool calls it made (and the ones it is
                # waiting to make) are exactly the evidence a reviewer needs.
                if full_response or collected_tool_names or collected_subagent_spawns or collected_handoffs:
                    try:
                        # Re-query session to ensure we have a fresh, attached object
                        final_session = (await async_db.execute(
                            select(ChatSession).where(ChatSession.session_id == session_id)
                        )).scalar_one_or_none()

                        if final_session:
                            logger.info(f"Before adding assistant message: total_messages={len(final_session.messages)}")

                            for hop in collected_handoffs:
                                _where = (
                                    f"{hop['from_label']} → {hop['to_label']}"
                                    if hop.get("from_label") else f"转交给「{hop['to_label']}」"
                                )
                                final_session.messages.append({
                                    "role": "handoff",
                                    "content": _where + (f" · {hop['reason']}" if hop["reason"] else ""),
                                    "from_step": hop.get("from_step"),
                                    "from_label": hop.get("from_label"),
                                    "to": hop["to"],
                                    "to_label": hop.get("to_label"),
                                    "reason": hop["reason"],
                                    "timestamp": hop["timestamp"],
                                })
                            if collected_handoffs:
                                flag_modified(final_session, "messages")

                            if full_response:
                                final_session.messages.append(
                                    _stored_message("assistant", full_response)
                                )
                                flag_modified(final_session, "messages")

                            # Update metrics with RAG token tracking
                            rough_tokens = len(request.message) + len(full_response)
                            final_session.metrics["total_tokens"] = final_session.metrics.get("total_tokens", 0) + rough_tokens + rag_tokens_used
                            final_session.metrics["rag_context_tokens"] = final_session.metrics.get("rag_context_tokens", 0) + rag_tokens_used
                            final_session.metrics["tool_calls"] = final_session.metrics.get("tool_calls", 0) + tool_calls_count
                            # The counter the Metrics panel prints, kept next to
                            # the tool_calls counter it sits beside. Only the
                            # spawn *list* used to be written, so the panel read
                            # 0 while the activity list showed two entries.
                            final_session.metrics["subagent_spawns"] = (
                                final_session.metrics.get("subagent_spawns", 0)
                                + len(collected_subagent_spawns)
                            )
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

                            if collected_subagent_spawns:
                                for spawn in collected_subagent_spawns:
                                    if spawn["status"] == "running":
                                        spawn["status"] = "completed"
                                final_session.subagent_spawns = (
                                    final_session.subagent_spawns or []
                                ) + collected_subagent_spawns
                                flag_modified(final_session, "subagent_spawns")

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
                    # The turn produced no answer. Retry ONCE (non-streamed) with a nudge, then report the
                    # truth: an empty turn is a failed turn, and dressing up the last tool output as an answer
                    # is how a dead build looked finished.
                    logger.warning("⚠ No response generated for session=%s (reasoning=%s chars) — retrying once",
                                   session_id, reasoning_chars)
                    _retry_text = ""
                    try:
                        _retry = await agent_instance.ainvoke(
                            {"messages": [HumanMessage(content=(
                                "你上一步执行完工具后没有输出任何最终答复（只有推理）。请直接给出最终答复，"
                                "要么继续调用工具推进任务，要么用一段话说明产物路径与检查数。"))]},
                            config={"configurable": {"thread_id": session_id},
                                    "recursion_limit": _resolve_recursion_limit(_safe_config)},
                        )
                        _rmsgs = getattr(_retry, "messages", None) or []
                        if _rmsgs:
                            _lastc = getattr(_rmsgs[-1], "content", "") or ""
                            if isinstance(_lastc, str):
                                _retry_text = _lastc.strip()
                    except Exception as _retry_exc:            # noqa: BLE001
                        logger.warning("retry after an empty turn failed: %s", _retry_exc)
                    if _retry_text:
                        full_response = _retry_text
                        yield f"data: {json.dumps({'type': 'chunk', 'content': _retry_text})}\n\n"
                    else:
                        _notice = ("⚠ 本轮模型没有给出最终答复（推理了 %d 字符，但 content 为空）。"
                                   "这不是完成 —— 产物请以 workspace 的 generated/ 与库里的表为准；"
                                   "再发一句「继续」即可推进，或把任务拆成更小的一步。") % reasoning_chars
                        full_response = _notice
                        yield f"data: {json.dumps({'type': 'chunk', 'content': _notice})}\n\n"

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


#: How much of a tool result is persisted with the transcript.
#:
#: It was 500, and that silently cut 190 of 260 results in one real ontology build mid-sentence — the evidence
#: needed to explain why a number changed was frequently past the cut. Storing the whole thing is not the answer
#: either (one `find /` can emit megabytes into a jsonb column), so: keep a generous slice, and say so when it was
#: cut, so a reader knows the difference between "the output ended here" and "the record ended here".
TOOL_RESULT_MAX_CHARS = 20_000

#: Markers the sandbox puts in a result when the command failed. `status` alone cannot be trusted: measured on the
#: same session, all 260 calls were recorded `completed`, including eight real failures (`No such file`,
#: `timed out after 120 seconds`, `ModuleNotFoundError`, `ERROR: column … does not exist`).
_FAILED_MARKERS = (
    "[Command failed",                 # the sandbox's own verdict, when it survives the clip
    "Command timed out",               # a timeout is a failure the harness still calls "completed"
    "ModuleNotFoundError",
    "Traceback (most recent call last)",
    "command not found",
    "[stderr] ERROR",                  # psql/psycopg errors land here, not in an exit code the caller sees
    "[stderr] bash:",
    "No such file or directory",
)


def clip_tool_result(text: str) -> dict:
    """The persisted form of a tool result: a bounded slice plus what was cut."""
    full = str(text or "")
    clipped = full[:TOOL_RESULT_MAX_CHARS]
    return {
        "result": clipped,
        "result_length": len(full),
        "result_truncated": len(full) > len(clipped),
    }


#: The sandbox's own verdict, when it survives the clip. Preferred over every heuristic below.
_SUCCEEDED_MARKERS = ("[Command succeeded with exit code 0]", "Command succeeded with exit code 0")


def derive_tool_status(text: str) -> str:
    """Failed or completed, decided from the text rather than from the harness.

    The harness reports every call as `completed`; the transcript has to carry what actually happened, because the
    next reader (a person, or an agent turning a session into a skill) relies on it.

    Order matters, and it was learned the hard way: a *probe* command legitimately prints
    `No such file or directory` while succeeding (`ls -d backend docs start.sh` to find out what is missing). When
    the sandbox states the outcome explicitly, that statement wins; the heuristics only serve results that were
    clipped before the marker.
    """
    lowered = str(text or "")
    if any(marker in lowered for marker in _SUCCEEDED_MARKERS):
        return "completed"
    if "[Command failed" in lowered or "Command failed with exit code" in lowered:
        return "failed"
    return "failed" if any(marker in lowered for marker in _FAILED_MARKERS) else "completed"


@router.get("/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the full chat history for a session.

    Loads from PostgreSQL session.messages (not from checkpointer).
    """
    session = load_session_for_caller(db, session_id)

    return ChatHistoryResponse(
        session_id=session.session_id,
        messages=[ChatMessage(**msg) for msg in session.messages],
        metrics=session.metrics,
        # The evidence half of the record: name, arguments, result and status per call, oldest first.
        tool_calls=list(session.tool_calls or []),
    )


@router.get("/{session_id}/metrics")
async def get_session_metrics(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed metrics for a chat session with cost calculations."""
    session = load_session_for_caller(db, session_id)

    total_tokens = session.metrics.get("total_tokens", 0)
    rag_tokens = session.metrics.get("rag_context_tokens", 0)

    agent = db.query(DeepAgentTemplate).filter_by(id=session.agent_id).first()
    model = "deepseek-flash"
    if agent and agent.config:
        model = agent.config.get("model", "deepseek-flash")

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

    # Context occupancy for the composer's ring: the same token count the
    # summarisation trigger uses, against the agent's own threshold. Read here
    # because the ring is rendered beside the session's other numbers, and
    # because occupancy changes with every turn.
    from services.context_occupancy import agent_context_config, occupancy

    agent_config = (agent.config or {}) if agent else {}
    guardrails = agent_context_config(agent_config) or (
        agent.guardrails_config if agent and isinstance(agent.guardrails_config, dict) else {}
    )
    occupancy_data = occupancy(
        messages=session.messages or [],
        guardrails=guardrails,
        system_prompt=agent_config.get("system_prompt", "") if isinstance(agent_config.get("system_prompt", ""), str) else "",
        # Both agent kinds live in deep_agent_templates; `use_deepagents` marks
        # which limit defaults apply when the row carries no guardrails.
        use_deepagents=bool(agent_config.get("use_deepagents", True)),
    ).as_dict()

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
        "context": occupancy_data,
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
    session = load_session_for_caller(db, session_id)

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
    session = load_session_for_caller(db, session_id)

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
