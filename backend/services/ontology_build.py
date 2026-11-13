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

import asyncio
import json
import logging
import os
import pathlib
from typing import Optional

from sqlalchemy.orm import Session

from services import ontology_publish as _pub   # noqa: E402  (the installed-ontology fact)

logger = logging.getLogger(__name__)

# A build is ONE agent turn, and that turn can hang: measured twice on the deployment — two builds sat
# "RUNNING" for 35+ minutes with zero file writes, ~0 % CPU (so: waiting on the model, not looping),
# and the queue row never settled because a restart killed the worker that owned it. A hang with no
# timeout is the worst failure mode: it looks alive, blocks the retry, and teaches the operator nothing.
# The cap is generous (a real build turn has been measured at a few minutes) and it is a FAILURE, with
# the second count, not a silent stop.
# 20 minutes KILLED a productive turn on the deployment: it had written 61 compiled metrics and
# 30 KB of axioms and was still going. The cap exists to catch a SILENT hang (measured: 35+ min with
# zero file writes), not to interrupt work, so it is now 45 minutes.
TURN_TIMEOUT_SECONDS = int(os.getenv("ONTOLOGY_BUILD_TURN_TIMEOUT", "2700"))

# A build IS one long agent turn, and the provider's SSE stream can drop in the middle of it. Measured
# on the deployment: `httpx.ReadError` from api.deepseek.com after "200 OK", twice in a row, and the
# whole turn was lost — no error in the task, just a row that stayed RUNNING. A dropped stream is a
# transport failure, not a wrong answer: the session still holds everything done so far, so the cheap
# fix is to ask it to CONTINUE rather than to start over.
STREAM_RETRIES = int(os.getenv("ONTOLOGY_BUILD_STREAM_RETRIES", "2"))
STREAM_RETRY_BACKOFF_SECONDS = float(os.getenv("ONTOLOGY_BUILD_STREAM_BACKOFF", "5"))

CONTINUE_AFTER_DROP = (
    "上一轮的模型连接在传输中途断开了（不是你的错，重试机制已经接上）。"
    "请**接着做**，不要重做：先看一眼 work/<key>/ 下已经写好的文件，从最后一个落盘的步骤之后继续；"
    "每完成一步就把文件写盘，并在回答里用一行报进度。"
)


def _is_stream_drop(exc: BaseException) -> bool:
    """Did the MODEL STREAM die (transport), rather than the work fail?

    Walks the cause chain: an HTTPException(500) from `send_message` wraps the httpx/openai error, and
    only the leaf names what happened. A TimeoutError is handled separately (that one fails the task).
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__.lower()
        text = f"{type(cur).__name__}: {cur}"
        if any(t in name for t in ("readerror", "remote protocol", "remoteprotocol",
                                   "connectionerror", "apiconnection", "incompleteread")):
            return True
        if "server disconnected" in text.lower() or "peer closed" in text.lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False

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


def _record_session(task_id: int, session_id: str) -> None:
    """Pin the session id onto the task's payload the moment it exists.

    `result` is written once, at the end of the turn. So a build that was still running (or that was
    cancelled) had no session anywhere — which is exactly why "resume task 12" was unanswerable: the id
    lived in a dict that only appeared after the thing you wanted to resume had already finished.
    """
    if not session_id:
        return
    db = _db()
    try:
        from models.background_task import BackgroundTask
        from sqlalchemy.orm.attributes import flag_modified

        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if task is None:
            return
        payload = dict(task.payload or {})
        if payload.get("session_id") == session_id:
            return
        payload["session_id"] = session_id
        task.payload = payload
        flag_modified(task, "payload")
        db.commit()
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("could not record the session for task %s: %s", task_id, exc)
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


def _agent_workspace(agent_id: int, project_id) -> pathlib.Path | None:
    """Where this agent writes — the same resolution the runner uses, so a reader sees the same files."""
    try:
        from services.workspace_manager import get_workspace_manager
        from models.deep_agent import DeepAgentTemplate as _T

        db = _db()
        try:
            agent = db.query(_T).filter(_T.id == agent_id).first()
            if agent is None:
                return None
            ws = get_workspace_manager()
            return ws.resolve_agent_workspace(
                agent, project_id,
                vault_key=ws.project_vault_key(db, project_id) or None,
                agent_key=ws.agent_vault_key(db, agent),
            )
        finally:
            db.close()
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("could not resolve the workspace for agent %s: %s", agent_id, exc)
        return None


def _tasks_needing_answers(limit: int = 8, include_answered: bool = False) -> list[dict]:
    """Builds that STOPPED on questions — the ones a person can still answer.

    A build's `questions.json` is written into the agent's workspace and then nothing reads it: the
    agent's prose says "I have nine questions", the UI shows that prose, and the answers have to be
    retyped into a fresh brief that starts a NEW session — losing the measurements it took. This turns
    the file into the list a panel can render, together with the session that must be continued.
    """
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    db = _db()
    try:
        from models.background_task import BackgroundTask

        rows = (db.query(BackgroundTask)
                  .filter(BackgroundTask.task_type == TASK_TYPE)
                  .order_by(BackgroundTask.id.desc())
                  .limit(40).all())
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            key = str(payload.get("ontology_key") or "")
            agent_id = int(payload.get("agent_id") or 0)
            if not key or not agent_id:
                continue
            if (agent_id, key) in seen:
                continue                     # a newer task for this key already answers for it
            seen.add((agent_id, key))
            workspace = _agent_workspace(agent_id, payload.get("project_id"))
            if workspace is None:
                continue
            base = pathlib.Path(workspace) / "work" / key
            # Where an agent actually writes its questions. `work/<key>/questions.json` is the
            # documented path, and it is not the only one agents reach for: measured twice on
            # 2026-11-13 — one build wrote `generated/questions.json`, another wrote a markdown
            # decision list — and in both cases the person was never asked, because this reader
            # only knew the documented path. The RULE can stay where it is; the READER has to
            # accept what the runtime produces, or "nobody answered" looks like "nobody asked".
            qdoc, qpath = None, None
            for candidate in (base / "questions.json",
                              pathlib.Path(workspace) / "generated" / "questions.json",
                              pathlib.Path(workspace) / "questions.json"):
                if not candidate.is_file():
                    continue
                try:
                    qdoc = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:                                # noqa: BLE001
                    continue
                qpath = candidate
                break
            if qdoc is None:
                continue
            # two shapes are legal: `{"questions": [...]}` and a bare list of questions
            raw = qdoc.get("questions") if isinstance(qdoc, dict) else qdoc
            questions = [q for q in (raw or []) if isinstance(q, dict)]
            if not questions:
                continue
            answered = _answers_recorded(base, questions)
            if not include_answered and answered >= len(questions):
                continue                     # nothing left to answer here
            out.append({
                "task_id": row.id,
                "agent_id": agent_id,
                "ontology_key": key,
                "status": row.status,
                # payload first: it exists while the turn is still running (see _record_session)
                "session_id": (payload.get("session_id")
                               or (row.result.get("session_id")
                                   if isinstance(row.result, dict) else None)),
                "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
                "questions": questions,
                "answered": answered,
                "missing_documents": _missing_documents(questions),
            })
            if len(out) >= limit:
                break
        return out
    finally:
        db.close()


def _recent_builds(limit_per_key: int = 3) -> list[dict]:
    """The last few builds per (agent, key) WITH the session each one owns.

    A build is one agent turn: it ends when the turn ends, and continuing means sending a new brief
    into the SAME session. The task list is the only place that session id exists — the dialog starts a
    fresh one every time — so "resume task 12" had no clickable path at all. This is that path.
    """
    out: list[dict] = []
    per_key: dict[tuple[int, str], int] = {}
    db = _db()
    try:
        from models.background_task import BackgroundTask

        rows = (db.query(BackgroundTask)
                  .filter(BackgroundTask.task_type == TASK_TYPE)
                  .order_by(BackgroundTask.id.desc())
                  .limit(60).all())
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            key = str(payload.get("ontology_key") or "")
            agent_id = int(payload.get("agent_id") or 0)
            if not key or not agent_id:
                continue
            slot = (agent_id, key)
            if per_key.get(slot, 0) >= limit_per_key:
                continue
            per_key[slot] = per_key.get(slot, 0) + 1
            result = row.result if isinstance(row.result, dict) else {}
            out.append({
                "task_id": row.id,
                "agent_id": agent_id,
                "ontology_key": key,
                "status": row.status,
                "session_id": payload.get("session_id") or result.get("session_id"),
                "landed": bool(result.get("landed")),
                "reason": (str(result.get("reason") or "")[:160] or None),
                "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
            })
        return out
    finally:
        db.close()


def _answers_recorded(base: pathlib.Path, questions: list[dict]) -> int:
    """How many of these questions already have an answer recorded (`answers.json` / an answer brief)."""
    path = base / "answers.json"
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return 0
    have = {str(a.get("id")) for a in (data.get("answers") or []) if isinstance(a, dict)}
    return sum(1 for q in questions if str(q.get("id")) in have)


def _missing_documents(questions: list[dict]) -> list[str]:
    """Documents a question says it CANNOT read — named, so the panel can ask for them by name.

    Read sentence by sentence, because the sentence that names them also names the one that arrived:
    measured — "只到了 DEMO案例.xlsx；X.docx 和 Y.md 不在我的工作区" listed all three as missing, and
    the panel then asked the reader to upload a file the agent already had.
    """
    import re
    HAVE = ("只到", "已在", "收到", "读到了", "在工作区里", "in my workspace")
    MISSING = ("不在", "读不到", "没有", "missing", "cannot read", "缺")
    found: list[str] = []
    present: set[str] = set()
    for q in questions:
        text = " ".join(str(q.get(k) or "") for k in ("ask", "default", "evidence"))
        for sentence in re.split(r"[。；;！？\n]", text):
            names = re.findall(r"[\w\u4e00-\u9fff.\-]+\.(?:docx|xlsx|md|pdf|csv)", sentence)
            if not names:
                continue
            if any(h in sentence for h in HAVE) and not any(m in sentence for m in MISSING):
                present.update(names)
                continue
            if any(m in sentence for m in MISSING):
                for name in names:
                    if name not in found:
                        found.append(name)
    return [n for n in found if n not in present]


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
        _record_session(task_id, str(session_id))

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
        async def one_turn(text: str):
            return await asyncio.wait_for(
                send_message(
                    SendMessageRequest(session_id=session_id, message=text, project_id=project_id), db),
                timeout=TURN_TIMEOUT_SECONDS,
            )

        reply = None
        for attempt in range(STREAM_RETRIES + 1):
            try:
                reply = await one_turn(message if attempt == 0 else
                                       CONTINUE_AFTER_DROP.replace("<key>", key))
                break
            except asyncio.TimeoutError as exc:
                # A turn that never returns must FAIL, with the number, and let the queue settle the
                # row: a build that stays RUNNING forever blocks the retry and teaches nobody anything.
                raise BuildError(
                    f"the agent's turn did not return within {TURN_TIMEOUT_SECONDS}s "
                    f"(session {session_id}); the build was stopped. Re-run it with a narrower brief, "
                    f"or raise ONTOLOGY_BUILD_TURN_TIMEOUT if the model is simply slow."
                ) from exc
            except Exception as exc:                                # noqa: BLE001
                if attempt >= STREAM_RETRIES or not _is_stream_drop(exc):
                    raise
                _note(task_id, f"the model stream dropped ({type(exc).__name__}); "
                               f"asking it to continue ({attempt + 1}/{STREAM_RETRIES})")
                await asyncio.sleep(STREAM_RETRY_BACKOFF_SECONDS * (attempt + 1))
        if reply is None:                                           # unreachable; kept honest
            raise BuildError(f"the agent never answered (session {session_id})")
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


def sweep_orphans() -> int:
    """A restart ends every running turn, so every RUNNING build row is now a lie.

    Measured: a `systemctl restart` during a build left task 13 RUNNING with 1 progress note and no
    process behind it. A row that claims to be running is not cosmetic — the UI disables 续跑 on it, so
    the build became unresumable precisely because it was stuck. One process serves the turns
    (UVICORN_WORKERS=1), therefore at startup any unfinished row belongs to a turn that no longer
    exists and must be marked CANCELLED with the reason written down.
    """
    db = _db()
    try:
        from models.background_task import BackgroundTask
        from sqlalchemy.orm.attributes import flag_modified

        rows = (db.query(BackgroundTask)
                  .filter(BackgroundTask.task_type == TASK_TYPE,
                          BackgroundTask.status.in_(["RUNNING", "PENDING"]))
                  .all())
        for row in rows:
            payload = dict(row.payload or {})
            payload["progress"] = list(payload.get("progress") or []) + [
                "cancelled: the API restarted while this turn was running, so the turn is gone — "
                "resume it (its workspace and session are intact)"]
            row.payload = payload
            flag_modified(row, "payload")
            row.status = "CANCELLED"
        if rows:
            db.commit()
            logger.warning("swept %d orphaned build task(s) at startup: %s",
                           len(rows), [r.id for r in rows])
        return len(rows)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("could not sweep orphaned build tasks: %s", exc)
        return 0
    finally:
        db.close()


_SWEPT = False


def register() -> None:
    """Register the handler (idempotent; the decorator would double-register on re-import)."""
    from core.task_queue import register_handler

    # ONCE per process. `enqueue_build` calls register() on every build, so an unguarded sweep here
    # would cancel the build that is already running — the sweeping tool cannot tell an orphan from a
    # live turn, it can only know that no turn survived the process that wrote the row.
    global _SWEPT
    if not _SWEPT:
        _SWEPT = True
        sweep_orphans()

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
            # `database` is what the build dialog shows as "which data is this about". It used to come
            # from the agent's `workbench.profile` block alone, so an agent seeded WITHOUT that block
            # (355, 376 — the newer seed writes `datasource` instead) advertised no database at all
            # while its datasource named one. The datasource is the connection the agent actually
            # gets, so it is the fallback that cannot disagree with the run.
            if not dsn.get("dbname"):
                try:
                    from services.deepagent_factory.assembly import _datasource_env  # noqa: PLC0415
                    _env, _dsn = _datasource_env(str(datasource))
                    dsn = {**(dsn or {}), **({"dbname": _env.get("PGDATABASE")} if _env.get("PGDATABASE") else {})}
                except Exception as exc:                        # noqa: BLE001
                    logger.debug("datasource %s has no resolvable dbname: %s", datasource, exc)
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
def active_build(agent_id: int, ontology_key: str) -> Optional[dict]:
    """The unfinished build for this exact (agent, key), if there is one.

    Two people on one instance is the normal case now, and one agent+key is ONE workspace and ONE
    conversation: a second build started on top of a running one writes into the same `work/<key>/`
    and answers the same session twice, which produces a half-merged ontology and no error anywhere.
    The busy state is checked here, at the moment a build is asked for, not in the UI.
    """
    db = _db()
    try:
        from models.background_task import BackgroundTask

        rows = (db.query(BackgroundTask)
                  .filter(BackgroundTask.task_type == TASK_TYPE,
                          BackgroundTask.status.in_(["RUNNING", "PENDING"]))
                  .order_by(BackgroundTask.id.desc()).limit(50).all())
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            if int(payload.get("agent_id") or 0) != int(agent_id):
                continue
            if str(payload.get("ontology_key") or "") != str(ontology_key):
                continue
            return {"task_id": row.id, "status": row.status,
                    "session_id": payload.get("session_id"),
                    "since": row.created_at.isoformat() if getattr(row, "created_at", None) else None}
        return None
    finally:
        db.close()


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
    busy = active_build(int(agent_id), key)
    if busy is not None:
        raise BuildError(
            f"{key} is already building on this agent (task {busy['task_id']}, {busy['status']}). "
            f"One agent+key is one workspace and one conversation, so a second build would answer the "
            f"same session twice. Wait for it, or continue that task instead of starting another.")
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
