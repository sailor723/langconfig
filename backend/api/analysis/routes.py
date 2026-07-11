"""
Data Analysis API — CSV → SQLite → Agent Analysis → Dashboard.

Endpoints:
  POST /api/analysis/upload — upload CSV file, convert to SQLite, return schema
  POST /api/analysis/init  — convert CSV by path to SQLite, return db_path
  POST /api/analysis/chat  — chat with the sql-analyst skill about the data
"""
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── Models ──────────────────────────────────────────────────────────

class AnalysisInitRequest(BaseModel):
    session_id: str
    csv_path: str
    table_name: str = "data"


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


ANALYSIS_DBS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"


# ── List dashboards ──────────────────────────────────────────────────

@router.get("/dashboards", response_model=list[DashboardFile])
async def list_dashboards():
    """List generated dashboard HTML files, enriched with meta from each HTML's
    LangConfig Dashboard Meta comment block. The Analysis panel's chat
    panel reads db_path and skills from this list to set up chat context.
    """
    import re
    META_DB = re.compile(r"LangConfig Dashboard Meta\s*\n\s*db:\s*(\S+)")
    META_SKILLS = re.compile(r"db:\s*\S+\s*\n\s*skills:\s*([^\n]+)")
    META_MODE = re.compile(r"Mode:\s*(\S+)")
    if not ANALYSIS_DBS_DIR.exists():
        return []
    files = sorted(ANALYSIS_DBS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
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
        out.append(DashboardFile(
            filename=f.name,
            path=f"/api/files/{f.name}",
            size_bytes=f.stat().st_size,
            created=str(f.stat().st_mtime),
            db_path=db_m.group(1) if db_m else None,
            skills=[s.strip() for s in sk_m.group(1).split(",")] if sk_m else [],
            mode=mo_m.group(1) if mo_m else None,
        ))
    return out


# ── Dashboard auto-generation helper ─────────────────────────────

async def _auto_generate_dashboard(db_path: str, skill_path: Optional[str] = None) -> Optional[str]:
    """Run the analysis agent to generate an interactive HTML dashboard, return file URL."""
    import asyncio
    import re

    session_id = f"auto-dash-{Path(db_path).stem}"
    dashboard_file = None
    try:
        biz_context = ""
        if skill_path:
            try:
                from services.data_dashboard import parse_skill
                _sk = parse_skill(skill_path)
                _sec = _sk.get("sections", {})
                parts = ["\n\n=== BUSINESS CONTEXT (from companion skill) ===\n"]
                if "Column Definitions" in _sec:
                    parts.append("COLUMN DEFINITIONS:\n" + _sec["Column Definitions"])
                if "Business Logic" in _sec:
                    parts.append("BUSINESS RULES:\n" + _sec["Business Logic"])
                if "Common Analysis Questions" in _sec:
                    parts.append("KEY QUESTIONS TO ANSWER:\n" + _sec["Common Analysis Questions"])
                if "Sample SQL" in _sec:
                    parts.append("REFERENCE SQL:\n" + _sec["Sample SQL"])
                parts.append("=== END BUSINESS CONTEXT ===\n")
                biz_context = "\n\n".join(parts)
                logger.info(f"Companion skill injected: {skill_path}")
            except Exception as e:
                logger.warning(f"Skill parse failed: {e}")

        dash_msg = (
            'Generate an interactive BUSINESS dashboard using Plotly for the data at '
            f'{db_path}. Read the business context below. '
            'MUST INCLUDE: 1) Control bar with filters for each categorical '
            'column + Reset button, 2) KPI cards for key business metrics, '
            '3) 2-3 charts that answer the key business questions from the companion skill, '
            '4) Key insights section at bottom with '
            '<ul id="insightList"> that updates dynamically. '
            'Put ALL data rows in the JS array. '
            'Save the HTML file in the analysis_dbs directory with python_execute. '
            'Reply with just the filename that was saved.'
        ) + biz_context
        dash_result = await asyncio.wait_for(
            _run_analysis_agent(
                db_path=db_path,
                message=dash_msg,
                session_id=session_id,
            ),
            timeout=180,
        )
        full_text = dash_result.message or ""
        fname_match = re.search(r'analysis_dbs/([\w.-]+\.html)', full_text)
        if fname_match:
            dashboard_file = f"/api/files/{fname_match.group(1)}"
        else:
            html_files = sorted(ANALYSIS_DBS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
            if html_files:
                dashboard_file = f"/api/files/{html_files[0].name}"
    except asyncio.TimeoutError:
        logger.warning(f"Dashboard generation timed out for {db_path}")
    except Exception as e:
        logger.error(f"Dashboard generation failed: {e}")
    return dashboard_file


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
        skill_path = str(ANALYSIS_DBS_DIR / skill_file.filename)
        Path(skill_path).write_bytes(skill_bytes)
        skill_status = "active"
    elif file.filename:
        # Auto-generate companion from CSV metadata
        csv_stem = Path(file.filename).stem.replace('-', '_').replace(' ', '_')
        _skill_path = ANALYSIS_DBS_DIR / f"{csv_stem}.skill.md"
        if not _skill_path.exists():
            try:
                from services.data_skill_generator import generate_data_skill
                _result = generate_data_skill(db_path.replace('.db', '.csv'), str(ANALYSIS_DBS_DIR))
                if _result:
                    skill_path = _result
                    skill_status = "pending"
                    logger.info(f"Auto-generated companion skill: {_result}")
            except Exception as e:
                logger.warning(f"Failed to auto-generate companion: {e}")

    # Auto-generate dashboard
    dashboard_file = await _auto_generate_dashboard(db_path, skill_path=skill_path)

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

    csv_path = Path(request.csv_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"CSV not found: {request.csv_path}")

    try:
        csv_bytes = csv_path.read_bytes()
        db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_path.name, request.table_name)
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

    # Auto-generate dashboard
    dashboard_file = await _auto_generate_dashboard(db_path, skill_path=request.skill_path)

    return AnalysisInitResponse(
        db_path=db_path,
        table_name=request.table_name,
        row_count=row_count,
        col_count=len(cols),
        columns=cols,
        dashboard_file=dashboard_file,
    )


# ── Chat: Ask questions about the data

@router.post("/chat", response_model=AnalysisChatResponse)
async def analysis_chat(request: AnalysisChatRequest, db: Session = Depends(get_db)):
    """
    Chat with the sql-analyst skill about the uploaded data.

    Uses create_deep_agent with the sql-analyst SKILL.md and
    sqlite_execute / python_execute tools.
    """
    import asyncio

    db_path = request.db_path
    if not Path(db_path).exists():
        raise HTTPException(status_code=404, detail=f"Database not found: {db_path}")

    # Persist the user message BEFORE running the agent so a 504/500 timeout
    # still leaves a record of what was asked. Assistant message is appended
    # only after the agent run succeeds.
    from models.analysis_chat import AnalysisChatMessage
    dashboard_filename = request.dashboard_filename
    if dashboard_filename:
        _persist_message(db, dashboard_filename, "user", request.message)

    try:
        result = await asyncio.wait_for(
            _run_analysis_agent(
                db_path=request.db_path,
                message=request.message,
                session_id=request.session_id,
                skill_content=request.skill_content,
                skills=request.skills or ["sql-analyst"],
            ),
            timeout=120,  # 2 minute timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Analysis timed out")
    except Exception as e:
        logger.error(f"Analysis chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # Persist the assistant's reply (clean content + tool_trace separately).
    if dashboard_filename:
        _persist_message(
            db, dashboard_filename, "assistant",
            result.message, tool_trace=result.tool_trace,
        )
    return result


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
        """Execute Python code (pandas, matplotlib, plotly for dashboards)."""
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

    skills_root = Path(__file__).resolve().parent.parent / "skills"

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    backend = FilesystemBackend(root_dir=str(skills_root))
    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            f"You are a data analyst. The user's data is in a SQLite database at:\n"
            f"  {db_path}\n\n"
            f"Use sqlite_execute to query it. Discover the schema first, then answer questions.\n"
            "Use python_execute for charts and dashboards.\n"
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
    """Return live data from the SQLite source for a dashboard."""
    meta = _load_dashboard_meta(hash_id)
    if not meta:
        from fastapi import HTTPException
        raise HTTPException(404, "Dashboard not found")
    try:
        import sqlite3
        conn = sqlite3.connect(meta["db_path"])
        conn.row_factory = sqlite3.Row
        cur = conn.execute(f'SELECT * FROM "{meta["table_name"]}"')
        rows = cur.fetchall()
                # Return as objects with clean keys (no spaces)
        cols = [d[0] for d in cur.description] if cur.description else []
        clean_cols = [c.replace(" ", "") for c in cols]
        result = [{clean_cols[i]: v if v is not None else "" for i, v in enumerate(row)} for row in rows]
        conn.close()
        return result
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(500, str(e))


@router.get("/meta/{hash_id}")
async def get_analysis_meta(hash_id: str):
    """Return column metadata for a dashboard."""
    meta = _load_dashboard_meta(hash_id)
    if not meta:
        from fastapi import HTTPException
        raise HTTPException(404, "Dashboard not found")
    return meta


def _load_dashboard_meta(hash_id: str) -> dict:
    """Load dashboard metadata from data/analysis_dbs/."""
    import json
    from pathlib import Path
    dbs_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"
    # Try dashboard_{hash}.meta.json (hash-based naming)
    meta_path = dbs_dir / f"dashboard_{hash_id}.meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    # Try {stem}.meta.json (stem-based naming, e.g. sample_sales_data_dashboard)
    meta_path = dbs_dir / f"{hash_id}.meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None
