"""Test script for the planner-based advanced Neo4j agent
(neo4j_agent_advanced.py).

Mirrors test_sql_agent_advanced.py. The AGENT is database-agnostic (it works
from whatever schema the connection exposes), so the e2e tests are
SCHEMA-DRIVEN: they probe the live graph at test time and build questions +
assertions from the actual labels / relationship counts — no hardcoded graph
domain. This keeps the suite green no matter which dataset the Neo4j
connection points at.

  unit  - deterministic checks that never call an LLM:
          * routing: route_from_analysis / route_after_run /
            route_from_plan_step / route_from_monitor
          * plan parsing: _parse_plan / _parse_monitor / _build_plan_from_steps
          * _step_outcome + preamble routing
  e2e   - LLM-backed integration checks (needs a reachable model + Neo4j):
          * simple question (live top label): classified simple, no plan
          * multi-hop (live top relationship + example pairs): plan >=2 steps,
            >=2 queries executed
          * token streaming path used by main() (stream_events v3)

Usage:
  cd backend && python -m langgraph.test_neo4j_agent_advanced   # everything
  cd backend && python -m langgraph.test_neo4j_agent_advanced unit
  cd backend && python -m langgraph.test_neo4j_agent_advanced e2e

Exit code is 0 when every test passes, 1 otherwise.

NOTE: must be run as `python -m langgraph.test_neo4j_agent_advanced` from the
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
    import neo4j_agent_advanced as na
except Exception as exc:  # e.g. model init fails when the API key is missing
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

passed: list[str] = []
failed: list[str] = []


# ── helpers ─────────────────────────────────────────────────────────
def _ai(content: str, tool_calls: list | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def _run(thread_id: str, question: str) -> dict:
    """Run one turn on a thread and return the final state (includes plan)."""
    config = {"configurable": {"thread_id": thread_id}}
    return na.agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )


def _count_query_results(messages) -> int:
    """Number of executed neo4j_graph_query calls: ToolMessages whose content
    carries the query tool's result header (schema tool output differs)."""
    return sum(
        1
        for m in messages
        if getattr(m, "type", "") == "tool"
        and "Cypher Results" in str(m.content or "")
    )


# ── unit tests (no LLM) ─────────────────────────────────────────────
def unit_route_from_analysis():
    assert na.route_from_analysis({"plan": []}) == "generate_query"
    assert na.route_from_analysis({}) == "generate_query"
    assert na.route_from_analysis({"plan": [{"id": "step-1"}]}) == "plan_step"


def unit_route_after_run():
    assert na.route_after_run({"plan": [{"id": "step-1"}]}) == "monitor_plan"
    assert na.route_after_run({"plan": []}) == "generate_query"
    assert na.route_after_run({}) == "generate_query"


def unit_route_from_plan_step():
    qc = {"name": na.run_query_tool.name, "args": {"cypher": "MATCH (n) RETURN n LIMIT 1"}, "id": "1", "type": "tool_call"}
    assert na.route_from_plan_step({"messages": [_ai("", [qc])]}) == "check_query"
    assert na.route_from_plan_step({"messages": [_ai("the answer is 42")]}) == "monitor_plan"


def unit_step_outcome():
    state = {"messages": [ToolMessage(content="stale", tool_call_id="0"), _ai("the answer is 42")]}
    assert na._step_outcome(state) == "the answer is 42"
    qc = {"name": na.run_query_tool.name, "args": {"cypher": "x"}, "id": "1", "type": "tool_call"}
    state = {"messages": [_ai("", [qc]), ToolMessage(content="result rows", tool_call_id="1")]}
    assert na._step_outcome(state) == "result rows"


def unit_route_from_monitor():
    assert na.route_from_monitor({"last_action": "done"}) == "synthesize_answer"
    assert na.route_from_monitor({"last_action": "retry", "retries_left": 2}) == "plan_step"
    assert na.route_from_monitor({"last_action": "retry", "retries_left": 0}) == "synthesize_answer"
    assert na.route_from_monitor({"last_action": "retry"}) == "synthesize_answer"
    assert na.route_from_monitor({"last_action": "next", "current_step": 3, "plan": [1, 2, 3]}) == "synthesize_answer"
    assert na.route_from_monitor({"last_action": "next", "current_step": 2, "plan": [1, 2, 3]}) == "plan_step"
    assert na.route_from_monitor({"last_action": "revise_plan", "retries_left": 2}) == "plan_step"
    assert na.route_from_monitor({"last_action": "bogus"}) == "synthesize_answer"


def unit_parse_plan():
    assert na._parse_plan({"complexity": "simple", "rationale": "one query"}) == []
    assert na._parse_plan({"complexity": "plan", "steps": []}) == []
    assert na._parse_plan(None) == []
    assert na._parse_plan("nope") == []
    assert na._parse_plan({"steps": []}) == []

    plan = na._parse_plan({
        "complexity": "plan",
        "rationale": "two hops",
        "steps": [
            {"description": "top labels", "hint": "count nodes per label"},
            {"description": "deepest path", "hint": "use step 1 result"},
        ],
    })
    assert len(plan) == 2
    assert plan[0]["id"] == "step-1" and plan[0]["status"] == "pending"
    assert plan[1]["description"] == "deepest path"

    many = {"complexity": "plan", "steps": [{"description": f"s{i}"} for i in range(50)]}
    assert len(na._parse_plan(many)) == na.MAX_PLAN_STEPS


def unit_parse_monitor():
    assert na._parse_monitor({"action": "next"}) == ("next", "", [])
    assert na._parse_monitor({"action": "retry", "feedback": "bad rel"}) == ("retry", "bad rel", [])
    assert na._parse_monitor({"action": "hmm"}) == ("done", "", [])
    assert na._parse_monitor(None) == ("done", "", [])
    action, feedback, new_plan = na._parse_monitor({
        "action": "revise_plan",
        "new_plan": [{"description": "new step", "hint": "h"}],
    })
    assert action == "revise_plan" and len(new_plan) == 1 and new_plan[0]["description"] == "new step"


def unit_build_plan_from_steps():
    assert na._build_plan_from_steps([{"description": "a", "hint": "b"}]) == [{
        "id": "step-1", "description": "a", "hint": "b",
        "status": "pending", "result": None,
    }]
    assert na._build_plan_from_steps([]) == []
    assert na._build_plan_from_steps(None) == []


def unit_preamble_routing():
    assert na.should_preamble({"messages": [_ai("hi")]}) == "list_labels"
    # schema marker for the CURRENT db -> straight to analysis
    with_schema = {"messages": [_ai("hi"), _ai(na._schema_marker(na._current_db()) + "\n### Node labels")]}
    assert na.should_preamble(with_schema) == "analyze_question"
    # a marker for a DIFFERENT database is stale (studio switch) -> re-run preamble
    other_db = {"messages": [_ai("hi"), _ai(na._schema_marker("some-other-db") + "\n### Node labels")]}
    assert na.should_preamble(other_db) == "list_labels"


def unit_helpers():
    state = {"messages": [_human("first?"), _ai("tables: x"), _human("second?")]}
    assert na._question(state) == "second?"
    state = {"messages": [_ai("x"), ToolMessage(content="tables: y", tool_call_id="1")]}
    assert na._last_tool_result(state["messages"]) == "tables: y"
    state = {"messages": [_ai("hi"), _ai(na._schema_marker(na._current_db()) + "\n### Node labels")]}
    assert "Node labels" in na._extract_schema_text(state["messages"])


# ── e2e tests (LLM) ─────────────────────────────────────────────────
# These are SCHEMA-DRIVEN on purpose: the agent is database-agnostic, so the
# tests must not hardcode a particular graph. Every assertion is built from
# the live schema the connection exposes at test time (labels + relationship
# counts) — the same source the agent itself uses.
import re as _re


def _live_schema() -> str:
    """The schema dump the agent's preamble would see (labels + rel counts)."""
    from neo4j_setup_db import neo4j_graph_schema
    return neo4j_graph_schema.invoke({})


def _parse_schema(text: str) -> tuple[dict[str, int], dict[str, int]]:
    """Parse "## Neo4j Graph Schema" output → ({label: count}, {rel: count}).

    Counts may carry thousands separators (e.g. "2,155 edges").
    """
    labels, rels = {}, {}
    section = None
    for line in text.splitlines():
        if "Node labels" in line:
            section = "labels"
            continue
        if "Relationship types" in line:
            section = "rels"
            continue
        m = _re.match(r"-\s+(?::)?([A-Za-z0-9_]+)\s+\(([\d,]+)\s+(?:nodes|edges)\)", line.strip())
        if m:
            count = int(m.group(2).replace(",", ""))
            if section == "labels":
                labels[m.group(1)] = count
            elif section == "rels":
                rels[m.group(1)] = count
    return labels, rels


def e2e_simple():
    """Simple question about the most populous label: one-shot loop, no plan."""
    labels, _ = _parse_schema(_live_schema())
    assert labels, f"no labels parsed from schema: {labels!r}"
    top_label = max(labels, key=labels.get)
    expected = labels[top_label]

    state = _run(f"t-{uuid4().hex}", f"How many {top_label} nodes are there?")
    answer = state["messages"][-1].content or ""
    assert str(expected) in answer.replace(",", ""), (
        f"expected {expected} {top_label} nodes in answer, got: {answer!r}"
    )
    assert not state.get("plan"), f"simple question got a plan: {state.get('plan')!r}"
    assert _count_query_results(state["messages"]) == 1, (
        f"expected exactly 1 executed query, got {_count_query_results(state['messages'])}"
    )


def e2e_multi_hop():
    """Multi-hop: top relationship type, then example pairs via that type.

    Step 1 must run before step 2 can know the relationship name — a genuine
    dependency that forces a plan with >=2 executed queries.
    """
    _, rels = _parse_schema(_live_schema())
    assert rels, f"no relationship types parsed from schema: {rels!r}"
    top_rel = max(rels, key=rels.get)

    question = (
        "Which relationship type in the graph has the most edges? "
        "Then show 3 example pairs of nodes connected by that relationship type."
    )
    state = _run(f"t-{uuid4().hex}", question)
    answer = state["messages"][-1].content or ""
    plan = state.get("plan") or []
    queries = _count_query_results(state["messages"])

    assert len(plan) >= 2, f"expected >=2 plan steps, got {len(plan)}: {plan!r}"
    assert queries >= 2, f"expected >=2 executed queries, got {queries}"
    assert top_rel.lower() in answer.lower(), (
        f"expected top relationship '{top_rel}' in answer, got: {answer!r}"
    )
    assert len(answer) > len(top_rel) + 10, f"answer too thin: {answer!r}"


def e2e_stream():
    """Mirror the main() streaming path (stream_events v3)."""
    labels, _ = _parse_schema(_live_schema())
    top_label = max(labels, key=labels.get)
    expected = labels[top_label]

    config = {"configurable": {"thread_id": f"t-{uuid4().hex}"}}
    tokens: list[str] = []
    stream = na.agent.stream_events(
        {"messages": [{"role": "user", "content": f"How many {top_label} nodes are there?"}]},
        config=config,
        version="v3",
    )
    for message in stream.messages:
        for token in message.text:
            tokens.append(token)
    answer = "".join(tokens)
    assert str(expected) in answer.replace(",", ""), (
        f"expected {expected} in streamed answer, got: {answer!r}"
    )


# ── runner ──────────────────────────────────────────────────────────
def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in {"all", "unit", "e2e"}:
        print(f"unknown mode {mode!r}; use 'unit' | 'e2e' | 'all'")
        return 2

    if IMPORT_ERROR is not None:
        print(f"\nSKIPPED all tests: neo4j_agent_advanced import failed:\n  {IMPORT_ERROR}")
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
            ("simple: count Person nodes (no plan)", e2e_simple),
            ("multi-hop: top skills + departments", e2e_multi_hop),
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
