"""
Test: combine system SKILL.md (mechanics) with hand-written companion (semantics).
Runs without the generator — just loads the two files and shows how the agent sees them.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent

# 1. System skill — content-independent mechanics
sys_skill_path = BASE / "backend" / "skills" / "builtin" / "data-analysis" / "SKILL.md"
sys_text = sys_skill_path.read_text(encoding="utf-8")

# 3. Hand-written companion — dataset semantics
companion_path = (
    BASE / "learning" / "phase5" / "examples" / "sample_sales_data.skill.md"
)
companion_text = companion_path.read_text(encoding="utf-8")

print("=" * 70)
print("  SYSTEM SKILL  (content-independent mechanics)")
print("=" * 70)
desc = [l for l in sys_text.split("\n") if l.startswith("description:")]
print(f"  File: backend/skills/builtin/data-analysis/SKILL.md")
print(f"  Size: {len(sys_text)} chars")
print(f"  {desc[0] if desc else ''}")
print()

print("=" * 70)
print("  COMPANION SKILL  (dataset-specific semantics)")
print("=" * 70)
print(f"  File: learning/phase5/examples/sample_sales_data.skill.md")
print(f"  Size: {len(companion_text)} chars")
desc2 = [l for l in companion_text.split("\n") if l.startswith("description:")]
print(f"  {desc2[0] if desc2 else ''}")
print()

print("=" * 70)
print("  HOW THE AGENT SEES IT — combined context")
print("=" * 70)
print()
print("# ── Injected via data-analysis subagent (system skill) ──")
print("# Chart types, tool invocation, edge case handling")
print()
print("## User Data Context -- sample_sales_data.csv")
print("# The user provided this interpretation guide alongside their data:")
print()

# Print companion content, skipping YAML frontmatter
in_frontmatter = True
for line in companion_text.split("\n"):
    if line == "---":
        if in_frontmatter:
            in_frontmatter = False
            continue
        break  # end of frontmatter
    if not in_frontmatter:
        print(line)

print()
print("─" * 70)
print("  The agent reads both. System skill says: how to analyze.")
print("  Companion says: what these columns mean, what questions to ask.")
print("─" * 70)
