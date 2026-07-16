#!/usr/bin/env python3
"""
Sun Hing KPI Dashboard — DeepAgent generates interactive dashboard.

Follows the same pattern as erp-analyst/9_erp_dashboard.py:
  1. Load sunhing-analyst skill (SKILL.md has schema + KPI defs + chart spec)
  2. Agent queries sunhing_kpi.db via sqlite_execute
  3. Agent generates standalone Plotly HTML dashboard via python_execute
  4. Saved to data/analysis_dbs/
"""

import asyncio, os, sqlite3, sys
from pathlib import Path

# Path resolution
_BASE = Path(__file__).resolve()
_BACKEND = _BASE.parent.parent.parent
_THIS_DIR = _BASE.parent
sys.path.insert(0, str(_BACKEND))

from langchain_core.tools import tool
from datetime import datetime as _dt

SKILLS_DIR = _BACKEND / "skills"
_PROJECT_ROOT = _BACKEND.parent
_OUTPUT_DIR = _PROJECT_ROOT / "data" / "analysis_dbs"
DB_PATH = str(_OUTPUT_DIR / "sunhing_kpi.db")
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HTML_FILE = _OUTPUT_DIR / f"sunhing_dashboard_{_dt.now().strftime('%Y%m%d_%H%M%S')}.html"


@tool
def sqlite_execute(sql: str) -> str:
    """Read-only SELECT query on sunhing_kpi.db. Only SELECT allowed."""
    sql_stripped = sql.strip().strip(";").strip()
    blocked = {"insert", "update", "delete", "drop", "alter", "create", "replace"}
    first_word = sql_stripped.lower().split()[0] if sql_stripped.split() else ""
    if first_word in blocked:
        return f"❌ BLOCKED: Only SELECT allowed. Got: '{first_word}'"
    try:
        conn = sqlite3.connect(str(DB_PATH))
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
    """Execute Python code. Use for Plotly chart generation and HTML assembly."""
    import subprocess, textwrap
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
            capture_output=True, text=True, timeout=60, cwd=str(_THIS_DIR)
        )
        output = result.stdout + result.stderr
        return f"✅ OK\n\n{output[:3000]}" if output.strip() else "✅ OK (no output)"
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
    print("  Sun Hing KPI Dashboard Generator")
    print("=" * 65)

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    backend = FilesystemBackend(root_dir=str(SKILLS_DIR))
    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            "You are a transformation KPI analyst for Sun Hing Vision Group. "
            "Use sqlite_execute to query sunhing_kpi.db. "
            "Use python_execute to generate Plotly HTML dashboards. "
            "Read SKILL.md from the sunhing-analyst skill for the full spec — "
            "schema, KPI definitions, chart spec, design rules, and data sources. "
            "SKILL.md is the single source of truth — follow it exactly. "
            "All labels, titles, UI text in Chinese. "
            "Theme: corporate (navy #1a1a2e), green #2ca02c for met targets, red #e74c3c for warnings. "
            "Reply in Chinese."
        ),
        backend=backend,
        skills=["sunhing-analyst"],
        checkpointer=checkpointer,
    )

    # Query 1: Agent reads SKILL.md and understands the data
    query1 = (
        f"Sun Hing KPI database is at {DB_PATH}. "
        "1. Read the sunhing-analyst SKILL.md "
        "2. List all 13 tables you found "
        "3. Confirm you understand the KPI definitions and chart spec"
    )
    print(f"\n>>> Query 1: Understand data + SKILL.md")
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query1}]},
        config={"configurable": {"thread_id": "sunhing-1"}, "recursion_limit": 1000},
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:150]
            print(f"\n  🔧 {name}: {inp}...")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:200]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # Query 2: Generate full interactive dashboard
    query2 = (
        f"Sun Hing KPI database is at {DB_PATH}. "
        "Generate the full interactive HTML transformation KPI dashboard per SKILL.md. "
        "Use Mode B (Static Embed) — embed all data as `var EMBEDDED_DATA = {...}` "
        "into the HTML. Do NOT use fetch(). "
        f"Save to exactly: `{HTML_FILE}` (overwrite if exists). "
        "After saving, print the absolute path and file size."
    )
    print(f"\n\n{'='*65}")
    print(f"  Query 2: Generate interactive HTML dashboard")
    print(f"{'='*65}")
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": query2}]},
        config={"configurable": {"thread_id": "sunhing-1"}, "recursion_limit": 1000},
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:150]
            print(f"\n  🔧 {name}: {inp}...")
        elif kind == "on_tool_end":
            out = str(event.get("data", {}).get("output", ""))[:200]
            print(f"  ✅ {out}")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)

    # ── Post-process: inject LangConfig Dashboard Meta block ──────
    # The Analysis panel in LangConfig reads this block to discover the
    # source DB and the agent skills needed for the chat panel.
    import re as _re_meta
    html_path = Path(HTML_FILE)
    if html_path.exists():
        txt = html_path.read_text(encoding="utf-8")
        if "LangConfig Dashboard Meta" not in txt:
            from datetime import datetime as _dt_meta
            meta_block = (
                "<!--\n"
                f"  Generated: {_dt_meta.now().strftime('%Y-%m-%d')} "
                "| Source: sunhing_kpi.db | Mode: static-embed\n"
                "  LangConfig Dashboard Meta\n"
                f"  db: {DB_PATH}\n"
                "  skills: sunhing-analyst\n"
                "-->"
            )
            # Insert right after <head> or after the first <!-- comment
            patched = _re_meta.sub(
                r"(<head>\s*\n)",
                r"\1" + meta_block + "\n",
                txt,
                count=1,
            )
            if patched != txt:
                html_path.write_text(patched, encoding="utf-8")
                print(f"📝 Injected LangConfig Dashboard Meta block")
            else:
                print(f"⚠ Could not inject meta block (no <head> found)")

        print(f"\n\n✅ Dashboard generated: {html_path} ({html_path.stat().st_size} bytes)")
        print(f"   Now available in LangConfig Analysis Panel")
    else:
        print(f"\n\n❌ Dashboard not found at {html_path}")
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())
