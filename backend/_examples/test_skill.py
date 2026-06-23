#!/usr/bin/env python3
"""
Minimal pure-Python test: run a deepagent with a skill loaded from filesystem.

Based on LangChain deepagents docs pattern:
  - create_deep_agent(skills=[skill_path], backend=..., store=...)
  - SkillsMiddleware auto-injects skill summaries into system prompt
  - Agent reads SKILL.md on-demand via read_file tool
  - Agent follows skill instructions to use scripts/

Usage:
  cd backend && .venv/bin/python _examples/test_skill.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Make 'core' importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    from deepagents import create_deep_agent
    from langchain.chat_models import init_chat_model
    from langgraph.checkpoint.memory import MemorySaver

    # 1) Path to the skill
    backend_root = Path(__file__).resolve().parent.parent
    skill_path = backend_root / "skills" / "builtin" / "data-analysis"
    print(f"📁 Skill path: {skill_path}")
    print(f"   SKILL.md exists: {(skill_path / 'SKILL.md').exists()}")
    print(f"   scripts/ exists: {(skill_path / 'scripts').exists()}")
    print()

    # 2) Model
    model = init_chat_model(
        model=os.environ.get("DEFAULT_MODEL", "deepseek-chat"),
        temperature=0.0,
    )

    # 3) Filesystem backend rooted at backend/skills/builtin/
    #    This makes /data-analysis/SKILL.md available inside the agent's
    #    virtual filesystem (root = builtin, so data-analysis is at top)
    try:
        from deepagents.backends.filesystem import FilesystemBackend
        backend = FilesystemBackend(
            root_dir=str(backend_root / "skills" / "builtin"),
            virtual_mode=True,
        )
        attrs = [a for a in dir(backend) if not a.startswith("_")]
        print(f"✅ FilesystemBackend created. attrs={attrs[:6]}...")
    except Exception as e:
        print(f"❌ FilesystemBackend failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4) Memory checkpointer (required for some deepagent features)
    checkpointer = MemorySaver()

    # 5) Create the deep agent with skills=[...]
    #    This is the KEY call — deepagents auto-registers SkillsMiddleware
    print("\n🤖 Creating deep agent with skills=[/data-analysis/]...")
    try:
        agent = create_deep_agent(
            model=model,
            backend=backend,
            skills=["/data-analysis/"],  # ← This is the magic
            checkpointer=checkpointer,
        )
        print("✅ Agent created!")
    except Exception as e:
        print(f"❌ create_deep_agent failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 6) Run a query — the agent should:
    #    a) See data-analysis in system prompt (SkillsMiddleware)
    #    b) Decide to use it (LLM judgment)
    #    c) Read SKILL.md via read_file
    #    d) Follow instructions
    query = "I have a CSV file at /tmp/test_data.csv with columns id,name,value. How should I analyze it?"
    print(f"\n💬 Query: {query}")
    print("=" * 70)

    config = {"configurable": {"thread_id": "test-1"}}
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": query}]},
        config=config,
    )

    print("=" * 70)
    print("\n📋 Final messages:")
    for msg in result.get("messages", []):
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            print(f"\n[{role}] {content[:800]}")
            if len(content) > 800:
                print(f"  ... ({len(content)} chars total)")
        else:
            print(f"\n[{role}] (non-text content)")


if __name__ == "__main__":
    asyncio.run(main())