#!/usr/bin/env python3
"""
Test the Skill Router LLM — verifies that a separate model (deepseek) can
correctly classify which skill matches a user's request.

Usage:
  cd backend && uv run python scripts/test_skill_router.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Build mock skill records ───────────────────────────────────────────
class MockSkill:
    def __init__(self, skill_id, description):
        self.skill_id = skill_id
        self.description = description

SKILLS = [
    MockSkill("ticket-classifier", "Classify customer support tickets by priority, category, and sentiment"),
    MockSkill("data-analysis", "Analyze CSV files and SQL databases using pandas, create visualizations"),
    MockSkill("code-review", "Systematic code review for best practices, security, performance, and maintainability"),
]

# ── Import the router from factory ──────────────────────────────────────
import asyncio
from services.deepagent_factory import DeepAgentFactory


async def test_router(query: str, expected_skill_id: str, test_name: str) -> bool:
    """Run the router and check if it selects the expected skill."""
    result = await DeepAgentFactory._run_skill_router(
        router_model="deepseek:deepseek-chat",
        skill_records=SKILLS,
        user_message=query,
    )
    matched = (result == expected_skill_id)
    status = "✅" if matched else "❌"
    print(f"  {status} Router selected: {result} (expected: {expected_skill_id})")
    if not matched:
        print(f"     Query: {query[:60]}...")
    return matched


async def main():
    print("=" * 60)
    print("Skill Router LLM Test (deepseek:deepseek-chat)")
    print("=" * 60)

    tests = [
        ("My order #12345 is 3 weeks late! Where is it?", "ticket-classifier",
         "Ticket query → ticket-classifier"),
        ("Can you analyze this CSV sales data and create a chart?", "data-analysis",
         "Data query → data-analysis"),
        ("Review this Python function for security issues", "code-review",
         "Code review → code-review"),
        ("I need a refund for my damaged item", "ticket-classifier",
         "Refund query → ticket-classifier"),
        ("How do I fix this SQL injection vulnerability in my code?", "code-review",
         "Security code → code-review"),
    ]

    passed = 0
    failed = 0

    for query, expected, name in tests:
        print(f"\n  Test: {name}")
        result = await test_router(query, expected, name)
        if result:
            passed += 1
        else:
            failed += 1
        print()

    print("=" * 60)
    if failed > 0:
        print(f"  ❌ {failed} test(s) FAILED, {passed} passed")
    else:
        print(f"  ✅ ALL {passed} tests PASSED!")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
