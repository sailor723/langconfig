"""
Create mock test data for Phase 9 graphindex testing.

Creates 3 small .md files in the project_1 docs folder, then runs
--rebuild-project to index them in Neo4j with LLM enrichment.
Run once to set up test data for all 5 CLI commands.

Usage:
    python create_mock_data.py
    # Then test:
    python -m learning.phase9.graphindex.index_build --list --project-id 1
    python -m learning.phase9.graphindex.index_build --show "mock_01_tesla_model3.md" --project-id 1
    python -m learning.phase9.graphindex.index_build --query "best selling ev" --project-id 1
"""
import sys
sys.path.insert(0, '/Users/weiping/dev/Learn/langchain-ai/langconfig')
from learning.phase9.graphindex.index_build import _DOCS_BASE
from pathlib import Path

PROJECT_DIR = _DOCS_BASE / "project_1"

MOCK_FILES = {
    "mock_01_tesla_model3.md": (
        "# Tesla Model 3 — Market Analysis\n\n"
        "The Tesla Model 3 was the best-selling electric vehicle globally in 2024, "
        "with over 500,000 units delivered. Key markets include North America, "
        "Europe, and China. The Model 3 dominates the midsize EV sedan segment.\n\n"
        "## Key Metrics\n"
        "- Global deliveries: 500,000+\n"
        "- Top market: China (35% of sales)\n"
        "- Average selling price: $42,000\n"
        "- Customer satisfaction: 4.7/5"
    ),
    "mock_02_byd_seal.md": (
        "# BYD Seal — Competitive Analysis\n\n"
        "The BYD Seal is a direct competitor to the Tesla Model 3 in the EV sedan "
        "market. Launched in 2023, it achieved 200,000 deliveries in 2024. "
        "The Seal offers competitive pricing and advanced Blade Battery technology.\n\n"
        "## Key Metrics\n"
        "- Global deliveries: 200,000+\n"
        "- Top market: China (80% of sales)\n"
        "- Average selling price: $28,000\n"
        "- Blade Battery range: 500km+"
    ),
    "mock_03_ev_market_2024.md": (
        "# Global EV Market Summary 2024\n\n"
        "The global EV market grew 25% year-over-year in 2024, reaching 14 million "
        "units sold. BYD leads overall with 3 million units, followed by Tesla at "
        "1.8 million. Chinese brands account for 60% of global EV production.\n\n"
        "## Top Players\n"
        "1. BYD — 3,000,000 units\n"
        "2. Tesla — 1,800,000 units\n"
        "3. SAIC — 1,200,000 units\n"
        "4. Geely — 900,000 units\n"
        "5. Volkswagen — 700,000 units"
    ),
}

def create_mock_data():
    print("Creating mock files in project_1...\n")
    for name, content in MOCK_FILES.items():
        path = PROJECT_DIR / name
        path.write_text(content)
        print(f"  ✓ created: {path.name}  ({len(content)} chars)")

    print("\nDone. Now run rebuild to index in Neo4j:")
    print(f"  python -m learning.phase9.graphindex.index_build --rebuild-project --project-id 1")
    print(f"  python -m learning.phase9.graphindex.index_build --list --project-id 1")

if __name__ == "__main__":
    create_mock_data()
