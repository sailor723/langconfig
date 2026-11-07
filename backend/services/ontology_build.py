"""Ontology builds as background jobs: generate off to the side, come back to the result.

The flow this serves, in the user's words: *run the ontology agent to generate the ontology since it
takes time; then open the workbench, check it, and refine it by chat*. Generation is minutes of
agent work with database introspection, so it must not be a chat turn you have to sit in front of:
closing the tab cancels the response stream and the run dies with it.

So a build is a row in `background_tasks` (Postgres queue, SKIP LOCKED claiming, retry/cancel
endpoints already exist), executed by a registered handler:

    enqueue_build(agent_id, ontology_key, brief, project_id, auto_land)
        → POST /api/ontology/build          returns the task id immediately
    handle_ontology_build(payload, task_id) → worker: run one agent turn, then decide the landing
    build_status(task_id)                   → status + the last note + the proposal

`auto_land` is the "first generation lands itself" rule the user chose: when the staged publish has
**no new refusal and no failing gate**, it is applied automatically (a first build is a new claim, not
a change to a number people already quote). Everything after that stays a human decision, because the
editor chat's apply is about changing what a number MEANS.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TASK_TYPE = "ontology_build"

# Long: a real build reads a schema, samples rows, writes three TTL files, a profile and a tutorial,
# then runs the compress/gate suite a few times. Measured builds took 10–25 minutes.
MAX_PROGRESS_NOTES = 20


class BuildError(RuntimeError):
    """A build that cannot be enqueued or continued; the reason is meant for the user."""


def _db():
    from db.database import SessionLocal
    return SessionLocal()


# ────────────────────────────────────────────────────────── the handler
def _note(task_id: int, note: str) -> None:
    """Append one progress line to the task's payload — what the UI shows while it runs.

    There is no percentage: an agent's steps are not proportional, and a fake progress bar would be
    the one thing this project never ships. The note says what just happened.
    """
    db = _db()
    try:
        from models.background_task import BackgroundTask

        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if task is None:
            return
        payload = dict(task.payload or {})
        notes = list(payload.get("progress") or [])
        notes.append(note)
        payload["progress"] = notes[-MAX_PROGRESS_NOTES:]
        task.payload = payload
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(task, "payload")
        db.commit()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("could not record build progress for task %s: %s", task_id, exc)
    finally:
        db.close()


async def _run_build(payload: dict, task_id: int) -> dict:
    """The worker body: one agent turn, then the landing decision. Returns the task result."""
    from api.chat.messages import send_message
    from api.chat.schemas import SendMessageRequest, StartChatRequest
    from api.chat.session import start_chat_session
    from services import ontology_publish

    agent_id = int(payload["agent_id"])
    key = str(payload["ontology_key"])
    brief = str(payload.get("brief") or "").strip()
    project_id = payload.get("project_id")
    auto_land = bool(payload.get("auto_land", True))
    session_id = payload.get("session_id")

    db = _db()
    try:
        from models.deep_agent import DeepAgentTemplate

        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if agent is None:
            raise BuildError(f"no agent {agent_id} in this install")
        if not session_id:
            started = await start_chat_session(
                StartChatRequest(agent_id=agent_id, project_id=project_id), db)
            session_id = getattr(started, "session_id", None) or started["session_id"]
            _note(task_id, f"opened chat session {session_id} with {agent.name}")

        _note(task_id, "agent is reading the database and writing the declarations")
        reply = await send_message(
            SendMessageRequest(session_id=session_id, message=brief, project_id=project_id), db)
        body = reply.model_dump() if hasattr(reply, "model_dump") else dict(reply or {})
        answer = body.get("message") or ""
        tool_calls = body.get("tool_calls") or []
        _note(task_id, f"agent turn finished ({len(tool_calls)} tool call(s))")
    finally:
        db.close()

    # What did it stage? The ledger is the truth, not the agent's prose.
    staged = [r for r in ontology_publish.history(key=key, limit=20) if r.get("status") == "staged"]
    if not staged:
        return {
            "ok": False,
            "session_id": session_id,
            "ontology_key": key,
            "answer": answer,
            "tool_calls": tool_calls,
            "landed": False,
            "reason": ("the agent finished without staging a publish — nothing to install. Its answer "
                       "is above; the likely reasons are a refusal it could not resolve or a build it "
                       "left in its workspace."),
        }

    staged.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    latest = staged[0]
    report = latest.get("report") or {}
    new_refusals = report.get("new_refusals") or []
    gates_ok = report.get("gates_ok")
    gates_fails = report.get("gates_fails") or []

    landed, reason, applied = False, "", None
    if not auto_land:
        reason = "auto-land is off for this build: a person applies it in Settings → Ontology."
    elif new_refusals or gates_fails or not gates_ok:
        reason = ("not landed automatically: "
                  + (f"new refusals {new_refusals}; " if new_refusals else "")
                  + (f"failing gates {gates_fails}" if gates_fails else "")
                  + ("" if (new_refusals or gates_fails) else "gates did not pass"))
    else:
        _note(task_id, f"gates are green — auto-landing {latest['id']}")
        applied = ontology_publish.apply(latest["id"], actor=f"build-job:{agent_id}",
                                         confirmed=True, git_commit=True)
        landed = bool(applied.get("ok"))
        reason = ("landed: commit %s, workbench %s" % (
            applied.get("git_commit") or "(no commit)",
            "reloaded" if applied.get("workbench_reloaded") else
            f"NOT reloaded ({applied.get('reload_note')})")) if landed else \
            f"auto-land failed: {applied.get('error')}"

    return {
        "ok": landed or not auto_land,
        "session_id": session_id,
        "ontology_key": key,
        "answer": answer,
        "tool_calls": tool_calls,
        "staged_id": latest["id"],
        "landed": landed,
        "reason": reason,
        "report": {"compile": report.get("compile"), "gates_ok": gates_ok,
                   "gates_fails": gates_fails, "gates_not_run": report.get("gates_not_run") or [],
                   "new_refusals": new_refusals,
                   "carried_refusals": report.get("carried_refusals") or [],
                   "files": report.get("files") or []},
    }


def register() -> None:
    """Register the handler (idempotent; the decorator would double-register on re-import)."""
    from core.task_queue import register_handler

    if TASK_TYPE in {h for h in _known_types()}:
        return

    @register_handler(TASK_TYPE)
    async def _handler(payload: dict, task_id: int) -> dict:     # noqa: ANN001
        return await _run_build(payload, task_id)


def _known_types() -> list[str]:
    try:
        from core.task_queue import task_queue
        return task_queue.registry.list_handlers()
    except Exception:                                           # noqa: BLE001
        return []


def builders(db: Optional[Session] = None) -> list[dict]:
    """Who can build, and for WHICH DATA — labelled the way a person reads it.

    A UI must not ask a user to choose an agent id or type a folder name: they know "ABC 冷链物流", not
    "agent 349 / ontologies/logistics". This joins the two facts the platform already has — which
    agents carry the publish tool and the `datasource` each is wired to, plus the business label the
    database catalogue gives that datasource — so a form can ask "which data?" and nothing else.
    """
    own = db is None
    db = db or _db()
    try:
        from models.deep_agent import DeepAgentTemplate

        labels: dict[str, str] = {}
        try:
            from api.graph_studio.routes import database_catalog  # noqa: PLC0415
            for row in database_catalog() or []:
                name = row.get("name")
                if name:
                    labels[str(name)] = str(row.get("label") or name)
        except Exception as exc:                                # noqa: BLE001
            logger.warning("database catalogue unavailable for builder labels: %s", exc)

        out: list[dict] = []
        for agent in db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id).all():
            cfg = agent.config or {}
            tools = cfg.get("native_tools") or []
            if "ontology_publish" not in tools:
                continue
            datasource = cfg.get("datasource")
            if not datasource:
                continue                       # the editor edits; it does not build a dataset
            workbench = cfg.get("workbench") or {}
            profile_file = workbench.get("profile_file") or ""
            key = profile_file.replace("_settings.json", "") if profile_file else str(datasource)
            profile = workbench.get("profile") or {}
            dsn = profile.get("dsn") or {}
            out.append({
                "agent_id": agent.id,
                "agent_name": agent.name,
                "datasource": datasource,
                "ontology_key": key,
                "business_label": labels.get(str(datasource), str(datasource)),
                "database": dsn.get("dbname"),
                "has_ontology": bool(workbench.get("profile")),
            })
        return out
    finally:
        if own:
            db.close()


# ────────────────────────────────────────────────────────── API helpers
async def enqueue_build(agent_id: int, ontology_key: str, brief: str, *, project_id: Optional[int] = None,
                        auto_land: bool = True,
                        session_id: Optional[str] = None) -> dict:
    """Queue one build. Returns immediately with the task id — the agent runs in a worker."""
    from core.task_queue import task_queue

    key = (ontology_key or "").strip()
    text = (brief or "").strip()
    if not key or "/" in key or key.startswith("."):
        raise BuildError("ontology_key must be a folder name under ontologies/, e.g. 'logistics'")
    if not text:
        raise BuildError("a build needs a brief: objects, the questions users ask, the decisions "
                         "the numbers support")
    register()
    task_id = await task_queue.enqueue(TASK_TYPE, {
        "agent_id": int(agent_id),
        "ontology_key": key,
        "brief": text,
        "project_id": project_id,
        "auto_land": bool(auto_land),
        "session_id": session_id,
    })
    return {"ok": True, "task_id": task_id, "ontology_key": key, "auto_land": bool(auto_land)}


def build_status(task_id: int, db: Optional[Session] = None) -> dict:
    """Status + the last progress notes + the proposal, in one read for the panel."""
    own = db is None
    db = db or _db()
    try:
        from models.background_task import BackgroundTask

        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if task is None:
            return {"ok": False, "error": f"no build task {task_id}"}
        payload = task.payload or {}
        result = task.result if isinstance(task.result, dict) else {}
        staged = result.get("staged_id")
        proposal = None
        if staged:
            from services import ontology_editor
            proposal = next((p for p in ontology_editor.proposals(db, payload.get("ontology_key", ""))
                             if p["id"] == staged), None)
        return {
            "ok": True,
            "task_id": task.id,
            "status": task.status,
            "ontology_key": payload.get("ontology_key"),
            "agent_id": payload.get("agent_id"),
            "auto_land": payload.get("auto_land"),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "progress": payload.get("progress") or [],
            "error": task.error,
            "result": result or None,
            "proposal": proposal,
        }
    finally:
        if own:
            db.close()


def recent_builds(db: Optional[Session] = None, ontology_key: Optional[str] = None,
                  limit: int = 10) -> list[dict]:
    """The builds for one ontology (newest first) — what the panel shows after a reload."""
    own = db is None
    db = db or _db()
    try:
        from models.background_task import BackgroundTask

        q = db.query(BackgroundTask).filter(BackgroundTask.task_type == TASK_TYPE)
        rows = q.order_by(BackgroundTask.id.desc()).limit(max(limit * 5, 25)).all()
        out = []
        for task in rows:
            payload = task.payload or {}
            if ontology_key and payload.get("ontology_key") != ontology_key:
                continue
            out.append({
                "task_id": task.id,
                "status": task.status,
                "ontology_key": payload.get("ontology_key"),
                "agent_id": payload.get("agent_id"),
                "auto_land": payload.get("auto_land"),
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "staged_id": (task.result or {}).get("staged_id") if isinstance(task.result, dict) else None,
                "landed": (task.result or {}).get("landed") if isinstance(task.result, dict) else None,
            })
            if len(out) >= limit:
                break
        return out
    finally:
        if own:
            db.close()
