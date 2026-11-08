"""The Ontology Editor agent, driven from the ontology panel.

The editor is an ordinary DeepAgent (agent 350): it opens a copy of an installed ontology, edits
one declaration, verifies the number, and hands the result to the publish channel. The panel
needs exactly two things from all of that — a conversational turn about one ontology, and the
proposal that turn produced — so this module is the seam:

* `editor_agent(db)` — which agent is the editor (looked up by name, never a hard-coded id: an
  id changes on every reinstall and a stale one would silently talk to a different agent);
* `ask(db, key, message, session_id)` — one turn, with the ontology bound in the message, in a
  session that belongs to that agent and vault (reused when the caller passes it back);
* `proposals(db, key)` — what is staged for that ontology right now. The panel renders these as
  cards WITH their diffs, because "the agent says it fixed it" is not evidence.

Two rules this file exists to keep:

1. **It never installs anything.** Ask → the agent stages; a human with `ontology_editor` applies
   (Settings → Ontology). That asymmetry is the product decision, not a technical limit.
2. **It reuses the chat path.** A second copy of "build the agent, invoke it, store the turn"
   would drift from the one the Chat panel uses — the message sanitisation and the identity
   re-bake live in `api.chat.messages`, and this module calls it rather than re-implementing it.
"""
from __future__ import annotations

import logging
import pathlib
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EDITOR_AGENT_NAME = "Ontology Editor"

# How the ontology is bound into a turn. Not a hidden system prompt: it is part of the visible
# message, so the transcript shows which ontology was being edited when the answer was produced.
PREAMBLE = ("[ontology_key={key}] 你正在编辑的 ontology 是 {key}；工作区副本应在 work/{key}/，"
            "不存在就先 ontology_open。只改一个文件，验证数字后交给 ontology_publish 暂存。\n\n")

MAX_MESSAGE_CHARS = 24_000


class EditorUnavailable(RuntimeError):
    """No editor agent, or a session that cannot be used. Named so the API can answer 409/404."""


def editor_agent(db: Session):
    """The agent named "Ontology Editor" (see scripts/seeds/in/seed_ontology_editor_agent.py)."""
    from models.deep_agent import DeepAgentTemplate

    agent = (db.query(DeepAgentTemplate)
             .filter(DeepAgentTemplate.name == EDITOR_AGENT_NAME)
             .order_by(DeepAgentTemplate.id.desc())
             .first())
    if agent is None:
        raise EditorUnavailable(
            f"no agent named {EDITOR_AGENT_NAME!r} in this install — run "
            "backend/scripts/seeds/in/seed_ontology_editor_agent.py")
    return agent


def _usable_session(db: Session, session_id: Optional[str], agent_id: int):
    """The session to continue, or None when the caller's session is gone or someone else's."""
    if not session_id:
        return None
    from models.deep_agent import ChatSession

    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if session is None or not session.is_active or int(session.agent_id) != int(agent_id):
        return None
    return session


async def prepare(db: Session, key: str, message: str, session_id: Optional[str] = None,
                  project_id: Optional[int] = None) -> dict:
    """Validate a turn and bind the ontology into it — everything the stream needs up front.

    Split from `ask` so the streaming route can create/continue the session BEFORE the response
    starts (a stream that discovers its session halfway through has no way to tell the panel
    which session to continue). Everything it rejects is rejected here, before a model call.
    """
    from api.chat.session import start_chat_session
    from api.chat.schemas import StartChatRequest

    key = (key or "").strip()
    text = (message or "").strip()
    if not key:
        raise EditorUnavailable("which ontology? pass its key (the folder under ontologies/)")
    if not text:
        raise EditorUnavailable("an empty message has nothing to edit")
    if len(text) > MAX_MESSAGE_CHARS:
        raise EditorUnavailable(f"that message is {len(text)} characters; keep it under "
                                f"{MAX_MESSAGE_CHARS} so the turn stays about one edit")

    # A key that is not an installed ontology must be refused HERE, not after a model turn: the
    # agent's first move is ontology_open, so a typo costs a full turn and produces a plausible
    # answer about an ontology that does not exist (measured: "doesnotexist" was accepted).
    from services import ontology_publish

    installed = set()
    try:
        installed = {p.name for p in pathlib.Path(ontology_publish.ONTOLOGIES).iterdir()
                     if p.is_dir() and not p.name.startswith(".")}
    except OSError:
        installed = set()
    if installed and key not in installed:
        raise EditorUnavailable(
            f"no installed ontology {key!r} — available: {', '.join(sorted(installed))}")

    agent = editor_agent(db)
    session = _usable_session(db, session_id, agent.id)
    if session is None:
        started = await start_chat_session(
            StartChatRequest(agent_id=agent.id, project_id=project_id), db)
        session_id = (started.session_id if hasattr(started, "session_id")
                      else started["session_id"])
    else:
        session_id = session.session_id

    return {
        "ok": True,
        "key": key,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "session_id": session_id,
        "message": PREAMBLE.format(key=key) + text,
    }


async def ask(db: Session, key: str, message: str, session_id: Optional[str] = None,
              project_id: Optional[int] = None) -> dict:
    """One turn (non-streaming): the answer, the tool calls, and what got staged."""
    from api.chat.messages import send_message
    from api.chat.schemas import SendMessageRequest

    prompt = await prepare(db, key, message, session_id=session_id, project_id=project_id)

    reply = await send_message(
        SendMessageRequest(session_id=prompt["session_id"], message=prompt["message"],
                           project_id=project_id), db)
    body = reply.model_dump() if hasattr(reply, "model_dump") else dict(reply or {})

    return {
        "ok": True,
        "key": prompt["key"],
        "agent": {"id": prompt["agent_id"], "name": prompt["agent_name"]},
        "session_id": prompt["session_id"],
        "answer": body.get("message") or "",
        "tool_calls": body.get("tool_calls") or [],
        "proposals": proposals(db, prompt["key"]),
    }


def proposals(db: Session, key: str) -> list[dict]:
    """Staged publishes for this ontology, newest first — each with the files it would change."""
    from services import ontology_publish

    out: list[dict] = []
    staging_root = ontology_publish._staging_dir(key)
    rows = ontology_publish.history(key=key, limit=50)

    # WHEN the last install happened, from the ledger alone. A staged publish older than the last
    # applied one is SUPERSEDED: its tree would overlay an already-installed version. File mtimes
    # cannot answer this (a `git stash pop` rewrites them; measured on the deployment: five v2
    # stagings all carried the same mtime), but every staged id starts with the epoch it was made.
    def _epoch(sid: str) -> int:
        head = str(sid).split("-")[0]
        return int(head) if head.isdigit() else 0

    applied_epoch = max((_epoch(r.get("id") or "") for r in rows
                         if r.get("status") == "applied"), default=0)

    for row in rows:
        # filter by key AND status here as well: `history(key=…)` already does the key, but a
        # panel that showed another ontology's staged publish would offer a diff for a file the
        # reader never opened — the cheap double check is worth more than trusting the ledger.
        if row.get("key") != key or row.get("status") != "staged":
            continue
        # A staging tree that is gone cannot be applied; the ledger row is then a leftover, not a
        # proposal (measured: a published tree leaves rows behind and the panel offered every one).
        if not (staging_root / str(row.get("id"))).is_dir():
            continue
        # Only the NEWEST staged publish is the candidate. An older one would overlay a tree that
        # has already moved past it, and listing it as "waiting to be applied" is how the settings
        # panel ended up showing ten pending publishes across three ontologies, every one stale.
        if applied_epoch and _epoch(str(row.get("id"))) < applied_epoch:
            continue                      # an install happened after this was staged
        if out:
            break
        report = row.get("report") or {}
        out.append({
            "id": row["id"],
            "actor": row.get("actor"),
            "note": row.get("note"),
            "created_at": row.get("created_at"),
            "files": report.get("files") or [],
            "new_refusals": report.get("new_refusals") or [],
            "carried_refusals": report.get("carried_refusals") or [],
            "gates_ok": report.get("gates_ok"),
            "gates_fails": report.get("gates_fails") or [],
            "gates_not_run": report.get("gates_not_run") or [],
            "compile": report.get("compile") or {},
        })
    return out
