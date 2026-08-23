"""Advanced Neo4j agent built with LangGraph primitives (planner + monitor).

Mirrors ``sql_agent_advanced.py`` for Cypher / graph databases: the same
analysis → plan → step → check → run → monitor → synthesize structure, and
the same simple-vs-plan routing (simple questions keep the classic one-shot
loop; multi-hop questions get an action plan that drives the execution and a
monitor that checks progress after every result).

Database-agnostic by design: NOTHING here is tied to a particular graph —
labels, relationship types and properties are discovered at runtime by the
schema preamble and everything downstream works from whatever graph the
connection points at (studio database dropdown / env / per-call state).

    START
      └─ should_preamble ─► [list_labels → get_schema_details]
                                  │
                                  ▼
                            analyze_question
                             │ classify
              ┌──────────────┴───────────────────┐
              ▼ (simple)                         ▼ (plan)
        generate_query                      plan_step ──► check_query ──► run_query
           │  └──► check_query ──► run_query         ▲                        │
           │        ▲                    │            └──── next / retry ──────┤
           └────────┘ (loop)             └────► monitor_plan ──► (revise) ─────┘
                                                    │
                                                    ▼ (done)
                                              synthesize_answer ──► END

Run:  cd backend && python -m langgraph.neo4j_agent_advanced
"""
import json
import logging
import os
from typing import Any, Literal, NotRequired, Optional

from dotenv import load_dotenv
from langchain.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore

from llm import build_chat_model
from neo4j_setup_db import (
    ensure_neo4j_db,
    neo4j_graph_query,
    neo4j_graph_schema,
    neo4j_graph_schema_details,
)

logger = logging.getLogger(__name__)

# ── Bounds (the plan loop must be able to terminate) ────────────────────────
MAX_PLAN_STEPS = 8        # hard cap on plan length (analyze/revise truncate)
MAX_RETRIES = 3           # retry budget per plan step before giving up


class AdvancedNeo4jAgentState(MessagesState):
    """MessagesState + plan machinery (mirrors sql_agent_advanced).

    ``plan`` is the action plan produced by ``analyze_question``; an empty
    list means "simple question — no plan" (classic one-shot loop). The
    per-call target database / connection are forwarded via the tools'
    ``InjectedState`` params (``neo4j_database`` / ``neo4j_connection``).
    """

    neo4j_database: NotRequired[str]
    neo4j_connection: NotRequired[dict]
    plan: NotRequired[list[dict]]
    current_step: NotRequired[int]
    step_results: NotRequired[list[str]]
    retries_left: NotRequired[int]
    last_action: NotRequired[str]
    last_feedback: NotRequired[str]
    analysis: NotRequired[str]

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
    )
)


# ── 1. Select an LLM ────────────────────────────────────────────────────────
# Same resolution as neo4j_agent.py: platform default model (DB settings →
# .env DEFAULT_MODEL → deepseek-chat).
model = build_chat_model(temperature=0)

# ── 2. Graph connection + tools (shared with neo4j_agent.py) ────────────────
ensure_neo4j_db()
tools = [neo4j_graph_schema, neo4j_graph_schema_details, neo4j_graph_query]

get_schema_tool = next(t for t in tools if t.name == "neo4j_graph_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

get_schema_details_tool = next(
    t for t in tools if t.name == "neo4j_graph_schema_details"
)
get_schema_details_node = ToolNode(
    [get_schema_details_tool], name="get_schema_details"
)

run_query_tool = next(t for t in tools if t.name == "neo4j_graph_query")
run_query_node = ToolNode([run_query_tool], name="run_query")

# Short-term memory: per-thread conversation history (checkpointed).
checkpointer = InMemorySaver()
# Long-term store exists so the graph compiles with the same shape as the
# other agents; the advanced agent does not bind memory tools in v1.
store = InMemoryStore()


# ── 3. Shared preamble nodes (mirror neo4j_agent.py) ────────────────────────
def _current_db() -> str:
    """The database the tools will resolve to (studio override → env)."""
    from neo4j_setup_db import get_target_database
    return get_target_database()


def _schema_marker(database: str) -> str:
    """History marker proving the schema was fetched for THIS database.

    Including the database name means a studio database switch invalidates
    the stale schema and re-runs the preamble instead of reusing labels from
    a different graph database.
    """
    return f"Available schema (db={database}):"


def list_labels(state: AdvancedNeo4jAgentState):
    """Predetermined tool call: force a compact schema dump (labels + rels).

    The per-call database / connection are forwarded from the state; the
    resolved database name is baked into the schema marker so a later
    database switch re-runs the preamble.
    """
    tool_call = {
        "name": "neo4j_graph_schema",
        "args": {},
        "id": "abc123",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])

    list_labels_tool = next(t for t in tools if t.name == "neo4j_graph_schema")
    invoke_kwargs: dict = {}
    if state.get("neo4j_database"):
        invoke_kwargs["database"] = state["neo4j_database"]
    if state.get("neo4j_connection"):
        invoke_kwargs["connection"] = state["neo4j_connection"]
    tool_message = list_labels_tool.invoke(invoke_kwargs)
    if not hasattr(tool_message, "content"):
        tool_message = ToolMessage(
            content=str(tool_message), tool_call_id=tool_call["id"]
        )
    resolved_db = state.get("neo4j_database") or _current_db()
    response = AIMessage(f"{_schema_marker(resolved_db)}\n{tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema_details(state: MessagesState):
    """Force the model to drill into the labels it cares about
    (tool_choice='any' — the labels come from the schema in the history)."""
    llm_with_tools = model.bind_tools(
        [get_schema_details_tool], tool_choice="any"
    )
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def should_preamble(state: MessagesState) -> Literal["list_labels", "analyze_question"]:
    """Skip the labels/schema preamble once the schema is in the history.

    The marker is database-scoped: if the studio switched the target
    database, the old schema is stale and the preamble re-runs. The question
    still needs classifying on follow-ups.
    """
    marker = _schema_marker(_current_db())
    has_schema = any(
        marker in str(getattr(m, "content", "") or "")
        for m in state["messages"]
    )
    return "analyze_question" if has_schema else "list_labels"


# ── 4. Analysis node: classify simple vs plan ───────────────────────────────
ANALYZE_SYSTEM_PROMPT = """
You are a senior data analyst working against a graph database. You are given
the graph schema (node labels, relationship types, properties) and a user's
question. Decide how the question should be answered.

- Classify "simple" when a SINGLE Cypher query (multi-hop patterns,
  aggregations, ORDER BY / LIMIT are fine) can produce the answer.
- Classify "plan" when the question needs multiple DEPENDENT steps: the
  result of one query feeds the next, or several distinct analytical
  questions must be answered and then combined into a final answer.

When you classify "plan", decompose the question into ordered, independently
executable Cypher steps. Each step must be answerable by one query; later
steps may use the results of earlier steps (say so in the hint). Do NOT write
the queries themselves — just plan them. Keep the plan minimal.
""".strip()

GENERATE_CYPHER_SYSTEM_PROMPT = """
You are an agent designed to interact with a Neo4j graph database.
Given an input question, create a syntactically correct Cypher query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant property to return the most interesting
examples in the database. Never query for all the properties from a specific
node, only ask for the relevant ones given the question. Use backticks for
labels and relationship types in Cypher (e.g. `Label`, `REL_TYPE`).

DO NOT make any DML statements (CREATE, MERGE, SET, DELETE, REMOVE, etc.)
to the database — the tools reject writes by design.
""".format(top_k=5)

CHECK_CYPHER_SYSTEM_PROMPT = """
You are a Cypher expert with a strong attention to detail.
Double check the Cypher query for common mistakes, including:
- Using NOT IN with NULL values
- Missing backticks around labels and relationship types (e.g. `Label`)
- Mismatched parentheses or brackets
- Data type mismatch in predicates (string vs int)
- Missing LIMIT when the result set could be large
- Returning the wrong variable or property
- Using the wrong relationship direction

If there are any of the above mistakes, rewrite the query. If there are no
mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check.
""".strip()


@tool
def create_plan(
    complexity: Literal["simple", "plan"],
    rationale: str,
    steps: list[dict[str, str]] = None,
) -> str:
    """Declare how the question will be answered against the graph.

    Args:
        complexity: "simple" when one Cypher query answers the question;
            "plan" when multiple dependent queries are needed.
        rationale: one-line reason for the classification.
        steps: for "plan" mode, the ordered steps, each
            {"description": short step goal, "hint": Cypher intent for this
            step, including which earlier results it consumes}. Empty for
            "simple" mode.
    """
    return f"Plan declared: {complexity} — {rationale}"


def _question(state) -> str:
    """The user's latest question (last HumanMessage content)."""
    for m in reversed(state["messages"]):
        if getattr(m, "type", "") == "human":
            return str(m.content or "")
    return ""


def _extract_schema_text(messages) -> str:
    """The schema dump the preamble fetched (last message containing it)."""
    marker = _schema_marker(_current_db())
    for m in reversed(messages):
        content = str(getattr(m, "content", "") or "")
        if marker in content or "Node labels" in content:
            return content
    return ""


def _build_plan_from_steps(steps) -> list[dict]:
    """Normalize raw step dicts into the state plan shape (capped, validated)."""
    plan: list[dict] = []
    for i, s in enumerate((steps or [])[:MAX_PLAN_STEPS]):
        if isinstance(s, dict):
            plan.append({
                "id": f"step-{i + 1}",
                "description": str(s.get("description", "")).strip() or f"step {i + 1}",
                "hint": str(s.get("hint", "")).strip(),
                "status": "pending",
                "result": None,
            })
    return plan


def _parse_plan(args: Any) -> list[dict]:
    """create_plan args → plan list; [] means "simple" (no plan)."""
    if not isinstance(args, dict) or args.get("complexity") != "plan":
        return []
    return _build_plan_from_steps(args.get("steps"))


def analyze_question(state: AdvancedNeo4jAgentState):
    """Classify the question and (for multi-hop) write the action plan."""
    schema = _extract_schema_text(state["messages"])
    system = {
        "role": "system",
        "content": ANALYZE_SYSTEM_PROMPT + "\n\n## Graph schema\n" + (schema or "(no schema yet)"),
    }
    llm_with_tools = model.bind_tools([create_plan], tool_choice="any")
    response = llm_with_tools.invoke([system] + state["messages"])

    args = response.tool_calls[0]["args"] if response.tool_calls else None
    plan = _parse_plan(args)
    logger.info(
        "[neo4j-agent-advanced] analyze_question: complexity=%s rationale=%r steps=%d",
        args.get("complexity") if isinstance(args, dict) else "simple",
        (args.get("rationale", "") if isinstance(args, dict) else "")[:120],
        len(plan),
    )
    for i, step in enumerate(plan):
        logger.info(
            "[neo4j-agent-advanced]   plan[%d] %s — %s",
            i + 1, step["description"][:80], step["hint"][:80],
        )
    # The create_plan tool call is parsed here, not executed — respond with a
    # ToolMessage so history stays well-formed for the next LLM call.
    tool_call_id = response.tool_calls[0]["id"] if response.tool_calls else "create_plan"
    plan_msg = ToolMessage(
        content=(
            f"complexity={args.get('complexity') if isinstance(args, dict) else 'simple'}; "
            f"planned_steps={len(plan)}"
        ),
        tool_call_id=tool_call_id,
    )
    return {
        "messages": [response, plan_msg],
        "analysis": str(args.get("rationale", "")) if isinstance(args, dict) else "",
        "plan": plan,
        "current_step": 0,
        "step_results": [],
        "retries_left": MAX_RETRIES,
        "last_action": "",
        "last_feedback": "",
    }


def route_from_analysis(state: AdvancedNeo4jAgentState) -> Literal["plan_step", "generate_query"]:
    """Simple (empty plan) → one-shot loop; plan → per-step executor."""
    return "plan_step" if state.get("plan") else "generate_query"


# ── 5. Simple path: one-shot generate → check → run ─────────────────────────
def generate_query(state: MessagesState):
    """Ask the model for a Cypher query (or a direct answer when none is needed)."""
    system_message = {"role": "system", "content": GENERATE_CYPHER_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


def should_continue_simple(state: MessagesState) -> Literal[END, "check_query"]:
    """Simple path: tool calls go to the checker, plain answers end the graph."""
    last_message = state["messages"][-1]
    return "check_query" if last_message.tool_calls else END


def check_query(state: MessagesState):
    """Cypher expert reviews the last generated query before execution."""
    system_message = {"role": "system", "content": CHECK_CYPHER_SYSTEM_PROMPT}

    last_message = state["messages"][-1]
    query_tool_calls = [
        call
        for call in last_message.tool_calls
        if call.get("name") == run_query_tool.name
    ]
    cypher = query_tool_calls[0].get("args", {}).get("cypher") if query_tool_calls else None
    if not cypher:
        return {"messages": []}

    user_message = {"role": "user", "content": cypher}
    llm_with_tools = model.bind_tools([run_query_tool], tool_choice="any")
    response = llm_with_tools.invoke([system_message, user_message])
    response.id = last_message.id
    return {"messages": [response]}


def route_after_run(state: AdvancedNeo4jAgentState) -> Literal["monitor_plan", "generate_query"]:
    """After a query executes: active plan → monitor; else back to the one-shot loop."""
    return "monitor_plan" if state.get("plan") else "generate_query"


# ── 6. Plan path: per-step executor + monitor ───────────────────────────────
PLAN_STEP_SYSTEM_PROMPT = """
You are executing an analytical Cypher plan against a Neo4j graph database.

## Question
{question}

## Plan
{plan}

## Current step ({step_number})
{step_description}

Hint: {step_hint}

## Results collected so far
{results}

## Feedback from the last attempt (empty on first attempt)
{feedback}

Write ONE Cypher query that completes ONLY the current step. Use the
collected results if the step depends on them. Do not attempt later steps.
Use backticks for labels and relationship types (e.g. `Label`, `REL_TYPE`).
If the current step cannot be completed, still emit the best-effort query —
the monitor will decide what to do next.
""".strip()


def plan_step(state: AdvancedNeo4jAgentState):
    """Generate the Cypher query for the CURRENT plan step only."""
    plan = state.get("plan", [])
    idx = state.get("current_step", 0)
    step = plan[idx] if 0 <= idx < len(plan) else {}
    if not step:
        # No active step (e.g. a revise_plan came back empty): answer in text
        # so route_from_plan_step sends us to the monitor, which finishes.
        logger.warning(
            "[neo4j-agent-advanced] plan_step: no active step (idx=%d, plan=%d)",
            idx, len(plan),
        )
        return {"messages": [AIMessage(content="No active plan step to execute.")]}
    system = {
        "role": "system",
        "content": PLAN_STEP_SYSTEM_PROMPT.format(
            question=_question(state),
            plan=json.dumps(_plan_view(plan), ensure_ascii=False, indent=2),
            step_number=idx + 1,
            step_description=step.get("description", ""),
            step_hint=step.get("hint", ""),
            results="\n\n".join(
                f"[{i + 1}] {r[:2000]}"
                for i, r in enumerate(state.get("step_results", []))
            ) or "(none yet)",
            feedback=state.get("last_feedback", "") or "(none)",
        ),
    }
    llm_with_tools = model.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system] + state["messages"])
    logger.info(
        "[neo4j-agent-advanced] plan_step %d/%d: %s",
        idx + 1, len(plan), step.get("description", "")[:80],
    )
    return {"messages": [response]}


def route_from_plan_step(state: AdvancedNeo4jAgentState) -> Literal["check_query", "monitor_plan"]:
    """A plan step either emitted a query (→ checker) or answered in text
    (→ monitor decides). Never send a tool-less message to the run_query
    ToolNode — that crashes it."""
    last = state["messages"][-1]
    if last.tool_calls and any(
        call.get("name") == run_query_tool.name for call in last.tool_calls
    ):
        return "check_query"
    return "monitor_plan"


@tool
def plan_next(
    action: Literal["next", "retry", "revise_plan", "done"],
    feedback: str = "",
    new_plan: list[dict[str, str]] = None,
) -> str:
    """Decide the next action after a query result.

    Args:
        action: "next" — current step succeeded, advance to the next one;
            "retry" — current step failed, re-run it with feedback;
            "revise_plan" — the plan no longer fits reality, replace it
            (provide new_plan);
            "done" — the question is answered, synthesize the final result.
        feedback: for "retry", what went wrong / how to fix the query.
        new_plan: for "revise_plan", the replacement ordered steps (same
            shape as create_plan's steps).
    """
    return f"Action: {action}"


def _parse_monitor(args: Any) -> tuple[str, str, list[dict]]:
    """plan_next args → (action, feedback, new_plan). Unknown → "done"."""
    if not isinstance(args, dict):
        return "done", "", []
    action = args.get("action")
    if action not in {"next", "retry", "revise_plan", "done"}:
        action = "done"
    feedback = str(args.get("feedback", "") or "")
    new_plan = (
        _build_plan_from_steps(args.get("new_plan"))
        if action == "revise_plan"
        else []
    )
    return action, feedback, new_plan


def _plan_view(plan: list[dict]) -> list[dict]:
    """Compact plan rendering for prompts (statuses only, no raw results)."""
    return [
        {"id": p.get("id"), "description": p.get("description"), "status": p.get("status")}
        for p in plan
    ]


def _last_tool_result(messages) -> str:
    """The most recent ToolMessage content (the last query result)."""
    for m in reversed(messages):
        if getattr(m, "type", "") == "tool":
            return str(m.content or "")
    return ""


def _step_outcome(state: AdvancedNeo4jAgentState) -> str:
    """The current step's outcome for the monitor.

    After ``run_query`` the outcome is the ToolMessage result; when
    ``plan_step`` answered in text without a query (no tool call), the
    outcome is that assistant text — not the stale previous result.
    """
    last = state["messages"][-1]
    if getattr(last, "type", "") in {"tool", "ai"} and not getattr(last, "tool_calls", None):
        return str(last.content or "")
    return _last_tool_result(state["messages"])


MONITOR_SYSTEM_PROMPT = """
You are monitoring the execution of an analytical Cypher plan. After every
query result you inspect the plan, decide whether the step succeeded, and
pick the next action.

## Question
{question}

## Plan
{plan}

## Last query result
{last_result}

Decide:
- "next" — the current step's result is usable; advance to the next step.
- "retry" — the current step failed (Cypher error or wrong data); give
  feedback on how to fix the query and re-run the SAME step.
- "revise_plan" — the plan itself is wrong (steps are impossible or the
  results revealed a different structure); provide a replacement plan.
- "done" — the question is answered (all steps done, or enough information
  collected to answer); the final answer will be synthesized from the
  collected results.
""".strip()


def monitor_plan(state: AdvancedNeo4jAgentState):
    """Check the last query result against the plan and pick the next action."""
    plan = list(state.get("plan", []))
    idx = state.get("current_step", 0)
    outcome = _step_outcome(state)

    system = {
        "role": "system",
        "content": MONITOR_SYSTEM_PROMPT.format(
            question=_question(state),
            plan=json.dumps(_plan_view(plan), ensure_ascii=False, indent=2),
            last_result=outcome[:4000] or "(no result)",
        ),
    }
    llm_with_tools = model.bind_tools([plan_next], tool_choice="any")
    response = llm_with_tools.invoke([system])
    args = response.tool_calls[0]["args"] if response.tool_calls else None
    action, feedback, new_plan = _parse_monitor(args)

    # Respond to the plan_next tool call so history stays well-formed.
    tool_call_id = response.tool_calls[0]["id"] if response.tool_calls else "plan_next"
    plan_msg = ToolMessage(
        content=f"action={action}; feedback={feedback or '(none)'}",
        tool_call_id=tool_call_id,
    )
    updates: dict[str, Any] = {"messages": [response, plan_msg], "last_action": action}
    retries_left = state.get("retries_left", MAX_RETRIES)
    step_results = list(state.get("step_results", []))

    if action in {"next", "done"} and 0 <= idx < len(plan):
        plan[idx]["status"] = "done"
        plan[idx]["result"] = outcome[:4000]
        step_results.append(outcome)
        updates["plan"] = plan
        updates["step_results"] = step_results
        updates["current_step"] = idx + 1
        updates["last_feedback"] = ""
        logger.info(
            "[neo4j-agent-advanced] monitor: step %d/%d done (%s), advancing to %d — action=%s",
            idx + 1, len(plan), plan[idx]["description"][:60], idx + 2, action,
        )
    elif action == "retry":
        updates["retries_left"] = retries_left - 1
        updates["last_feedback"] = feedback
        logger.warning(
            "[neo4j-agent-advanced] monitor: step %d/%d retry (%d left) — %s",
            idx + 1, len(plan), retries_left - 1, feedback[:120],
        )
    elif action == "revise_plan":
        if not new_plan:
            # Empty replacement plan would strand plan_step — finish instead.
            action = "done"
            updates["last_action"] = action
            if 0 <= idx < len(plan):
                plan[idx]["status"] = "done"
                plan[idx]["result"] = outcome[:4000]
                step_results.append(outcome)
                updates["plan"] = plan
                updates["step_results"] = step_results
                updates["current_step"] = idx + 1
            logger.info(
                "[neo4j-agent-advanced] monitor: revise_plan returned empty — finishing with %d result(s)",
                len(step_results),
            )
        else:
            updates["plan"] = new_plan
            updates["current_step"] = 0
            updates["step_results"] = []
            updates["retries_left"] = MAX_RETRIES
            updates["last_feedback"] = ""
            logger.info(
                "[neo4j-agent-advanced] monitor: revise_plan — %d new step(s)",
                len(new_plan),
            )

    return updates


def route_from_monitor(state: AdvancedNeo4jAgentState) -> Literal["plan_step", "synthesize_answer"]:
    """Monitor outcome → next step, or finish.

    Terminates on "done" / unknown actions, when every step is complete, or
    when the retry budget is exhausted (best-effort synthesis).
    """
    action = state.get("last_action", "done")
    if action == "retry" and state.get("retries_left", 0) <= 0:
        return "synthesize_answer"
    if action == "next" and state.get("current_step", 0) >= len(state.get("plan", [])):
        return "synthesize_answer"
    if action in {"next", "retry", "revise_plan"}:
        return "plan_step"
    return "synthesize_answer"  # done / unknown → finish safely


# ── 7. Final synthesis for multi-step plans ─────────────────────────────────
SYNTHESIZE_SYSTEM_PROMPT = """
You are writing the final answer for an analytical question that was answered
through several graph queries.

## Question
{question}

## Plan
{plan}

## Collected query results (in step order)
{results}

Write a clear, complete answer to the question using ONLY the collected
results. Cite which step each claim comes from when useful. If some steps
failed, say what could not be determined.
""".strip()


def synthesize_answer(state: AdvancedNeo4jAgentState):
    """Combine every step result into the final answer (no tools needed)."""
    system = {
        "role": "system",
        "content": SYNTHESIZE_SYSTEM_PROMPT.format(
            question=_question(state),
            plan=json.dumps(_plan_view(state.get("plan", [])), ensure_ascii=False, indent=2),
            results="\n\n".join(
                f"[{i + 1}] {r[:2000]}"
                for i, r in enumerate(state.get("step_results", []))
            ) or "(no results collected)",
        ),
    }
    response = model.invoke([system])
    logger.info(
        "[neo4j-agent-advanced] synthesize_answer: %d step result(s) collected",
        len(state.get("step_results", [])),
    )
    return {"messages": [response]}


# ── 8. Graph ────────────────────────────────────────────────────────────────
builder = StateGraph(AdvancedNeo4jAgentState)
builder.add_node(list_labels)
builder.add_node(call_get_schema_details)
builder.add_node(get_schema_details_node, "get_schema_details")
builder.add_node(analyze_question)
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")
builder.add_node(plan_step)
builder.add_node(monitor_plan)
builder.add_node(synthesize_answer)

# START → preamble (once) → analyze
builder.add_conditional_edges(START, should_preamble)
builder.add_edge("list_labels", "call_get_schema_details")
builder.add_edge("call_get_schema_details", "get_schema_details")
builder.add_edge("get_schema_details", "analyze_question")

# analyze → simple loop | plan loop
builder.add_conditional_edges("analyze_question", route_from_analysis)

# simple path: generate → check → run → back to generate (classic loop)
builder.add_conditional_edges("generate_query", should_continue_simple)
builder.add_edge("check_query", "run_query")

# after a query runs: plan present → monitor, else classic loop
builder.add_conditional_edges("run_query", route_after_run)

# plan path: step → (query? check_query : monitor) → run → monitor → ...
builder.add_conditional_edges("plan_step", route_from_plan_step)
builder.add_conditional_edges("monitor_plan", route_from_monitor)
builder.add_edge("synthesize_answer", END)

agent = builder.compile(checkpointer=checkpointer, store=store)


# ── 9. Visualize + run ──────────────────────────────────────────────────────
def main() -> None:
    print("Advanced Neo4j agent (planner) over the active graph database.")
    print("Simple questions answer directly; multi-hop questions get a plan.")
    print("Type a question, or 'exit' / 'quit' / 'q' to stop.\n")

    config = {"configurable": {"thread_id": "neo4j-agent-advanced-demo"}}

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            print("Bye!")
            break

        print("Agent: ", end="", flush=True)
        stream = agent.stream_events(
            {"messages": [{"role": "user", "content": question}]},
            config=config,
            version="v3",
        )
        for message in stream.messages:
            for token in message.text:
                print(token, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
