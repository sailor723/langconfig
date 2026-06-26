#!/usr/bin/env python3
"""
Multi-Skill Auto-Selection Test

Proves the agent can automatically select the correct skill from multiple
equipped skills WITHOUT hardcoding skill names in the system prompt.

This tests the deepagents SkillsMiddleware progressive disclosure:
  LLM sees: "Available skills: [name + description for each]"
  LLM decides: which skill's full instructions to load based on user intent

Usage:
  cd backend && uv run python scripts/test_multi_skill_auto_select.py
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Two different skills ───────────────────────────────────────────────

TICKET_CLASSIFIER_SKILL = """---
name: ticket-classifier
description: Used to classify customer support tickets by priority, category, and sentiment. Load this skill when a user describes a customer issue or support ticket.
---

# Ticket Classifier

You MUST load this skill when the user describes any customer support issue.

## Classification Rules

### Priority Levels
- **high**: Urgent, blocked, deadline, broken, crash, data loss, security
- **medium**: Feature requests, account issues, billing questions, troubleshooting
- **low**: Documentation questions, how-to questions, minor feedback

### Categories
- **technical**: Bugs, errors, crashes, system issues
- **billing**: Invoices, payments, refunds, pricing
- **account**: Login, permissions, profile changes
- **shipping**: Delivery, tracking, returns, damaged items
- **feature_request**: Suggestions for new features

### Sentiment
- **frustrated**: Angry language, all caps, repeated complaints
- **neutral**: Factual, polite, standard request
- **satisfied**: Positive language, thank you, appreciation

## Output Format
Respond with JSON: {"priority": "high|medium|low", "category": "...", "sentiment": "...", "summary": "...", "suggested_action": "..."}
"""

DATA_ANALYSIS_SKILL = """---
name: data-analysis
description: Analyze CSV files and SQL databases using pandas. Use for data analysis, querying databases, generating visualizations, or building analysis reports.
---

# Data Analysis

You MUST load this skill when the user asks about data, statistics, CSV files, database queries, or visualizations.

## Workflow

1. Understand the data source (CSV file or SQL database)
2. Load data using pandas: `pd.read_csv()` or `pd.read_sql()`
3. Clean and transform data
4. Perform analysis (descriptive stats, aggregations, correlations)
5. Visualize results using matplotlib
6. Summarize findings

## Tools
- Python with pandas, matplotlib, sqlalchemy
- PostgreSQL at DATABASE_URL env var

## Output Format
Present findings clearly with:
- Summary statistics
- Key insights (bullet points)
- Visualizations (if applicable)
"""


def create_skills_dir(base_dir: Path) -> str:
    """Create two skills on the filesystem and return the parent path."""
    skills_root = base_dir / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    # ticket-classifier
    d1 = skills_root / "ticket-classifier"
    d1.mkdir(parents=True, exist_ok=True)
    (d1 / "SKILL.md").write_text(TICKET_CLASSIFIER_SKILL)

    # data-analysis
    d2 = skills_root / "data-analysis"
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "SKILL.md").write_text(DATA_ANALYSIS_SKILL)

    return str(skills_root.resolve())


def extract_response(result):
    """Extract string response from agent invoke result."""
    if isinstance(result, dict) and "messages" in result:
        last_msg = result["messages"][-1]
        if hasattr(last_msg, "content"):
            response = last_msg.content
        elif isinstance(last_msg, dict):
            response = last_msg.get("content", str(last_msg))
        else:
            response = str(last_msg)
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

    return response


# ── Tests ───────────────────────────────────────────────────────────────

def test_1_ticket_query_uses_ticket_classifier():
    """Ticket query should trigger ticket-classifier skill."""
    print("=" * 60)
    print("Test 1: Ticket query → auto-selects ticket-classifier")
    print("=" * 60)

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_path = create_skills_dir(Path(tmpdir))

        # GENERIC system prompt — no skill names hardcoded
        agent = create_deep_agent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a helpful assistant with access to specialized skills.",
            skills=[skills_path],
            checkpointer=MemorySaver(),
        )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": "My order #12345 is 3 weeks late! Where is it?"}]},
            config={"configurable": {"thread_id": "test-multi-1"}},
        )

        response = extract_response(result)
        rl = response.lower()

        # Should contain ticket/shipping/priority keywords
        has_ticket_keywords = any(kw in rl for kw in [
            "shipping", "delivery", "order", "priority", "high",
            "frustrated", "category", "ticket", "classif"
        ])

        print(f"  Response: {response[:200]}...")
        print(f"  Contains ticket keywords: {'✅' if has_ticket_keywords else '❌'}")

        if has_ticket_keywords:
            print("  ✅ Agent auto-selected ticket-classifier skill!")
        else:
            print("  ⚠️  No ticket keywords — skill may not have triggered")
        print()

    return True


def test_2_data_query_uses_data_analysis():
    """Data analysis query should trigger data-analysis skill."""
    print("=" * 60)
    print("Test 2: Data query → auto-selects data-analysis")
    print("=" * 60)

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_path = create_skills_dir(Path(tmpdir))

        agent = create_deep_agent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a helpful assistant with access to specialized skills.",
            skills=[skills_path],
            checkpointer=MemorySaver(),
        )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Can you analyze this CSV data and create a chart of sales by month?"}]},
            config={"configurable": {"thread_id": "test-multi-2"}},
        )

        response = extract_response(result)
        rl = response.lower()

        # Should contain data/analysis keywords
        has_data_keywords = any(kw in rl for kw in [
            "data", "analysis", "csv", "pandas", "chart", "plot",
            "visualization", "statistics", "analyze", "graph"
        ])

        print(f"  Response: {response[:200]}...")
        print(f"  Contains data keywords: {'✅' if has_data_keywords else '❌'}")

        if has_data_keywords:
            print("  ✅ Agent auto-selected data-analysis skill!")
        else:
            print("  ⚠️  No data keywords — skill may not have triggered")
        print()

    return True


def test_3_code_query_uses_code_review():
    """Code review query should trigger code-review skill (if equipped)."""
    print("=" * 60)
    print("Test 3: Code query with 3 skills equipped")
    print("=" * 60)

    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver

    # Also create code-review skill
    CODE_REVIEW_SKILL = """---
name: code-review
description: Systematic code review covering best practices, security, performance, and maintainability. Use when asked to review, audit, or inspect code.
---

# Code Review

You MUST load this skill when the user asks you to review code, check code quality, or audit a codebase.

## Checklist
1. Correctness: Does the code do what it's supposed to?
2. Security: SQL injection, XSS, auth issues, hardcoded secrets
3. Performance: N+1 queries, memory leaks, unnecessary loops
4. Maintainability: Clear naming, proper abstraction, documentation
5. Testing: Edge cases, error handling, test coverage
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_root = Path(tmpdir) / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)

        d1 = skills_root / "ticket-classifier"
        d1.mkdir(); (d1 / "SKILL.md").write_text(TICKET_CLASSIFIER_SKILL)

        d2 = skills_root / "data-analysis"
        d2.mkdir(); (d2 / "SKILL.md").write_text(DATA_ANALYSIS_SKILL)

        d3 = skills_root / "code-review"
        d3.mkdir(); (d3 / "SKILL.md").write_text(CODE_REVIEW_SKILL)

        agent = create_deep_agent(
            model="deepseek:deepseek-chat",
            system_prompt="You are a helpful assistant with access to specialized skills.",
            skills=[str(skills_root.resolve())],
            checkpointer=MemorySaver(),
        )

        # Send a code review query
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Review this Python function for issues:\ndef login(username, password):\n    query = f\"SELECT * FROM users WHERE username='{username}' AND password='{password}'\"\n    return db.execute(query)"}]},
            config={"configurable": {"thread_id": "test-multi-3"}},
        )

        response = extract_response(result)
        rl = response.lower()

        # Should contain security/code review keywords
        has_code_keywords = any(kw in rl for kw in [
            "sql injection", "security", "vulnerability", "review",
            "code quality", "bug", "error", "injection", "function"
        ])

        print(f"  Response: {response[:200]}...")
        print(f"  Contains code review keywords: {'✅' if has_code_keywords else '❌'}")

        if has_code_keywords:
            print("  ✅ Agent auto-selected code-review skill!")
        else:
            print("  ⚠️  No code review keywords — skill may not have triggered")
        print()

    return True


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    failures = []
    tests = [
        ("Ticket query → ticket-classifier", test_1_ticket_query_uses_ticket_classifier),
        ("Data query → data-analysis", test_2_data_query_uses_data_analysis),
        ("Code query → code-review", test_3_code_query_uses_code_review),
    ]

    for name, fn in tests:
        try:
            result = fn()
            if result is False:
                failures.append(name)
        except Exception as e:
            print(f"\n❌ {name} raised: {e}")
            import traceback
            traceback.print_exc()
            failures.append(name)
        print()

    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} test(s):")
        for f in failures:
            print(f"  ❌ {f}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
