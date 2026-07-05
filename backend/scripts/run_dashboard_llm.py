#!/usr/bin/env python3
"""
Generate a business dashboard using the LLM agent + companion skill.

Usage:
    python run_dashboard_llm.py --csv data.csv --skill data.skill.md --output dashboard.html
    python run_dashboard_llm.py --csv data.csv --skill data.skill.md --query "revenue by region"
"""
import argparse, asyncio, json, os, sys, sqlite3, subprocess, textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.csv_to_sqlite import csv_to_sqlite_from_bytes
from services.data_dashboard import parse_skill

async def main():
    parser = argparse.ArgumentParser(description="Business Dashboard via LLM agent + companion skill")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--skill", default=None, help="Path to companion .skill.md")
    parser.add_argument("--output", default=None, help="Output path for dashboard HTML")
    parser.add_argument("--query", default=None, help="Natural language query or business question")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)

    # Parse companion skill
    companion_context = ""
    skill_path = None
    if args.skill:
        skill_path = Path(args.skill)
        if skill_path.exists():
            skill = parse_skill(str(skill_path))
            sections = skill.get("sections", {})
            companion_context = (
                "The user has provided a companion skill describing their data:\n\n"
                + f"## Column Definitions\n{sections.get('Column Definitions', 'N/A')}\n\n"
                + f"## Business Logic\n{sections.get('Business Logic', 'N/A')}\n\n"
                + f"## Common Analysis Questions\n{sections.get('Common Analysis Questions', 'N/A')}\n\n"
                + f"## Sample SQL\n{sections.get('Sample SQL', 'N/A')}"
            )
        else:
            print(f"Warning: skill file not found: {skill_path}")

    # Convert CSV to SQLite
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    csv_bytes = csv_path.read_bytes()
    table_name = csv_path.stem.replace("-", "_").replace(" ", "_")
    db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_path.name, table_name)
    print(f"CSV converted to SQLite: {db_path}")

    # Create agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    from config import settings

    skills_root = Path(__file__).resolve().parent.parent / "skills"
    backend = FilesystemBackend(root_dir=str(skills_root))

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    # Tools
    @tool_def
    def sqlite_execute(sql: str, db_path_override: str = "") -> str:
        actual = db_path_override or db_path
        sql_stripped = sql.strip().strip(";").strip()
        blocked = {"insert","update","delete","drop","alter","create","replace"}
        if sql_stripped.lower().split()[0] if sql_stripped.split() else "" in blocked:
            return "❌ BLOCKED: Only SELECT allowed."
        try:
            conn = sqlite3.connect(actual)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description] if cursor.description else []
            conn.close()
            return f"{len(rows)} row(s)\nCols: {cols}" + "\n".join(str(dict(r)) for r in rows[:30])
        except Exception as e:
            return f"Error: {e}"

    @tool_def
    def python_execute(code: str) -> str:
        try:
            wrapper = (
                "import sys, io\n_buf = io.StringIO()\nsys.stdout = _buf\n"
                + textwrap.indent(code, '    ') + "\n"
                "sys.stdout = sys.__stdout__\nprint(_buf.getvalue(), end='')"
            )
            result = subprocess.run(
                [sys.executable, "-c", wrapper],
                capture_output=True, text=True, timeout=30
            )
            out = result.stdout + result.stderr
            return f"OK\n{out[:3000]}" if out.strip() else "OK"
        except subprocess.TimeoutExpired:
            return "Timeout (>30s)"
        except Exception as e:
            return f"Error: {e}"

    checkpointer = MemorySaver()

    # The companion skill as system prompt context
    biz_context = f"""
IMPORTANT BUSINESS CONTEXT FOR THIS DATASET:
{companion_context}

Generate a BUSINESS DASHBOARD that answers the user's business questions.
The dashboard should include:
1. Filter controls for each categorical column
2. KPI cards showing key business metrics
3. Charts that answer the business questions from the companion skill
4. Key insights section
All data embedded as JS array for client-side filtering.
"""

    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt=(
            f"You are a business data analyst. The data is at: {db_path}\n"
            "Use sqlite_execute to query, python_execute for charts.\n"
            f"{biz_context}"
        ),
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    # Determine the message
    if args.output:
        output_dir = Path(args.output).parent
        msg = (
            f"Generate a business dashboard HTML for the data at {db_path}. "
            f"Read the companion skill context above. "
            f"Generate charts that answer the key business questions. "
            f"MUST INCLUDE: 1) Control bar with filters for each categorical column + Reset button, "
            f"2) KPI cards for key business metrics, "
            f"3) Charts that answer the business questions from the companion skill, "
            f"4) Key insights section at bottom with <ul id=\"insightList\">. "
            f"Put ALL data rows in the JS array. "
            f"Save the HTML file to: {Path(args.output).resolve()}"
        )
    elif args.query:
        msg = f"Answer this business question: {args.query}\nUse the data at {db_path}."
    else:
        # Default: show profile
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(f"SELECT * FROM \"{table_name}\" LIMIT 5")
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        conn.close()
        print(f"\nTable: {table_name}")
        print(f"Columns: {cols}")
        print(f"\nUse --output to generate dashboard or --query to ask questions.")
        return

    print(f"\nAgent running... (may take 1-2 minutes)")
    full_response = ""
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": msg}]},
        config={"configurable": {"thread_id": f"dash-{Path(csv_path).stem}"}, "recursion_limit": 50},
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

    if args.output:
        html_path = Path(args.output)
        if html_path.exists():
            print(f"\n✓ Dashboard saved: {html_path}")
        else:
            print(f"\n⚠ Response does not contain saved filename. Agent output was:")
            print(full_response[:500])
    elif args.query:
        print(f"\n\nAnswer:\n{full_response}")


def tool_def(func):
    """Minimal @tool decorator."""
    from langchain_core.tools import tool
    return tool(func)


if __name__ == "__main__":
    asyncio.run(main())
