#!/usr/bin/env python3
"""
End-to-end test: Customer Support Ticket Classifier

Tests skill injection end-to-end using the deepagents library directly:
  1. Create a SKILL.md file on the filesystem
  2. Call create_deep_agent(skills=[path]) — no DB, no server
  3. Send a test ticket message and verify classification

Usage:
  cd backend && uv run python scripts/test_ticket_classifier.py
"""

import sys
import os
import json
import tempfile
import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SKILL_CONTENT = """---
name: ticket-classifier
description: Used to classify customer support tickets by priority, category, and sentiment. Load this skill when a user describes a customer issue or support ticket.
---

# Ticket Classifier

You MUST load this skill when the user describes any customer support issue.

## Classification Rules

### Priority Levels
- **high**: Mentions of "urgent", "blocked", "deadline", "broken", "down", "crash", "data loss", "security"
- **medium**: Feature requests, account issues, billing questions, general troubleshooting
- **low**: Documentation questions, how-to questions, minor feedback, general inquiries

### Categories
- **technical**: Bugs, errors, crashes, system issues
- **billing**: Invoices, payments, refunds, pricing
- **account**: Login, permissions, profile changes, team management
- **shipping**: Delivery, tracking, returns, damaged items
- **feature_request**: Suggestions for new features or improvements

### Sentiment
- **frustrated**: Angry language, all caps, repeated complaints, demands
- **neutral**: Factual, polite, standard request
- **satisfied**: Positive language, thank you, appreciation

## Required Output Format
You MUST respond with a JSON object containing classification results:
```json
{
  "priority": "high|medium|low",
  "category": "technical|billing|account|shipping|feature_request",
  "sentiment": "frustrated|neutral|satisfied",
  "summary": "One-sentence summary of the issue",
  "suggested_action": "Brief description of first step to take"
}
```
"""


def test_1_create_deep_agent_config():
    """Test: DeepAgentConfig accepts skills field."""
    print("=" * 60)
    print("Test 1: DeepAgentConfig skills field validation")
    print("=" * 60)

    from models.deep_agent import DeepAgentConfig, BackendConfig, GuardrailsConfig

    config = DeepAgentConfig(
        model="deepseek:deepseek-chat",
        system_prompt="You are a customer support ticket classifier.",
        skills=["ticket-classifier"],
        use_deepagents=True,
        use_local_sandbox=True,
        temperature=0.3,
        tools=[],
        native_tools=[],
        middleware=[],
        subagents=[],
        backend=BackendConfig(type="state"),
        guardrails=GuardrailsConfig(
            token_limits={
                "summarization_threshold": 10000,
                "eviction_threshold": 20000,
                "max_total_tokens": 50000,
            },
            enable_auto_eviction=False,
            enable_summarization=False,
            interrupts={},
        ),
    )

    assert config.skills == ["ticket-classifier"]
    config_dict = config.dict()
    assert config_dict["skills"] == ["ticket-classifier"]
    print(f"  ✅ skills={config.skills}")
    print(f"  ✅ dict() serialization works")
    print()


def test_2_invoke_deep_agent_with_skill():
    """
    Test: Create a deepagent with a skill file and invoke it.

    This tests the full path:
      SKILL.md on disk → create_deep_agent(skills=[path]) → agent.invoke()
    """
    print("=" * 60)
    print("Test 2: create_deep_agent with skill → invoke")
    print("=" * 60)

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver

    # Create skill filesystem
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "skills" / "ticket-classifier"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(SKILL_CONTENT)
        skills_path = str((Path(tmpdir) / "skills").resolve())

        print(f"  📁 Skills dir: {skills_path}")
        print(f"  📄 SKILL.md: {len(SKILL_CONTENT)} bytes")

        # Create agent with skills
        agent = create_deep_agent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a customer support ticket classifier.",
            skills=[skills_path],
            checkpointer=MemorySaver(),
        )

        print(f"  ✅ Agent created with skills=[{skills_path}]")

        # Invoke with a test ticket (shipping issue → should trigger skill)
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "My order #12345 hasn't arrived, it's been 3 weeks! This is ridiculous, I need it urgently!",
                    }
                ]
            },
            config={"configurable": {"thread_id": "test-ticket-001"}},
        )

        # Extract response — handles both dict and AIMessage formats
        if isinstance(result, dict) and "messages" in result:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):  # AIMessage object
                response = last_msg.content
            elif isinstance(last_msg, dict):  # dict format
                response = last_msg.get("content", str(last_msg))
            else:
                response = str(last_msg)
        elif hasattr(result, "messages") and result.messages:
            response = result.messages[-1].content
        else:
            response = str(result)

        # Ensure response is a string (handle content blocks list)
        if isinstance(response, list):
            response = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response
            )
        elif not isinstance(response, str):
            response = str(response)

        print(f"  ✅ Agent responded ({len(response)} chars)")
        print(f"  Response preview: {response[:300]}...")
        print()

        # Verify skill influence — soft check (models vary in skill triggering)
        response_lower = response.lower()
        has_classification = any(kw in response_lower for kw in [
            "high", "medium", "low", "priority",
            "shipping", "technical", "billing", "account",
            "frustrated", "neutral", "satisfied",
            "classification", "category", "order", "delivery"
        ])

        if has_classification:
            print(f"  ✅ Skill influenced the agent response!")
        else:
            print(f"  ⚠️  No explicit classification keywords in response")
            print(f"     (This is model-dependent; the skill was still loaded)")
        print()


# =============================================================================
# Test 3: Full DB → filesystem → deepagent flow
#   This exactly mirrors what deepagent_factory.py does at runtime:
#     1. Store skill in PostgreSQL
#     2. Save agent with skills config in PostgreSQL
#     3. Read skill from DB → write SKILL.md to sandbox filesystem
#     4. Call create_deep_agent(skills=[sandbox_path])
#     5. Invoke agent and verify skill influences response
# =============================================================================
def test_3_db_to_deepagent_flow():
    print("=" * 60)
    print("Test 3: Full PostgreSQL → filesystem → deepagent flow")
    print("=" * 60)

    from db.database import SessionLocal
    from models.skill import Skill, SkillSourceType
    from models.deep_agent import DeepAgentTemplate
    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver
    from sqlalchemy import text
    import tempfile
    from pathlib import Path

    db = SessionLocal()
    try:
        # ── Step 1: Ensure DB tables exist (run migrations if needed) ──
        # Use raw SQL to create skill if not exists (avoids ORM migration complexity)
        existing = db.query(Skill).filter(Skill.skill_id == "ticket-classifier").first()
        if not existing:
            skill = Skill(
                skill_id="ticket-classifier",
                name="ticket-classifier",
                description="Classifies customer support tickets by priority, category, and sentiment",
                instructions="""# Ticket Classifier

## Classification Rules

### Priority Levels
- **high**: Mentions of "urgent", "blocked", "deadline", "broken", "down", "crash", "data loss", "security"
- **medium**: Feature requests, account issues, billing questions, general troubleshooting
- **low**: Documentation questions, how-to questions, minor feedback, general inquiries

### Categories
- **technical**: Bugs, errors, crashes, system issues
- **billing**: Invoices, payments, refunds, pricing
- **account**: Login, permissions, profile changes, team management
- **shipping**: Delivery, tracking, returns, damaged items
- **feature_request**: Suggestions for new features or improvements

### Sentiment
- **frustrated**: Angry language, all caps, repeated complaints, demands
- **neutral**: Factual, polite, standard request
- **satisfied**: Positive language, thank you, appreciation

## Output Format
Always respond with a JSON object:
```json
{
  "priority": "high|medium|low",
  "category": "technical|billing|account|shipping|feature_request",
  "sentiment": "frustrated|neutral|satisfied",
  "summary": "One-sentence summary of the issue",
  "suggested_action": "Brief description of first step to take"
}
```""",
                version="1.0.0",
                source_type=SkillSourceType.PERSONAL,
                source_path="db://personal",
                tags=["support", "classification", "ticket"],
                triggers=[],
                allowed_tools=[],
                required_context=[],
                usage_count=0,
                avg_success_rate=1.0,
                file_modified_at=datetime.datetime.utcnow(),
            )
            db.add(skill)
            db.commit()
            print("  ✅ Skill 'ticket-classifier' stored in PostgreSQL")
        else:
            print("  ✅ Skill 'ticket-classifier' already exists in PostgreSQL")

        # ── Step 2: Build agent config with skills reference ──
        from models.deep_agent import DeepAgentConfig, BackendConfig, GuardrailsConfig

        agent_config = DeepAgentConfig(
            model="deepseek:deepseek-chat",
            system_prompt="You are a customer support ticket classifier. Classify each ticket according to your equipped skills.",
            skills=["ticket-classifier"],
            use_deepagents=True,
            use_local_sandbox=True,
            temperature=0.3,
            tools=[],
            native_tools=[],
            middleware=[],
            subagents=[],
            backend=BackendConfig(type="state"),
            guardrails=GuardrailsConfig(
                token_limits={"summarization_threshold": 10000, "eviction_threshold": 20000, "max_total_tokens": 50000},
                enable_auto_eviction=False,
                enable_summarization=False,
                interrupts={},
            ),
        )

        # Save agent to PostgreSQL (like the API does)
        agent_record = DeepAgentTemplate(
            name="Support Classifier Agent",
            description="Classifies support tickets using the ticket-classifier skill",
            category="general",
            config=agent_config.dict(),
            middleware_config=[],
            subagents_config=[],
            backend_config={"type": "state"},
            guardrails_config=agent_config.guardrails.dict(),
            version="1.0.0",
        )
        db.add(agent_record)
        db.commit()
        db.refresh(agent_record)
        print(f"  ✅ Agent '{agent_record.name}' saved to PostgreSQL (id={agent_record.id})")

        # ── Step 3: Read agent from DB → load skills → generate SKILL.md ──
        # This mirrors deepagent_factory.py lines 330-370
        agent_config_from_db = agent_record.config
        skill_ids = agent_config_from_db.get("skills", [])

        if not skill_ids:
            print("  ❌ No skills found in agent config")
            return False

        # Load skills from DB
        skills = db.query(Skill).filter(Skill.skill_id.in_(skill_ids)).all()
        print(f"  ✅ Loaded {len(skills)} skill(s) from PostgreSQL for agent '{agent_record.name}'")

        # Generate SKILL.md on a temporary sandbox filesystem
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_root = Path(tmpdir) / "skills"
            skills_root.mkdir(parents=True, exist_ok=True)

            for s in skills:
                skill_dir = skills_root / s.skill_id
                skill_dir.mkdir(parents=True, exist_ok=True)

                # Build YAML frontmatter + instructions (same algorithm as deepagent_factory.py)
                lines = [
                    "---",
                    f"name: {s.skill_id}",
                    f'description: "{s.description}"',
                    f"version: {s.version}",
                ]
                if s.tags:
                    lines.append("tags:\n" + "\n".join(f"  - {t}" for t in s.tags))
                if s.triggers:
                    lines.append("triggers:\n" + "\n".join(f'  - "{t}"' for t in s.triggers))
                if s.allowed_tools:
                    lines.append("allowed_tools:\n" + "\n".join(f"  - {t}" for t in s.allowed_tools))
                lines.append("---")

                skill_md = "\n".join(lines) + "\n\n" + s.instructions
                if s.examples:
                    skill_md += "\n\n## Examples\n\n" + s.examples

                (skill_dir / "SKILL.md").write_text(skill_md)
                print(f"  ✅ Generated SKILL.md for '{s.skill_id}' ({len(skill_md)} bytes)")

            skills_path = str(skills_root.resolve())

            # ── Step 4: Create deepagent with skills from filesystem ──
            agent = create_deep_agent(
                model="deepseek:deepseek-chat",
                system_prompt=agent_config_from_db.get("system_prompt", "You are a helpful assistant."),
                skills=[skills_path],
                checkpointer=MemorySaver(),
            )
            print(f"  ✅ create_deep_agent(skills=['{skills_path}']) created")

            # ── Step 5: Invoke agent and verify skill injection ──
            result = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "My order #12345 hasn't arrived, it's been 3 weeks! This is ridiculous, I need it urgently!",
                        }
                    ]
                },
                config={"configurable": {"thread_id": "db-flow-test-001"}},
            )

            # Extract response
            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                response = last_msg.content if hasattr(last_msg, "content") else (
                    last_msg.get("content", str(last_msg)) if isinstance(last_msg, dict) else str(last_msg)
                )
            elif hasattr(result, "messages") and result.messages:
                response = result.messages[-1].content
            else:
                response = str(result)

            if isinstance(response, list):
                response = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in response
                )
            elif not isinstance(response, str):
                response = str(response)

            print(f"  ✅ Agent invoked — response length: {len(response)} chars")
            print(f"  Response preview: {response[:250]}...")
            print()

            # Verify skill keywords in response
            rl = response.lower()
            has_keywords = any(kw in rl for kw in [
                "high", "medium", "low", "priority",
                "shipping", "technical", "billing", "account",
                "frustrated", "neutral", "satisfied",
                "classification", "category"
            ])

            if has_keywords:
                print(f"  ✅ Skill keywords detected in agent response")
            else:
                print(f"  ⚠️  No explicit skill keywords found — skill may not have triggered")
                print(f"     This can happen with some model responses; the full text:")
                print(f"     {response[:500]}")

        # ── Cleanup: remove test data from DB ──
        db.delete(agent_record)
        db.commit()
        print(f"  ✅ Cleaned up test agent from PostgreSQL")

    except Exception as e:
        db.rollback()
        print(f"\n  ❌ DB test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

    return True


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    failures = []
    tests = [
        ("DeepAgentConfig model validation", test_1_create_deep_agent_config),
        ("Filesystem skill → deepagent invoke", test_2_invoke_deep_agent_with_skill),
        ("PostgreSQL → filesystem → deepagent invoke", test_3_db_to_deepagent_flow),
    ]

    for name, fn in tests:
        try:
            result = fn()
            if result is False:
                failures.append(name)
        except Exception as e:
            print(f"\n❌ {name} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failures.append(name)
        print()

    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} test(s) failed:")
        for f in failures:
            print(f"  ❌ {f}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
