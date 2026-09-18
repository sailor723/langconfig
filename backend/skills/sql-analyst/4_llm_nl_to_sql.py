#!/usr/bin/env python3
"""
Step 5: Layer 4 — Skill Binding + Layer 5 — Visualization.

Shows:
  - What SkillsMiddleware injects into system prompt
  - Full end-to-end: NL → SQL → Python chart → Report
"""
import asyncio
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))

# SQL skill + visualization tools inline (same as 4_llm_nl_to_sql.py + chart gen)
import sqlite3
from langchain_core.tools import tool

DB_PATH = str(_THIS_DIR / "sample_sales.db")

@tool
def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """Read-only SELECT query on SQLite. Block DDL/DML."""
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
    """Execute Python code for data analysis/visualization (pandas, matplotlib)."""
    import io, traceback, subprocess, tempfile, textwrap
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
        return f"✅ Execution OK\n\n{output[:2000]}" if output.strip() else "✅ Execution OK (no output)"
    except subprocess.TimeoutExpired:
        return "❌ Timeout (>30s)"
    except Exception as e:
        return f"❌ Error: {e}"


async def main():
    # Hardcoded skill catalog (this is what SkillsMiddleware auto-generates)
    print("=" * 65)
    print("  Layer 4: Skill Binding — What gets injected")
    print("=" * 65)
    print("""
    create_deep_agent(
        tools=[sqlite_execute, python_execute],
        skills=["sql-analyst"],      ← SkillsMiddleware reads SKILL.md
        backend=FilesystemBackend,    ← from backend/skills/
    )
    
    SkillsMiddleware auto-injects into system prompt:
    ┌─────────────────────────────────────────────────┐
    │ ## Available Skills                              │
    │                                                  │
    │ sql-analyst: SQL data analysis specialist.       │
    │   Queries SQLite databases, analyzes CSV data,  │
    │   generates insights, creates visualizations...  │
    │   Tools: [sqlite_execute, python_execute, ...]   │
    │   Triggers: when user uploads CSV, asks about    │
    │     SQL analysis, wants charts or dashboards...  │
    └─────────────────────────────────────────────────┘
    
    When LLM calls read_file("skills/sql-analyst/SKILL.md"):
    → Full 5-step workflow returned (progressive disclosure)
""")

    # Now run the full end-to-end
    for key in ("DEBUG",):
        os.environ.pop(key, None)
    from dotenv import load_dotenv; load_dotenv(override=True)
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from config import settings

    print("=" * 65)
    print("  Layer 5: End-to-End — NL → SQL → Chart → Report")
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

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            "You are a data analyst expert. "
            "Use sqlite_execute to query the database. "
            "Use python_execute to generate charts and visualizations. "
            "Always read the skill file first for guidance. "
            "Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    # Query 1: Let LLM decide on chart type
    query1 = (
        f"I have a sales database at {DB_PATH}. "
        "Analyze the data and decide the best chart type to visualize it. "
        "Create a chart that gives the most insight, save it to best_insight.png. "
        "Explain WHY you chose that chart type over others."
    )
    print(f"\n>>> User query 1 (LLM chooses chart type):\n    {query1}")
    print(f"\n{'='*65}")
    print("  Streaming:")
    print("=" * 65)

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query1}]},
        config={
            "configurable": {"thread_id": "sql-test-5a"},
            "recursion_limit": 50,
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

    # Query 2: Interactive HTML dashboard with Plotly
    query2 = (
        f"I have a sales database at {DB_PATH}. "
        "Create an interactive HTML dashboard using Plotly. Include: "
        "1) A bar chart of top 5 products by revenue, "
        "2) A pie chart of revenue by sales region, "
        "3) A line chart of monthly revenue trend. "
        "Arrange them in a nice layout. "
        "Save to interactive_dashboard.html. "
        "Tell me what insights you find."
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
            "configurable": {"thread_id": "sql-test-5b"},
            "recursion_limit": 50,
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

    print(f"\n\n✅ Layer 4+5 complete!")


if __name__ == "__main__":
    asyncio.run(main())
