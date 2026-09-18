"""Advanced SQL agent built with LangGraph primitives (planner + monitor).

Extends ``sql_agent.py`` with an analysis/planning layer for analytical and
multi-hop questions, following the DeepAgent "todo / plan" concept:

    START
      └─ should_preamble ─► [list_tables → call_get_schema → get_schema]
                                  │   (preamble runs once per thread)
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

- Simple questions (a single SQL query answers them) keep the proven
  one-shot loop from ``sql_agent.py`` — they pay exactly one extra
  classification call.
- Complex / multi-hop questions get an explicit **action plan** stored in the
  graph state. Each plan step emits its own query (executed read-only), and a
  **monitor node** checks progress after every result and decides
  next / retry / revise_plan / done — the deepagent-style plan loop.

State carries the plan (checkpointed), the active step index, accumulated step
results (for the final synthesis), and a per-step retry budget so the graph can
never loop forever.

Run:  cd backend && python -m langgraph.sql_agent_advanced
      (script-style `python backend/langgraph/sql_agent_advanced.py` does NOT
       work: the installed `langgraph` SDK is a namespace package, so
       `from langgraph.connection import ...` only resolves to the local
       backend/langgraph/ package when `backend/` is on sys.path — i.e. run
       from the backend/ cwd with `-m langgraph.<module>`.)
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
from sql_setup_db import ensure_chinook_db, sql_db_list_tables, sql_db_schema, sql_db_query

logger = logging.getLogger(__name__)

# ── Bounds (the plan loop must be able to terminate) ────────────────────────
MAX_PLAN_STEPS = 8        # hard cap on plan length (analyze/revise truncate)
MAX_RETRIES = 3           # retry budget per plan step before giving up


class AdvancedSqlAgentState(MessagesState):
    """MessagesState + plan machinery.

    ``plan`` is the action plan produced by ``analyze_question``; an empty
    list means "simple question — no plan" (the graph then uses the classic
    one-shot loop). ``current_step`` indexes into ``plan``; ``step_results``
    accumulates each completed step's query result for the final synthesis.
    ``last_action`` / ``last_feedback`` are set by the monitor node and read
    by the routing function / the next ``plan_step``.
    """

    sql_database: NotRequired[str]
    sql_connection: NotRequired[dict]
    plan: NotRequired[list[dict]]
    current_step: NotRequired[int]
    step_results: NotRequired[list[str]]
    retries_left: NotRequired[int]
    last_action: NotRequired[str]
    last_feedback: NotRequired[str]
    analysis: NotRequired[str]

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


# ── 1. Select an LLM ────────────────────────────────────────────────────────
# Same resolution as sql_agent.py: the platform's default model (DB settings
# → .env DEFAULT_MODEL → deepseek-chat). Local Ollama defaults go through
# their OpenAI-compatible endpoint; cloud models through their provider.
model = build_chat_model(temperature=0)

# ── 2. Database + tools (shared with sql_agent.py) ─────────────────────────
ensure_chinook_db()
tools = [sql_db_list_tables, sql_db_schema, sql_db_query]

get_schema_tool = next(t for t in tools if t.name == "sql_db_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

run_query_tool = next(t for t in tools if t.name == "sql_db_query")
run_query_node = ToolNode([run_query_tool], name="run_query")

# Short-term memory: per-thread conversation history (checkpointed).
checkpointer = InMemorySaver()
# Long-term store exists so the graph compiles with the same shape as
# sql_agent.py; the advanced agent does not bind memory tools in v1.
store = InMemoryStore()


# ── 3. Shared preamble nodes (mirror sql_agent.py) ─────────────────────────
def _current_db() -> str:
    """The database the tools will resolve to (studio override → env)."""
    from sql_setup_db import get_target_database
    return get_target_database()


def _schema_marker(database: str) -> str:
    """History marker proving the schema was fetched for THIS database.

    Including the database name means a studio database switch invalidates
    the stale schema and re-runs the preamble instead of reusing tables from
    a different database.
    """
    return f"Available tables (db={database}):"


def list_tables(state: AdvancedSqlAgentState):
    """Predetermined tool call: force listing the available tables.

    The per-call database / connection are forwarded from the state; the
    resolved database name is baked into the schema marker so a later
    database switch re-runs the preamble.
    """
    tool_call = {
        "name": "sql_db_list_tables",
        "args": {},
        "id": "abc123",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])

    list_tables_tool = next(t for t in tools if t.name == "sql_db_list_tables")
    invoke_kwargs: dict = {}
    if state.get("sql_database"):
        invoke_kwargs["database"] = state["sql_database"]
    if state.get("sql_connection"):
        invoke_kwargs["connection"] = state["sql_connection"]
    tool_message = list_tables_tool.invoke(invoke_kwargs)
    # Plain-kwargs invoke returns the raw content string (not a ToolMessage,
    # unlike a full tool_call dict) — normalize so history stays well-formed.
    if not hasattr(tool_message, "content"):
        tool_message = ToolMessage(
            content=str(tool_message), tool_call_id=tool_call["id"]
        )
    resolved_db = state.get("sql_database") or _current_db()
    response = AIMessage(f"{_schema_marker(resolved_db)} {tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema(state: MessagesState):
    """Force the model to emit a sql_db_schema tool call (tool_choice='any')."""
    llm_with_tools = model.bind_tools([get_schema_tool], tool_choice="any")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def should_preamble(state: MessagesState) -> Literal["list_tables", "analyze_question"]:
    """Skip the table/schema preamble once the schema is in the history.

    The marker is database-scoped: if the studio switched the target
    database, the old schema is stale and the preamble re-runs. On follow-ups
    the question still needs classifying (the answer may need a plan even
    when the schema is already known).
    """
    marker = _schema_marker(_current_db())
    has_schema = any(
        marker in str(getattr(m, "content", "") or "")
        for m in state["messages"]
    )
    return "analyze_question" if has_schema else "list_tables"


# ── 4. Analysis node: classify simple vs plan ───────────────────────────────
ANALYZE_SYSTEM_PROMPT = """
You are a senior data analyst. You are given the database schema and a user's
question. Decide how the question should be answered against the database.

- Classify "simple" when a SINGLE SQL query (joins / subqueries / CTEs are
  fine) can produce the answer.
- Classify "plan" when the question needs multiple DEPENDENT steps: the
  result of one query feeds the next, or several distinct analytical
  questions must be answered and then combined into a final answer.

When you classify "plan", decompose the question into ordered, independently
executable SQL steps. Each step must be answerable by one query; later steps
may use the results of earlier steps (say so in the hint). Do NOT write the
queries themselves — just plan them. Keep the plan minimal: no more steps
than necessary.
""".strip()

GENERATE_QUERY_SYSTEM_PROMPT = """
You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.
""".format(dialect="postgresql", top_k=5)

CHECK_QUERY_SYSTEM_PROMPT = """
You are a SQL expert with a strong attention to detail.
Double check the {dialect} query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins

If there are any of the above mistakes, rewrite the query. If there are no mistakes,
just reproduce the original query.

You will call the appropriate tool to execute the query after running this check.
""".format(dialect="postgresql")


@tool
def create_plan(
    complexity: Literal["simple", "plan"],
    rationale: str,
    steps: list[dict[str, str]] = None,
) -> str:
    """Declare how the question will be answered against the database.

    Args:
        complexity: "simple" when one SQL query answers the question;
            "plan" when multiple dependent queries are needed.
        rationale: one-line reason for the classification.
        steps: for "plan" mode, the ordered steps, each
            {"description": short step goal, "hint": SQL intent for this
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
    """The schema DDL the preamble fetched (last message containing it)."""
    marker = _schema_marker(_current_db())
    for m in reversed(messages):
        content = str(getattr(m, "content", "") or "")
        if "CREATE TABLE" in content or marker in content:
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


def analyze_question(state: AdvancedSqlAgentState):
    """Classify the question and (for multi-hop) write the action plan.

    The classification LLM is forced to call ``create_plan``; its args are
    parsed into the state ``plan``. Simple questions produce an empty plan,
    so the router sends them down the classic one-shot loop.
    """
    schema = _extract_schema_text(state["messages"])
    system = {
        "role": "system",
        "content": ANALYZE_SYSTEM_PROMPT + "\n\n## Database schema\n" + (schema or "(no schema yet)"),
    }
    llm_with_tools = model.bind_tools([create_plan], tool_choice="any")
    response = llm_with_tools.invoke([system] + state["messages"])

    args = response.tool_calls[0]["args"] if response.tool_calls else None
    plan = _parse_plan(args)
    logger.info(
        "[sql-agent-advanced] analyze_question: complexity=%s rationale=%r steps=%d",
        args.get("complexity") if isinstance(args, dict) else "simple",
        (args.get("rationale", "") if isinstance(args, dict) else "")[:120],
        len(plan),
    )
    for i, step in enumerate(plan):
        logger.info(
            "[sql-agent-advanced]   plan[%d] %s — %s",
            i + 1, step["description"][:80], step["hint"][:80],
        )
    # The create_plan tool call is parsed here, not executed — respond with a
    # ToolMessage so the history stays well-formed for the next LLM call
    # (providers reject an assistant tool_call without a matching response).
    tool_call_id = response.tool_calls[0]["id"] if response.tool_calls else "create_plan"
    plan_msg = ToolMessage(
        content=(
            f"complexity={args.get('complexity') if isinstance(args, dict) else 'simple'}; "
            f"planned_steps={len(plan)}"
        ),
        tool_call_id=tool_call_id,
    )
    updates: dict = {
        "messages": [response, plan_msg],
        "analysis": str(args.get("rationale", "")) if isinstance(args, dict) else "",
        "plan": plan,
        "current_step": 0,
        "step_results": [],
        "retries_left": MAX_RETRIES,
        "last_action": "",
        "last_feedback": "",
    }
    if plan:
        updates["plan"] = plan
    return updates


def route_from_analysis(state: AdvancedSqlAgentState) -> Literal["plan_step", "generate_query"]:
    """Simple (empty plan) → one-shot loop; plan → per-step executor."""
    return "plan_step" if state.get("plan") else "generate_query"


# ── 5. Simple path: one-shot generate → check → run (mirror sql_agent) ──────
def generate_query(state: MessagesState):
    """Ask the model for a SQL query (or a direct answer when no query is needed)."""
    system_message = {"role": "system", "content": GENERATE_QUERY_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


def should_continue_simple(state: MessagesState) -> Literal[END, "check_query"]:
    """Simple path: tool calls go to the checker, plain answers end the graph."""
    last_message = state["messages"][-1]
    return "check_query" if last_message.tool_calls else END


def check_query(state: MessagesState):
    """SQL expert reviews the last generated query before it is executed."""
    system_message = {"role": "system", "content": CHECK_QUERY_SYSTEM_PROMPT}

    last_message = state["messages"][-1]
    query_tool_calls = [
        call
        for call in last_message.tool_calls
        if call.get("name") == run_query_tool.name
    ]
    query = query_tool_calls[0].get("args", {}).get("query") if query_tool_calls else None
    if not query:
        return {"messages": []}

    user_message = {"role": "user", "content": query}
    llm_with_tools = model.bind_tools([run_query_tool], tool_choice="any")
    response = llm_with_tools.invoke([system_message, user_message])
    response.id = last_message.id
    return {"messages": [response]}


def route_after_run(state: AdvancedSqlAgentState) -> Literal["monitor_plan", "generate_query"]:
    """After a query executes: active plan → monitor; else back to the one-shot loop."""
    return "monitor_plan" if state.get("plan") else "generate_query"


# ── 6. Plan path: per-step executor + monitor ───────────────────────────────
PLAN_STEP_SYSTEM_PROMPT = """
You are executing an analytical SQL plan against a PostgreSQL database.

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

Write ONE SQL query that completes ONLY the current step. Use the collected
results if the step depends on them. Do not attempt later steps. If the
current step cannot be completed, still emit the best-effort query — the
monitor will decide what to do next.
""".strip()


def plan_step(state: AdvancedSqlAgentState):
    """Generate the SQL query for the CURRENT plan step only.

    The system prompt carries the question, the plan with statuses, the
    collected results, and any retry feedback; the model emits exactly one
    query, which flows through the shared check_query → run_query nodes.
    """
    plan = state.get("plan", [])
    idx = state.get("current_step", 0)
    step = plan[idx] if 0 <= idx < len(plan) else {}
    if not step:
        # No active step (e.g. a revise_plan came back empty): answer in text
        # so route_from_plan_step sends us to the monitor, which finishes.
        logger.warning(
            "[sql-agent-advanced] plan_step: no active step (idx=%d, plan=%d)",
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
        "[sql-agent-advanced] plan_step %d/%d: %s",
        idx + 1, len(plan), step.get("description", "")[:80],
    )
    return {"messages": [response]}


def route_from_plan_step(state: AdvancedSqlAgentState) -> Literal["check_query", "monitor_plan"]:
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


def _step_outcome(state: AdvancedSqlAgentState) -> str:
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
You are monitoring the execution of an analytical SQL plan. After every query
result you inspect the plan, decide whether the step succeeded, and pick the
next action.

## Question
{question}

## Plan
{plan}

## Last query result
{last_result}

Decide:
- "next" — the current step's result is usable; advance to the next step.
- "retry" — the current step failed (SQL error or wrong data); give feedback
  on how to fix the query and re-run the SAME step.
- "revise_plan" — the plan itself is wrong (steps are impossible or the
  results revealed a different structure); provide a replacement plan.
- "done" — the question is answered (all steps done, or enough information
  collected to answer); the final answer will be synthesized from the
  collected results.
""".strip()


def monitor_plan(state: AdvancedSqlAgentState):
    """Check the last query result against the plan and pick the next action.

    Updates the plan (step statuses), accumulates step results, and records
    ``last_action`` / ``last_feedback`` for the router and the next
    ``plan_step``. The retry budget lives in ``retries_left``.
    """
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

    # Respond to the plan_next tool call so history stays well-formed (the
    # next plan_step / synthesize sends this history to the model).
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
            "[sql-agent-advanced] monitor: step %d/%d done (%s), advancing to %d — action=%s",
            idx + 1, len(plan), plan[idx]["description"][:60], idx + 2, action,
        )
    elif action == "retry":
        updates["retries_left"] = retries_left - 1
        updates["last_feedback"] = feedback
        logger.warning(
            "[sql-agent-advanced] monitor: step %d/%d retry (%d left) — %s",
            idx + 1, len(plan), retries_left - 1, feedback[:120],
        )
    elif action == "revise_plan":
        if not new_plan:
            # A replacement plan that came back empty would strand plan_step
            # on an undefined step — finish with what we have instead.
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
                "[sql-agent-advanced] monitor: revise_plan returned empty — finishing with %d result(s)",
                len(step_results),
            )
        else:
            updates["plan"] = new_plan
            updates["current_step"] = 0
            updates["step_results"] = []
            updates["retries_left"] = MAX_RETRIES
            updates["last_feedback"] = ""
            logger.info(
                "[sql-agent-advanced] monitor: revise_plan — %d new step(s)",
                len(new_plan),
            )

    return updates


def route_from_monitor(state: AdvancedSqlAgentState) -> Literal["plan_step", "synthesize_answer"]:
    """Monitor outcome → next step, or finish.

    Terminates when the monitor says "done" (or returns an unknown action),
    when every step is complete, or when the retry budget for the current
    step is exhausted (best-effort synthesis instead of an infinite retry
    loop). Only "next" / "retry" / "revise_plan" continue the loop.
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
through several database queries.

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


def synthesize_answer(state: AdvancedSqlAgentState):
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
        "[sql-agent-advanced] synthesize_answer: %d step result(s) collected",
        len(state.get("step_results", [])),
    )
    return {"messages": [response]}


# ── 8. Graph ────────────────────────────────────────────────────────────────
builder = StateGraph(AdvancedSqlAgentState)
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(analyze_question)
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")
builder.add_node(plan_step)
builder.add_node(monitor_plan)
builder.add_node(synthesize_answer)

# START → preamble (once) → analyze
builder.add_conditional_edges(START, should_preamble)
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "analyze_question")

# analyze → simple loop | plan loop
builder.add_conditional_edges("analyze_question", route_from_analysis)

# simple path: generate → check → run → back to generate (classic loop)
builder.add_conditional_edges("generate_query", should_continue_simple)
builder.add_edge("check_query", "run_query")

# after a query runs: plan present → monitor, else classic loop
builder.add_conditional_edges("run_query", route_after_run)

# plan path: step → (query? check_query : monitor) → run → monitor → ...
builder.add_conditional_edges("plan_step", route_from_plan_step)
builder.add_edge("check_query", "run_query")
builder.add_conditional_edges("monitor_plan", route_from_monitor)
builder.add_edge("synthesize_answer", END)

agent = builder.compile(checkpointer=checkpointer, store=store)


# ── 9. Visualize + run ──────────────────────────────────────────────────────
def main() -> None:
    print("Advanced SQL agent (planner) over the Chinook database.")
    print("Simple questions answer directly; multi-hop questions get a plan.")
    print("Type a question, or 'exit' / 'quit' / 'q' to stop.\n")

    config = {"configurable": {"thread_id": "sql-agent-advanced-demo"}}

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
