#!/usr/bin/env python3
"""Sync FS SKILL.md content → DB for data-analysis (fix drift)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import AsyncSessionLocal
from models.skill import Skill as SkillModel
from sqlalchemy import select
from datetime import datetime

SKILL_DIR = Path("/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/skills/builtin/data-analysis")


def parse_frontmatter(text: str):
    """Parse YAML frontmatter from SKILL.md."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_str = text[3:end].strip()
    body = text[end + 4:].strip()
    try:
        import yaml
        return yaml.safe_load(yaml_str) or {}, body
    except Exception:
        return {}, body


async def main():
    skill_md = SKILL_DIR / "SKILL.md"
    fm, body = parse_frontmatter(skill_md.read_text())
    print(f"FS SKILL.md: name={fm.get('name')}, desc={fm.get('description', '')[:60]}")
    print(f"  body length: {len(body)}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SkillModel).where(SkillModel.skill_id == "data-analysis")
        )
        skill = result.scalar_one_or_none()
        if not skill:
            print("ERROR: data-analysis not in DB")
            return

        print(f"BEFORE: desc={skill.description!r}, instructions_len={len(skill.instructions or '')}")

        # Update from FS
        skill.name = fm.get("name", skill.name)
        skill.description = fm.get("description", skill.description)
        skill.tags = fm.get("tags", skill.tags)
        skill.triggers = fm.get("triggers", skill.triggers)
        skill.allowed_tools = fm.get("allowed_tools", skill.allowed_tools)
        skill.instructions = body
        skill.file_modified_at = datetime.utcnow()
        skill.updated_at = datetime.utcnow()

        await session.commit()
        print(f"AFTER: desc={skill.description!r}, instructions_len={len(skill.instructions or '')}")
        print("Drift fixed!")


if __name__ == "__main__":
    asyncio.run(main())