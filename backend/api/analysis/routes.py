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
    dashboard_file: Optional[str] = None  # path to generated HTML dashboard


class AnalysisChatRequest(BaseModel):
    session_id: str
    db_path: str
    message: str


class AnalysisChatResponse(BaseModel):
    message: str
    content: str = ""
    tool_calls: int = 0
    total_tokens: int = 0


class DashboardFile(BaseModel):
    filename: str
    path: str
    size_bytes: int
    created: str


ANALYSIS_DBS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "analysis_dbs"


# ── List dashboards ──────────────────────────────────────────────────

@router.get("/dashboards", response_model=list[DashboardFile])
async def list_dashboards():
    """List generated dashboard HTML files."""
    if not ANALYSIS_DBS_DIR.exists():
        return []
    files = sorted(ANALYSIS_DBS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        DashboardFile(
            filename=f.name,
            path=f"/api/files/{f.name}",
            size_bytes=f.stat().st_size,
            created=str(f.stat().st_mtime),
        )
        for f in files
    ]


# ── Dashboard auto-generation helper ─────────────────────────────

async def _auto_generate_dashboard(db_path: str) -> Optional[str]:
    """Run the analysis agent to generate an interactive HTML dashboard, return file URL."""
    import asyncio
    import re

    session_id = f"auto-dash-{Path(db_path).stem}"
    dashboard_file = None
    try:
        dash_msg = (
            'Generate an interactive HTML dashboard using Plotly for the data at '
            f'{db_path}. MUST INCLUDE: 1) Control bar with filters for each categorical '
            'column + Reset button, 2) KPI cards for key metrics, 3) 2-3 charts '
            '(bar + pie + optional line), 4) Key insights section at bottom with '
            '<ul id="insightList"> that updates dynamically. '
            'Put ALL data rows in the JS array. '
            'Save the HTML file in the analysis_dbs directory with python_execute. '
            'Reply with just the filename that was saved.'
        )
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

    # Auto-generate dashboard
    dashboard_file = await _auto_generate_dashboard(db_path)

    return AnalysisInitResponse(
        db_path=db_path,
        table_name=table_name,
        row_count=row_count,
        col_count=len(cols),
        columns=cols,
        dashboard_file=dashboard_file,
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
    dashboard_file = await _auto_generate_dashboard(db_path)

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

    try:
        result = await asyncio.wait_for(
            _run_analysis_agent(
                db_path=request.db_path,
                message=request.message,
                session_id=request.session_id,
            ),
            timeout=120,  # 2 minute timeout
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Analysis timed out")
    except Exception as e:
        logger.error(f"Analysis chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _run_analysis_agent(
    db_path: str,
    message: str,
    session_id: str,
) -> AnalysisChatResponse:
    """Run the sql-analyst deep agent with the given message."""
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
            "Read the SKILL.md for guidance. Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    # ── Invoke ───────────────────────────────────────────────────────

    full_response = ""
    tool_call_count = 0

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
            tool_call_count += 1
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                full_response += chunk.content

    return AnalysisChatResponse(
        message=full_response,
        content=full_response,
        tool_calls=tool_call_count,
        total_tokens=len(full_response.split()),
    )
