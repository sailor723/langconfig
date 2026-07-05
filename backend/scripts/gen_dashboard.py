#!/usr/bin/env python3
"""Generate Plotly dashboard: LLM generates the HTML code, script saves it. No file path issues."""
import argparse, asyncio, json, os, sys, sqlite3, subprocess, textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.csv_to_sqlite import csv_to_sqlite_from_bytes
from services.data_dashboard import parse_skill

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--skill", default=None)
    parser.add_argument("--output", default="/tmp/dashboard.html")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    from config import settings
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend

    # Convert CSV to SQLite
    csv_bytes = csv_path.read_bytes()
    table_name = csv_path.stem.replace("-", "_").replace(" ", "_")
    db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_path.name, table_name)
    print(f"CSV -> SQLite: {db_path}")

    # Build business context
    biz_context = ""
    if args.skill:
        skill_path = Path(args.skill)
        if skill_path.exists():
            skill = parse_skill(str(skill_path))
            sec = skill.get("sections", {})
            parts = ["=== BUSINESS CONTEXT ==="]
            if "Column Definitions" in sec:
                parts.append("COLUMNS:\n" + sec["Column Definitions"])
            if "Business Logic" in sec:
                parts.append("BUSINESS RULES:\n" + sec["Business Logic"])
            if "Common Analysis Questions" in sec:
                parts.append("QUESTIONS:\n" + sec["Common Analysis Questions"])
            biz_context = "\n\n".join(parts)
            print(f"Companion skill: {skill_path}")

    # Agent setup (same as original _run_analysis_agent)
    skills_root = Path(__file__).resolve().parent.parent / "skills"
    backend = FilesystemBackend(root_dir=str(skills_root))

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    from langchain_core.tools import tool

    @tool
    def sqlite_query(sql: str) -> str:
        """Execute SELECT query on the SQLite database."""
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(f"SELECT * FROM ({sql.strip().strip(';').strip()}) LIMIT 200")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            if not rows: return "No rows."
            return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)
        except Exception as e:
            return f"Error: {e}"

    checkpointer = MemorySaver()
    agent = create_deep_agent(
        model=model,
        tools=[sqlite_query],
        system_prompt="You are a data analyst. Use sqlite_query to get data. Return ONLY HTML code.",
        backend=backend,
        skills=["sql-analyst"],
        checkpointer=checkpointer,
    )

    # Ask agent to generate HTML code directly
    msg = (
        f"Data is at {db_path}.\n{biz_context}\n\n"
        f"Generate a standalone Plotly HTML dashboard for this data. "
        f"CRITICAL INSTRUCTION: Return ONLY the complete HTML code between ```html and ``` markers. "
        f"Do NOT write to a file. Do NOT explain. Just return the HTML code.\n\n"
        f"The HTML must include:\n"
        f"- Plotly.js from CDN\n"
        f"- KPI cards showing key metrics\n"
        f"- Charts answering the business questions from the companion skill\n"
        f"- ALL data rows embedded as a JS array\n"
        f"- Key insights section\n"
        f"- NO dropdown filters\n\n"
        f"Start with ```html"
    )

    print("Generating dashboard via LLM...")
    full_response = ""
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": msg}]},
        config={"configurable": {"thread_id": f"gen-{Path(csv_path).stem}"}, "recursion_limit": 30},
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            print(f"  Querying data...")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                full_response += chunk.content

    # Extract HTML from response
    import re
    html_match = re.search(r"```html\n?(.*?)```", full_response, re.DOTALL)
    if html_match:
        html = html_match.group(1).strip()
    else:
        html = full_response.strip()

    # Save
    output_path = Path(args.output)
    output_path.write_text(html, encoding="utf-8")
    plotly_count = html.count("Plotly.newPlot") + html.count("Plotly.react")
    print(f"\nSaved: {output_path} ({len(html)} bytes, {plotly_count} Plotly charts)")
    if plotly_count == 0:
        print("WARNING: No Plotly charts found in output!")
        print("Response preview (first 500 chars):")
        print(full_response[:500])

if __name__ == "__main__":
    asyncio.run(main())
