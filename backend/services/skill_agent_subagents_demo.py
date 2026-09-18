"""
DeepAgent Subagent-per-Skill Demo (3 skills).

Extends skill_agent_demo.py by adding the subagent-per-skill pattern:
- Main agent has NO skills — it just delegates via `task()` to subagents
- Each subagent has isolated SkillsMiddleware for ONE skill
- LLM routes the query to the right subagent via `description`

This is the deepagents "Multiple specialized subagents" pattern from
docs (https://docs.langchain.com/oss/python/deepagents/subagents).

Run:
    cd /Users/weiping/dev/Learn/langchain-ai/langconfig/backend
    .venv/bin/python services/skill_agent_subagents_demo.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Hardcoded absolute path so this works in REPL/Jupyter (no __file__ needed).
_BACKEND = Path("/Users/weiping/dev/Learn/langchain-ai/langconfig/backend")
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "notebooks" / "module-5"))

# IDE/Trae sets DEBUG=release in env, which pydantic-settings picks up for
# `debug: bool` and fails. Strip the conflicting env var BEFORE config import.
for _key in ("DEBUG", "ENVIRONMENT"):
    os.environ.pop(_key, None)

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

from utils import stream_agent
from config import settings

load_dotenv(override=True)

# ── Domain tools (shared by main + subagents) ──────────────────────────

repl = PythonREPL()


@tool
def python_analyst(code: str):
    """Execute Python analysis. Has access to enterprise_data/ files."""
    return repl.run(code)


@tool
def generate_report(csv_path: str):
    """Generate a GlobalCorp visual report (bar + pie charts) for any CSV."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns
    import pandas as pd

    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False

    df = pd.read_csv(csv_path)
    col_map = {c: c.lower().strip() for c in df.columns}
    rev = {v: k for k, v in col_map.items()}

    region_col = rev.get("region")
    qty_col = rev.get("quantity") or rev.get("qty")
    price_col = (
        rev.get("unit_price") or rev.get("price_per_unit") or rev.get("unit price")
    )
    cat_col = (
        rev.get("product_category")
        or rev.get("prod_cat")
        or rev.get("product category")
    )
    discount_col = rev.get("discount") or rev.get("rebate")

    if not all([region_col, qty_col, price_col, cat_col]):
        return f"Error: CSV missing required columns. Found: {list(df.columns)}"

    df[price_col] = (
        df[price_col]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .astype(float)
    )

    if discount_col:
        df["Total_Revenue"] = (
            df[qty_col].astype(float) * df[price_col]
            - df[discount_col].astype(float)
        )
    else:
        df["Total_Revenue"] = df[qty_col].astype(float) * df[price_col]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    region_data = df.groupby(region_col)["Total_Revenue"].sum().sort_values(ascending=False)
    sns.barplot(
        x=region_data.index, y=region_data.values,
        hue=region_data.index, ax=ax1, palette="viridis", legend=False,
    )
    ax1.set_title("Net Revenue by Region", fontsize=14, fontweight="bold")
    ax1.set_ylabel("Revenue (USD)")

    cat_data = df.groupby(cat_col)["Total_Revenue"].sum()
    ax2.pie(
        cat_data, labels=cat_data.index, autopct="%1.1f%%", startangle=140,
        colors=sns.color_palette("pastel"),
        wedgeprops={"edgecolor": "white", "linewidth": 2},
    )
    centre_circle = plt.Circle((0, 0), 0.70, fc="white")
    ax2.add_artist(centre_circle)
    ax2.set_title("Product Category Contribution", fontsize=14, fontweight="bold")

    plt.suptitle(f"GlobalCorp Report: {csv_path}", fontsize=18)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    out_path = f"enterprise_data/report_{os.path.basename(csv_path).replace('.csv', '')}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return f"报告已保存: {out_path}"


# ── Skill definitions (3 distinct skills) ──────────────────────────────

# Each tuple: (skill_id, name, description, fs_path, system_prompt)
SKILLS = [
    (
        "market_wizard",
        "Market Wizard",
        "Cleans messy CSV files: normalizes column names, handles currency/percent strings, standardizes to canonical schema (region/product_category/quantity/price).",
        "skills/market_wizard",
        "You are the Market Wizard. Your job is data cleaning only.\n"
        "1. Read the CSV with read_file\n"
        "2. Normalize column names (lowercase, strip)\n"
        "3. Strip $/, from prices\n"
        "4. Output cleaned CSV to enterprise_data/cleaned_<name>.csv\n"
        "Return a brief summary of what was cleaned.",
    ),
    (
        "finance_pro",
        "Finance Pro",
        "Financial analysis: computes net revenue, regional tax rates (US 8%, EMEA 15%, APAC 12%), flags under-performing regions (<500 net after tax).",
        "skills/finance_pro",
        "You are the Finance Pro. Apply these rules:\n"
        "- US: 8% tax\n"
        "- EMEA: 15% tax\n"
        "- APAC: 12% tax\n"
        "- Other regions: 0% (flag for review)\n"
        "Net = (qty * price - discount) * (1 - tax)\n"
        "Flag regions with net_after_tax < 500 as UNDER_PERFORMING.\n"
        "Return a summary table.",
    ),
    (
        "unit-test-writer",
        "Unit Test Writer",
        "Writes pytest unit tests for a given function signature. Returns test file content + explains edge cases covered.",
        "skills/personal_skills/unit-test-writer",
        "You are the Unit Test Writer.\n"
        "1. Read the function signature or code via read_file\n"
        "2. Generate comprehensive pytest test cases:\n"
        "   - Happy path\n"
        "   - Edge cases (empty, zero, negative, large numbers)\n"
        "   - Type errors (None, wrong types)\n"
        "3. Return the test code as a fenced block\n"
        "Do NOT execute tests — just write them.",
    ),
]


# ── Build the agent ────────────────────────────────────────────────────


async def main():
    notebook_dir = _BACKEND / "notebooks" / "module-5"
    os.chdir(notebook_dir)
    os.makedirs("skills", exist_ok=True)
    os.makedirs("enterprise_data", exist_ok=True)

    model = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-M3"),
        base_url=settings.MINIMAX_API_BASE,
        api_key=settings.MINIMAX_API_KEY,
        streaming=True,
    )

    backend = FilesystemBackend(root_dir=str(Path.cwd()))
    checkpointer = MemorySaver()

    # ── Build subagents: one per skill ────────────────────────────────
    # Each subagent has isolated SkillsMiddleware so its SKILL.md body
    # only loads into its own context — main agent stays clean.
    subagents = []
    for skill_id, name, description, fs_path, system_prompt in SKILLS:
        subagents.append({
            "name": skill_id,
            "description": description,           # ← main agent uses this to route
            "system_prompt": system_prompt,
            "skills": [fs_path],                  # ← library creates SkillsMiddleware
            "tools": [python_analyst, generate_report],
        })
        print(f"  • Subagent: {skill_id:20s} skills=[{fs_path}]")

    # ── Main agent: just delegates via `task()` tool ─────────────────
    main_agent = create_deep_agent(
        model=model,
        tools=[],                                # ← no domain tools on main
        backend=backend,
        subagents=subagents,                     # ← library creates SubAgentMiddleware
        checkpointer=checkpointer,
        # Main agent has NO system_prompt — it routes via description.
        # The library auto-injects task descriptions into the prompt.
    )

    print()
    print("=" * 70)
    print("  Test 1: Cleaning + Finance pipeline (multi-step via task)")
    print("=" * 70)
    print()
    query1 = (
        "First have the market_wizard clean modern_marketing.csv, "
        "then have finance_pro analyze the cleaned CSV and tell me "
        "the tax summary by region."
    )
    print("User:", query1)
    print()

    await stream_agent(
        main_agent,
        {"messages": [("human", query1)]},
        config={
            "configurable": {"thread_id": "subagents-demo-1"},
            "recursion_limit": 50,
        },
    )

    print()
    print("=" * 70)
    print("  Test 2: Single subagent (unit-test-writer)")
    print("=" * 70)
    print()
    query2 = (
        "Ask unit-test-writer to write pytest tests for this function:\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b"
    )
    print("User:", query2)
    print()

    await stream_agent(
        main_agent,
        {"messages": [("human", query2)]},
        config={
            "configurable": {"thread_id": "subagents-demo-2"},
            "recursion_limit": 50,
        },
    )

    print()
    print("=" * 70)
    print("  Done — main agent delegated to market_wizard + finance_pro + unit-test-writer")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())