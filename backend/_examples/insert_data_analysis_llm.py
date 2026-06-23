#!/usr/bin/env python3
"""Insert/refresh data-analysis-llm in DB so it appears in the UI."""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import AsyncSessionLocal
from models.skill import Skill as SkillModel
from sqlalchemy import select


SKILL_DATA = {
    "skill_id": "data-analysis-llm",
    "name": "Data Analysis (LLM-Driven)",
    "description": "Flexible data analysis where the agent writes Python code based on the user's question. Use when the user's analysis request is custom or novel and doesn't fit a predefined pattern.",
    "version": "1.0.0",
    "author": "LangConfig",
    "source_type": "builtin",
    "source_path": "/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/skills/builtin/data-analysis-llm",
    "tags": ["data-analysis", "csv", "sql", "python", "flexible", "custom-analysis"],
    "triggers": [
        "when user asks a custom or novel data question",
        "when user asks for an analysis not covered by data-analysis",
        "when user wants custom visualization",
        "when user wants exploratory data analysis",
        "when the analysis question is open-ended",
    ],
    "allowed_tools": ["execute", "filesystem"],
    "instructions": "See SKILL.md file in backend/skills/builtin/data-analysis-llm/ for full instructions.",
    "examples": None,
}


async def main():
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(SkillModel).where(SkillModel.skill_id == SKILL_DATA["skill_id"])
        )
        skill = existing.scalar_one_or_none()
        if skill:
            print(f"Updating {SKILL_DATA['skill_id']} in DB...")
            for k, v in SKILL_DATA.items():
                setattr(skill, k, v)
        else:
            print(f"Inserting {SKILL_DATA['skill_id']} into DB...")
            skill = SkillModel(**SKILL_DATA)
            skill.file_modified_at = now
            skill.indexed_at = now
            session.add(skill)
        await session.commit()
        print("Done!")


if __name__ == "__main__":
    asyncio.run(main())