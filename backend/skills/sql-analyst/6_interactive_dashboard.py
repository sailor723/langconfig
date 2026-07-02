#!/usr/bin/env python3
"""
Step 6: Interactive HTML Dashboard — Test Plotly via python_execute + SkillsMiddleware.

No API server needed. Uses create_deep_agent with Plotly template from SKILL.md.
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

@tool
def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """Read-only SELECT on SQLite. Block DDL/DML."""
    sql_stripped = sql.strip().strip(";").strip()
    blocked = {"insert","update","delete","drop","alter","create","replace"}
    first_word = sql_stripped.lower().split()[0] if sql_stripped.split() else ""
    if first_word in blocked:
        return f"❌ BLOCKED: Only SELECT allowed. Got: '{first_word}'"
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
        rows = cursor.fetchall()
        col_names = [d[0] for d in cursor.description] if cursor.description else []
        if not rows: conn.close(); return "✅ No rows."
        widths = [len(c) for c in col_names]
        for row in rows:
            for i, v in enumerate(row):
                widths[i] = max(widths[i], len(str(v)))
        header = " | ".join(c.ljust(w) for c, w in zip(col_names, widths))
        sep = "-+-".join("-"*w for w in widths)
        body = "\n".join(" | ".join(str(v).ljust(w) for v,w in zip(row,widths)) for row in rows[:50])
        conn.close()
        return f"✅ {len(rows)} row(s)\n\n{header}\n{sep}\n{body}"
    except Exception as e:
        return f"❌ Error: {e}"

@tool
def python_execute(code: str) -> str:
    """Execute Python code. Use for data analysis and HTML generation."""
    import subprocess, textwrap
    try:
        wrapper = (
            "import sys, io\n"
            "_buf = io.StringIO()\n"
            "sys.stdout = _buf\n"
            "sys.stderr = _buf\n"
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
    from dotenv import load_dotenv; load_dotenv(override=True)
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from config import settings

    print("=" * 65)
    print("  Step 6: Interactive HTML Dashboard (Plotly)")
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
            "You are a data analyst. "
            "Use sqlite_execute to query the database. "
            "Use python_execute to generate interactive HTML with Plotly. "
            "Read the SKILL.md for exact chart patterns. Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    query = (
        f"I have a sales database at {DB_PATH}. "
        "Create an interactive HTML page using Plotly that shows: "
        "1) A bar chart: top 3 products by total revenue "
        "2) A pie chart: revenue % by sales region "
        "Save to interactive_dashboard.html. "
        "Make it a clean, single-page dashboard."
    )
    print(f"\n>>> Query:\n    {query}")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "html-test"}, "recursion_limit": 60},
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

    # Verify file
    html_path = _THIS_DIR / "interactive_dashboard.html"
    if html_path.exists():
        size = html_path.stat().st_size
        print(f"\n\n✅ HTML dashboard created: {html_path} ({size} bytes)")
        print(f"   Open it: open {html_path}")
    else:
        print(f"\n\n⚠️  HTML file not found at {html_path}")

    print("\n✅ Step 6 complete!")


if __name__ == "__main__":
    asyncio.run(main())
