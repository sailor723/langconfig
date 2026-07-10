#!/usr/bin/env python3
"""
Step 9: ERP Financial Dashboard — End-to-end LLM agent on ERP data.

Based on step 4's pattern but uses the erp-analyst skill (erp_skill.md) and
loads both skills (sql-analyst + erp-analyst) to combine generic analysis
mechanics with financial domain knowledge.

Tables: companies, income_statement, balance_sheet, cash_flow, products, customers
DB:     erp_data.db
"""
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

# Support both script mode (__file__ defined) and REPL mode
if '__file__' in globals():
    _BASE = Path(__file__).resolve()
else:
    _BASE = Path.cwd() / "skills/sql-analyst/9_erp_dashboard.py"  # REPL fallback
_BACKEND = _BASE.parent.parent.parent
_THIS_DIR = _BASE.parent
sys.path.insert(0, str(_BACKEND))

from langchain_core.tools import tool

DB_PATH = str(_THIS_DIR / "erp_data.db")
CHART_FILE = str(_THIS_DIR / "erp_best_insight.png")
SKILL_PATH = str(_THIS_DIR / "SKILL.md")
# Persist outputs in the project-wide dashboard directory so they live next to
# other analysis artifacts and can be served from LangConfig's Analysis panel.
# Use a timestamp suffix so re-runs don't clobber prior generations.
from datetime import datetime as _dt
_OUTPUT_DIR = _BACKEND.parent / "data" / "analysis_dbs"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
_RUN_STAMP = _dt.now().strftime("%Y%m%d_%H%M%S")
HTML_FILE = str(_OUTPUT_DIR / f"erp_dashboard_{_RUN_STAMP}.html")


@tool
def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """Read-only SELECT query on SQLite. Block DDL/DML."""
    sql_stripped = sql.strip().strip(";").strip()
    blocked = {"insert", "update", "delete", "drop", "alter", "create", "replace"}
    first_word = sql_stripped.lower().split()[0] if sql_stripped.split() else ""
    if first_word in blocked:
        return f"❌ BLOCKED: Only SELECT allowed. Got: '{first_word}'"
    try:
        conn = sqlite3.connect(db_path)
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
    """Execute Python code. Use for data analysis and visualization."""
    import subprocess
    import textwrap

    try:
        wrapper = (
            "import sys, io\n"
            "_buf = io.StringIO()\n"
            "sys.stdout = _buf\n"
            "sys.stderr = _buf\n"
            "try:\n"
            + textwrap.indent(code, "    ")
            + "\n"
            "except Exception:\n"
            "    import traceback; traceback.print_exc()\n"
            "finally:\n"
            "    sys.stdout = sys.__stdout__\n"
            "    sys.stderr = sys.__stderr__\n"
            "    print(_buf.getvalue(), end='')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True, text=True, timeout=30, cwd=str(_THIS_DIR)
        )
        output = result.stdout + result.stderr
        return f"✅ OK\n\n{output[:2000]}" if output.strip() else "✅ OK (no output)"
    except subprocess.TimeoutExpired:
        return "❌ Timeout (>30s)"
    except Exception as e:
        return f"❌ Error: {e}"


async def main():
    for key in ("DEBUG",):
        os.environ.pop(key, None)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from config import settings

    print("=" * 65)
    print("  Step 9: ERP Financial Dashboard")
    print("=" * 65)

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    skills_root = _BACKEND / "skills"
    backend = FilesystemBackend(root_dir=str(skills_root))
    checkpointer = MemorySaver()

    # Load BOTH skills: generic sql-analyst + ERP-specific erp-analyst
    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            "You are a financial analyst expert. "
            "Use sqlite_execute to query the ERP database. "
            "Use python_execute to generate charts and visualizations. "
            f"Read {SKILL_PATH}  for the full spec — "
            "schema, business logic, filter rules, 10-chart structure, "
            "KPI_SPEC/CHART_SPEC, dynamic dashboard pipeline, cross-chart filter, "
            "and insight format. SKILL.md is the single source of truth — follow it exactly. "
            "All UI labels, section names, and axis titles in Chinese. "
            "Theme: corporate business (navy #1e3a8a + gold #c8a96a), no green/red. "
            "Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst", "erp-analyst"],
        checkpointer=checkpointer,
    )

    # Query 1: LLM chooses best chart to show ERP insight
    query1 = (
        f"ERP database is at {DB_PATH}. SKILL.MD is at {SKILL_PATH}. "
        "Step 1: Read the erp-analyst SKILL.md and summarize your understanding of it "
        "(schema, metrics, 10-chart structure, dynamic pipeline, theme, insights). "
        "Step 2: Then follow steps in skill.md to generate full dashbaord."
    )
    print(f"\n>>> User query 1 (LLM chooses chart type):\n    {query1}")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query1}]},
        config={
            "configurable": {"thread_id": "erp-test-9a"},
            "recursion_limit": 1000,
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:150]
            print(f"\n  🔧 {name}: {inp}...")
            # Highlight when SKILL.md is being accessed
            if "SKILL" in inp or "skill" in inp:
                print(f"     📘 SKILL.md referenced!")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:250]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # Query 2: Generate interactive HTML dashboard per SKILL.md.
    # The absolute save path is handed to the LLM explicitly so the file lands
    # in the LangConfig Analysis panel's expected directory
    # (data/analysis_dbs/), not the skill folder.
    query2 = (
        f"ERP database is at {DB_PATH}. "
        "Generate the interactive HTML financial dashboard per the erp-analyst SKILL.md. "
        "Use **Mode B (Static Embed)** — inline the JSON data directly into the HTML as "
        "`var EMBEDDED = {...}` and call `renderAll(salesData)` directly in bootstrap. "
        "Do NOT use fetch(); do NOT create erp_data.json as a separate file. "
        f"**Save the HTML file at exactly this absolute path** (create parent dir if "
        f"needed, overwrite if it exists):\n`{HTML_FILE}`\n"
        "After saving, print the absolute path you wrote to so the caller can verify. "
        "The HTML must be self-contained and work when opened via file:// (no HTTP server)."
    )

    # Query 3: Simple follow-up question to verify the dashboard works
    query3 = (
        "Based on the dashboard data you just generated, "
        "which quarter had the best combination of revenue growth and ROE improvement? "
        "Show the numbers."
    )
    print(f"\n\n{'='*65}")
    print(f"  Query 2: Interactive HTML Dashboard (Plotly)")
    print(f"{'='*65}")
    print(f">>> User:\n    {query2}")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query2}]},
        config={
            "configurable": {"thread_id": "erp-test-9a"},
            "recursion_limit": 1000,
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:150]
            print(f"\n  🔧 {name}: {inp}...")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:250]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # Query 3: Simple follow-up business question
    print(f"\n\n{'='*65}")
    print(f"  Query 3: Follow-up business question")
    print(f"{'='*65}")
    print(f">>> User:\n    {query3}")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query3}]},
        config={
            "configurable": {"thread_id": "erp-test-9a"},
            "recursion_limit": 1000,
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:150]
            print(f"\n  🔧 {name}: {inp}...")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:250]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # Verify outputs. Mode B embeds everything into one HTML under
    # data/analysis_dbs, so Chart is an optional side-product and there is no
    # separate erp_data.json (data is inlined into the HTML).
    html_path = Path(HTML_FILE)
    print()
    if html_path.exists():
        print(f"✅ Dashboard created: {html_path} ({html_path.stat().st_size} bytes)")
        print(f"   👉 Open in the LangConfig Analysis panel → charts render.")
    else:
        print(f"❌ Dashboard not found at {html_path} (check agent output above)")

    png_path = Path(CHART_FILE)
    if png_path.exists():
        print(f"✅ Chart created: {png_path} ({png_path.stat().st_size} bytes)")

    print("\n✅ Step 9 complete!")


if __name__ == "__main__":
    asyncio.run(main())
