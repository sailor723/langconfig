#!/usr/bin/env python3
"""CLI wrapper — calls dashboard_generator.generate_dashboard."""
import argparse, asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.dashboard_generator import generate_dashboard

async def main():
    parser = argparse.ArgumentParser(description="Generate Plotly dashboard (LLM-based)")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--skill", default=None, help="Path to companion .skill.md")
    parser.add_argument("--output", default=None, help="Copy output to this path")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)

    csv_bytes = csv_path.read_bytes()
    skill_bytes = Path(args.skill).read_bytes() if args.skill and Path(args.skill).exists() else None
    output_dir = str(Path(args.output).parent) if args.output else "/tmp"

    result = await generate_dashboard(csv_bytes, skill_bytes, csv_path.name, output_dir)
    print(f"\nDashboard: {result}")

    if args.output:
        import shutil
        shutil.copy(result, args.output)
        print(f"Copied to: {args.output}")

if __name__ == "__main__":
    asyncio.run(main())
