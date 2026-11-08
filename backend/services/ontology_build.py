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

import json
import logging
import pathlib
from typing import Optional

from sqlalchemy.orm import Session

from services import ontology_publish as _pub   # noqa: E402  (the installed-ontology fact)

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


# ── the rebuild seed, and the delta verdict ─────────────────────────────────────────────────────
def _installed_dir(key: str):
    root = getattr(_pub, "ONTOLOGIES", None)
    if root is None:
        return None
    d = pathlib.Path(root) / key
    return d if d.is_dir() else None


def _installed_facts(key: str) -> dict:
    """What the installed ontology already declares — small enough to put IN the prompt.

    Measured: a rebuild turn that had to open `01-structure.ttl` (597 lines) + `metrics_ext.ttl` + the
    uploaded documents spent 285 s and 188 tool calls and wrote nothing; the same job, with this list
    handed over inline, answered in 12 s / 1 tool call. The platform knows these facts, so it composes
    them instead of making the model read a 600-line file to learn 28 names.
    """
    d = _installed_dir(key)
    if d is None:
        return {}
    metrics = []
    ttl = d / "metrics_ext.ttl"
    if ttl.is_file():
        for line in ttl.read_text(encoding="utf-8").splitlines():
            if "a owl:DatatypeProperty" not in line:
                continue
            raw = line.split(":", 1)[1] if ":" in line else line
            name = raw.split()[0].strip() if raw.split() else ""
            label = ""
            if 'rdfs:label "' in line:
                label = line.split('rdfs:label "', 1)[1].split('"', 1)[0]
            if name:
                metrics.append(name + (f"({label})" if label else ""))
    objects = []
    struct = d / "ontology" / "01-structure.ttl"
    if struct.is_file():
        for line in struct.read_text(encoding="utf-8").splitlines():
            if "a owl:Class" in line and line.strip().startswith(":"):
                objects.append(line.strip().split(":", 1)[1].split()[0])
    settings = {}
    try:
        import json as _json
        settings = _json.loads((d / f"{key}_settings.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        settings = {}
    return {"objects": objects, "metrics": metrics,
            "samples": len(settings.get("samples") or []),
            "guard": settings.get("guard") or {}}


def _rebuild_seed(key: str) -> str:
    """The context a rebuild must start from: installed declarations + the answers already given.

    A rebuild is not "build it again": it is "prove what changed against the installed declarations,
    then ask only about the delta". The seed says that, in the words the skill uses.
    """
    facts = _installed_facts(key)
    if not facts:
        return ""
    lines = [
        "## 这次是 **重建**，不是首次生成",
        "",
        f"已装本体 `{key}` 已经声明了 {len(facts.get('objects') or [])} 个对象、{len(facts.get('metrics') or [])} 个指标、"
        f"{facts.get('samples') or 0} 条样例。**先证明 delta，再动手**：",
        "",
        "1. 对照【已装声明】+【上次口径】+【本次文档】，产出 `work/<key>/delta.json`："
        "`{\"items\": [{\"kind\": \"unchanged|changed|added|removed\", ...}], \"questions\": [], \"skip\": []}`；",
        "2. 若 `changed=added=removed=0` 且 `questions` 为空，**停在这里**，最后一行输出"
        " `NO DELTA`（不要重编译、不要跑 S1..S8、不要 publish —— 没有 delta 就没有要建的东西）；",
        "3. 只有 delta 非空时才继续 ladder，且**只改 delta 涉及的声明**；与已装冲突的必须问业务（进 questions，带 default）。",
        "",
        "【已装指标】" + "、".join(facts.get("metrics") or []) or "",
        "",
        "【已装对象】" + "、".join(facts.get("objects") or []),
        "",
    ]
    answers = _answers_of(key)
    if answers:
        lines += ["【上次口径（已答，不要重复问）】" + answers, ""]
    return "\n".join([ln for ln in lines if ln is not None])


def _answers_of(key: str) -> str:
    """The answers already recorded for this ontology, one line each — cheap and decisive."""
    d = _installed_dir(key)
    candidates = []
    if d is not None:
        candidates.append(d / ".build" / "answers.json")
    # the builder's workspace copy, where the skill writes it
    try:
        from services.workspace_manager import get_workspace_manager
        ws = get_workspace_manager()
        for agent_dir in (pathlib.Path(getattr(ws, "ROOT", "")) if getattr(ws, "ROOT", None) else None,) if False else ():
            pass
    except Exception:                                            # noqa: BLE001
        pass
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:                                    # noqa: BLE001
                continue
            rows = data.get("answers") or []
            out = "; ".join(f"{r.get('id')}={r.get('answer')}" + ("(assumed)" if r.get("assumed") else "")
                            for r in rows if isinstance(r, dict))
            if out:
                return out[:1500]
    return ""


def _delta_of(workspace: pathlib.Path | None, key: str) -> dict | None:
    """`work/<key>/delta.json` if the agent produced one. The ledger is the truth, not the prose."""
    if workspace is None:
        return None
    path = pathlib.Path(workspace) / "work" / key / "delta.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    items = data.get("items") or []
    changed = sum(1 for i in items if isinstance(i, dict) and i.get("kind") in ("changed", "added", "removed"))
    return {"path": str(path), "items": len(items), "changed": changed,
            "questions": len(data.get("questions") or []),
            "unchanged": sum(1 for i in items if isinstance(i, dict) and i.get("kind") == "unchanged")}


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

        # A REBUILD gets the installed facts IN the prompt. Measured: without this the turn explored the
        # installed TTL and the documents for 285 s / 188 tool calls and wrote nothing; with it, 12 s /
        # 1 tool call. The platform knows these facts — making the model read 600 lines to learn 28 names
        # is the expensive way to ask.
        message = brief
        if _installed_dir(key) is not None:
            seed = _rebuild_seed(key)
            if seed:
                message = seed + "\n\n" + brief
                _note(task_id, "rebuild: the installed declarations and the answers already given are in the prompt")

        _note(task_id, "agent is proving the delta" if _installed_dir(key) is not None
              else "agent is reading the database and writing the declarations")
        reply = await send_message(
            SendMessageRequest(session_id=session_id, message=message, project_id=project_id), db)
        body = reply.model_dump() if hasattr(reply, "model_dump") else dict(reply or {})
        answer = body.get("message") or ""
        tool_calls = body.get("tool_calls") or []
        _note(task_id, f"agent turn finished ({len(tool_calls)} tool call(s))")
    finally:
        db.close()

    # A rebuild that proves NO DELTA is a finished job, not a failure: the documents already agree with
    # the installed ontology, so re-running the ladder would rewrite green declarations for nothing.
    # The verdict comes from the artifact (`work/<key>/delta.json`), never from the agent's prose.
    workspace = None
    try:
        from services.workspace_manager import get_workspace_manager
        from models.deep_agent import DeepAgentTemplate as _T
        _db2 = _db()
        try:
            _agent = _db2.query(_T).filter(_T.id == agent_id).first()
            _ws = get_workspace_manager()
            workspace = _ws.resolve_agent_workspace(
                _agent, project_id,
                vault_key=_ws.project_vault_key(_db2, project_id) or None,
                agent_key=_ws.agent_vault_key(_db2, _agent),
            ) if _agent is not None else None
        finally:
            _db2.close()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("could not resolve the build workspace: %s", exc)

    delta = _delta_of(workspace, key)
    if delta and delta["changed"] == 0 and delta["questions"] == 0:
        _note(task_id, f"NO DELTA — {delta['unchanged']} item(s) compared, 0 changed, 0 questions "
                       f"({delta['path']})")
        return {
            "ok": True,
            "no_delta": True,
            "delta": delta,
            "session_id": session_id,
            "ontology_key": key,
            "answer": answer,
            "tool_calls": tool_calls,
            "landed": False,
            "reason": (f"no delta: the material agrees with the installed ontology on all "
                       f"{delta['items']} item(s) — nothing to rebuild, so nothing was staged. "
                       f"To change a number, say which one and what it should become."),
        }
    if delta:
        _note(task_id, f"delta: {delta['changed']} change(s), {delta['questions']} question(s) "
                       f"({delta['path']})")

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
            "delta": delta,
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
    # IS THIS A FIRST GENERATION OR A REBUILD? `auto_land` means "a first generation lands itself"
    # — a new claim, not a change to a number people already quote. A rebuild of an ontology that is
    # already installed is the SECOND case, and auto-landing one replaces verified declarations with a
    # fresh generation without anybody reading the diff. Measured: the dialog defaulted auto-land to
    # true for every key, so rebuilding the just-installed new_coldchain would have installed itself.
    # The installed profile is the fact that decides it, and this checks it at decision time.
    root = getattr(ontology_publish, "ONTOLOGIES", None)
    already_installed = bool(root is not None and (pathlib.Path(root) / key).is_dir())
    if not auto_land:
        reason = "auto-land is off for this build: a person applies it in Settings → Ontology."
    elif already_installed:
        reason = ("not landed automatically: this ontology is ALREADY INSTALLED, so this is a rebuild, "
                  "not a first generation — a person applies it in Settings → Ontology.")
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
            # Which ONTOLOGY this agent builds is declared by the agent, not inferred from its
            # datasource: a second builder on the SAME database is the normal way to start a fresh
            # ontology ("new_coldchain_v2") without touching the installed one. Measured: a seeded
            # v2 builder was offered in the dialog as `new_coldchain`, so clicking it would have
            # rebuilt the installed ontology instead of starting the fresh one.
            skill_params = (cfg.get("skill_params") or {}).get("build-ontology-from-db") or {}
            key = (skill_params.get("ontology_key") or cfg.get("ontology_key")
                   or (profile_file.replace("_settings.json", "") if profile_file else "")
                   or str(datasource))
            profile = workbench.get("profile") or {}
            dsn = profile.get("dsn") or {}
            # `has_ontology` decides two things a person sees — "首次生成" vs "重建", and whether
            # auto-land may default on — so it must answer "is this installed", not "does this agent's
            # config happen to carry a workbench block". Measured: agent 355's config has no workbench
            # block, so new_coldchain was advertised as 尚无本体 while its profile was already installed.
            root = getattr(_pub, "ONTOLOGIES", None)
            installed = bool(root is not None and (pathlib.Path(root) / key).is_dir())
            out.append({
                "agent_id": agent.id,
                "agent_name": agent.name,
                "datasource": datasource,
                "ontology_key": key,
                "business_label": labels.get(str(datasource), str(datasource)),
                "database": dsn.get("dbname"),
                "has_ontology": bool(workbench.get("profile")) or installed,
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
