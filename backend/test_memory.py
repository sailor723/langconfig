"""
Test SimpleMemory — text-based, no vector store.

Run: cd backend && python3 test_memory.py
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("test_memory")


def test_basic_store_recall():
    """Basic store → recall, no deps."""
    print("\n" + "=" * 60)
    print("TEST 1: Store → Recall (sync, no deps)")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=1, agent_id="test")

    # Store
    r = mem.save_to_memory(
        memory_content="Auth uses JWT in httpOnly cookies, 24h expiry.",
        memory_type="fact",
        importance=9,
        tags=["auth", "security"]
    )
    print(f"  Store: {r}")

    r = mem.save_to_memory(
        memory_content="Passwords hashed with bcrypt (12 rounds).",
        memory_type="decision",
        importance=10,
        tags=["auth", "password"]
    )
    print(f"  Store: {r}")

    r = mem.save_to_memory(
        memory_content="Frontend: React 19 + Tailwind CSS.",
        memory_type="fact",
        importance=5,
        tags=["frontend"]
    )
    print(f"  Store: {r}")

    assert mem.memory_count == 3, f"Expected 3, got {mem.memory_count}"

    # Recall all
    result = mem.recall_memory()
    print(f"\n  Recall all:\n{result}")
    assert "JWT" in result
    assert "bcrypt" in result
    assert "React 19" in result

    # Recall filtered
    result = mem.recall_memory(memory_type="decision")
    print(f"  Recall decisions:\n{result}")
    assert "bcrypt" in result
    assert "JWT" not in result

    print("  ✓ PASS")
    return True


def test_tools_interface():
    """Test that tools are created correctly and can be invoked."""
    print("\n" + "=" * 60)
    print("TEST 2: Tool interface (StructuredTool)")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=2, agent_id="tools_test")
    tools = mem.create_memory_tools()

    assert len(tools) == 2, f"Expected 2 tools, got {len(tools)}"
    names = {t.name for t in tools}
    assert "memory_store" in names, f"missing memory_store, got {names}"
    assert "memory_recall" in names, f"missing memory_recall, got {names}"
    print(f"  Tools: {names}")

    # Invoke store via tool
    store_tool = [t for t in tools if t.name == "memory_store"][0]
    result = store_tool.invoke({
        "memory_content": "API rate limit: 100 req/min per user.",
        "memory_type": "fact",
        "importance": 7,
        "tags": ["api", "rate-limit"]
    })
    print(f"  Store via tool: {result}")
    assert "Memory stored" in result

    # Invoke recall via tool
    recall_tool = [t for t in tools if t.name == "memory_recall"][0]
    result = recall_tool.invoke({"query": "rate limit"})
    print(f"  Recall via tool:\n{result}")
    assert "rate limit" in result.lower()

    print("  ✓ PASS")
    return True


def test_multi_turn_chat():
    """Simulate a multi-turn conversation using memory."""
    print("\n" + "=" * 60)
    print("TEST 3: Multi-turn chat simulation")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=3, agent_id="chat")

    # Turn 1: First interaction, check memory (empty), then store
    print("\n  --- Turn 1 ---")
    recall = mem.recall_memory(query="architecture")
    print(f"  Recall: {recall[:80]}...")
    assert "No memories stored" in recall

    mem.save_to_memory(
        memory_content="Decided on microservices: auth, users, payments, notifications.",
        memory_type="decision",
        importance=9,
        tags=["architecture", "microservices"]
    )
    print("  ✓ Stored architecture decision")

    # Turn 2: New question, should find Turn 1's memory
    print("\n  --- Turn 2 ---")
    recall = mem.recall_memory(query="system design")
    print(f"  Recall:\n{recall}")
    assert "microservices" in recall

    mem.save_to_memory(
        memory_content="Auth service uses PostgreSQL + Redis for session caching.",
        memory_type="fact",
        importance=7,
        tags=["auth", "database", "caching"]
    )
    print("  ✓ Stored auth details")

    # Turn 3: Should find BOTH memories
    print("\n  --- Turn 3 ---")
    recall = mem.recall_memory(query="authentication database")
    print(f"  Recall:\n{recall}")
    assert mem.memory_count == 2
    assert "microservices" in recall
    assert "PostgreSQL" in recall

    print("  ✓ PASS")
    return True


def test_agent_memory_system_compat():
    """Test that AgentMemorySystem (legacy wrapper) still works."""
    print("\n" + "=" * 60)
    print("TEST 4: AgentMemorySystem (legacy compat)")
    print("=" * 60)

    from core.agents.memory import AgentMemorySystem

    # No vector_store needed
    mem = AgentMemorySystem(project_id=4, agent_id="legacy")
    tools = mem.create_memory_tools()

    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"memory_store", "memory_recall"}

    # Test it works
    store_tool = [t for t in tools if t.name == "memory_store"][0]
    result = store_tool.invoke({
        "memory_content": "Legacy compat test.",
        "memory_type": "fact",
        "importance": 3,
    })
    assert "Memory stored" in result

    recall_tool = [t for t in tools if t.name == "memory_recall"][0]
    result = recall_tool.invoke({"query": ""})
    assert "Legacy compat test" in result

    print("  ✓ PASS")
    return True


def main():
    print("=" * 60)
    print("SimpleMemory Test Suite (text-based, no vector store)")
    print("=" * 60)

    results = []

    for name, test in [
        ("Store → Recall", test_basic_store_recall),
        ("Tool interface", test_tools_interface),
        ("Multi-turn chat", test_multi_turn_chat),
        ("Legacy compat", test_agent_memory_system_compat),
    ]:
        try:
            passed = test()
            results.append((name, passed))
        except Exception as e:
            print(f"\n  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_pass = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n✓ ALL TESTS PASSED — memory works end-to-end!")
    else:
        print("\n✗ SOME TESTS FAILED")
        exit(1)


if __name__ == "__main__":
    main()