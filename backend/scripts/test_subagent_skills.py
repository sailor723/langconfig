"""Test: explicit SkillsMiddleware injection for skill-per-subagent isolation.

Each subagent gets its own manually-constructed SkillsMiddleware with a
real FilesystemBackend backed by SKILL.md files on disk.

This demonstrates how the framework processes skills under the hood —
the auto approach (skills=["..."]) just creates the same middleware for you.
"""
import asyncio
import json
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from db.database import SessionLocal
from models.skill import Skill


async def main():
    AGENT_ID = 47

    # ── 1. Load skills from DB ──────────────────────────────────────
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT config FROM deep_agent_templates WHERE id = :id"),
            {"id": AGENT_ID},
        ).scalar()
        config = json.loads(row) if isinstance(row, str) else row
        skill_ids = config.get("skills", [])
        skill_records = db.query(Skill).filter(Skill.skill_id.in_(skill_ids)).all()
    finally:
        db.close()
    print(f"Skills loaded: {[s.skill_id for s in skill_records]}\n")

    # ── 2. Write SKILL.md files to a real temp directory ────────────
    tmp_dir = Path(tempfile.mkdtemp(suffix="_skills_test"))
    skills_root = tmp_dir / "skills"

    for s in skill_records:
        skill_dir = skills_root / s.skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        md = f"---\nname: {s.skill_id}\ndescription: {s.description}\n---\n\n{s.instructions}"
        if s.examples:
            md += f"\n\n## Examples\n\n{s.examples}"
        (skill_dir / "SKILL.md").write_text(md)

    print(f"Skills on disk: {skills_root}\n")

    # ── 3. Each skill → one subagent with explicit SkillsMiddleware ──
    # We use a single FilesystemBackend for all skills, then create one
    # SkillsMiddleware per subagent pointing to its specific skill dir.
    subagents = []
    # root_dir = skills directory, so sources are relative skill names
    shared_backend = FilesystemBackend(root_dir=str(skills_root))

    for s in skill_records:
        skill_mw = SkillsMiddleware(
            backend=shared_backend,
            sources=[s.skill_id],  # relative to root_dir → skills_root/{id}/SKILL.md
            system_prompt=None,
        )
        subagents.append({
            "name": s.skill_id,
            "description": s.description,
            "system_prompt": (
                f"You are a {s.skill_id} specialist. "
                "Follow the skill instructions exactly. "
                "Return only the result."
            ),
            "middleware": [skill_mw],
        })
        print(f"  Subagent [{s.skill_id}] ← SkillsMiddleware(sources=[{s.skill_id}])")

    print()

    # ── 4. Main agent — clean, no skills ───────────────────────────
    delegation_hints = "\n".join(
        f"  - {s.skill_id}: {s.description}" for s in skill_records
    )
    main_prompt = (
        "You are a helpful assistant with access to specialized subagents.\n\n"
        "When a task requires specialized knowledge, delegate using task() "
        "with the matching subagent name:\n"
        f"{delegation_hints}\n\n"
        "For simple questions, answer directly. For skill tasks, always delegate."
    )

    model = init_chat_model(config.get("model", "google_genai:gemini-2.5-flash"))
    agent = create_deep_agent(
        model=model,
        system_prompt=main_prompt,
        subagents=subagents,
        checkpointer=MemorySaver(),
        # NO skills — main agent stays clean
    )

    # ── 5. Multi-turn conversation ──────────────────────────────────
    thread = {"configurable": {"thread_id": "skills-mw-test-2"}}
    questions = [
        (
            "Order #12345 is 3 weeks late! I want a refund!",
            {"priority", "category", "sentiment"},
        ),
        (
            'Review: def login(p): return "SELECT * FROM users WHERE pass=\'"+p+"\'"',
            {"sql injection", "security", "severity"},
        ),
        (
            "Can you analyze my monthly sales CSV?",
            {"revenue", "csv", "chart", "sales"},
        ),
    ]

    all_passed = True
    for i, (q, expected_kws) in enumerate(questions):
        print(f"{'='*60}")
        print(f"  Turn {i+1}: {q[:60]}...")
        print(f"{'='*60}")

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": q}]},
            config=thread,
        )

        response = str(result["messages"][-1].content)
        print(f"  Response: {response[:400]}\n")

        matched = [kw for kw in expected_kws if kw.lower() in response.lower()]
        if matched:
            print(f"  ✅ {matched}")
        else:
            print(f"  ❌ No expected keywords — wrong skill?")
            all_passed = False

        print()

    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"{'='*60}")
    print(f"  {'✅ ALL PASSED' if all_passed else '❌ SOME FAILED'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
