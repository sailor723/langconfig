"""The Ontology BUILDER, driven from a chat — the conversational half of `ontology_build`.

The Build dialog's one-shot job answers "generate it now". That shape cannot carry the part that
needs a conversation: S0 is a set of questions about the business, and a rebuild is "prove the delta,
then ask only about the delta". Measured on this project: a one-shot turn ends at the clarification
questions with nothing staged, and the panel has nothing to show but "finished".

So this module is the seam for a chat turn against the same agent the job uses — the BUILDER (it has
the datasource, so it can measure the database), never the editor (it can only edit what exists):

* `builder_agent(db, key)` — which agent builds THIS key (declared on the agent, not inferred from
  its datasource: two builders on one database are two ontologies);
* `pinned(db, key)` — what every turn starts from: the installed declarations (or "nothing installed
  yet"), the answers already given, and the documents sitting in the agent's `upload/`;
* `prepare(...)` / `ask(...)` — one turn, with that seed on the FIRST message of a session so later
  turns do not re-send it;
* `state(db, key)` — what the panel renders next to the chat (pinned facts + the ladder artifacts).

Rules kept here, same as the editor seam: it never installs (publish stops at staged), and it reuses
`api.chat.messages` instead of re-implementing the turn.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 24_000


class BuildChatUnavailable(RuntimeError):
    """No builder for this key, or an unusable session. Named so the API can answer 409."""


def _workspace(db: Session, agent) -> Optional[pathlib.Path]:
    try:
        from services.workspace_manager import get_workspace_manager
        ws = get_workspace_manager()
        project_id = getattr(agent, "project_id", None)
        return ws.resolve_agent_workspace(
            agent, project_id,
            vault_key=ws.project_vault_key(db, project_id) or None,
            agent_key=ws.agent_vault_key(db, agent))
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("build chat: cannot resolve the workspace for agent %s: %s",
                       getattr(agent, "id", "?"), exc)
        return None


def builder_agent(db: Session, key: str):
    """The builder whose DECLARED ontology key is `key`."""
    from services import ontology_build as _ob

    rows = _ob.builders(db)
    match = [r for r in rows if r.get("ontology_key") == key]
    if not match:
        known = ", ".join(sorted({str(r.get("ontology_key")) for r in rows})) or "none"
        raise BuildChatUnavailable(
            f"no builder is wired to {key!r} — wire one first (it carries the datasource this build "
            f"has to measure). Builders on this install: {known}")
    from models.deep_agent import DeepAgentTemplate
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == int(match[0]["agent_id"])).first()
    if agent is None:
        raise BuildChatUnavailable(f"builder agent {match[0]['agent_id']} is gone from this install")
    return agent


def pinned(db: Session, key: str) -> dict:
    """Everything a build turn starts from — small enough to put IN the prompt."""
    from services import ontology_build as _ob

    agent = builder_agent(db, key)
    ws = _workspace(db, agent)
    installed = _ob._installed_dir(key)
    facts = _ob._installed_facts(key) if installed is not None else {}
    docs = sorted(p.name for p in (ws / "upload").glob("*") if p.is_file()) if ws else []
    work = ws / "work" / key if ws else None
    artifacts = {}
    if work is not None and work.is_dir():
        for name in ("steps.json", "delta.json", "delta_audit.json", "questions.json",
                     "answers.json", "samples.json", "tutorial.json"):
            p = work / name
            if p.is_file():
                artifacts[name] = p.stat().st_size
    return {
        "key": key,
        "agent": {"id": agent.id, "name": agent.name},
        "workspace": str(ws) if ws else None,
        "installed": installed is not None,
        "metrics": len(facts.get("metrics") or []),
        "objects": len(facts.get("objects") or []),
        "documents": docs,
        "artifacts": artifacts,
        "answers": bool(_ob._answers_of(key)),
    }


def _seed(db: Session, key: str, info: dict) -> str:
    """The pinned context, as the first message of a session."""
    from services import ontology_build as _ob

    lines = [f"## 这次是构建 `{key}` 的对话（不是一次性任务）", ""]
    if info["installed"]:
        lines += [
            f"已装本体：{info['objects']} 个对象 / {info['metrics']} 个指标。**先证明 delta 再动手**：",
            "对照已装声明 + 上次口径 + 本次材料，产出 `work/<key>/delta.json`；"
            "`changed=added=removed=0` 且无 questions 就停下并说 `NO DELTA`，不要重跑 S1..S8。",
            "",
        ]
        facts = _ob._installed_facts(key)
        lines += ["【已装指标】" + "、".join(facts.get("metrics") or []), ""]
    else:
        lines += [
            "**这是首次生成**：还没有任何声明。按 ladder 走 S0→S8，每步一个产物 + 一个门，"
            "红了就按门的话改；口径拿不准就问业务，不要猜。",
            "",
        ]
    if info["documents"]:
        lines += ["【本次文档】在 `upload/`：" + "、".join(f"`{d}`" for d in info["documents"])
                  + "（用 `read_any_file` 读，业务口径以它们为准）", ""]
    if info["answers"]:
        lines += ["【上次口径】`work/<key>/answers.json` 里已有答案，不要重复问。", ""]
    if info["artifacts"]:
        lines += ["【已有产物】" + "、".join(sorted(info["artifacts"])) + "（先读它们再决定做什么）", ""]
    lines += ["每轮末尾用一句话说明：这一步的产物是什么、门是什么、结果是什么。发布停在 staged。"]
    return "\n".join(lines)


def _session_has_messages(db: Session, session_id: str) -> bool:
    from models.deep_agent import ChatSession
    s = (db.query(ChatSession).filter(ChatSession.session_id == session_id).first())
    return bool(s and (s.messages or []))


async def prepare(db: Session, key: str, message: str, session_id: Optional[str] = None,
                  project_id: Optional[int] = None) -> dict:
    """Validate one turn and bind the build into it (everything the stream needs up front)."""
    from api.chat.schemas import StartChatRequest
    from api.chat.session import start_chat_session

    key = (key or "").strip()
    text = (message or "").strip() or "开始"
    if len(text) > MAX_MESSAGE_CHARS:
        raise BuildChatUnavailable(f"that message is {len(text)} characters; keep it under "
                                   f"{MAX_MESSAGE_CHARS} so the turn stays about one step")
    info = pinned(db, key)
    agent = builder_agent(db, key)

    session_ok = False
    if session_id:
        from models.deep_agent import ChatSession
        s = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        session_ok = bool(s and s.is_active and int(s.agent_id) == int(agent.id))
    if not session_ok:
        started = await start_chat_session(
            StartChatRequest(agent_id=agent.id, project_id=project_id), db)
        session_id = (started.session_id if hasattr(started, "session_id") else started["session_id"])

    first = not _session_has_messages(db, session_id)
    body = (_seed(db, key, info) + "\n\n---\n\n" + text) if first else text
    return {"ok": True, "key": key, "agent_id": agent.id, "agent_name": agent.name,
            "session_id": session_id, "message": body, "seeded": first, "pinned": info}


async def ask(db: Session, key: str, message: str, session_id: Optional[str] = None,
              project_id: Optional[int] = None) -> dict:
    """One builder turn (non-streaming): the answer, the tool calls, and what got staged."""
    from api.chat.messages import send_message
    from api.chat.schemas import SendMessageRequest

    prompt = await prepare(db, key, message, session_id=session_id, project_id=project_id)
    reply = await send_message(
        SendMessageRequest(session_id=prompt["session_id"], message=prompt["message"],
                           project_id=project_id), db)
    body = reply.model_dump() if hasattr(reply, "model_dump") else dict(reply or {})
    from services import ontology_publish
    staged = [r for r in ontology_publish.history(key=key, limit=10) if r.get("status") == "staged"]
    return {"ok": True, "key": key, "session_id": prompt["session_id"],
            "agent": {"id": prompt["agent_id"], "name": prompt["agent_name"]},
            "seeded": prompt["seeded"], "pinned": prompt["pinned"],
            "answer": body.get("message") or "",
            "tool_calls": len(body.get("tool_calls") or []),
            "staged": staged[:3]}


def state(db: Session, key: str) -> dict:
    """What the panel shows beside the chat."""
    info = pinned(db, key)
    from services import ontology_publish
    staged = [r for r in ontology_publish.history(key=key, limit=5) if r.get("status") == "staged"]
    return {"ok": True, **info, "staged": staged}
