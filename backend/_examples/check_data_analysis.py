#!/usr/bin/env python3
"""Check what data-analysis has in DB."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import AsyncSessionLocal
from models.skill import Skill as SkillModel
from sqlalchemy import select


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SkillModel).where(SkillModel.skill_id == 'data-analysis')
        )
        s = result.scalar_one_or_none()
        if s:
            print(f"name: {s.name}")
            print(f"description: {(s.description or '')[:120]}")
            print(f"source_type: {s.source_type}")
            print(f"source_path: {s.source_path}")
            print(f"tags: {s.tags}")
            print(f"triggers count: {len(s.triggers or [])}")
            print(f"allowed_tools: {s.allowed_tools}")
            print(f"instructions length: {len(s.instructions or '')}")
            print(f"--- first 300 chars of instructions ---")
            print((s.instructions or '')[:300])


if __name__ == "__main__":
    asyncio.run(main())