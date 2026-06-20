"""Test: skill-per-subagent isolation for multi-turn conversations.

Each skill is a separate subagent with its own isolated SkillsMiddleware.
Main agent has NO skills — keeps clean context, delegates via task().
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver
from db.database import SessionLocal
from models.skill import Skill


async def main():
    AGENT_ID = 47

    # ── 1. Load config + skills from DB ──────────────────────────────
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

    print(f"Skills loaded: {[s.skill_id for s in skill_records]}")

    # ── 2. Build subagents dynamically from skills ──────────────────
    subagents = []
    for s in skill_records:
        subagents.append({
            "name": s.skill_id,
            "description": s.description,
            "system_prompt": (
                f"You are a {s.skill_id} specialist.\n"
                "When a task matches your skill, read the SKILL.md and follow its instructions exactly.\n"
                "Return only the result with no extra commentary."
            ),
            "skills": [f"/skills/{s.skill_id}/"],
        })

    # ── 3. Generate main agent system prompt dynamically ────────────
    delegation_hints = "\n".join(
        f"  - {s.skill_id}: {s.description}" for s in skill_records
    )
    main_prompt = (
        "You are a helpful assistant with access to specialized subagents.\n\n"
        "When a task requires specialized knowledge, delegate using task() with the matching subagent name:\n"
        f"{delegation_hints}\n\n"
        "For simple questions, answer directly. For skill tasks, always delegate."
    )

    # ── 4. Create model & agent ─────────────────────────────────────
    model = init_chat_model(config.get("model", "google_genai:gemini-2.5-flash"))
    agent = create_deep_agent(
        model=model,
        system_prompt=main_prompt,
        subagents=subagents,
        checkpointer=MemorySaver(),
        # Main agent gets NO skills — keeps context clean
    )

    print(f"\nSystem prompt ({len(main_prompt)} chars):")
    print(main_prompt)
    print()

    # ── 5. Multi-turn conversation ──────────────────────────────────
    thread = {"configurable": {"thread_id": "subagent-test-1"}}
    questions = [
        "Order #12345 is 3 weeks late! This is ridiculous, I want a refund!",
        'Review this code: def login(p): return "SELECT * FROM users WHERE pass=\'"+p+"\'"',
        "Can you analyze my monthly sales CSV data?",
    ]

    skill_keywords = {
        "ticket-classifier": ["priority", "category", "sentiment"],
        "code-review": ["sql injection", "security", "severity"],
        "data-analysis": ["revenue", "csv", "chart", "sales"],
    }

    all_passed = True
    for i, q in enumerate(questions):
        print(f"{'='*60}")
        print(f"  Turn {i+1}: {q[:60]}...")
        print(f"{'='*60}")

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": q}]},
            config=thread,
        )

        response = str(result["messages"][-1].content)
        print(f"  Response: {response[:400]}\n")

        # Detect which skill was used
        matched = []
        for skill_id, keywords in skill_keywords.items():
            for kw in keywords:
                if kw.lower() in response.lower():
                    matched.append(f"{kw}({skill_id})")
                    break
        if matched:
            print(f"  ✅ {', '.join(matched)}")
        else:
            print(f"  ❌ No skill keywords detected")
            all_passed = False

    print(f"\n{'='*60}")
    print(f"  {'✅ ALL PASSED' if all_passed else '❌ SOME FAILED'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
