"""
Test SimpleMemory — in-memory + PostgreSQL backends.

Run: cd backend && python3 test_memory.py
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("test_memory")


# =========================================================================
# In-Memory Tests (async)
# =========================================================================

async def test_basic_store_recall():
    """Basic store → recall using in-memory backend."""
    print("\n" + "=" * 60)
    print("TEST 1: Store → Recall (in-memory)")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=1, agent_id="test")

    r = await mem.save_to_memory(
        memory_content="Auth uses JWT in httpOnly cookies, 24h expiry.",
        memory_type="fact",
        importance=9,
        tags=["auth", "security"]
    )
    print(f"  Store: {r}")

    r = await mem.save_to_memory(
        memory_content="Passwords hashed with bcrypt (12 rounds).",
        memory_type="decision",
        importance=10,
        tags=["auth", "password"]
    )
    print(f"  Store: {r}")

    r = await mem.save_to_memory(
        memory_content="Frontend: React 19 + Tailwind CSS.",
        memory_type="fact",
        importance=5,
        tags=["frontend"]
    )
    print(f"  Store: {r}")

    assert mem.memory_count == 3, f"Expected 3, got {mem.memory_count}"

    result = await mem.recall_memory()
    print(f"\n  Recall all:\n{result}")
    assert "JWT" in result
    assert "bcrypt" in result
    assert "React 19" in result

    result = await mem.recall_memory(memory_type="decision")
    print(f"  Recall decisions:\n{result}")
    assert "bcrypt" in result
    assert "JWT" not in result

    print("  ✓ PASS")
    return True


async def test_tools_interface():
    """Test that tools are created correctly and can be invoked (async)."""
    print("\n" + "=" * 60)
    print("TEST 2: Tool interface (async coroutine)")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=2, agent_id="tools_test")
    tools = mem.create_memory_tools()

    assert len(tools) == 2, f"Expected 2 tools, got {len(tools)}"
    names = {t.name for t in tools}
    assert "memory_store" in names
    assert "memory_recall" in names
    print(f"  Tools: {names}")

    # Invoke store via ainvoke (async)
    store_tool = [t for t in tools if t.name == "memory_store"][0]
    result = await store_tool.ainvoke({
        "memory_content": "API rate limit: 100 req/min per user.",
        "memory_type": "fact",
        "importance": 7,
        "tags": ["api", "rate-limit"]
    })
    print(f"  Store via tool: {result}")
    assert "Memory stored" in result

    # Invoke recall via ainvoke (async)
    recall_tool = [t for t in tools if t.name == "memory_recall"][0]
    result = await recall_tool.ainvoke({"query": "rate limit"})
    print(f"  Recall via tool:\n{result}")
    assert "rate limit" in result.lower()

    print("  ✓ PASS")
    return True


async def test_multi_turn_chat():
    """Simulate a multi-turn conversation using in-memory backend."""
    print("\n" + "=" * 60)
    print("TEST 3: Multi-turn chat (in-memory)")
    print("=" * 60)

    from core.agents.memory import SimpleMemory

    mem = SimpleMemory(project_id=3, agent_id="chat")

    print("\n  --- Turn 1 ---")
    recall = await mem.recall_memory(query="architecture")
    print(f"  Recall: {recall[:80]}...")
    assert "No memories stored" in recall

    await mem.save_to_memory(
        memory_content="Decided on microservices: auth, users, payments, notifications.",
        memory_type="decision",
        importance=9,
        tags=["architecture", "microservices"]
    )
    print("  Stored architecture decision")

    print("\n  --- Turn 2 ---")
    recall = await mem.recall_memory(query="system design")
    print(f"  Recall:\n{recall}")
    assert "microservices" in recall

    await mem.save_to_memory(
        memory_content="Auth service uses PostgreSQL + Redis for session caching.",
        memory_type="fact",
        importance=7,
        tags=["auth", "database", "caching"]
    )
    print("  Stored auth details")

    print("\n  --- Turn 3 ---")
    recall = await mem.recall_memory(query="authentication database")
    print(f"  Recall:\n{recall}")
    assert mem.memory_count == 2
    assert "microservices" in recall
    assert "PostgreSQL" in recall

    print("  ✓ PASS")
    return True


async def test_memory_cache_persistence():
    """Test that get_or_create_memory returns the same instance (cache works)."""
    print("\n" + "=" * 60)
    print("TEST 4: Memory cache persistence")
    print("=" * 60)

    from core.agents.memory import get_or_create_memory

    mem1 = get_or_create_memory(project_id=5, agent_id="cache_test")
    tools1 = mem1.create_memory_tools()
    store_tool = [t for t in tools1 if t.name == "memory_store"][0]
    await store_tool.ainvoke({
        "memory_content": "Cache test: this should persist.",
        "memory_type": "fact",
        "importance": 8,
    })
    print(f"  Turn 1: stored (count={mem1.memory_count})")
    assert mem1.memory_count == 1

    mem2 = get_or_create_memory(project_id=5, agent_id="cache_test")
    assert mem2 is mem1, "Cache should return the SAME instance"
    assert mem2.memory_count == 1, f"Expected 1, got {mem2.memory_count}"
    print(f"  Turn 2: same instance (count={mem2.memory_count})")

    tools2 = mem2.create_memory_tools()
    store_tool2 = [t for t in tools2 if t.name == "memory_store"][0]
    await store_tool2.ainvoke({
        "memory_content": "Another memory from turn 2.",
        "memory_type": "fact",
        "importance": 5,
    })
    assert mem2.memory_count == 2
    assert mem1.memory_count == 2
    print(f"  Turn 2: added 2nd memory (count={mem2.memory_count})")

    recall_tool = [t for t in tools1 if t.name == "memory_recall"][0]
    result = await recall_tool.ainvoke({"query": ""})
    assert "Cache test" in result
    assert "turn 2" in result
    print(f"  Recall via mem1 sees both memories")

    mem3 = get_or_create_memory(project_id=5, agent_id="other_agent")
    assert mem3 is not mem1
    assert mem3.memory_count == 0
    print(f"  Different agent: new instance (count={mem3.memory_count})")

    print("  ✓ PASS")
    return True


async def test_agent_memory_system_compat():
    """Test that AgentMemorySystem (legacy wrapper) still works."""
    print("\n" + "=" * 60)
    print("TEST 5: AgentMemorySystem (legacy compat)")
    print("=" * 60)

    from core.agents.memory import AgentMemorySystem

    mem = AgentMemorySystem(project_id=4, agent_id="legacy")
    tools = mem.create_memory_tools()

    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"memory_store", "memory_recall"}

    store_tool = [t for t in tools if t.name == "memory_store"][0]
    result = await store_tool.ainvoke({
        "memory_content": "Legacy compat test.",
        "memory_type": "fact",
        "importance": 3,
    })
    assert "Memory stored" in result

    recall_tool = [t for t in tools if t.name == "memory_recall"][0]
    result = await recall_tool.ainvoke({"query": ""})
    assert "Legacy compat test" in result

    print("  ✓ PASS")
    return True


# =========================================================================
# PostgreSQL Tests
# =========================================================================

DB_URL = "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5433/langconfig"


async def test_postgres_store_recall():
    """Store → recall using PostgreSQL backend."""
    print("\n" + "=" * 60)
    print("TEST 6: Store → Recall (PostgreSQL)")
    print("=" * 60)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from core.agents.memory import SimpleMemory
    from models.agent_memory import AgentMemory

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        mem = SimpleMemory(project_id=1, agent_id="pg_test", db_session=session)

        r = await mem.save_to_memory(
            memory_content="PG test: JWT auth with 24h expiry.",
            memory_type="fact",
            importance=9,
            tags=["auth", "pg"]
        )
        print(f"  Store: {r}")
        assert "DB id=" in r

        result = await mem.recall_memory()
        print(f"  Recall:\n{result}")
        assert "JWT" in result

        # Cleanup
        from sqlalchemy import delete
        await session.execute(
            delete(AgentMemory).where(
                AgentMemory.project_id == 1,
                AgentMemory.agent_id == "pg_test"
            )
        )
        await session.commit()

    await engine.dispose()
    print("  ✓ PASS")
    return True


async def test_postgres_empty_recall():
    """Recall with no stored memories in PostgreSQL."""
    print("\n" + "=" * 60)
    print("TEST 7: Empty recall (PostgreSQL)")
    print("=" * 60)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from core.agents.memory import SimpleMemory

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        mem = SimpleMemory(project_id=1, agent_id="empty_test", db_session=session)

        result = await mem.recall_memory()
        print(f"  Recall: {result[:80]}...")
        assert "No memories stored" in result

    await engine.dispose()
    print("  ✓ PASS")
    return True


# =========================================================================
# Runner
# =========================================================================

async def main_async():
    print("=" * 60)
    print("SimpleMemory Test Suite (in-memory + PostgreSQL)")
    print("=" * 60)

    # In-memory tests
    inmem_tests = [
        ("Store → Recall", test_basic_store_recall),
        ("Tool interface", test_tools_interface),
        ("Multi-turn chat", test_multi_turn_chat),
        ("Cache persistence", test_memory_cache_persistence),
        ("Legacy compat", test_agent_memory_system_compat),
    ]

    # PostgreSQL tests
    pg_tests = [
        ("PG Store → Recall", test_postgres_store_recall),
        ("PG Empty recall", test_postgres_empty_recall),
    ]

    results = []

    print("\n--- In-Memory Tests ---")
    for name, test in inmem_tests:
        try:
            passed = await test()
            results.append((name, passed))
        except Exception as e:
            print(f"\n  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n--- PostgreSQL Tests ---")
    for name, test in pg_tests:
        try:
            passed = await test()
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
    asyncio.run(main_async())