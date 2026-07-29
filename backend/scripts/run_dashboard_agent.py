#!/usr/bin/env python3
"""
Standalone business dashboard generator.
Follows the same process as the LangConfig analysis UI, but Python-only.
No FastAPI server needed.

Usage:
    python run_dashboard_agent.py --csv data.csv --skill data.skill.md --output dashboard.html
    python run_dashboard_agent.py --csv data.csv --skill data.skill.md --query "top products"
    python run_dashboard_agent.py --db data/analysis_dbs/sunhing_kpi.db --skill backend/skills/sunhing-analyst/SKILL.md --query "What is 资产周转率?"
"""
import argparse, asyncio, os, sys, sqlite3, subprocess, textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.csv_to_sqlite import csv_to_sqlite_from_bytes
from services.data_dashboard import parse_skill


async def main():
    parser = argparse.ArgumentParser(description="Business Dashboard via LLM agent + companion skill")
    parser.add_argument("--csv", default=None, help="Path to CSV file")
    parser.add_argument("--db", default=None, help="Path to existing SQLite database")
    parser.add_argument("--skill", default=None, help="Path to companion .skill.md")
    parser.add_argument("--output", default=None, help="Path to save dashboard HTML")
    parser.add_argument("--query", default=None, help="Business question to answer")
    args = parser.parse_args()

    if not args.csv and not args.db:
        print("Error: provide either --csv or --db")
        sys.exit(1)
    if args.csv and args.db:
        print("Error: use only one of --csv or --db")
        sys.exit(1)

    csv_path = Path(args.csv) if args.csv else None
    db_input_path = Path(args.db) if args.db else None
    if csv_path and not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)
    if db_input_path and not db_input_path.exists():
        print(f"Error: DB not found: {db_input_path}")
        sys.exit(1)

    # ── 1. Load environment ─────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(override=True)
    from config import settings

    # ── 2. Determine SQLite source ──────────────────────────────
    if csv_path:
        csv_bytes = csv_path.read_bytes()
        table_name = csv_path.stem.replace("-", "_").replace(" ", "_")
        db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_path.name, table_name)
        source_name = csv_path.name
        thread_key = csv_path.stem
        print(f"1. CSV → SQLite: {db_path}")
    else:
        table_name = None
        db_path = str(db_input_path.resolve())
        source_name = db_input_path.name
        thread_key = db_input_path.stem
        print(f"1. Using existing SQLite DB: {db_path}")

    # ── 3. Parse companion skill ────────────────────────────────
    biz_context = ""
    if args.skill:
        skill_path = Path(args.skill)
        if skill_path.exists():
            skill = parse_skill(str(skill_path))
            sec = skill.get("sections", {})
            parts = ["\n\n=== BUSINESS CONTEXT ===\n"]
            if "Column Definitions" in sec:
                parts.append("COLUMNS:\n" + sec["Column Definitions"])
            if "Business Logic" in sec:
                parts.append("BUSINESS RULES:\n" + sec["Business Logic"])
            if "Common Analysis Questions" in sec:
                parts.append("QUESTIONS TO ANSWER:\n" + sec["Common Analysis Questions"])
            if "Sample SQL" in sec:
                parts.append("REFERENCE SQL:\n" + sec["Sample SQL"])
            # Keep the full skill available for domain-specific skills whose headings
            # do not match the generic English section names above.
            parts.append("FULL SKILL MARKDOWN:\n" + skill.get("raw", ""))
            parts.append("=== END BUSINESS CONTEXT ===")
            biz_context = "\n\n".join(parts)
            print(f"2. Companion skill loaded: {skill_path}")
        else:
            print(f"Warning: skill not found: {skill_path}")
    else:
        print(f"2. No companion skill — dashboard will be generic")

    # ── 4. Create deep agent (same pattern as _run_analysis_agent) ──
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from langchain_core.tools import tool

    skills_root = Path(__file__).resolve().parent.parent / "skills"
    backend = FilesystemBackend(root_dir=str(skills_root))

    # Use DeepSeek (same as agent-workspace backend)
    model = ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        temperature=0.3,
    )

    @tool
    def sqlite_execute(sql: str) -> str:
        """Execute a read-only SELECT query on the SQLite database."""
        sql_s = sql.strip().strip(";").strip()
        blocked = {"insert", "update", "delete", "drop", "alter", "create", "replace"}
        if sql_s.lower().split()[0] if sql_s.split() else "" in blocked:
            return "❌ Only SELECT allowed."
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(f"SELECT * FROM ({sql_s}) LIMIT 200")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            if not rows: return "No rows."
            return f"{len(rows)} row(s)\nCols: {cols}\n" + "\n".join(str(dict(r)) for r in rows[:50])
        except Exception as e:
            return f"Error: {e}"

    @tool
    def python_execute(code: str) -> str:
        """Execute Python code (pandas, plotly, matplotlib). Use for charts and HTML."""
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
                [sys.executable, "-c", wrapper],
                capture_output=True, text=True, timeout=30
            )
            out = result.stdout + result.stderr
            return f"OK\n{out[:3000]}" if out.strip() else "OK (no output)"
        except subprocess.TimeoutExpired:
            return "Timeout (>30s)"
        except Exception as e:
            return f"Error: {e}"

    checkpointer = MemorySaver()
    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            f"You are a business data analyst. Data is at: {db_path}\n"
            f"Source name: {source_name}\n"
            "Use sqlite_execute to query, python_execute for HTML/Plotly.\n"
            "Always use sqlite_execute to verify numeric answers from the database.\n"
            "Reply in Chinese."
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )
    print("3. Agent created (sql-analyst skill + Minimax M3)")
    print("4. Running agent to generate dashboard...")

    # ── 5. Determine message ────────────────────────────────────
    if args.output:
        msg = (
            "Generate an interactive BUSINESS dashboard using Plotly for "
            f"the data at {db_path}. "
            f"{biz_context}"
            "MUST INCLUDE: "
            "1) Control bar with filters for each categorical column + Reset button, "
            "2) KPI cards for key business metrics, "
            "3) Charts that answer the key business questions from the companion skill, "
            "4) Key insights section at bottom with "
            "<ul id='insightList'>. "
            f"Save the HTML file to {Path(args.output).resolve()} using python_execute. "
            "Put ALL data rows in the JS array for client-side filtering. "
            "Reply with just the saved filename."
        )
    elif args.query:
        msg = f"Answer this business question using the data: {args.query}\n{biz_context}"
    else:
        # Just show schema
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        if table_name:
            cur = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 5')
        else:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        print(f"\nSource: {source_name}")
        if table_name:
            print(f"Table: {table_name}\nColumns: {cols}")
        else:
            print(f"Columns: {cols}")
            print(f"Rows: {[dict(r) for r in rows[:20]]}")
        print("Use --output to generate dashboard or --query to ask questions.")
        return

    # ── 6. Invoke agent ─────────────────────────────────────────
    full_response = ""
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": msg}]},
        config={
            "configurable": {"thread_id": f"dash-{thread_key}"},
            "recursion_limit": int(os.getenv("ANALYSIS_RECURSION_LIMIT", "1000")),
        },
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            name = event.get("name", "")
            inp = str(event.get("data", {}).get("input", ""))[:80]
            print(f"  Tool: {name}({inp}...)")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                full_response += chunk.content
                if not args.output:
                    print(chunk.content, end="", flush=True)

    # ── 7. Show result ──────────────────────────────────────────
    if args.output:
        html_path = Path(args.output)
        if html_path.exists():
            print(f"\n✓ Dashboard saved: {html_path} ({html_path.stat().st_size:,} bytes)")
        else:
            print(f"\nResponse:\n{full_response[:500]}")
    elif args.query:
        print(f"\nAnswer:\n{full_response}")


if __name__ == "__main__":
    asyncio.run(main())
