#!/usr/bin/env python3
"""
Step 7: Business Insight Report — Enriched analysis using updated SKILL.md.
Generates a self-contained HTML report with KPI trends, proactive insights,
anomaly detection, and business recommendations.

Usage:
    python 7_business_insight_report.py
"""
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))

from langchain_core.tools import tool

DB_PATH = str(_THIS_DIR / "sample_sales.db")
OUTPUT_FILE = str(_THIS_DIR / "business_insight_report.html")


@tool
def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """Read-only SELECT on SQLite. Block DDL/DML."""
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
    """Execute Python code. Use for data analysis and HTML generation."""
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
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_THIS_DIR),
        )
        output = result.stdout + result.stderr
        return f"✅ OK\n\n{output[:2000]}" if output.strip() else "✅ OK (no output)"
    except subprocess.TimeoutExpired:
        return "❌ Timeout (>60s)"
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
    print("  Step 7: Business Insight Report (Enriched Analysis)")
    print("=" * 65)

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    backend = FilesystemBackend(root_dir=str(_BACKEND / "skills"))
    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            "You are a business data analyst. "
            "Use sqlite_execute to query the database. "
            "Use python_execute to generate HTML output. "
            "Read the SKILL.md for enriched analysis patterns. "
            "Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    # Simple focused query — follows same pattern as step 6
    query = (
        f"I have a sales database at {DB_PATH}. "
        "Please create a comprehensive Business Insight Report.\n\n"
        f"CRITICAL: Use python_execute to SAVE the HTML file to: r'{OUTPUT_FILE}'\n"
        "Do NOT return the HTML in your response text.\n\n"
        "The report must include:\n"
        "1. Executive Summary — top findings (what happened, why it matters, what to do)\n"
        "2. KPI cards with trend indicators (↑↓) and period comparison\n"
        "3. Charts via Plotly.js CDN: revenue by product (bar), by region (pie), "
        "daily trend with moving average (line), customer ranking (horizontal bar), "
        "category AOV (bar), price vs volume scatter\n"
        "4. Proactive Insights — categorized as finding/trend/anomaly/action\n"
        "5. Business Recommendations — actionable next steps\n\n"
        "Embed data in `var salesData = [...]` with camelCase keys. "
        "Define `function renderAll(data)` that renders everything. "
        "Call `renderAll(salesData)` at the end. "
        "Put <script> at end of <body>."
    )
    print(f"\n>>> Query:\n    {query[:300]}...")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query}]},
        config={
            "configurable": {"thread_id": "insight-report"},
            "recursion_limit": 80,
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:120]
            print(f"\n  🔧 {name}: {inp}...")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:200]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # Verify the output file
    html_path = Path(OUTPUT_FILE)
    if html_path.exists():
        size = html_path.stat().st_size
        content = html_path.read_text(encoding="utf-8")
        chart_count = content.count("Plotly.newPlot") + content.count("Plotly.react")
        insight_count = content.count("<li class=")
        print(f"\n\n✅ Business Insight Report created: {html_path}")
        print(f"   Size: {size} bytes")
        print(f"   Charts: {chart_count}")
        print(f"   Insights + Recommendations: {insight_count}")
        print(f"   Open it: open {html_path}")
    else:
        print(f"\n\n⚠️  Report not found at {OUTPUT_FILE}")

    print("\n✅ Step 7 complete!")


if __name__ == "__main__":
    asyncio.run(main())
