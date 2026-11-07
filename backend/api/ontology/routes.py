"""Ontology workbench routes.

The workbench is one process per ontology profile, and nobody should have to start them by
hand: these endpoints report what is running and start whatever is not. The supervisor lives
in `services/ontology_workbench.py` (lazy start, one child per profile, health = the
workbench's own answer).
"""
from __future__ import annotations

import logging

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import (ontology_build, ontology_editor, ontology_publish, ontology_samples,
                      ontology_workbench)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/workbenches")
async def list_workbenches(ensure: bool = True):
    """Every configured ontology, with its live state. Starts what is not running."""
    return await ontology_workbench.status(ensure=ensure)


@router.post("/workbenches/{key}/stop")
async def stop_workbench(key: str):
    return ontology_workbench.stop(key)


# ── talking to the editor agent about one ontology ──────────────────────────
# The panel asks; the agent stages; a human applies. Nothing here can install.

class AskEditorRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    project_id: Optional[int] = None


@router.get("/editor")
async def editor_agent():
    """Which agent is the ontology editor (by name, never a hard-coded id)."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        agent = ontology_editor.editor_agent(db)
        return {"ok": True, "id": agent.id, "name": agent.name,
                "model": (agent.config or {}).get("model"),
                "skills": (agent.config or {}).get("skills") or [],
                "native_tools": (agent.config or {}).get("native_tools") or []}
    except ontology_editor.EditorUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        db.close()


@router.get("/{key}/proposals")
async def ontology_proposals(key: str):
    """What is staged for this ontology right now — each proposal carries the files it changes."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        return {"ok": True, "key": key, "proposals": ontology_editor.proposals(db, key)}
    finally:
        db.close()


@router.post("/{key}/ask-editor/stream")
async def ask_editor_stream(key: str, req: AskEditorRequest):
    """One editor turn, STREAMED — the same events the global Chat panel receives.

    The panel needs what a chat needs: tokens as they arrive, the tool calls, a session it can
    continue, and a stop button. Rather than re-implement any of that, this delegates to
    `api.chat.messages.send_message_stream` after binding the ontology into the message — and
    prepends one extra event, `{"type": "session"}`, because a stream that only learns its session
    id at the end cannot be continued.

    The chat handler needs a database session for the whole stream, so it gets its own here and the
    wrapper closes it when the last event is sent (FastAPI's dependency would have closed it as
    soon as this route returned).
    """
    import json as _json

    from fastapi.responses import StreamingResponse

    from api.chat.messages import send_message_stream
    from api.chat.schemas import SendMessageRequest
    from db.database import SessionLocal

    prep_db = SessionLocal()
    try:
        prompt = await ontology_editor.prepare(prep_db, key, req.message,
                                              session_id=req.session_id,
                                              project_id=req.project_id)
    except ontology_editor.EditorUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        prep_db.close()

    stream_db = SessionLocal()
    inner = await send_message_stream(
        SendMessageRequest(session_id=prompt["session_id"], message=prompt["message"],
                           project_id=req.project_id), stream_db)

    async def with_session():
        head = {"type": "session", "session_id": prompt["session_id"], "key": prompt["key"],
                "agent": {"id": prompt["agent_id"], "name": prompt["agent_name"]}}
        yield f"data: {_json.dumps(head)}\n\n"
        try:
            async for chunk in inner.body_iterator:
                yield chunk
        finally:
            stream_db.close()

    return StreamingResponse(with_session(), media_type="text/event-stream")


@router.post("/{key}/ask-editor")
async def ask_editor(key: str, req: AskEditorRequest):
    """One editor turn about this ontology: the answer, the tool calls, and what it staged."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        return await ontology_editor.ask(db, key, req.message, session_id=req.session_id,
                                        project_id=req.project_id)
    except ontology_editor.EditorUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        db.close()


# ── tutorial samples: click through one, then reset it ─────────────────────
# A guided intake still asks a person to type nine answers before anything happens. A sample is the
# answers already filled with a question they recognise, so the whole pipeline (intake → interpretation
# → declaration → verification → proposal → apply) can be watched and then undone.

@router.get("/{key}/samples")
async def list_samples(key: str):
    """Three business questions for this ontology, with whether each is already installed."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        return {"ok": True, "key": key, "samples": ontology_samples.list_samples(db, key)}
    finally:
        db.close()


@router.post("/{key}/samples/{sample_id}/reset")
async def reset_sample(key: str, sample_id: str, apply_now: bool = True):
    """Undo a sample: remove its declaration through the channel (compile + gates), then install it."""
    try:
        return {"ok": True, **ontology_samples.reset(key, sample_id, apply_now=apply_now)}
    except ontology_samples.SampleError as exc:
        raise HTTPException(409, str(exc)) from exc


# ── generating an ontology (a job, because it takes minutes) ────────────────
# Generation is step one and it is slow: schema introspection, three declaration files, a profile,
# a tutorial, then the gate suite a few times. As a chat turn it dies with the connection; as a
# background task it survives the tab, reports what step it is on, and can be cancelled or retried.

class BuildRequest(BaseModel):
    agent_id: int
    ontology_key: str
    brief: str
    project_id: Optional[int] = None
    # The user's rule for the FIRST generation: gates green -> it lands itself. Anything after that
    # is a change to what a number means, and stays a human decision in the editor chat.
    auto_land: bool = True
    session_id: Optional[str] = None


@router.get("/builders")
async def build_options():
    """Which data an agent can build an ontology for — labelled for a person, not by agent id.

    The build form asks one question ("which data?") and gets these entries back; the agent id and the
    ontology folder are the platform's business, not the user's.
    """
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        return {"ok": True, "builders": ontology_build.builders(db)}
    finally:
        db.close()


@router.post("/build")
async def start_build(req: BuildRequest):
    """Queue a build. Returns the task id immediately; poll /build/{task_id} for progress."""
    try:
        return await ontology_build.enqueue_build(
            req.agent_id, req.ontology_key, req.brief, project_id=req.project_id,
            auto_land=req.auto_land, session_id=req.session_id)
    except ontology_build.BuildError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/build/{task_id}")
async def build_status(task_id: int):
    res = ontology_build.build_status(task_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error") or "no such build")
    return res


@router.get("/builds")
async def build_list(key: Optional[str] = None, limit: int = 10):
    """Recent builds (for one ontology when `key` is given) — what survives a page reload."""
    return {"ok": True, "builds": ontology_build.recent_builds(ontology_key=key, limit=limit)}


# ── publishing declarations ────────────────────────────────────────────────
# Stage validates and changes nothing; apply needs confirmation and an editor. An agent can
# only reach `stage` — that is the difference between "the agent did the work" and "the agent
# changed production on its own".

class StageRequest(BaseModel):
    key: str
    files: dict[str, str]
    note: Optional[str] = ""
    profile_name: Optional[str] = None


class ApplyRequest(BaseModel):
    confirmed: bool = False
    git_commit: bool = True


def _require_editor() -> str:
    """Who may publish. `ontology_editor` (or admin) — a role, because a publish changes what
    a number MEANS for everyone."""
    try:
        from services.user_roots import subject_user_id
        from db.database import SessionLocal
        from services.user_service import get_user

        uid = subject_user_id()
        if uid is None:
            return "owner"                     # single-user install: the owner publishes
        db = SessionLocal()
        try:
            user = get_user(db, uid)
            role = getattr(user, "role", None)
            role = getattr(role, "value", role)
            name = getattr(user, "username", str(uid))
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        raise HTTPException(500, f"could not verify your role ({exc})") from exc
    if role not in ("admin", "ontology_editor"):
        raise HTTPException(
            403,
            f"publishing an ontology needs the ontology_editor role (you are role={role!r}); "
            "ask an admin to grant it, or keep the change as a proposal",
        )
    return name


@router.post("/publish/stage")
async def publish_stage(req: StageRequest):
    """Validate a candidate ontology without touching the installed one."""
    actor = _require_editor()
    return ontology_publish.stage(req.key, req.files, actor=actor, note=req.note or "",
                                  profile_name=req.profile_name)


@router.post("/publish/{staged_id}/apply")
async def publish_apply(staged_id: str, req: ApplyRequest):
    """Install a staged publish. Needs `confirmed` from a human (agents cannot confirm)."""
    actor = _require_editor()
    if not req.confirmed:
        raise HTTPException(400, "confirmed=false: a publish lands only after a human says so")
    res = ontology_publish.apply(staged_id, actor=actor, confirmed=True,
                                 git_commit=req.git_commit)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error") or "publish failed")
    return res


@router.get("/publish/history")
async def publish_history(key: Optional[str] = None, limit: int = 50,
                          status: Optional[str] = None):
    """The publish ledger, newest first. `status=staged` is what a human has to decide on."""
    rows = ontology_publish.history(key=key, limit=limit)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return {"ok": True, "publishes": rows}


@router.get("/publish/{staged_id}/diff")
async def publish_diff(staged_id: str):
    """What this publish would change, file by file. Read-only, and available for a refusal too."""
    res = ontology_publish.diff(staged_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error") or "no diff")
    return res


@router.get("/publish/{staged_id}/values")
async def publish_values(staged_id: str):
    """Which NUMBERS this publish would move — before/after per metric, under the guardrails.

    Slower than the diff (it runs both ontologies), which is why it is its own call: a reviewer
    asks it about the one proposal they are about to apply.
    """
    res = ontology_publish.value_delta(staged_id)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error") or "value comparison failed")
    return res


@router.post("/publish/{staged_id}/discard")
async def publish_discard(staged_id: str):
    """Drop a staged candidate (an editor decision, same role as apply)."""
    actor = _require_editor()
    res = ontology_publish.discard(staged_id, actor=actor)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error") or "discard failed")
    return res


@router.get("/publish/{staged_id}")
async def publish_one(staged_id: str):
    rows = ontology_publish._audit_list(staged_id)
    if not rows:
        raise HTTPException(404, f"no publish {staged_id!r}")
    return {"ok": True, "publish": rows[0]}
