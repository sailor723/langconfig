#!/usr/bin/env python3
"""
CLI entry point for Data Dashboard + Q&A.
Usage:
    python run_dashboard.py --csv data.csv --skill data.skill.md --output dashboard.html
    python run_dashboard.py --csv data.csv --skill data.skill.md --query "total revenue by region"
    python run_dashboard.py --csv data.csv --query "top 5 products"   # auto-generate skill if missing
"""

import argparse, sys, json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.data_dashboard import generate_dashboard, answer_query, parse_skill, compute_metrics


def main():
    parser = argparse.ArgumentParser(description="Data Dashboard + Q&A from CSV + companion .skill.md")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--skill", default=None, help="Path to companion .skill.md (optional)")
    parser.add_argument("--output", default=None, help="Output path for dashboard HTML")
    parser.add_argument("--query", default=None, help="Natural language query to answer")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)

    # Auto-detect companion skill
    skill_path = args.skill
    if not skill_path:
        candidates = [
            csv_path.with_suffix(".skill.md"),
            csv_path.parent / f"{csv_path.stem}.skill.md",
        ]
        for c in candidates:
            if c.exists():
                skill_path = str(c)
                break

    if args.output:
        print(f"\nGenerating dashboard...")
        generate_dashboard(str(csv_path), skill_path or "", args.output)
        print(f"Open: file://{Path(args.output).resolve()}")

    if args.query:
        if not skill_path:
            print("Note: No companion .skill.md found — answering without domain context.")
        print(f"\nQuery: {args.query}")
        print("-" * 50)
        result = answer_query(str(csv_path), skill_path or "", args.query)
        print(result["answer"])
        if "matched_question" in result:
            print(f"(matched from: {result['matched_question']})")
        print()

    if not args.output and not args.query:
        # Default: show profile
        print(f"\nCSV: {csv_path.name}")
        if skill_path:
            skill = parse_skill(skill_path)
            desc = skill.get("frontmatter", {}).get("description", "")
            print(f"Skill: {skill_path} — {desc}")
        df_reader = __import__("pandas").read_csv(csv_path)
        metrics = compute_metrics(df_reader, {"sections": {}, "tables": {}, "frontmatter": {}, "raw": ""})
        print(f"\nRows: {metrics['shape']['rows']:,} | Columns: {metrics['shape']['columns']}")
        print(f"Columns: {', '.join(c['name'] for c in metrics['columns'])}")
        print(f"\nUse --output to generate dashboard HTML, or --query to ask questions.")


if __name__ == "__main__":
    main()
