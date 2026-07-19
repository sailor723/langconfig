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
from fastapi.responses import StreamingResponse
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
    entry: Optional[str] = None  # 'hub' | 'detail' | None


ANALYSIS_DBS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"


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
    META_SKILLS = re.compile(r"db:\s*\S+\s*\n\s*skills:\s*([^\n]+)")
    META_MODE = re.compile(r"Mode:\s*(\S+)")
    META_ENTRY = re.compile(r"entry:\s*([^\n]+)")
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
        en_m = META_ENTRY.search(head)
        out.append(DashboardFile(
            filename=f.name,
            path=f"/api/files/{f.name}",
            size_bytes=f.stat().st_size,
            created=str(f.stat().st_mtime),
            db_path=db_m.group(1) if db_m else None,
            skills=[s.strip() for s in sk_m.group(1).split(",")] if sk_m else [],
            mode=mo_m.group(1) if mo_m else None,
            entry=en_m.group(1).strip() if en_m else None,
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
    if not db_full_path.exists():
        raise HTTPException(status_code=404, detail=f"Database not found: {db_path}")
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
        import sqlite3
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import MemorySaver
        from deepagents import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
        from config import settings

        skills_root = Path(__file__).resolve().parent.parent.parent / "skills"

        model = ChatOpenAI(
            model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
            base_url=settings.MINIMAX_API_BASE,
            api_key=settings.MINIMAX_API_KEY,
            temperature=0.3,
        )

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

    skills_root = Path(__file__).resolve().parent.parent.parent / "skills"

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


@router.get("/data-embedded/{filename}")
async def get_embedded_data(filename: str):
    """Return the `EMBEDDED_DATA` JSON object from a dashboard's HTML.

    Used by the Data panel to show the actual rows the dashboard renders
    (the most useful "data view" since it matches what the user sees in
    the charts). Filename must be a basename, no path separators.
    """
    from fastapi import HTTPException
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    data = _extract_embedded_data_from_html(filename)
    if not data:
        raise HTTPException(404, "No EMBEDDED_DATA in dashboard")
    return data


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


@router.get("/meta/{hash_id}")
async def get_analysis_meta(hash_id: str):
    """Return column metadata for a dashboard."""
    meta = _load_dashboard_meta(hash_id)
    if not meta:
        from fastapi import HTTPException
        raise HTTPException(404, "Dashboard not found")
    return meta


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
        sk_m = re.search(r"db:\s*\S+\s*\n\s*skills:\s*([^\n]+)", head)
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
