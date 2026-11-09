"""
Data Analysis API — CSV → SQLite → Agent Analysis → Dashboard.

Endpoints:
  POST /api/analysis/upload — upload CSV file, convert to SQLite, return schema
  POST /api/analysis/init  — convert CSV by path to SQLite, return db_path
  POST /api/analysis/chat  — chat with the sql-analyst skill about the data
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
# The dashboards directory and the page→database grouping rule live in
# services/dashboard_keys so the Settings table (graph-studio catalog) lists the
# same databases this browser groups into; services/offered_databases is the
# on/off rule both surfaces follow.
from services.dashboard_keys import (
    ANALYSIS_DBS_DIR,
    family_key_of as _family_impl,
    load_registry as _registry_impl,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── Models ──────────────────────────────────────────────────────────

class AnalysisInitRequest(BaseModel):
    session_id: str
    csv_path: str
    table_name: str = "data"
    # Optional companion skill file path for the generated dashboard.
    skill_path: Optional[str] = None


class AnalysisInitResponse(BaseModel):
    db_path: str
    table_name: str
    row_count: int
    col_count: int
    columns: list[str]
    dashboard_file: Optional[str] = None
    skill_status: str = "none"
    db_path: str
    table_name: str
    row_count: int
    col_count: int
    columns: list[str]
    dashboard_file: Optional[str] = None  # path to generated HTML dashboard


class AnalysisChatRequest(BaseModel):
    session_id: str
    db_path: str
    message: str
    skill_content: Optional[str] = None
    # The dashboard's skills list as parsed from the LangConfig Dashboard Meta
    # block. The chat agent will load exactly these skills via deepagent.
    # If omitted, falls back to ['sql-analyst'] for backward compatibility.
    skills: list[str] = []
    # Optional: the dashboard's filename. When set, the user + assistant
    # messages are persisted to `analysis_chat_messages` so re-opening the
    # same dashboard shows the full chat history.
    dashboard_filename: Optional[str] = None


class AnalysisChatResponse(BaseModel):
    message: str          # the user-facing clean answer (<think> blocks stripped)
    content: str = ""     # alias for message, kept for backward compat
    # List of {step, type, name, input, output} dicts captured during the
    # agent run. Surfaced in the UI as a collapsible "thinking" trace.
    tool_trace: list[dict] = []
    tool_calls: int = 0
    total_tokens: int = 0


class AnalysisChatHistoryItem(BaseModel):
    id: int
    role: str
    content: str
    tool_trace: Optional[list[dict]] = None
    created_at: str


class DashboardFile(BaseModel):
    filename: str
    path: str
    size_bytes: int
    created: str
    # ── Enriched from LangConfig Dashboard Meta block in the HTML ──
    # (used by the Analysis panel's chat to know the source DB
    # and the deepagent skills the agent should load).
    db_path: Optional[str] = None
    skills: list[str] = []
    mode: Optional[str] = None   # 'static-embed' | 'live-fetch' | None
    entry: Optional[str] = None  # 'hub' | 'detail' | None
    # The page's own <title> — the dashboard browser shows this instead of the
    # filename. Parsed here because the HTML is served from the API origin, so
    # the browser client could not read it without a CORS fetch per card.
    title: Optional[str] = None


# backend/ — needed to reach langgraph/ (assigned.py, sql_setup_db.py) and semantics/.
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _analysis_skills_root() -> Path:
    """Where the bundled analysis skills actually live.

    It was `backend/skills`, but the skills are filed under `backend/skills/builtin/…`,
    so `SkillsMiddleware` logged "Cannot load skills from 'sql-analyst': path_not_found"
    and the analysis agent ran without its skill.
    """
    return Path(__file__).resolve().parent.parent.parent / "skills" / "builtin"


async def _analysis_model():
    """The chat model for analysis work — the platform's own resolution.

    This used to construct `ChatOpenAI(model=MINIMAX_MODEL, api_key=MINIMAX_API_KEY)`
    directly, so on an install whose MiniMax key is stale every dashboard
    generation died with 401 while the rest of the app answered fine (the
    platform keeps provider keys in the database, not in `.env`).
    """
    from core.settings import runtime_get
    from services.agent_utils import resolve_model

    model_name = (
        os.getenv("ANALYSIS_MODEL")
        or runtime_get("models", "default_model")
        or "deepseek-flash"
    )
    return await resolve_model(model_name, temperature=0.3, max_tokens=None, config={})


def _load_skill_markdown_parts(skills: list[str]) -> list[str]:
    """Load SKILL.md files for the given skill names."""
    skills_root = Path(__file__).resolve().parent.parent.parent / "skills"
    parts: list[str] = []
    for skill_name in skills or []:
        if "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            continue
        skill_md = skills_root / skill_name / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            txt = skill_md.read_text(encoding="utf-8")
            parts.append(f"# Skill: {skill_name}\n\n{txt}\n")
        except Exception as e:
            logger.warning(f"Failed to read {skill_md}: {e}")
    return parts


# ── List dashboards ──────────────────────────────────────────────────

@router.get("/dashboards", response_model=list[DashboardFile])
async def list_dashboards():
    """List generated dashboard HTML files, enriched with meta from each HTML's
    LangConfig Dashboard Meta comment block. The Analysis panel's chat
    panel reads db_path and skills from this list to set up chat context.
    """
    import re
    META_DB = re.compile(r"LangConfig Dashboard Meta\s*\n\s*db:\s*(\S+)")
    META_SKILLS = re.compile(r"db:[ \t]*\S+[ \t]*\n[ \t]*skills:[ \t]*([^\n]*)")
    META_MODE = re.compile(r"Mode:\s*(\S+)")
    META_ENTRY = re.compile(r"entry:\s*([^\n]+)")
    TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    if not ANALYSIS_DBS_DIR.exists():
        return []
    # Who sees a page — three cases, one rule (services/offered_databases):
    #   * the database is switched ON in Settings → every account sees it. The
    #     list is a team decision, so the dashboards behind it are team data; the
    #     old rule (page belongs to its generator) left every other account with
    #     an empty board.
    #   * switched OFF on purpose            → hidden from everyone;
    #   * not in the setting at all          → a private draft: its generator only.
    from services.dashboard_owners import filter_visible
    from services.offered_databases import settings_items, visibility_of
    from services.user_roots import subject_user_id

    _uid = subject_user_id()
    _registry = _registry_impl()
    _items = settings_items()
    files = sorted(ANALYSIS_DBS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    _visible = set(filter_visible([f.name for f in files], _uid))

    def _show(f) -> bool:
        key = _family_key_of(f.name, None, _registry)
        vis = visibility_of(key, _items)
        if vis == "published":
            return True
        if vis == "hidden":
            return False
        return f.name in _visible  # private draft

    files = [f for f in files if _show(f)]
    out = []
    for f in files:
        # Read only the first ~16KB to find the meta block (it's always in <head>)
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(16_384)
        except Exception:
            head = ""
        db_m = META_DB.search(head)
        sk_m = META_SKILLS.search(head)
        mo_m = META_MODE.search(head)
        en_m = META_ENTRY.search(head)
        ti_m = TITLE_RE.search(head)
        out.append(DashboardFile(
            filename=f.name,
            path=f"/api/files/{f.name}",
            size_bytes=f.stat().st_size,
            created=str(f.stat().st_mtime),
            db_path=db_m.group(1) if db_m else None,
            # `skills:` may legitimately be empty (a generated page with no companion
            # skill); splitting "" yields [""], which renders as a blank skill chip.
            skills=[s.strip() for s in sk_m.group(1).split(",") if s.strip()] if sk_m else [],
            mode=mo_m.group(1) if mo_m else None,
            entry=en_m.group(1).strip() if en_m else None,
            title=(ti_m.group(1).strip() if ti_m else None),
        ))
    return out


# ── Databases: the browser's first level ────────────────────────────
# The Analysis rail lists DATABASES, not files: 38 pages is a file tree, and a
# user cannot tell "sunhing_dashboard_liability.html" from "sunhing_gantt.html"
# without opening both. A database gets one row, one intro, one home page.
_DATABASES_REGISTRY = ANALYSIS_DBS_DIR / "databases.json"


def _load_db_registry() -> dict:
    """Curated {db_key: {name, intro, home, match[]}} — rule lives in services."""
    return _registry_impl()


def _family_key_of(filename: str, db_path: Optional[str], registry: dict) -> str:
    """Which registered database a page belongs to (rule lives in services)."""
    return _family_impl(filename, db_path, registry)


def _pick_home(key: str, cfg: dict, pages: list[dict]) -> Optional[dict]:
    """The page a click on this database opens."""
    by_name = {p["filename"]: p for p in pages}
    wanted = (cfg or {}).get("home")
    if wanted and wanted in by_name:
        return by_name[wanted]
    hubs = [p for p in pages if (p.get("entry") or "").lower() == "hub"]
    if hubs:
        return hubs[0]
    named = [p for p in pages if p["filename"] in (f"{key}_dashboard.html", f"{key}_dashboard_v2.html")]
    if named:
        return named[0]
    rest = [p for p in pages if f"{key}_dashboard" in p["filename"]]
    if rest:
        return rest[0]
    return max(pages, key=lambda p: float(p["created"] or 0)) if pages else None


@router.get("/databases")
async def list_databases():
    """One entry per database: name, intro, home page, page count.

    This is what the dashboard browser renders. Pages are grouped with the
    curated registry in data/analysis_dbs/databases.json (a page's meta db_path or
    its filename prefix decides membership); `home` falls back to entry=hub, then
    <key>_dashboard.html, then the newest page, so a registry edit is optional.
    """
    rows = await list_dashboards()
    pages = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in rows]
    registry = _load_db_registry()

    grouped: dict[str, list[dict]] = {}
    for p in pages:
        grouped.setdefault(_family_key_of(p["filename"], p.get("db_path"), registry), []).append(p)

    # Visibility was already decided per page in list_dashboards() (published /
    # hidden / private draft), so grouping must not filter again: doing it here
    # would also drop a private draft, i.e. hide someone's own upload from them.
    out = []
    for key, members in grouped.items():
        cfg = registry.get(key, {})
        home = _pick_home(key, cfg, members)
        out.append({
            "key": key,
            "name": cfg.get("name") or (home or {}).get("title") or key,
            "intro": cfg.get("intro") or (
                f"{len(members)} 个页面，来自 {key}。"
                if len(members) > 1 else (home or {}).get("title") or key
            ),
            "home": home,
            "pages": len(members),
            "latest": max((float(p["created"] or 0) for p in members), default=0),
            "registered": bool(cfg),
        })
    out.sort(key=lambda d: (-d["pages"], d["key"]))
    return out


# ── Dashboard metadata (the page's own `db:` binding) ─────────────

def _inject_dashboard_meta(html_path: Path, db_path: str, skill_path: Optional[str]) -> None:
    """Insert the `LangConfig Dashboard Meta` comment into a generated page.

    Idempotent: a page that already carries the block is left untouched (the
    deterministic generators write their own). The `db:` value must be the same
    string the analysis chat resolves — a SQLite path for CSV uploads, a target
    name for Postgres-backed pages — because that is what the panel passes back.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        if "LangConfig Dashboard Meta" in text:
            return
        skills = Path(skill_path).name if skill_path else ""
        meta = (
            "<!--\n"
            "  LangConfig Dashboard Meta\n"
            f"  db: {db_path}\n"
            f"  skills: {skills}\n"
            "  Mode: static-embed\n"
            "  entry: hub\n"
            "-->\n"
        )
        lower = text.lower()
        insert_at = lower.find("<head>")
        if insert_at != -1:
            insert_at += len("<head>")
        else:
            insert_at = lower.find("<html")
            insert_at = insert_at if insert_at == -1 else text.find(">", insert_at) + 1
        if insert_at == -1:
            return
        html_path.write_text(text[:insert_at] + "\n" + meta + text[insert_at:], encoding="utf-8")
        logger.info("injected dashboard meta into %s (db=%s)", html_path.name, db_path)
    except Exception as exc:  # noqa: BLE001 — metadata is an extra, never a failed upload
        logger.warning("could not inject dashboard meta into %s: %s", html_path, exc)


# ── Upload: CSV file → SQLite ───────────────────────────────────────

@router.post("/upload", response_model=AnalysisInitResponse)
async def analysis_upload(
    file: UploadFile = File(...),
    skill_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Upload a CSV file, convert to SQLite, auto-generate dashboard, return schema."""
    import sqlite3
    from services.csv_to_sqlite import csv_to_sqlite_from_bytes

    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    try:
        csv_bytes = await file.read()
        table_name = Path(file.filename).stem.replace('-', '_').replace(' ', '_')
        db_path = csv_to_sqlite_from_bytes(csv_bytes, file.filename, table_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to convert CSV: {e}")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(f"PRAGMA table_info(\"{table_name}\")")
        cols = [r["name"] for r in cursor.fetchall()]
        cursor = conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
        row_count = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read schema: {e}")

    # Handle companion skill file
    skill_path = None
    skill_status = "none"
    if skill_file and skill_file.filename:
        skill_bytes = await skill_file.read()
        # Use basename only so a crafted filename cannot escape
        # ANALYSIS_DBS_DIR (path traversal write).
        skill_path = str(ANALYSIS_DBS_DIR / Path(skill_file.filename).name)
        Path(skill_path).write_bytes(skill_bytes)
        skill_status = "active"
    elif file.filename:
        # Auto-generate companion from CSV metadata
        csv_stem = Path(file.filename).stem.replace('-', '_').replace(' ', '_')
        _skill_path = ANALYSIS_DBS_DIR / f"{csv_stem}.skill.md"
        if not _skill_path.exists():
            try:
                from services.data_skill_generator import generate_data_skill

                # The generator reads COLUMNS from a CSV, so it needs one on disk.
                # `db_path.replace('.db', '.csv')` pointed at a file that never
                # existed (the converter's temp CSV is deleted when it finishes), so
                # every upload logged "CSV not found" and shipped without a
                # companion — silently, because the dashboard step used to dominate
                # the log. Park the source next to the .db it produced instead: one
                # file, and it is the input the tables were built from.
                _csv_for_skill = ANALYSIS_DBS_DIR / f"{csv_stem}.csv"
                if not _csv_for_skill.exists():
                    _csv_for_skill.write_bytes(csv_bytes)
                _result = generate_data_skill(str(_csv_for_skill), str(ANALYSIS_DBS_DIR))
                if _result:
                    skill_path = _result
                    skill_status = "pending"
                    logger.info(f"Auto-generated companion skill: {_result}")
            except Exception as e:
                logger.warning(f"Failed to auto-generate companion: {e}")

    # NO dashboard here (2026-11-04). Uploading a CSV means "make this queryable",
    # not "build me a page": dashboards have exactly ONE producer — the dashboard
    # agent (template 343, deterministic generator) — plus the explicit scripts for
    # the ERP/Sun Hing study cases. The old auto-generation ran its own LLM with a
    # "write Plotly HTML" prompt inside the upload request (180 s timeout), which is
    # how a 1.4 MB hand-written page appeared with no meta block, no home card and
    # nothing tying it to the data it came from.
    dashboard_file = None

    # This page belongs to the account that uploaded the CSV.
    if dashboard_file:
        try:
            from services.dashboard_owners import record
            from services.user_roots import subject_user_id

            record(Path(dashboard_file).name, subject_user_id(db))
        except Exception as exc:  # noqa: BLE001 — never fail the upload over bookkeeping
            logger.warning(f"could not record dashboard owner: {exc}")

    # Save metadata for refresh capability (creates {stem}.meta.json)
    if dashboard_file:
        try:
            _stem = Path(dashboard_file).stem
            _meta_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs" / f"{_stem}.meta.json"
            if not _meta_path.exists():
                import json as _json
                _meta_path.write_text(
                    _json.dumps({"db_path": db_path, "table_name": table_name, "columns": cols}, ensure_ascii=False),
                    encoding="utf-8"
                )
        except Exception:
            pass

    return AnalysisInitResponse(
        db_path=db_path,
        table_name=table_name,
        row_count=row_count,
        col_count=len(cols),
        columns=cols,
        dashboard_file=dashboard_file,
        skill_status=skill_status,
    )


# ── Init: CSV → SQLite (by path from sandbox) ────────────────────────

@router.post("/init", response_model=AnalysisInitResponse)
async def analysis_init(request: AnalysisInitRequest, db: Session = Depends(get_db)):
    """Convert CSV by path to SQLite, auto-generate dashboard, return schema."""
    import sqlite3
    from services.csv_to_sqlite import csv_to_sqlite_from_bytes

    csv_path = _resolve_csv_path(request.csv_path, request.session_id)
    out_dir = _analysis_out_dir(request.session_id)

    try:
        csv_bytes = csv_path.read_bytes()
        db_path = csv_to_sqlite_from_bytes(
            csv_bytes, csv_path.name, request.table_name, out_dir=out_dir
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to convert CSV: {e}")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(f"PRAGMA table_info(\"{request.table_name}\")")
        cols = [r["name"] for r in cursor.fetchall()]
        cursor = conn.execute(f"SELECT COUNT(*) FROM \"{request.table_name}\"")
        row_count = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read schema: {e}")

    # No dashboard on /init either — same rule as /upload above. This endpoint now
    # only converts a CSV (or accepts an existing SQLite) so the data is queryable.
    dashboard_file = None

    return AnalysisInitResponse(
        db_path=db_path,
        table_name=request.table_name,
        row_count=row_count,
        col_count=len(cols),
        columns=cols,
        dashboard_file=dashboard_file,
    )


# ── Chat: Ask questions about the data

@router.post("/chat")
async def analysis_chat(request: AnalysisChatRequest, db: Session = Depends(get_db)):
    """
    Chat with the sql-analyst skill about the uploaded data.
    Returns SSE stream with real-time tokens and tool calls.

    Uses create_deep_agent with the sql-analyst SKILL.md and
    sqlite_execute / python_execute tools.
    """
    import json

    db_path = request.db_path
    db_full_path = Path(db_path)
    if not db_full_path.is_absolute():
        # db_path from the meta block is relative to the project root
        # (e.g. "data/analysis_dbs/sunhing_kpi.db") but the server
        # process CWD may be backend/.  Resolve against ANALYSIS_DBS_DIR
        # by using only the filename portion.
        db_full_path = ANALYSIS_DBS_DIR / db_full_path.name

    # A dashboard's meta `db:` can name a SQLite FILE (CSV uploads) or a
    # POSTGRES target (the generated Chinook pages say `db: chinook`). The chat
    # used to 404 on the second kind — "Database not found: chinook" — which is
    # why it looked broken. When the name is not a file but resolves as a SQL
    # target, the answer comes from the code-defined LangGraph instead, so the
    # chat obeys the same SEMANTICS.md the Studio shows.
    graph_id = None
    sql_target = None
    if not db_full_path.exists():
        graph_id, sql_target = _resolve_analysis_graph(db_path)
        if graph_id is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Database not found: {db_path}. Neither a SQLite file under "
                    f"{ANALYSIS_DBS_DIR} nor a SQL target with an assigned graph "
                    f"(assigned: {_assigned_graph_ids()})."
                ),
            )
        logger.info(f"[analysis-chat] '{db_path}' -> LangGraph '{graph_id}' (target={sql_target})")
    # Use the resolved absolute path for all downstream operations
    db_path = str(db_full_path)

    resolved_skills = list(request.skills or [])
    if request.dashboard_filename and not resolved_skills:
        meta = _load_dashboard_meta(request.dashboard_filename)
        if meta:
            resolved_skills = meta.get("skills") or []

    resolved_skill_content = request.skill_content
    if not resolved_skill_content and resolved_skills:
        resolved_skill_content = "\n---\n\n".join(_load_skill_markdown_parts(resolved_skills))

    # Persist the user message BEFORE running the agent so a 504/500 timeout
    # still leaves a record of what was asked. Assistant message is appended
    # only after the agent run succeeds.
    dashboard_filename = request.dashboard_filename
    if dashboard_filename:
        _persist_message(db, dashboard_filename, "user", request.message)

    async def generate_stream():
        """Async generator that yields SSE events during agent execution."""
        import re

        # ── A Postgres-backed dashboard answers through its LangGraph ────────
        # Same SSE protocol as the SQLite path (tool_start / tool_end / chunk /
        # done), so the panel's transcript, tool trace and persistence all keep
        # working. The graph carries the prompt, the tools, the checkpointer and —
        # the reason this exists — the SEMANTICS.md definitions.
        if graph_id is not None:
            _think = re.compile(r"<think>.*?</think>", re.DOTALL)
            tool_trace: list[dict] = []
            step_idx = 0
            full_response = ""
            try:
                sys.path.insert(0, str(BACKEND_DIR))
                from langgraph.tool_adapters import get_graph_runnable

                runnable = get_graph_runnable(graph_id)
                init_state = {
                    "messages": [{"role": "user", "content": request.message}],
                    # The NAME the user's dashboard declared (`chinook`), not the
                    # resolved path — a path is not a database.
                    "sql_database": sql_target or db_path,
                }
                cfg = {
                    "configurable": {
                        "thread_id": f"analysis-{request.session_id}-{dashboard_filename or 'dash'}",
                    },
                    "recursion_limit": 60,
                }
                async for upd in runnable.astream(init_state, config=cfg, stream_mode="updates"):
                    for _node, payload in (upd or {}).items():
                        # Every node the graph enters is a step a reader can watch:
                        # this is the difference between "the agent answered" and
                        # "here is what it did". Cheap to emit, and the panel only
                        # renders it when expanded.
                        yield f"data: {json.dumps({'type': 'node', 'name': str(_node)})}\n\n"
                        if not isinstance(payload, dict):
                            continue
                        for msg in payload.get("messages") or []:
                            # Reasoning the model exposes (DeepSeek/Qwen-style
                            # `reasoning_content`) plus the text it wrote on the way
                            # to the final answer — the "thinking" viewers expect.
                            _reason = ""
                            _extra = getattr(msg, "additional_kwargs", None) or {}
                            if isinstance(_extra, dict):
                                _reason = str(_extra.get("reasoning_content") or "")
                            if _reason.strip():
                                yield f"data: {json.dumps({'type': 'thinking', 'content': _reason[:4000], 'source': 'reasoning'})}\n\n"
                            calls = getattr(msg, "tool_calls", None) or []
                            if not calls and getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
                                # e.g. check_query rewrote the SQL, or a node explained itself
                                yield f"data: {json.dumps({'type': 'thinking', 'content': str(msg.content)[:2000], 'source': 'text'})}\n\n"
                            if calls:
                                for call in calls:
                                    step_idx += 1
                                    name = str(call.get("name", ""))
                                    tool_trace.append({
                                        "step": step_idx, "type": "tool_call", "name": name,
                                        "input": str(call.get("args"))[:500], "output": None,
                                    })
                                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': name, 'data': {'input': str(call.get('args'))[:500]}})}\n\n"
                            elif getattr(msg, "type", "") == "tool":
                                for step in reversed(tool_trace):
                                    if step.get("output") is None:
                                        step["output"] = str(getattr(msg, "content", ""))[:1500]
                                        break
                                yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': step.get('name', '') if step else ''})}\n\n"
                            elif getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
                                full_response = str(msg.content)

                clean = _think.sub("", full_response).strip()
                if not clean:
                    clean = "(图跑完了，但没有产出一句话回答)"
                if dashboard_filename:
                    _persist_message(db, dashboard_filename, "assistant", clean, tool_trace=tool_trace)
                yield f"data: {json.dumps({'type': 'chunk', 'content': clean})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'content': clean, 'tool_calls': len(tool_trace), 'tool_trace': tool_trace})}\n\n"
            except Exception as exc:  # noqa: BLE001 — surface the reason, keep the stream valid
                logger.error(f"Analysis graph chat failed ({graph_id}): {exc}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        import sqlite3
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import MemorySaver
        from deepagents import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
        from config import settings

        skills_root = _analysis_skills_root()

        model = await _analysis_model()

        backend = FilesystemBackend(root_dir=str(skills_root))
        checkpointer = MemorySaver()

        @tool
        def sqlite_execute(sql: str, db_path_override: str = "") -> str:
            """Execute a read-only SELECT query on a SQLite database."""
            actual_db_path = db_path_override or db_path
            sql_stripped = sql.strip().strip(";").strip()
            blocked = {"insert","update","delete","drop","alter","create","replace"}
            first_word = sql_stripped.lower().split()[0] if sql_stripped.split() else ""
            if first_word in blocked:
                return "❌ BLOCKED: Only SELECT allowed."
            try:
                conn = sqlite3.connect(actual_db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
                rows = cursor.fetchall()
                col_names = [d[0] for d in cursor.description] if cursor.description else []
                if not rows:
                    conn.close()
                    return "✅ No rows."
                widths = [len(c) for c in col_names]
                for row in rows:
                    for i, v in enumerate(row):
                        widths[i] = max(widths[i], len(str(v)))
                header = " | ".join(c.ljust(w) for c, w in zip(col_names, widths))
                sep = "-+-".join("-" * w for w in widths)
                body = "\n".join(
                    " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
                    for row in rows[:50]
                )
                conn.close()
                return f"✅ {len(rows)} row(s)\n\n{header}\n{sep}\n{body}"
            except Exception as e:
                return f"❌ Error: {e}"

        @tool
        def python_execute(code: str) -> str:
            """Execute Python code (pandas, matplotlib). To return charts, use
            matplotlib Agg backend → base64 → markdown data URI in stdout:
              import matplotlib; matplotlib.use("Agg")
              import matplotlib.pyplot as plt, base64, io
              ... plt.savefig(buf, format="png") ...
              print(f"![chart](data:image/png;base64,{b64})")"""
            import subprocess, textwrap
            try:
                wrapper = (
                    "import sys, io\n"
                    "_buf = io.StringIO()\n"
                    "sys.stdout = _buf\nsys.stderr = _buf\n"
                    "try:\n"
                    + textwrap.indent(code, '    ') + "\n"
                    "except Exception:\n"
                    "    import traceback; traceback.print_exc()\n"
                    "finally:\n"
                    "    sys.stdout = sys.__stdout__\n"
                    "    sys.stderr = sys.__stderr__\n"
                    "    print(_buf.getvalue(), end='')\n"
                )
                result = subprocess.run(
                    [__import__("sys").executable, "-c", wrapper],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(Path(db_path).parent)
                )
                out = result.stdout + result.stderr
                return f"✅ OK\n\n{out[:3000]}" if out.strip() else "✅ OK"
            except subprocess.TimeoutExpired:
                return "❌ Timeout (>30s)"
            except Exception as e:
                return f"❌ Error: {e}"

        agent = create_deep_agent(
            model=model,
            tools=[sqlite_execute, python_execute],
            system_prompt=(
                f"You are a data analyst. The user's data is in a SQLite database at:\n"
                f"  {db_path}\n\n"
                f"Use sqlite_execute to query it. Discover the schema first, then answer questions.\n"
                "Use python_execute for charts.\n"
                "To return a chart, use matplotlib Agg + base64 data URI:\n"
                '  ```python\n  import matplotlib; matplotlib.use("Agg")\n'
                "  import matplotlib.pyplot as plt, base64, io\n"
                "  ... plt.savefig(buf, format='png') ...\n"
                '  print(f"![chart](data:image/png;base64,{b64})")\n  ```\n'
                "Read the SKILL.md for guidance. Reply in Chinese.\n"
                "## Output style\n"
                "- All UI text in Chinese.\n"
                "- Use **markdown headings** (`##`, `###`) to break up long answers; one heading per logical section.\n"
                "- Use **bulleted lists** (`- item`) for multi-point answers; one fact per bullet.\n"
                "- Use **pipe tables** for any 3+ row data dump (KPI snapshot, top-N, comparison).\n"
                "- **Do NOT use `---` horizontal rules** in normal answers — they create visual noise.\n"
                "- **Currency**: render ≥$1M as `$X.XM` (1 decimal), <$1M as `$X,XXX` (no decimals), currency table cells use the same rule. Always include thousand separators.\n"
                "- **Period labels**: always `YYYY-Q#` (e.g. `2024-Q4`). Never write `Q4\\'24` or `Q1 23`.\n"
                "- **End every answer with a one-line conclusion** in a quote block: `> **结论:** ...` — one sentence, not a paragraph.\n"
                "- **Long answers**: if the answer is >8 lines, lead with a 2-3 line summary, then detail.\n"
                "- **Numbers**: when comparing two values, always show the % delta next to the absolute (e.g. `$10.1M → $11.4M (+12.9%)`).\n"
                "- For dashboard-linked chats, answer directly from the business context. Do not add long process disclosures unless the user asks for methodology.\n"
                "- If the user asks about a value visible on the dashboard, use SQLite queries and the skill logic to derive or verify it. Do not treat HTML-rendered numbers as the answer source.\n"
                + (f"\\n=== COMPANION SKILL ===\\n{resolved_skill_content}\\n=== END COMPANION SKILL ===\\n" if resolved_skill_content else "")
            ),
            backend=backend,
            skills=resolved_skills or ["sql-analyst"],
            checkpointer=checkpointer,
        )

        # ── Stream ───────────────────────────────────────────────────

        _think_re = re.compile(r"<think>.*?</think>", re.DOTALL)
        full_response = ""
        tool_trace: list[dict] = []
        step_idx = 0

        # Load conversation history from DB so the agent remembers
        # previous turns. The current user message was already persisted
        # (line 358-359), so we query all messages for this dashboard
        # and pass them to the agent for full context.
        all_messages = [{"role": "user", "content": request.message}]
        if dashboard_filename:
            from models.analysis_chat import AnalysisChatMessage
            try:
                prev_msgs = (
                    db.query(AnalysisChatMessage)
                    .filter(AnalysisChatMessage.dashboard_filename == dashboard_filename)
                    .order_by(AnalysisChatMessage.created_at.asc(), AnalysisChatMessage.id.asc())
                    .all()
                )
                if prev_msgs:
                    all_messages = [{"role": m.role, "content": m.content} for m in prev_msgs]
            except Exception:
                pass  # No history — use just the current message

        try:
            async for event in agent.astream_events(
                {"messages": all_messages},
                config={
                    "configurable": {"thread_id": f"analysis-{request.session_id}"},
                    "recursion_limit": 50,
                },
                version="v2",
            ):
                kind = event.get("event")
                if kind == "on_tool_start":
                    step_idx += 1
                    name = event.get("name", "")
                    inp = event.get("data", {}).get("input", "")
                    tool_trace.append({
                        "step": step_idx,
                        "type": "tool_call",
                        "name": name,
                        "input": str(inp)[:500],
                        "output": None,
                    })
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': name, 'data': {'input': str(inp)[:500]}})}\n\n"

                elif kind == "on_tool_end":
                    out = event.get("data", {}).get("output", "")
                    for step in reversed(tool_trace):
                        if step.get("type") == "tool_call" and step.get("output") is None:
                            step["output"] = str(out)[:1500]
                            break
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': event.get('name', '')})}\n\n"

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if hasattr(chunk, "content") and chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content})}\n\n"

            # Streaming complete — strip <think> blocks
            clean_response = _think_re.sub("", full_response).strip()
            if not clean_response and full_response:
                clean_response = "(模型只输出了内部推理过程，未生成可见回答)"

            # Persist assistant message
            if dashboard_filename:
                _persist_message(
                    db, dashboard_filename, "assistant",
                    clean_response, tool_trace=tool_trace,
                )

            # Send done event with final content + complete tool_trace
            done_payload = json.dumps({
                "type": "done",
                "content": clean_response,
                "tool_calls": len(tool_trace),
                "tool_trace": tool_trace,
            })
            yield f"data: {done_payload}\n\n"

        except Exception as e:
            logger.error(f"Analysis streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


# ── Dashboard chat: pick the graph that owns a Postgres-backed dashboard ────
# The Analysis chat historically only spoke SQLite because every dashboard came
# from a CSV upload. The generated dashboards declare their source database as a
# name (`db: chinook`), which is a Postgres target — so the chat has to hand those
# questions to the code-defined LangGraph instead of opening a file that is not
# there. Preference order is deliberate: a database that has a SEMANTICS.md gets
# the semantic graph, because that is the graph whose answers obey the file.
_SEMANTIC_GRAPH = "langgraph_semantic"
_PLAIN_SQL_GRAPH = "sql_agent"


def _assigned_graph_ids() -> list[str]:
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from langgraph.assigned import ASSIGNED_GRAPHS

        return sorted(ASSIGNED_GRAPHS)
    except Exception:  # noqa: BLE001 — a missing whitelist must not 500 the chat
        return []


def _resolve_analysis_graph(db_name: str) -> tuple[Optional[str], Optional[str]]:
    """(graph_id, target) for a dashboard whose `db:` is not a SQLite file.

    Returns (None, None) when the name is neither a registered SQL target nor a
    database on the platform server — the caller turns that into a 404 that names
    both possibilities instead of only "Database not found".
    """
    name = (db_name or "").strip()
    if not name or "/" in name or name.startswith("."):
        return None, None
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from langgraph.sql_setup_db import is_target, list_targets, platform_params

        known = set(list_targets())
        if not is_target(name):
            import psycopg2

            try:
                conn = psycopg2.connect(**platform_params())
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
                        if cur.fetchone() is None:
                            return None, None
                finally:
                    conn.close()
                known.add(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[analysis-chat] cannot list databases to resolve '{name}': {exc}")
                return None, None
        if name not in known:
            return None, None

        # Prefer the semantic graph when this database has a semantics file.
        semantics = BACKEND_DIR / "semantics" / name / "SEMANTICS.md"
        assigned = set(_assigned_graph_ids())
        for candidate in (_SEMANTIC_GRAPH if semantics.is_file() else None, _PLAIN_SQL_GRAPH):
            if candidate and candidate in assigned:
                return candidate, name
        return None, None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[analysis-chat] graph resolution failed for '{db_name}': {exc}")
        return None, None


def _persist_message(db, dashboard_filename: str, role: str, content: str,
                     tool_trace: list[dict] | None = None) -> None:
    """Insert a chat message row. No-op on any error (chat is best-effort)."""
    from models.analysis_chat import AnalysisChatMessage
    try:
        row = AnalysisChatMessage(
            dashboard_filename=dashboard_filename,
            role=role,
            content=content,
            tool_trace=tool_trace,
        )
        db.add(row)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist chat message: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _resolve_csv_path(raw: str, session_id: str | None = None) -> Path:
    """Find the uploaded CSV wherever this platform actually put it — or 404.

    The chat uploader writes into the agent's own workspace
    (`outputs/users/<uid>/agents/agent_<id>/upload/…`), while the Analysis panel
    has always asked for `outputs/default/<name>` — a path from before the
    per-agent workspaces existed. The mismatch turned "upload a CSV, get a
    dashboard" into `404 CSV not found` with the file sitting right there.
    """
    from fastapi import HTTPException

    given = Path(raw)
    candidates = [given]
    name = given.name

    # the conversation's own workspace: the authoritative location
    if session_id:
        try:
            from db.database import SessionLocal
            from models.deep_agent import ChatSession
            from services.workspace_manager import get_workspace_manager

            with SessionLocal() as db:
                session = db.query(ChatSession).filter(
                    ChatSession.session_id == session_id
                ).first()
                if session and session.agent_id:
                    # Same resolution the chat uploader used, so the reader and
                    # the writer cannot disagree about where the file is.
                    from api.chat.documents import _resolve_agent_workspace

                    mgr = get_workspace_manager()
                    ws = _resolve_agent_workspace(session, db, mgr)
                    candidates += [ws / "upload" / name, ws / name]
        except Exception as e:      # never let resolution break the request
            logger.warning(f"CSV path resolution via session failed: {e}")

    # legacy + shared locations, so older links keep working
    for extra in ("outputs/default", "outputs/agents/default"):
        candidates.append(Path(extra) / name)
    try:
        from services.workspace_manager import get_workspace_manager

        candidates.append(get_workspace_manager().user_base() / "default" / name)
    except Exception:
        pass

    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand
    raise HTTPException(
        status_code=404,
        detail=f"CSV not found: {raw} (also tried the session workspace and outputs/default)",
    )


def _analysis_out_dir(session_id: str | None) -> Path:
    """The agent workspace this analysis belongs to (or the shared dir as fallback).

    Uploaded files and generated files live in the agent's own workspace — that is
    the platform rule, and the Files panel is built on it. Analysis used to write
    its database and dashboard into the shared `data/analysis_dbs`, so a CSV a
    customer uploaded to one agent piled up next to everybody else's dashboards and
    none of it appeared in Files.
    """
    if session_id:
        try:
            from db.database import SessionLocal
            from models.deep_agent import ChatSession
            from services.workspace_manager import get_workspace_manager
            from api.chat.documents import _resolve_agent_workspace

            with SessionLocal() as db:
                session = db.query(ChatSession).filter(
                    ChatSession.session_id == session_id
                ).first()
                if session and session.agent_id:
                    ws = _resolve_agent_workspace(session, db, get_workspace_manager())
                    out = ws / "generated" / "analysis"
                    out.mkdir(parents=True, exist_ok=True)
                    return out
        except Exception as e:
            logger.warning(f"Analysis workspace resolution failed, using shared dir: {e}")
    return ANALYSIS_DBS_DIR


def _find_dashboard(filename: str) -> Path | None:
    """Locate a dashboard by name: agent workspaces first, then the shared dir."""
    from services.workspace_manager import get_workspace_manager

    try:
        base = Path(get_workspace_manager().user_base())
        for p in base.rglob(filename):
            if p.is_file():
                return p
    except Exception:
        pass
    shared = ANALYSIS_DBS_DIR / filename
    return shared if shared.is_file() else None


async def _run_analysis_agent(
    db_path: str,
    message: str,
    session_id: str,
    skill_content: Optional[str] = None,
    skills: list[str] = None,
) -> AnalysisChatResponse:
    """Run the deep agent with the given message and the dashboard's skills.
    The `skills` list comes from the dashboard's LangConfig Dashboard Meta
    block (parsed by the frontend from /api/analysis/dashboards). Falls back
    to ['sql-analyst'] for backward compatibility when not provided."""
    import sqlite3
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from dotenv import load_dotenv; load_dotenv(override=True)

    from config import settings

    # ── Tools ────────────────────────────────────────────────────────

    @tool
    def sqlite_execute(sql: str, db_path_override: str = "") -> str:
        """Execute a read-only SELECT query on a SQLite database."""
        actual_db_path = db_path_override or db_path
        sql_stripped = sql.strip().strip(";").strip()
        blocked = {"insert","update","delete","drop","alter","create","replace"}
        first_word = sql_stripped.lower().split()[0] if sql_stripped.split() else ""
        if first_word in blocked:
            return f"❌ BLOCKED: Only SELECT allowed."
        try:
            conn = sqlite3.connect(actual_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description] if cursor.description else []
            if not rows:
                conn.close()
                return "✅ No rows."
            widths = [len(c) for c in col_names]
            for row in rows:
                for i, v in enumerate(row):
                    widths[i] = max(widths[i], len(str(v)))
            header = " | ".join(c.ljust(w) for c, w in zip(col_names, widths))
            sep = "-+-".join("-" * w for w in widths)
            body = "\n".join(
                " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
                for row in rows[:50]
            )
            conn.close()
            return f"✅ {len(rows)} row(s)\n\n{header}\n{sep}\n{body}"
        except Exception as e:
            return f"❌ Error: {e}"

    @tool
    def python_execute(code: str) -> str:
        """Execute Python code (pandas, matplotlib). To return charts, use
        matplotlib Agg backend → base64 → markdown data URI in stdout:
          import matplotlib; matplotlib.use("Agg")
          import matplotlib.pyplot as plt, base64, io
          ... plt.savefig(buf, format="png") ...
          print(f"![chart](data:image/png;base64,{b64})")"""
        import subprocess, textwrap
        try:
            wrapper = (
                "import sys, io\n"
                "_buf = io.StringIO()\n"
                "sys.stdout = _buf\nsys.stderr = _buf\n"
                "try:\n"
                + textwrap.indent(code, '    ') + "\n"
                "except Exception:\n"
                "    import traceback; traceback.print_exc()\n"
                "finally:\n"
                "    sys.stdout = sys.__stdout__\n"
                "    sys.stderr = sys.__stderr__\n"
                "    print(_buf.getvalue(), end='')\n"
            )
            result = subprocess.run(
                [__import__("sys").executable, "-c", wrapper],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(db_path).parent)
            )
            out = result.stdout + result.stderr
            return f"✅ OK\n\n{out[:3000]}" if out.strip() else "✅ OK"
        except subprocess.TimeoutExpired:
            return "❌ Timeout (>30s)"
        except Exception as e:
            return f"❌ Error: {e}"

    # ── Agent ────────────────────────────────────────────────────────

    skills_root = _analysis_skills_root()

    model = await _analysis_model()

    backend = FilesystemBackend(root_dir=str(skills_root))
    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            f"You are a data analyst. The user's data is in a SQLite database at:\n"
            f"  {db_path}\n\n"
            f"Use sqlite_execute to query it. Discover the schema first, then answer questions.\n"
            "Use python_execute for charts.\n"
            "To return a chart, use matplotlib Agg + base64 data URI:\n"
            '  ```python\n  import matplotlib; matplotlib.use("Agg")\n'
            "  import matplotlib.pyplot as plt, base64, io\n"
            "  ... plt.savefig(buf, format='png') ...\n"
            '  print(f"![chart](data:image/png;base64,{b64})")\n  ```\n'
            "Read the SKILL.md for guidance. Reply in Chinese.\n"
            # ── Output formatting rules (markdown-aware, chat-friendly) ──
            "## Output style\n"
            "- All UI text in Chinese.\n"
            "- Use **markdown headings** (`##`, `###`) to break up long answers; one heading per logical section.\n"
            "- Use **bulleted lists** (`- item`) for multi-point answers; one fact per bullet.\n"
            "- Use **pipe tables** for any 3+ row data dump (KPI snapshot, top-N, comparison).\n"
            "- **Do NOT use `---` horizontal rules** in normal answers — they create visual noise.\n"
            "- **Currency**: render ≥$1M as `$X.XM` (1 decimal), <$1M as `$X,XXX` (no decimals), currency table cells use the same rule. Always include thousand separators.\n"
            "- **Period labels**: always `YYYY-Q#` (e.g. `2024-Q4`). Never write `Q4'24` or `Q1 23`.\n"
            "- **End every answer with a one-line conclusion** in a quote block: `> **结论:** ...` — one sentence, not a paragraph.\n"
            "- **Long answers**: if the answer is >8 lines, lead with a 2-3 line summary, then detail.\n"
            "- **Numbers**: when comparing two values, always show the % delta next to the absolute (e.g. `$10.1M → $11.4M (+12.9%)`).\n"
            "- For dashboard-linked chats, answer directly from the business context. Do not add long process disclosures unless the user asks for methodology.\n"
            "- If the user asks about a value visible on the dashboard, use SQLite queries and the skill logic to derive or verify it. Do not treat HTML-rendered numbers as the answer source.\n"
            + f"{'\\n=== COMPANION SKILL ===\\n' + (skill_content or '') + '\\n=== END COMPANION SKILL ===\\n' if skill_content else ''}"
        ),
        backend=backend,
        skills=(skills if skills else ["sql-analyst"]),
        checkpointer=checkpointer,
    )

    # ── Invoke ───────────────────────────────────────────────────────

    import re as _re_think
    _think_re = _re_think.compile(r"<think>.*?</think>", _re_think.DOTALL)

    full_response = ""
    tool_trace: list[dict] = []
    step_idx = 0
    pending_tool_inputs: dict[str, str] = {}   # run_id -> tool name

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": message}]},
        config={
            "configurable": {"thread_id": f"analysis-{session_id}"},
            "recursion_limit": 50,
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            step_idx += 1
            name = event.get("name", "")
            inp = event.get("data", {}).get("input", "")
            run_id = event.get("run_id", "")
            pending_tool_inputs[run_id] = name
            tool_trace.append({
                "step": step_idx,
                "type": "tool_call",
                "name": name,
                "input": str(inp)[:500],   # truncate huge queries
                "output": None,
            })
        elif kind == "on_tool_end":
            run_id = event.get("run_id", "")
            out = event.get("data", {}).get("output", "")
            # Patch the most recent step with this run_id
            for step in reversed(tool_trace):
                if step.get("type") == "tool_call" and step.get("output") is None:
                    step["output"] = str(out)[:1500]
                    break
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                full_response += chunk.content

    # Strip <think>...</think> blocks from the user-facing answer.
    # Reasoning should be in the trace, not in the chat bubble.
    clean_response = _think_re.sub("", full_response).strip()
    # If the model emitted ONLY thinking and no real answer, surface a fallback.
    if not clean_response and full_response:
        clean_response = "(模型只输出了内部推理过程，未生成可见回答)"

    return AnalysisChatResponse(
        message=clean_response,
        content=clean_response,
        tool_trace=tool_trace,
        tool_calls=len(tool_trace),
        total_tokens=len(clean_response.split()),
    )

# ── Existing endpoint — now returns SSE stream ──


@router.get("/chat-history/{filename}", response_model=list[AnalysisChatHistoryItem])
async def get_chat_history(filename: str, db: Session = Depends(get_db)):
    """Return all chat messages for a given dashboard filename, oldest first.

    Used by the Analysis panel's chat to populate the conversation when
    the user re-opens a dashboard. Filename is the dashboard's basename
    (e.g. 'erp_dashboard_20260711_055116.html'); we don't accept paths.
    """
    from fastapi import HTTPException
    # Defend against path traversal: only allow a basename, no slashes
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    from models.analysis_chat import AnalysisChatMessage
    rows = (
        db.query(AnalysisChatMessage)
        .filter(AnalysisChatMessage.dashboard_filename == filename)
        .order_by(AnalysisChatMessage.created_at.asc(), AnalysisChatMessage.id.asc())
        .all()
    )
    return [
        AnalysisChatHistoryItem(
            id=r.id,
            role=r.role,
            content=r.content,
            tool_trace=r.tool_trace,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.delete("/chat-history/{filename}")
async def clear_chat_history(filename: str, db: Session = Depends(get_db)):
    """Delete all chat messages for a given dashboard filename."""
    from fastapi import HTTPException
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    from models.analysis_chat import AnalysisChatMessage
    deleted = (
        db.query(AnalysisChatMessage)
        .filter(AnalysisChatMessage.dashboard_filename == filename)
        .delete()
    )
    db.commit()
    return {"deleted": deleted}


@router.get("/data/{hash_id}")
async def get_analysis_data(hash_id: str):
    """Return live data from the SQLite source for a dashboard.

    Tries the SQLite source first; if the DB is unreachable, falls back
    to the data embedded in the dashboard HTML (`var EMBEDDED_DATA = ...`).
    The embedded data is what's actually rendered by the dashboard, so
    showing it in the Data panel is still useful even when the DB
    can't be re-queried.
    """
    from fastapi import HTTPException
    meta = _load_dashboard_meta(hash_id)
    if not meta:
        raise HTTPException(404, "Dashboard not found")

    # (a) Try the live SQLite DB first
    db_path = meta.get("db_path")
    if db_path and meta.get("table_name"):
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(f'SELECT * FROM "{meta["table_name"]}"')
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            clean_cols = [c.replace(" ", "") for c in cols]
            result = [{clean_cols[i]: v if v is not None else "" for i, v in enumerate(row)} for row in rows]
            conn.close()
            return result
        except Exception as e:
            logger.warning(f"SQLite read failed for {db_path}: {e}; falling back to embedded data")

    # (b) Fall back to data embedded in the dashboard HTML
    embedded = _extract_embedded_data_from_html(meta.get("filename") or hash_id)
    if embedded:
        # Pick the largest array — that's the row data the dashboard renders
        best_key = max(
            (k for k, v in embedded.items() if isinstance(v, list) and v and isinstance(v[0], dict)),
            key=lambda k: len(embedded[k]),
            default=None,
        )
        if best_key:
            return embedded[best_key]

    raise HTTPException(404, "No data found (no live DB, no embedded data)")


def _extract_embedded_data_from_html(filename_or_hash: str) -> dict:
    """Parse the `var EMBEDDED_DATA = {...}` block out of a dashboard HTML.

    Used as a fallback for the Data panel when the source DB can't be
    queried. Returns the parsed dict, or {} if not found.
    """
    import re
    from pathlib import Path
    dbs_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"
    target = None
    for f in dbs_dir.glob("*.html"):
        if filename_or_hash and filename_or_hash in f.name:
            target = f
            break
    if not target:
        return {}
    try:
        c = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    m = re.search(r"var\s+EMBEDDED_DATA\s*=\s*(\{.*?\})\s*;", c, re.DOTALL)
    if not m:
        return {}
    try:
        import json
        return json.loads(m.group(1))
    except Exception:
        return {}



@router.get("/skill-content/{filename}")
async def get_skill_content(filename: str):
    """Return the SKILL.md content for the active dashboard.

    Reads the dashboard's HTML meta block, finds the declared skills
    (e.g. ['erp-analyst']), and concatenates each skill's SKILL.md.
    Returns the concatenated markdown for the Skill panel.
    """
    from fastapi import HTTPException
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    # Use _load_dashboard_meta's HTML-parse path by passing the filename
    meta = _load_dashboard_meta(filename)
    if not meta:
        raise HTTPException(404, "Dashboard not found")
    skills = meta.get("skills") or []
    parts = _load_skill_markdown_parts(skills)
    if not parts:
        raise HTTPException(404, "No skill content found")
    return {"skills": skills, "content": "\n---\n\n".join(parts)}



def _load_dashboard_meta(hash_id: str) -> dict:
    """Load dashboard metadata from data/analysis_dbs/.

    Resolves a dashboard by either:
      1. A sidecar .meta.json file (legacy: dashboard_{hash}.meta.json or
         {hash}.meta.json), or
      2. The dashboard HTML's `LangConfig Dashboard Meta` comment block
         (self-describing — every dashboard we generate has one).
    """
    import json
    import re
    from pathlib import Path
    dbs_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"

    # (1) Try sidecar meta.json files
    for stem in (f"dashboard_{hash_id}", hash_id):
        meta_path = dbs_dir / f"{stem}.meta.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))

    # (2) Parse the LangConfig Dashboard Meta block from the HTML itself.
    #     Match the most recently-created dashboard whose filename contains
    #     the hash_id as a substring, so it works for both legacy hash-based
    #     URLs and the new filename-based URLs.
    candidates = sorted(
        dbs_dir.glob("*.html"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for f in candidates:
        if hash_id and hash_id not in f.name:
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(8_192)
        except Exception:
            continue
        if "LangConfig Dashboard Meta" not in head:
            continue
        db_m = re.search(r"LangConfig Dashboard Meta\s*\n\s*db:\s*(\S+)", head)
        sk_m = re.search(r"db:[ \t]*\S+[ \t]*\n[ \t]*skills:[ \t]*([^\n]*)", head)
        mo_m = re.search(r"Mode:\s*(\S+)", head)
        en_m = re.search(r"entry:\s*([^\n]+)", head)
        if not db_m:
            continue
        return {
            "filename": f.name,
            "db_path": db_m.group(1),
            "skills": [s.strip() for s in sk_m.group(1).split(",")] if sk_m else [],
            "mode": mo_m.group(1) if mo_m else None,
            "entry": en_m.group(1).strip() if en_m else None,
            "table_name": "",   # unknown without reading the embedded data
            "source": "html_meta",
        }
    return None
