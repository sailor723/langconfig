"""Test script for the memory-enabled SQL agent (sql_agent.py).

Covers three layers:
  unit  - deterministic checks that never call an LLM:
          * should_continue routing (END / memory_tools / check_query)
          * store_memory / search_memories store behavior
          * check_query safety net for malformed tool calls
  e2e   - LLM-backed integration checks (needs DEEPSEEK_API_KEY / model reachable):
          * simple count query
          * join query (artist with most albums)
          * cross-thread memory: store then recall in a later turn
          * token streaming path used by main() (stream_events v3)

Usage:
  python backend/langgraph/test_sql_agent.py          # run everything
  python backend/langgraph/test_sql_agent.py unit     # fast, no LLM
  python backend/langgraph/test_sql_agent.py e2e      # LLM-backed only

Exit code is 0 when every test passes, 1 otherwise.
"""
import sys
import traceback
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.messages import AIMessage

try:
    import sql_agent as sa
except Exception as exc:  # e.g. model init fails when DEEPSEEK_API_KEY is missing
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

passed: list[str] = []
failed: list[str] = []


# ── helpers ─────────────────────────────────────────────────────────
def _ai(content: str, tool_calls: list | None = None) -> AIMessage:
    """Build an AIMessage, optionally with tool calls."""
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _run(thread_id: str, question: str) -> str:
    """Run one turn on a thread and return the final assistant text."""
    config = {"configurable": {"thread_id": thread_id}}
    state = sa.agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )
    return state["messages"][-1].content or ""


# ── unit tests (no LLM) ─────────────────────────────────────────────
def unit_routing():
    # plain answer with no tool call ends the graph
    assert sa.should_continue({"messages": [_ai("8 employees")]}) == sa.END

    # memory-only tool calls go to the memory node
    store_call = {
        "name": sa.store_memory.name,
        "args": {"memory": "x"},
        "id": "1",
        "type": "tool_call",
    }
    assert sa.should_continue({"messages": [_ai("", [store_call])]}) == "memory_tools"

    search_call = {
        "name": sa.search_memories.name,
        "args": {"query": "x"},
        "id": "2",
        "type": "tool_call",
    }
    assert sa.should_continue({"messages": [_ai("", [search_call])]}) == "memory_tools"

    # a SQL query call goes to the query checker
    query_call = {
        "name": sa.run_query_tool.name,
        "args": {"query": "select 1"},
        "id": "3",
        "type": "tool_call",
    }
    assert sa.should_continue({"messages": [_ai("", [query_call])]}) == "check_query"


def unit_memory_tools():
    # read/write through the raw store in an isolated namespace
    ns = ("test-mem", uuid4().hex)
    sa.store.put(ns, "k1", {"memory": "prefers jazz"})
    item = sa.store.get(ns, "k1")
    assert item is not None and item.value["memory"] == "prefers jazz"
    assert any("jazz" in it.value["memory"] for it in sa.store.search(ns, query="jazz"))

    # an empty namespace yields no results
    assert sa.store.search(("test-mem", uuid4().hex), query="anything") == []

    # the agent's store_memory tool persists into the agent namespace
    key = f"unit-{uuid4().hex[:8]}"
    sa.store_memory.invoke({"memory": "test fact", "key": key})
    item = sa.store.get(sa.MEMORY_NAMESPACE, key)
    assert item is not None and item.value["memory"] == "test fact"


def unit_preamble_skip():
    # a fresh thread has no schema marker yet -> run the preamble
    assert sa.should_preamble({"messages": [_ai("hi")]}) == "list_tables"

    # once the list_tables marker is in history, follow-ups skip straight to query
    with_schema = {
        "messages": [_ai("hi"), _ai("Available tables: Album, Artist, Track")]
    }
    assert sa.should_preamble(with_schema) == "generate_query"


def unit_check_query_malformed():
    # A run_query tool call with no usable args must not blow up: the
    # checker returns an empty update so the graph can loop back.
    bad = {
        "name": sa.run_query_tool.name,
        "args": {},
        "id": "9",
        "type": "tool_call",
    }
    assert sa.check_query({"messages": [_ai("", [bad])]}) == {"messages": []}

    # tool calls that target other tools are ignored by the checker too
    other = {
        "name": sa.search_memories.name,
        "args": {"query": "x"},
        "id": "10",
        "type": "tool_call",
    }
    assert sa.check_query({"messages": [_ai("", [other])]}) == {"messages": []}


# ── e2e tests (LLM) ─────────────────────────────────────────────────
def e2e_simple_count():
    answer = _run(f"t-{uuid4().hex}", "How many employees are there?")
    assert "8" in answer, f"expected 8 in answer, got: {answer!r}"


def e2e_join():
    answer = _run(f"t-{uuid4().hex}", "Which artist has the most albums?")
    assert "Iron Maiden" in answer, f"expected Iron Maiden, got: {answer!r}"


def e2e_memory_store_recall():
    thread = f"t-{uuid4().hex}"
    first = _run(thread, "Remember that I prefer rock music.")

    # the memory must actually be persisted in the cross-thread store
    memories = [
        it.value.get("memory", "")
        for it in sa.store.search(sa.MEMORY_NAMESPACE, query="rock")
    ]
    assert any("rock" in m.lower() for m in memories), f"memory not stored: {memories!r}"

    # a later turn on the same thread recalls it
    second = _run(thread, "What did I say I prefer?")
    assert "rock" in second.lower(), f"expected rock recalled, got: {second!r}"


def e2e_followup_skips_preamble():
    thread = f"t-{uuid4().hex}"
    first = _run(thread, "How many employees are there?")
    assert "8" in first, f"expected 8 in first answer, got: {first!r}"

    # follow-up on the same thread must not re-run the table/schema preamble
    state = sa.agent.invoke(
        {"messages": [{"role": "user", "content": "How many tracks are there?"}]},
        config={"configurable": {"thread_id": thread}},
    )
    msgs = state["messages"]
    preamble_runs = sum(
        1 for m in msgs if "Available tables" in str(getattr(m, "content", "") or "")
    )
    assert preamble_runs == 1, f"preamble re-ran {preamble_runs} times"

    answer = (msgs[-1].content or "").replace(",", "")
    assert "3503" in answer, f"expected 3503 in follow-up answer, got: {answer!r}"


def e2e_stream():
    # mirror the main() streaming path (stream_events v3)
    config = {"configurable": {"thread_id": f"t-{uuid4().hex}"}}
    tokens: list[str] = []
    stream = sa.agent.stream_events(
        {"messages": [{"role": "user", "content": "How many employees are there?"}]},
        config=config,
        version="v3",
    )
    for message in stream.messages:
        for token in message.text:
            tokens.append(token)
    answer = "".join(tokens)
    assert "8" in answer, f"expected 8 in streamed answer, got: {answer!r}"


# ── runner ──────────────────────────────────────────────────────────
def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in {"all", "unit", "e2e"}:
        print(f"unknown mode {mode!r}; use 'unit' | 'e2e' | 'all'")
        return 2

    if IMPORT_ERROR is not None:
        print(f"\nSKIPPED all tests: sql_agent import failed:\n  {IMPORT_ERROR}")
        print("Set DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL (or point the model block at a local LLM).")
        return 0

    groups = []
    if mode in {"all", "unit"}:
        groups.append(("unit", [
            ("should_continue routing", unit_routing),
            ("preamble skip routing", unit_preamble_skip),
            ("memory tools read/write", unit_memory_tools),
            ("check_query malformed call", unit_check_query_malformed),
        ]))
    if mode in {"all", "e2e"}:
        groups.append(("e2e", [
            ("count employees (8)", e2e_simple_count),
            ("join: artist with most albums", e2e_join),
            ("memory: store then recall", e2e_memory_store_recall),
            ("follow-up skips preamble", e2e_followup_skips_preamble),
            ("streaming tokens (v3)", e2e_stream),
        ]))

    for group_name, tests in groups:
        print(f"\n=== {group_name} ===")
        for name, fn in tests:
            try:
                fn()
                passed.append(f"{group_name}:{name}")
                print(f"  PASS  {name}")
            except Exception as exc:
                failed.append(f"{group_name}:{name}")
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=2)

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
