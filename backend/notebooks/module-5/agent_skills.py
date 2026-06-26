"""
DeepAgent Skills Progressive Disclosure Demo (terminal version)

Demonstrates how the skill middleware's built-in progressive disclosure works.
The middleware automatically injects the skill catalog. The agent reads skills
on demand using built-in file tools.

Usage: uv run python notebooks/module-5/agent_skills.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure module dir is on path so we can import utils
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SKILLS_SYSTEM_PROMPT
from utils import stream_agent

load_dotenv(override=True)

# Show what the middleware auto-injects
print("=" * 70)
print("  Middleware Skill Prompt (auto-injected):")
print("=" * 70)
print(SKILLS_SYSTEM_PROMPT)
print("=" * 70)

# ── Tools ──────────────────────────────────────────────────────────────

repl = PythonREPL()


@tool
def python_analyst(code: str):
    """Execute Python analysis. Has access to enterprise_data/ files."""
    return repl.run(code)


@tool
def generate_report(csv_path: str):
    """
    Generate a GlobalCorp visual report (bar + pie charts) for any CSV.
    Handles standard and cleaned column naming conventions.
    """
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


# ── Main ───────────────────────────────────────────────────────────────


async def main():
    os.makedirs("skills/finance_pro", exist_ok=True)
    os.makedirs("skills/market_wizard", exist_ok=True)
    os.makedirs("enterprise_data", exist_ok=True)

    model = init_chat_model(
        model="agnes-2.0-flash",
        model_provider="openai",
        base_url=os.getenv("AGNES_BASE_URL"),
        api_key=os.getenv("AGNES_API_KEY"),
        streaming=True,
    )

    root_dir = Path.cwd()
    backend = FilesystemBackend(root_dir=str(root_dir))
    checkpointer = MemorySaver()

    # No system_prompt — middleware auto-injects Skills prompt
    agent = create_deep_agent(
        model=model,
        tools=[python_analyst, generate_report],
        backend=backend,
        skills=[str(root_dir / "skills")],
        checkpointer=checkpointer,
    )

    query = "请分析 modern_marketing.csv 并给我一份完整的分析报告"

    print()
    print("=" * 70)
    print("  User:", query)
    print("  Watch progressive disclosure: agent sees skill names,")
    print("  reads SKILL.md on demand, analyzes data, generates charts.")
    print("=" * 70)
    print()

    # Use the same stream_agent from utils.py (rich-formatted output)
    await stream_agent(
        agent,
        {"messages": [("human", query)]},
        config={
            "configurable": {"thread_id": "skills-demo-1"},
            "recursion_limit": 50,
        },
    )

    print()
    print("=" * 70)
    print("  Done - check enterprise_data/ for generated charts")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
