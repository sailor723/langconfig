#!/usr/bin/env python3
"""
Core dashboard generation module — shared by CLI (gen_dashboard.py) and API (analysis_server.py).

Usage:
    from services.dashboard_generator import generate_dashboard
    html_path = await generate_dashboard(csv_bytes, skill_bytes, "data.csv", output_dir="/tmp")
"""
import asyncio, hashlib, json, logging, os, re, sqlite3
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv; load_dotenv(override=True)

logger = logging.getLogger(__name__)


def _build_biz_context(skill_text: str) -> str:
    """Extract business context sections from a companion skill markdown."""
    lines = skill_text.split("\n")
    sections = {}
    cur = None
    cl = []
    for line in lines:
        if line.startswith("## "):
            if cur and cl:
                sections[cur] = "\n".join(cl).strip()
            cur = line[3:].strip()
            cl = []
        elif cur:
            cl.append(line)
    if cur and cl:
        sections[cur] = "\n".join(cl).strip()

    labels = {
        "Column Definitions": "COLUMNS",
        "Business Logic": "BUSINESS RULES",
        "Common Analysis Questions": "QUESTIONS",
        "Chart Configuration": "CHART CONFIG",
        "Chart Configuration": "CHART CONFIG",
    }
    parts = ["=== BUSINESS CONTEXT ==="]
    for sec, label in labels.items():
        if sec in sections:
            parts.append(f"{label}:\n{sections[sec]}")
    return "\n\n".join(parts)


def _fix_html(html: str) -> str:
    """Fix common LLM-generated JavaScript issues."""
    # Fix invalid function name fmt$(2,n) -> fmt2$(n)
    if "function fmt$(2" in html:
        html = html.replace("function fmt$(2,n)", "function fmt2$(n)")
        for v in ["fmt$(2, aov)", "fmt$(2,aov)"]:
            html = html.replace(v, "fmt2$(aov)")

    # Ensure the last <script> block (rendering code) is before </body>
    body_end = html.rfind("</body>")
    if body_end > 0:
        lss = html.rfind("<script")
        lse = html.rfind("</script>") + len("</script>")
        if 0 <= lss < lse and lse > body_end:
            block = html[lss:lse]
            html = html[:lss] + html[lse:]
            html = html.replace("</body>", block + "\n</body>")
            logger.info("Fixed: moved <script> to end of <body>")

    return html


async def generate_dashboard(
    csv_bytes: bytes,
    skill_bytes: Optional[bytes],
    csv_filename: str,
    output_dir: str | Path,
) -> str:
    """Generate a standalone Plotly HTML dashboard.

    Args:
        csv_bytes: Raw CSV file content.
        skill_bytes: Raw companion skill markdown content (or None).
        csv_filename: Original CSV filename (used for table name).
        output_dir: Directory to save the generated HTML.

    Returns:
        Path to the generated HTML file (str).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Content-hash caching ──
    content_hash = hashlib.sha256(csv_bytes + (skill_bytes or b"")).hexdigest()[:16]
    cache_file = output_dir / f"dashboard_{content_hash}.html"
    if cache_file.exists():
        pc = cache_file.read_text(encoding="utf-8").count("Plotly.newPlot")
        logger.info(f"Cache HIT: {cache_file.name} ({pc} charts)")
        return str(cache_file)
    logger.info(f"Cache key: {content_hash}")

    # ── CSV -> SQLite ──
    table_name = Path(csv_filename).stem.replace("-", "_").replace(" ", "_")
    # Import the service (works when called from backend/ context)
    from services.csv_to_sqlite import csv_to_sqlite_from_bytes
    db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_filename, table_name)
    logger.info(f"CSV -> SQLite: {db_path}")

    # ── Business context ──
    biz_context = ""
    if skill_bytes:
        skill_text = skill_bytes.decode("utf-8")
        biz_context = _build_biz_context(skill_text)
        logger.info(f"Companion skill loaded ({len(skill_text)} bytes)")

    # ── Agent setup ──
    from config import settings
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend

    skills_root = Path(__file__).resolve().parent.parent / "skills"
    backend = FilesystemBackend(root_dir=str(skills_root))

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-m3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        temperature=0.3,
    )

    @tool
    def sqlite_query(sql: str) -> str:
        """Execute SELECT query on the SQLite database."""
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(f"SELECT * FROM ({sql.strip().strip(';').strip()}) LIMIT 200")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No rows."
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

    # ── LLM prompt ──
    msg = (
        f"Data is at {db_path}.\n{biz_context}\n\n"
        "Generate a standalone Plotly HTML dashboard for this data. "
        "CRITICAL INSTRUCTION: Return ONLY the complete HTML code between ```html and ``` markers. "
        "Do NOT write to a file. Do NOT explain. Just return the HTML code.\n\n"
        "STRUCTURE RULES:\n"
        "1. Put ALL data in `var salesData = [...]` (use `var`, NOT `const`)\n"
        "2. Use CSV column names as JS keys, remove spaces (e.g. `Units Sold` -> `UnitsSold`)\n"
        "3. Define `function renderAll(data)` that re-renders ALL charts, KPIs, insights\n"
        "4. End with `renderAll(salesData);`\n"
        "5. ALSO include: Plotly.js CDN, KPI cards, section layout, "
        "charts per companion skill, insights <ul id=\"insightList\">, NO filters\n"
        "6. <script> at END of <body>\n\n"
        "Start with ```html"
    )

    # ── Invoke LLM ──
    logger.info("Generating dashboard via LLM...")
    full_response = ""
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": msg}]},
        config={"configurable": {"thread_id": f"gen-{table_name}"}, "recursion_limit": 50},
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_tool_start":
            logger.info("  Querying data...")
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if hasattr(chunk, "content") and chunk.content:
                full_response += chunk.content

    # ── Extract and fix HTML ──
    html_match = re.search(r"```html\n?(.*?)```", full_response, re.DOTALL)
    html = html_match.group(1).strip() if html_match else full_response.strip()
    html = _fix_html(html)

    # ── Save ──
    cache_file.write_text(html, encoding="utf-8")
    pc = html.count("Plotly.newPlot") + html.count("Plotly.react")
    logger.info(f"Saved: {cache_file} ({len(html)} bytes, {pc} Plotly charts)")

    if pc == 0:
        logger.warning("No Plotly charts found in output!")
        logger.warning(f"Response preview: {full_response[:500]}")

    return str(cache_file)
