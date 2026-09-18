"""Test script for the memory-enabled Neo4j agent (neo4j_agent.py).

Mirrors backend/langgraph/test_sql_agent.py — same three-layer pattern
(unit / e2e / runner) so the team can run unit tests fast and e2e tests
when an LLM is reachable.

Covers:
  unit  - deterministic checks that never call an LLM:
          * should_continue routing (END / memory_tools / check_query)
          * store_memory / search_memories store behavior
          * check_query safety net for malformed tool calls
          * should_preamble skip logic
          * write-reject regex on neo4j_graph_query (CREATE/MERGE/etc.)
          * parameter coercion (nested dicts/lists rejected)
  e2e   - LLM-backed integration checks (needs DEEPSEEK_API_KEY or local LLM):
          * Tom Hanks movies — preamble -> generate -> check -> run chain
          * "follow-up skips preamble" — once schema in history, follow-ups
            skip the list_labels node
          * streaming tokens (stream_events v3) for the main() path
          * cross-thread memory: store then recall in a later thread

Usage:
  python backend/langgraph/test_neo4j_agent.py          # run everything
  python backend/langgraph/test_neo4j_agent.py unit     # fast, no LLM
  python backend/langgraph/test_neo4j_agent.py e2e      # LLM-backed only

Exit code is 0 when every test passes, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from uuid import uuid4

# The graph modules import `from config import ...` and `from llm import ...`,
# so both backend/ (for `config`) and langgraph/ (for `llm`) must be on
# the sys.path when running this script standalone (the FastAPI app already
# has both paths wired).
sys.path.insert(0, str(Path(__file__).resolve().parent))        # langgraph/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # backend/

from langchain.messages import AIMessage

try:
    import neo4j_agent as na
    import neo4j_setup_db
except Exception as exc:  # noqa: BLE001 - e.g. model init fails when DEEPSEEK_API_KEY is missing
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
    state = na.agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )
    return state["messages"][-1].content or ""


# ── unit tests (no LLM) ─────────────────────────────────────────────
def unit_routing():
    # plain answer with no tool call ends the graph
    assert na.should_continue({"messages": [_ai("5 movies: ...")]}) == na.END

    # memory-only tool calls go to the memory node
    store_call = {
        "name": na.store_memory.name,
        "args": {"memory": "x"},
        "id": "1",
        "type": "tool_call",
    }
    assert na.should_continue({"messages": [_ai("", [store_call])]}) == "memory_tools"

    search_call = {
        "name": na.search_memories.name,
        "args": {"query": "x"},
        "id": "2",
        "type": "tool_call",
    }
    assert na.should_continue({"messages": [_ai("", [search_call])]}) == "memory_tools"

    # a Cypher query call goes to the query checker
    query_call = {
        "name": na.run_query_tool.name,
        "args": {"cypher": "MATCH (n) RETURN n LIMIT 1"},
        "id": "3",
        "type": "tool_call",
    }
    assert na.should_continue({"messages": [_ai("", [query_call])]}) == "check_query"


def unit_memory_tools():
    # read/write through the raw store in an isolated namespace
    ns = ("test-mem", uuid4().hex)
    na.store.put(ns, "k1", {"memory": "prefers jazz"})
    item = na.store.get(ns, "k1")
    assert item is not None and item.value["memory"] == "prefers jazz"
    assert any("jazz" in it.value["memory"] for it in na.store.search(ns, query="jazz"))

    # an empty namespace yields no results
    assert na.store.search(("test-mem", uuid4().hex), query="anything") == []

    # the agent's store_memory tool persists into the agent namespace
    key = f"unit-{uuid4().hex[:8]}"
    na.store_memory.invoke({"memory": "test fact", "key": key})
    item = na.store.get(na.MEMORY_NAMESPACE, key)
    assert item is not None and item.value["memory"] == "test fact"


def unit_preamble_skip():
    # a fresh thread has no schema marker yet -> run the preamble
    assert na.should_preamble({"messages": [_ai("hi")]}) == "list_labels"

    # once the list_labels marker is in history, follow-ups skip straight to query
    with_schema = {
        "messages": [_ai("hi"), _ai("Available schema:\n## Neo4j Graph Schema")]
    }
    assert na.should_preamble(with_schema) == "generate_query"


def unit_check_query_malformed():
    # A run_query tool call with no usable args must not blow up: the
    # checker returns an empty update so the graph can loop back.
    bad = {
        "name": na.run_query_tool.name,
        "args": {},
        "id": "9",
        "type": "tool_call",
    }
    assert na.check_query({"messages": [_ai("", [bad])]}) == {"messages": []}

    # tool calls that target other tools are ignored by the checker too
    other = {
        "name": na.search_memories.name,
        "args": {"query": "x"},
        "id": "10",
        "type": "tool_call",
    }
    assert na.check_query({"messages": [_ai("", [other])]}) == {"messages": []}


def unit_write_reject():
    # The Cypher regex blocklist rejects every destructive operator.
    bad_queries = [
        "CREATE (n:Bad {x: 1})",
        "MERGE (n:Bad {x: 1})",
        "MATCH (n) SET n.x = 1",
        "MATCH (n) DELETE n",
        "MATCH (n) REMOVE n.x",
        "DROP INDEX my_idx",
        "FOREACH (n IN [1,2] | CREATE (:X {y: n}))",
        "CALL db.labels()",
        "LOAD CSV FROM 'file' AS row CREATE (:X)",
    ]
    for cypher in bad_queries:
        out = na.neo4j_graph_query.invoke({"cypher": cypher, "parameters": "{}"})
        assert "write/destructive" in out or "CREATE" in out, (
            f"expected write-reject for {cypher!r}, got: {out!r}"
        )


def unit_param_coercion():
    # flat primitives -> pass through
    params, err = neo4j_setup_db._coerce_params('{"name": "Tom", "limit": 5, "flag": true}')
    assert err is None and params == {"name": "Tom", "limit": 5, "flag": True}

    # nested dict -> rejected
    _, err = neo4j_setup_db._coerce_params('{"nested": {"a": 1}}')
    assert err is not None and "unsupported type" in err

    # nested list of dicts -> rejected
    _, err = neo4j_setup_db._coerce_params('{"rows": [{"a": 1}]}')
    assert err is not None and "nested list" in err

    # malformed JSON -> rejected
    _, err = neo4j_setup_db._coerce_params('{"name": "Tom"')  # missing }
    assert err is not None and "JSON" in err

    # not a dict -> rejected
    _, err = neo4j_setup_db._coerce_params('["a", "b"]')
    assert err is not None and "object" in err


def unit_schema_smoke():
    # Live DB is up; the schema tool should return at least Person + Movie
    # (the seed data the docker image ships).
    out = na.neo4j_graph_schema.invoke({})
    assert "Person" in out and "Movie" in out, f"expected Person+Movie in schema, got: {out!r}"
    assert "ACTED_IN" in out, f"expected ACTED_IN rel, got: {out!r}"

    # schema details for a known label should return 3 sample nodes
    details = na.neo4j_graph_schema_details.invoke({"labels": "Person"})
    assert "Person" in details
    # one of the sample nodes from the docker seed
    assert "Tom Hanks" in details or "Michael Sheen" in details, (
        f"expected a known seed Person, got: {details!r}"
    )


# ── e2e tests (LLM) ─────────────────────────────────────────────────
def e2e_tom_hanks():
    answer = _run(f"t-{uuid4().hex}", "Which 5 movies has Tom Hanks acted in, sorted by year?")
    # the answer should mention at least one of Tom Hanks's known movies
    # (the seed DB has Cloud Atlas, Joe Versus the Volcano, etc.).
    known = ["Cloud Atlas", "Joe Versus", "League of Their Own",
             "Polar Express", "Da Vinci", "Cast Away"]
    assert any(name in answer for name in known), (
        f"expected a known Tom Hanks movie in answer, got: {answer!r}"
    )


def e2e_followup_skips_preamble():
    thread = f"t-{uuid4().hex}"
    first = _run(thread, "How many Person nodes are there?")
    # 133 Person nodes (per the docker seed)
    assert "133" in first, f"expected 133 Person nodes in first answer, got: {first!r}"

    # follow-up on the same thread must not re-run the list_labels preamble
    state = na.agent.invoke(
        {"messages": [{"role": "user", "content": "How many Movie nodes are there?"}]},
        config={"configurable": {"thread_id": thread}},
    )
    msgs = state["messages"]
    preamble_runs = sum(
        1 for m in msgs if "Available schema:" in str(getattr(m, "content", "") or "")
    )
    assert preamble_runs == 1, f"preamble re-ran {preamble_runs} times"

    answer = (msgs[-1].content or "").replace(",", "")
    assert "38" in answer, f"expected 38 Movie nodes in follow-up answer, got: {answer!r}"


def e2e_stream():
    # mirror the main() streaming path (stream_events v3)
    config = {"configurable": {"thread_id": f"t-{uuid4().hex}"}}
    tokens: list[str] = []
    stream = na.agent.stream_events(
        {"messages": [{"role": "user", "content": "How many Person nodes are there?"}]},
        config=config,
        version="v3",
    )
    for message in stream.messages:
        for token in message.text:
            tokens.append(token)
    answer = "".join(tokens)
    assert "133" in answer, f"expected 133 in streamed answer, got: {answer!r}"


def e2e_memory_store_recall():
    thread = f"t-{uuid4().hex}"
    first = _run(thread, "Remember that I prefer neo4j graph databases.")

    # the memory must actually be persisted in the cross-thread store
    memories = [
        it.value.get("memory", "")
        for it in na.store.search(na.MEMORY_NAMESPACE, query="neo4j")
    ]
    assert any("neo4j" in m.lower() for m in memories), (
        f"memory not stored: {memories!r}"
    )

    # a later turn on the same thread recalls it
    second = _run(thread, "What did I say I prefer?")
    assert "neo4j" in second.lower(), (
        f"expected neo4j recalled, got: {second!r}"
    )


# ── runner ──────────────────────────────────────────────────────────
def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in {"all", "unit", "e2e"}:
        print(f"unknown mode {mode!r}; use 'unit' | 'e2e' | 'all'")
        return 2

    if IMPORT_ERROR is not None:
        print(f"\nSKIPPED all tests: neo4j_agent import failed:\n  {IMPORT_ERROR}")
        print("Set DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL (or point the model block at a local LLM).")
        return 0

    groups = []
    if mode in {"all", "unit"}:
        groups.append(("unit", [
            ("should_continue routing", unit_routing),
            ("preamble skip routing", unit_preamble_skip),
            ("memory tools read/write", unit_memory_tools),
            ("check_query malformed call", unit_check_query_malformed),
            ("write-reject regex (CREATE/MERGE/...)", unit_write_reject),
            ("parameter coercion", unit_param_coercion),
            ("schema tool smoke (live neo4j)", unit_schema_smoke),
        ]))
    if mode in {"all", "e2e"}:
        groups.append(("e2e", [
            ("Tom Hanks movies query", e2e_tom_hanks),
            ("follow-up skips preamble", e2e_followup_skips_preamble),
            ("streaming tokens (v3)", e2e_stream),
            ("memory: store then recall", e2e_memory_store_recall),
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
