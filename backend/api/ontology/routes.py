"""Ontology workbench routes.

The workbench is one process per ontology profile, and nobody should have to start them by
hand: these endpoints report what is running and start whatever is not. The supervisor lives
in `services/ontology_workbench.py` (lazy start, one child per profile, health = the
workbench's own answer).
"""
from __future__ import annotations

import asyncio
import logging
import datetime
import pathlib

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from services import (ontology_actions, ontology_build, ontology_dashboard, ontology_editor,
                      ontology_pages, ontology_publish, ontology_samples, ontology_tutorial_chapters,
                      ontology_workbench)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/installed")
async def list_installed():
    """Every ontology that is INSTALLED, derived from the profiles on disk.

    A published ontology must appear in the Ontology activity without anyone editing a list. Measured:
    v6 applied twice (48/48 and 32/32 compiled, gates green) and still could not be found, because the
    activity renders the `ontology` settings document and nothing had added a row for it — the list was
    a hand-maintained roster, and a roster rots. The settings document now only carries DECISIONS about
    those ontologies (label override, note, order, enabled), never their existence.
    """
    from services import ontology_publish

    root = pathlib.Path(ontology_publish.ONTOLOGIES)
    rows = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            profile = None
            for name in (f"{d.name}_settings.json", "settings.json"):
                if (d / name).is_file():
                    profile = name
                    break
            if profile is None:
                continue                      # a folder without a profile is not an ontology
            title = None
            try:
                import json as _json
                title = (_json.loads((d / profile).read_text(encoding="utf-8")) or {}).get("title")
            except Exception:                                  # noqa: BLE001
                title = None
            # WHEN it was last touched, so the activity can be read newest-first. It is the newest
            # mtime among the DECLARATION files (the TTLs, the overlay, the settings, the dashboard,
            # the samples) — not the folder's, which a `.staging/` copy or a backup run also updates.
            # A publish rewrites TTLs, so this is exactly "when did this ontology last change".
            newest = 0.0
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(d)
                if rel.parts and rel.parts[0] in (".staging", ".backup", ".archive"):
                    continue
                if f.suffix not in (".ttl", ".json", ".sql"):
                    continue
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    continue
            rows.append({"key": d.name, "label": (title or d.name), "profile": f"{d.name}/{profile}",
                         "installed": True,
                         "modified_at": datetime.datetime.fromtimestamp(newest, datetime.timezone.utc).isoformat()
                                        if newest else None})
    return {"ok": True, "installed": rows}


@router.get("/workbenches")
async def list_workbenches(ensure: bool = False):
    """The per-ontology workbench servers — a DEVELOPMENT tool, not what serves the app.

    Every page and every number the app shows is compiled in-process; these five ports exist only to
    look at one profile's raw pages while editing them. `ensure=true` starts what is missing (that is
    the development flow) and is explicit on purpose: nothing in the UI turns it on any more.
    """
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
    # The gate suite shells out and may run for minutes (timeout 600 s). Called directly inside an
    # `async def` it blocks the ONLY worker's event loop, so /health stopped answering while a build
    # staged (measured on the deployment: health 000, load 0.5). A thread keeps the loop free; the
    # service layer is untouched and already thread-safe (own session, own runtime lock).
    return await asyncio.to_thread(
        ontology_publish.stage, req.key, req.files, actor=actor, note=req.note or "",
        profile_name=req.profile_name)


@router.post("/publish/{staged_id}/apply")
async def publish_apply(staged_id: str, req: ApplyRequest):
    """Install a staged publish. Needs `confirmed` from a human (agents cannot confirm)."""
    actor = _require_editor()
    if not req.confirmed:
        raise HTTPException(400, "confirmed=false: a publish lands only after a human says so")
    res = await asyncio.to_thread(
        ontology_publish.apply, staged_id, actor=actor, confirmed=True,
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


# ── the dashboard: a declaration, run ───────────────────────────────────────
# A dashboard is `<profile dir>/dashboard.json`: which DECLARED metric each panel shows, what it is
# cut by, and what a missing one costs. These two routes carry that declaration through the
# ontology's own compiler — they never name a metric themselves, so a panel cannot show a number
# the ontology does not declare, and a panel that cannot answer arrives as a refusal, not as a gap.

@router.get("/dashboards")
async def dashboards():
    """Which ontologies have a dashboard declaration (a nav must not invent entries)."""
    return {"ok": True, "ontologies": ontology_dashboard.installed()}


@router.get("/{key}/dashboard/panels")
async def dashboard_panels(key: str, refresh: bool = False, filter: Optional[str] = None):
    """Every panel + its data, or the refusal that names what is missing.

    `refresh=true` re-runs it (the cache is 30 s so a page reload does not re-scan the warehouse).
    """
    try:
        payload = await asyncio.to_thread(ontology_dashboard.panels, key,
                                        refresh=refresh, filter=filter)
        return {"ok": True, **payload}
    except ontology_dashboard.DashboardError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── the pages and documents the app used to fetch from a per-ontology workbench ────────────
# Five workbench processes existed to serve three JSON documents and a few HTML pages. The compiler is
# in this process now, so these routes serve the same shapes from the same declarations — one origin,
# no ports, and no second resolver to disagree about which ontology a page belongs to.

@router.get("/{key}/document")
async def ontology_document(key: str, refresh: bool = False):
    """Objects, definitions, links and metrics of one ontology (the browser page's whole input).

    Cached on the declaration files; `refresh=true` recompiles now (the browser's reload button).
    """
    try:
        doc = await asyncio.to_thread(ontology_pages.document, key, refresh)
        return {"ok": True, **doc}
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/metrics/cards")
async def ontology_metric_cards(key: str, refresh: bool = False):
    """Every metric as a card: declaration, compiled SQL, value under the guard — or the refusal.

    One query per metric, cached for half a minute; `refresh=true` re-runs them all.
    """
    try:
        cards = await asyncio.to_thread(ontology_pages.cards, key, refresh)
        return {"ok": True, "cards": cards}
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/sections")
async def ontology_sections(key: str):
    """Which sections this profile serves; a switched-off one is named, not omitted silently."""
    try:
        return {"ok": True, "key": key, "sections": ontology_pages.sections(key)}
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/tutorial/steps")
async def ontology_tutorial_steps(key: str):
    try:
        return ontology_pages.steps(key)
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/tutorial/run")
async def ontology_tutorial_run(key: str, metric: str):
    try:
        return ontology_pages.tutorial_run(key, metric)
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/tutorial/definition")
async def ontology_tutorial_definition(key: str, cls: str = Query(default="", alias="class")):
    """One definition's compiled predicate and the rows it selects (`?class=…`, a reserved word here)."""
    try:
        return ontology_pages.tutorial_definition(key, cls)
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── the conversational build: same builder agent as the job, but a chat ─────────────────────
class BuildChatRequest(BaseModel):
    message: str = ""
    session_id: Optional[str] = None
    project_id: Optional[int] = None


@router.get("/{key}/build/state")
async def build_chat_state(key: str):
    """What a build conversation starts from: installed facts, documents, artifacts, proposals."""
    from db.database import SessionLocal
    from services import ontology_build_chat

    db = SessionLocal()
    try:
        return ontology_build_chat.state(db, key)
    except ontology_build_chat.BuildChatUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        db.close()


@router.post("/{key}/build/ask")
async def build_chat_ask(key: str, req: BuildChatRequest):
    """One builder turn, non-streaming (the CLI and the smoke tests use this)."""
    from db.database import SessionLocal
    from services import ontology_build_chat

    db = SessionLocal()
    try:
        return await ontology_build_chat.ask(db, key, req.message, session_id=req.session_id,
                                             project_id=req.project_id)
    except ontology_build_chat.BuildChatUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        db.close()


@router.post("/{key}/build/ask/stream")
async def build_chat_stream(key: str, req: BuildChatRequest):
    """One builder turn, STREAMED — the chat panel's endpoint (same events as the global chat)."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from api.chat.messages import send_message_stream
    from api.chat.schemas import SendMessageRequest
    from db.database import SessionLocal
    from services import ontology_build_chat

    prep_db = SessionLocal()
    try:
        prompt = await ontology_build_chat.prepare(prep_db, key, req.message,
                                                   session_id=req.session_id,
                                                   project_id=req.project_id)
    except ontology_build_chat.BuildChatUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        prep_db.close()

    stream_db = SessionLocal()
    inner = await send_message_stream(
        SendMessageRequest(session_id=prompt["session_id"], message=prompt["message"],
                           project_id=req.project_id), stream_db)

    async def with_session():
        head = {"type": "session", "session_id": prompt["session_id"], "key": prompt["key"],
                "seeded": prompt["seeded"],
                "agent": {"id": prompt["agent_id"], "name": prompt["agent_name"]}}
        yield f"data: {_json.dumps(head, ensure_ascii=False)}\n\n"
        try:
            async for chunk in inner.body_iterator:
                yield chunk
        finally:
            stream_db.close()

    return StreamingResponse(with_session(), media_type="text/event-stream")


@router.get("/{key}/page/{name}")
async def ontology_page(key: str, name: str):
    """Serve one of this profile's OWN HTML pages, from this origin.

    The tutorial page's JavaScript calls absolute `/api/tutorial/...` paths; `ontology_pages.page`
    rewrites them to this ontology's routes at serve time, which is the whole compatibility layer.
    """
    try:
        html, content_type = ontology_pages.page(key, name)
        return Response(content=html, media_type=content_type)
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{key}/asset/{name}")
async def ontology_page_asset(key: str, name: str):
    """A page's own static file (`tutorial_graph.js`, `architecture.svg`) — same origin, whitelisted."""
    try:
        body, content_type = ontology_pages.asset(key, name)
    except ontology_pages.PageError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=body, media_type=content_type)


# ── the authored tutorial chapters ──────────────────────────────────────────
# Retail's eight hand-written chapters and ABC's eight training steps used to live on their own
# workbench ports. They are teaching material, not an API: each chapter is one HTML page plus the
# endpoints its own JavaScript calls. Both are served here now — the pages rewritten so their absolute
# paths reach this ontology, the endpoints calling the SAME functions the workbench called.

@router.get("/{key}/tutorial/chapter/{number}")
async def ontology_tutorial_chapter(key: str, number: int):
    try:
        html = ontology_tutorial_chapters.chapter(key, number)
    except ontology_tutorial_chapters.ChapterError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{key}/abct")
async def ontology_abct_shell(key: str):
    """ABC's training shell: the eight-step frame."""
    try:
        html = ontology_tutorial_chapters.abct(key)
    except ontology_tutorial_chapters.ChapterError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{key}/abct/{number}")
async def ontology_abct_step(key: str, number: int, embed: bool = False):
    try:
        html = ontology_tutorial_chapters.abct(key, number, embed=embed)
    except ontology_tutorial_chapters.ChapterError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{key}/wb/{rest:path}")
async def ontology_chapter_api(key: str, rest: str, request: Request):
    """The JSON a chapter's JavaScript asks for, by the path it asked for under the workbench."""
    try:
        return ontology_tutorial_chapters.call(key, rest, dict(request.query_params))
    except ontology_tutorial_chapters.ChapterError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{key}/wb/{rest:path}")
async def ontology_chapter_api_post(key: str, rest: str, request: Request):
    """The same endpoints in their write/ask form (chapter 4's buttons, chapters 6–8's ask box)."""
    try:
        payload = await request.json()
    except Exception:                                          # noqa: BLE001 — an empty or broken body
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        return ontology_tutorial_chapters.call(key, rest, dict(request.query_params), payload)
    except ontology_tutorial_chapters.ChapterError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── declared writes ─────────────────────────────────────────────────────────
# A write is an action declared in the ontology's `schema/actions.yml`, never a free INSERT from a
# client. `dry_run=true` is the read-only form: it reports every precondition with the parameters
# bound and writes nothing. A refusal (exit 2) is a RESULT — nothing was written — so it comes back
# as 200 with ok=false and the engine's own words, not as a 500.

class ActionRequest(BaseModel):
    params: dict = {}
    dry_run: bool = False
    actor: Optional[str] = None


@router.get("/{key}/actions")
async def list_ontology_actions(key: str):
    """The verbs this ontology declares — with parameters, preconditions and the compiled effect."""
    return ontology_actions.list_actions(key)


class AskQuestionRequest(BaseModel):
    question: str
    polish: bool = False


@router.post("/{key}/ask")
async def ask_ontology(key: str, req: AskQuestionRequest):
    """A business question answered by the ontology's own pipeline — or refused BY NAME.

    This is the dashboard's chat: the same three parts as the Query page (the number, the compiled
    SQL, the refusal) because a number without its definition is a rumour. Deterministic template
    first (`polish=false`); a refusal is a 200 with `ok=false`, not an error.
    """
    try:
        return {"ok": True, **ontology_dashboard.ask(key, req.question, polish=req.polish)}
    except ontology_dashboard.DashboardError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{key}/actions/audit")
async def ontology_action_audit(key: str, limit: int = 50):
    """The append-only trail: who ran which declared write, with before/after rows."""
    return ontology_actions.audit(key, limit=limit)


@router.post("/{key}/actions/{action}")
async def run_ontology_action(key: str, action: str, req: ActionRequest):
    """`dry_run=true` → check; otherwise run it (one transaction + an audit row)."""
    try:
        return ontology_actions.invoke(key, action, req.params, dry_run=req.dry_run,
                                       actor=req.actor)
    except ontology_actions.ActionError as exc:
        raise HTTPException(409, str(exc)) from exc
