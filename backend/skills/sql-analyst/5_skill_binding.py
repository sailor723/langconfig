#!/usr/bin/env python3
"""
Step 5: Layer 4 — Skill Binding via SkillsMiddleware.

Shows exactly how SkillsMiddleware:
  1. Reads SKILL.md frontmatter (name, description, tags, triggers, allowed-tools)
  2. Injects a skill catalog into the system prompt (progressive disclosure, Stage 1)
  3. When LLM calls read_file(), returns full SKILL.md content (Stage 2)
  4. Opens the FilesystemBackend so file paths are resolvable

Run: cd backend && .venv/bin/python skills/sql-analyst/5_skill_binding.py
"""
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))

# ── Part A: Parse SKILL.md frontmatter (what SkillsMiddleware does) ──
SKILL_PATH = _THIS_DIR / "SKILL.md"

print("=" * 70)
print("  Part A: SKILL.md Frontmatter (parsed by SkillsMiddleware)")
print("=" * 70)

with open(SKILL_PATH) as f:
    raw = f.read()

# Extract frontmatter between --- markers
parts = raw.split("---")
if len(parts) >= 3:
    frontmatter = parts[1].strip()
    instructions = parts[2].strip()
else:
    frontmatter = ""
    instructions = raw

# Parse YAML-like frontmatter manually (simple key: value)
metadata = {}
for line in frontmatter.split("\n"):
    if ":" in line:
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'").strip(">-").strip()
        metadata[key] = val

print(f"  name:         {metadata.get('name', '?')}")
print(f"  description:  {metadata.get('description', '?')[:80]}...")
print(f"  tags:         {metadata.get('tags', '[]')}")
print(f"  triggers:")
for t in raw.split("triggers:")[1].split("allowed-tools:")[0].strip().split("\n"):
    t = t.strip().strip("- ").strip('"').strip()
    if t:
        print(f"    - {t}")
print(f"  allowed-tools: {metadata.get('allowed-tools', '[]')}")
print(f"  author:       {metadata.get('author', '?')}")
print(f"  instructions: {len(instructions)} chars")

# ── Part B: What SkillsMiddleware injects into system prompt ──
print("\n" + "=" * 70)
print("  Part B: Skill Catalog Injected into System Prompt")
print("  (Stage 1 — Progressive Disclosure)")
print("=" * 70)
print(f"""
    ┌────────────────────────────────────────────────────────────┐
    │ ## Available Skills                                        │
    │                                                            │
    │ • sql-analyst: {metadata.get('description', '?')[:70]}...  │
    │   Allowed tools: {metadata.get('allowed-tools', '[]')[:60]}...│
    │   Tags: {metadata.get('tags', '[]')}                        │
    │   Triggers: when user wants data analysis, charts, SQL...  │
    │                                                            │
    │   💡 Read full instructions:                               │
    │      read_file("../../../skills/sql-analyst/SKILL.md")     │
    └────────────────────────────────────────────────────────────┘

    LLM sees ↑ this ↑ in its system prompt.
    Only name + short desc + tools — NOT the full 5-step workflow yet!
""")

# ── Part C: Stage 2 — LLM reads full SKILL.md ──
print("=" * 70)
print("  Part C: Stage 2 — LLM reads full SKILL.md on demand")
print("=" * 70)
print(f"""
    LLM decides "this is a data analysis task" →
    calls read_file("skills/sql-analyst/SKILL.md") →
    receives COMPLETE instructions ({len(instructions)} chars):

    ┌────────────────────────────────────────────────────────────┐
    │ # 角色定位                                                   │
    │                                                             │
    │ 你是 SQL Data Analyst — 精通 SQL 和 Python 数据分析          │
    │                                                             │
    │ # 工作流程                                                   │
    │                                                             │
    │ ## 第一步：理解数据 (Discover schema, PRAGMA, LIMIT 5)        │
    │ ## 第二步：理解业务 (Columns meaning, keys, missing values)    │
    │ ## 第三步：回答问题 (Generate SQL/Python, READ-ONLY SELECT)    │
    │ ## 第四步：生成可视化 (matplotlib charts, save to file)        │
    │ ## 第五步：输出报告 (Structured Markdown, write_file)          │
    │                                                             │
    │ # Business Logic Examples:                                  │
    │   客户分析, 销售分析, 库存分析...                               │
    └────────────────────────────────────────────────────────────┘
    
    This is "Progressive Disclosure":
    Stage 1: light catalog (few hundred tokens, always visible)
    Stage 2: full instructions (few thousand tokens, on demand)
""")

# ── Part D: FilesystemBackend — how file paths work ──
print("=" * 70)
print("  Part D: FilesystemBackend — how paths resolve")
print("=" * 70)

# Show the actual backend root
print(f"""
    create_deep_agent(
        backend=FilesystemBackend(root_dir="{_BACKEND / 'skills'}"),
        skills=["sql-analyst"],
    )
    
    FilesystemBackend root: {_BACKEND / 'skills'}
    Skill path resolved:  {_BACKEND / 'skills' / 'sql-analyst' / 'SKILL.md'}
    
    The LLM reads: read_file("sql-analyst/SKILL.md")
    Backend maps to: {_BACKEND / 'skills' / 'sql-analyst' / 'SKILL.md'}
""")

# ── Part E: Full binding code (same as 4_llm_nl_to_sql.py line ~100) ──
print("=" * 70)
print("  Part E: The actual binding code")
print("=" * 70)
print("""
    from deepagents import create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend
    
    backend = FilesystemBackend(root_dir=str(skills_root))
    
    agent = create_deep_agent(
        model=model,
        tools=[sqlite_execute, python_execute],
        system_prompt="You are a data analyst expert...",
        backend=backend,
        skills=["sql-analyst"],   #  ← SkillsMiddleware auto-creates from this list
        checkpointer=checkpointer,
    )
    
    # SkillsMiddleware internally:
    # 1. Reads <root>/sql-analyst/SKILL.md
    # 2. Parses frontmatter for name/description/tags/tools
    # 3. Injects catalog into system_prompt (Stage 1)
    # 4. Registers read_file handler for full content (Stage 2)
""")

print("\n✅ Layer 4 complete: Skill Binding explained!")
