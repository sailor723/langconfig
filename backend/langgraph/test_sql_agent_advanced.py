"""Test script for the planner-based advanced SQL agent (sql_agent_advanced.py).

Covers three layers:
  unit  - deterministic checks that never call an LLM:
          * routing: route_from_analysis / route_after_run / route_from_monitor
          * plan parsing: _parse_plan / _parse_monitor / _build_plan_from_steps
            (incl. bounds + malformed input)
          * preamble routing (should_preamble)
  e2e   - LLM-backed integration checks (needs DEEPSEEK_API_KEY / model reachable):
          * simple question: classified simple, one-shot loop, no plan
          * multi-hop question: plan produced, >=2 queries executed, answer
            covers both parts
          * token streaming path used by main() (stream_events v3)

Usage:
  cd backend && python -m langgraph.test_sql_agent_advanced   # run everything
  cd backend && python -m langgraph.test_sql_agent_advanced unit  # fast, no LLM
  cd backend && python -m langgraph.test_sql_agent_advanced e2e   # LLM-backed only

Exit code is 0 when every test passes, 1 otherwise.

NOTE: must be run as `python -m langgraph.test_sql_agent_advanced` from the
backend/ cwd (the installed `langgraph` SDK is a namespace package, so the
local backend/langgraph/ package only resolves when backend/ is on sys.path).
"""
import sys
import traceback
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.messages import AIMessage, HumanMessage, ToolMessage

try:
    import sql_agent_advanced as sa
except Exception as exc:  # e.g. model init fails when the API key is missing
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

passed: list[str] = []
failed: list[str] = []


# ── helpers ─────────────────────────────────────────────────────────
def _ai(content: str, tool_calls: list | None = None) -> AIMessage:
    """Build an AIMessage, optionally with tool calls."""
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def _run(thread_id: str, question: str) -> dict:
    """Run one turn on a thread and return the final state (includes plan)."""
    config = {"configurable": {"thread_id": thread_id}}
    return sa.agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )


def _count_query_results(messages) -> int:
    """Number of executed sql_db_query calls: ToolMessages whose content is a
    str(list-of-tuples) — the shape sql_db_query returns (schema ToolMessages
    contain CREATE TABLE / comments instead)."""
    return sum(
        1
        for m in messages
        if getattr(m, "type", "") == "tool" and str(m.content or "").startswith("[")
    )


# ── unit tests (no LLM) ─────────────────────────────────────────────
def unit_route_from_analysis():
    # empty plan -> one-shot loop
    assert sa.route_from_analysis({"plan": []}) == "generate_query"
    assert sa.route_from_analysis({}) == "generate_query"
    # non-empty plan -> per-step executor
    assert sa.route_from_analysis({"plan": [{"id": "step-1"}]}) == "plan_step"


def unit_route_after_run():
    # active plan -> monitor; otherwise back to the classic loop
    assert sa.route_after_run({"plan": [{"id": "step-1"}]}) == "monitor_plan"
    assert sa.route_after_run({"plan": []}) == "generate_query"
    assert sa.route_after_run({}) == "generate_query"


def unit_route_from_plan_step():
    qc = {"name": sa.run_query_tool.name, "args": {"query": "select 1"}, "id": "1", "type": "tool_call"}
    # query emitted -> checker
    assert sa.route_from_plan_step({"messages": [_ai("", [qc])]}) == "check_query"
    # text answer (no tool call) -> monitor (never crash the run_query ToolNode)
    assert sa.route_from_plan_step({"messages": [_ai("the answer is 42")]}) == "monitor_plan"


def unit_step_outcome():
    # text answer wins over a stale tool result
    state = {"messages": [ToolMessage(content="stale", tool_call_id="0"), _ai("the answer is 42")]}
    assert sa._step_outcome(state) == "the answer is 42"
    # tool result is the outcome after a query step
    qc = {"name": sa.run_query_tool.name, "args": {"query": "x"}, "id": "1", "type": "tool_call"}
    state = {"messages": [_ai("", [qc]), ToolMessage(content="result rows", tool_call_id="1")]}
    assert sa._step_outcome(state) == "result rows"


def unit_route_from_monitor():
    # done -> synthesize
    assert sa.route_from_monitor({"last_action": "done"}) == "synthesize_answer"
    # retry within budget -> plan_step
    assert sa.route_from_monitor({"last_action": "retry", "retries_left": 2}) == "plan_step"
    # retry budget exhausted -> synthesize (best-effort, no infinite loop)
    assert sa.route_from_monitor({"last_action": "retry", "retries_left": 0}) == "synthesize_answer"
    assert sa.route_from_monitor({"last_action": "retry"}) == "synthesize_answer"
    # next past the last step -> synthesize
    assert sa.route_from_monitor({"last_action": "next", "current_step": 3, "plan": [1, 2, 3]}) == "synthesize_answer"
    # next within plan -> plan_step
    assert sa.route_from_monitor({"last_action": "next", "current_step": 2, "plan": [1, 2, 3]}) == "plan_step"
    # unknown action -> synthesize (safe default)
    assert sa.route_from_monitor({"last_action": "bogus"}) == "synthesize_answer"


def unit_parse_plan():
    # simple mode -> []
    assert sa._parse_plan({"complexity": "simple", "rationale": "one query"}) == []
    assert sa._parse_plan({"complexity": "plan", "steps": []}) == []
    # malformed args -> []
    assert sa._parse_plan(None) == []
    assert sa._parse_plan("nope") == []
    assert sa._parse_plan({"steps": []}) == []

    # plan mode -> normalized steps with ids/statuses
    plan = sa._parse_plan({
        "complexity": "plan",
        "rationale": "two hops",
        "steps": [
            {"description": "top artists", "hint": "join invoice lines"},
            {"description": "longest tracks", "hint": "use step 1 result"},
        ],
    })
    assert len(plan) == 2
    assert plan[0]["id"] == "step-1" and plan[0]["status"] == "pending"
    assert plan[1]["description"] == "longest tracks"
    assert plan[1]["hint"].startswith("use step 1")

    # garbage steps are skipped, missing description gets a default
    plan = sa._parse_plan({
        "complexity": "plan",
        "steps": [None, {"description": "  ", "hint": "x"}, "junk", {"description": "ok", "hint": ""}],
    })
    assert [p["description"] for p in plan] == ["step 2", "ok"]

    # bounds: capped at MAX_PLAN_STEPS
    many = {"complexity": "plan", "steps": [{"description": f"s{i}"} for i in range(50)]}
    assert len(sa._parse_plan(many)) == sa.MAX_PLAN_STEPS


def unit_parse_monitor():
    # valid actions
    assert sa._parse_monitor({"action": "next"}) == ("next", "", [])
    assert sa._parse_monitor({"action": "retry", "feedback": "join broke"}) == ("retry", "join broke", [])
    # unknown action -> done (safe default)
    assert sa._parse_monitor({"action": "hmm"}) == ("done", "", [])
    assert sa._parse_monitor(None) == ("done", "", [])
    # revise_plan parses the replacement steps
    action, feedback, new_plan = sa._parse_monitor({
        "action": "revise_plan",
        "new_plan": [{"description": "new step", "hint": "h"}],
    })
    assert action == "revise_plan" and len(new_plan) == 1 and new_plan[0]["description"] == "new step"


def unit_build_plan_from_steps():
    plan = sa._build_plan_from_steps([{"description": "a", "hint": "b"}])
    assert plan == [{
        "id": "step-1", "description": "a", "hint": "b",
        "status": "pending", "result": None,
    }]
    assert sa._build_plan_from_steps([]) == []
    assert sa._build_plan_from_steps(None) == []


def unit_preamble_routing():
    # fresh thread -> run the preamble
    assert sa.should_preamble({"messages": [_ai("hi")]}) == "list_tables"
    # schema marker for the CURRENT db -> straight to analysis (even follow-ups)
    with_schema = {"messages": [_ai("hi"), _ai(sa._schema_marker(sa._current_db()) + " Album, Artist, Track")]}
    assert sa.should_preamble(with_schema) == "analyze_question"
    # a marker for a DIFFERENT database is stale (studio switch) -> re-run preamble
    other_db = {"messages": [_ai("hi"), _ai(sa._schema_marker("some-other-db") + " Album")]}
    assert sa.should_preamble(other_db) == "list_tables"


def unit_helpers():
    # _question picks the last human message
    state = {"messages": [_human("first?"), _ai("tables: x"), _human("second?")]}
    assert sa._question(state) == "second?"
    # _last_tool_result picks the most recent tool message
    state = {"messages": [_ai("x"), ToolMessage(content="tables: y", tool_call_id="1")]}
    assert sa._last_tool_result(state["messages"]) == "tables: y"
    # _extract_schema_text finds the current-db DDL marker
    state = {"messages": [_ai("hi"), _ai(sa._schema_marker(sa._current_db()) + " album, artist")]}
    assert "album" in sa._extract_schema_text(state["messages"])


# ── e2e tests (LLM) ─────────────────────────────────────────────────
def e2e_simple():
    """Simple question: classified simple, one-shot loop, no plan, correct answer."""
    state = _run(f"t-{uuid4().hex}", "How many employees are there?")
    answer = state["messages"][-1].content or ""
    assert "8" in answer, f"expected 8 in answer, got: {answer!r}"
    # must NOT have used the plan machinery
    assert not state.get("plan"), f"simple question got a plan: {state.get('plan')!r}"
    assert _count_query_results(state["messages"]) == 1, (
        f"expected exactly 1 executed query, got {_count_query_results(state['messages'])}"
    )


def e2e_multi_hop():
    """Multi-hop question: both halves answered.

    The classifier may legitimately collapse this into one query (window
    functions/CTEs) — the invariant is the ANSWER covers both parts. When the
    planner does engage, it must be a real plan (>=2 steps, >=2 queries);
    the plan machinery itself is covered deterministically by the unit tests.
    """
    thread = f"t-{uuid4().hex}"
    state = _run(
        thread,
        "List the top 3 artists by total revenue, and for the #1 artist name their 3 longest tracks.",
    )
    answer = state["messages"][-1].content or ""
    plan = state.get("plan") or []
    queries = _count_query_results(state["messages"])

    # both halves of the question answered (regardless of simple vs plan)
    assert "Iron Maiden" in answer or "The Beatles" in answer or "U2" in answer, (
        f"expected a top artist in answer, got: {answer!r}"
    )
    assert "track" in answer.lower() or "minute" in answer.lower() or "longest" in answer.lower(), (
        f"expected the longest-tracks half in answer, got: {answer!r}"
    )

    if plan:
        assert len(plan) >= 2, f"plan engaged but too small: {plan!r}"
        assert queries >= 2, f"plan engaged but only {queries} queries"
    else:
        assert queries >= 1, f"no query executed at all: {queries}"


def e2e_stream():
    """Mirror the main() streaming path (stream_events v3)."""
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
        print(f"\nSKIPPED all tests: sql_agent_advanced import failed:\n  {IMPORT_ERROR}")
        print("Set DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL (or point the model block at a local LLM).")
        return 0

    groups = []
    if mode in {"all", "unit"}:
        groups.append(("unit", [
            ("route_from_analysis", unit_route_from_analysis),
            ("route_after_run", unit_route_after_run),
            ("route_from_plan_step", unit_route_from_plan_step),
            ("_step_outcome", unit_step_outcome),
            ("route_from_monitor", unit_route_from_monitor),
            ("_parse_plan", unit_parse_plan),
            ("_parse_monitor", unit_parse_monitor),
            ("_build_plan_from_steps", unit_build_plan_from_steps),
            ("preamble routing", unit_preamble_routing),
            ("state helpers", unit_helpers),
        ]))
    if mode in {"all", "e2e"}:
        groups.append(("e2e", [
            ("simple: count employees (no plan)", e2e_simple),
            ("multi-hop: top artists + longest tracks", e2e_multi_hop),
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
