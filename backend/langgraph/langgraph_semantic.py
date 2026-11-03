"""SQL agent with a SEMANTICS node: the graph reads a semantic layer instead of guessing.

Same pipeline as `sql_agent.py` (list tables -> schema -> generate -> check -> execute),
plus one deterministic node up front:

    START -> load_semantics -> should_preamble -> ...

`load_semantics` reads `backend/semantics/<database>/SEMANTICS.md` (or an explicit
`semantics_path`) and keeps its three blocks — schema, business rules, reference SQL —
which are appended to the `generate_query` and `check_query` prompts. Without that file
the prompts are byte-identical to `sql_agent.py`'s.

    python backend/langgraph/langgraph_semantic.py
""" if False else """Custom SQL agent built with LangGraph primitives (no human-in-the-loop).

Mimics https://docs.langchain.com/oss/python/langgraph/sql-agent sections 1-5.
Dedicated nodes force the tool-call order (list tables -> schema -> query)
and add a query-checker step, instead of relying only on the system prompt.
The table/schema preamble runs once per thread; follow-ups skip it and
reuse the schema already in the checkpointed history.

Memory:
- Short-term (thread-scoped): an InMemorySaver checkpointer keeps the
  conversation history, so consecutive runs in the same thread can
  reference earlier turns.
- Long-term (cross-thread): an InMemoryStore lets the agent persist and
  recall durable facts via the store_memory / search_memories tools.

Run:  python backend/langgraph/sql_agent.py
"""
import os
from pathlib import Path
from typing import Literal, NotRequired
from uuid import uuid4

from dotenv import load_dotenv
from langchain.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore

from llm import build_chat_model
from sql_setup_db import ensure_chinook_db, sql_db_list_tables, sql_db_schema, sql_db_query


class SqlAgentState(MessagesState):
    """MessagesState + per-call SQL target.

    ``sql_database`` selects the target database for this run (the tools read
    it via ``InjectedState``); ``sql_connection`` optionally overrides the
    server connection (dsn or host/port/dbname/user/password). Both fall back
    to the studio override / env when left empty.
    """

    sql_database: NotRequired[str]
    sql_connection: NotRequired[dict]
    # Which SKILL.md gives this run its business meaning (schema / 口径 / few-shot).
    # Empty = no semantics file = the prompts stay generic.
    semantics_path: NotRequired[str]
    semantics: NotRequired[dict]

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


# ── 1. Select an LLM ────────────────────────────────────────────────
# Use the platform's default model — the one chosen in
# Settings > Model Cards > "Set Default" (falls back to .env DEFAULT_MODEL,
# then deepseek-chat). A local Ollama default is served through its
# OpenAI-compatible endpoint; cloud models go through their provider.
# The comment below shows the raw call for a local Ollama model:
#   model = init_chat_model(
#       "qwen2.5:14b",
#       model_provider="openai",
#       base_url="http://localhost:11434/v1",
#       api_key="ollama",  # placeholder; Ollama ignores the key
#       temperature=0,
#   )
model = build_chat_model(temperature=0)
# ── 2. Database + tools ─────────────────────────────────────────────
ensure_chinook_db()
tools = [sql_db_list_tables, sql_db_schema, sql_db_query]

get_schema_tool = next(t for t in tools if t.name == "sql_db_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

run_query_tool = next(t for t in tools if t.name == "sql_db_query")
run_query_node = ToolNode([run_query_tool], name="run_query")


# ── 2b. Memory: thread checkpoint + cross-thread store ──────────────
# Short-term: the checkpointer keeps per-thread conversation history.
# Long-term: the store persists durable facts across threads; the model
# can save/recall them through the memory tools bound in generate_query.
MEMORY_NAMESPACE = ("memories", "user")

checkpointer = InMemorySaver()
store = InMemoryStore()


@tool
def store_memory(memory: str, key: str | None = None) -> str:
    """Save a durable fact or user detail that may be useful later.

    Args:
        memory: the fact to remember, e.g. "user prefers rock music".
        key: optional stable id; a random id is generated when omitted.
    """
    item_key = key or f"m_{uuid4().hex}"
    store.put(MEMORY_NAMESPACE, item_key, {"memory": memory})
    return f"Stored memory '{item_key[:8]}'"


@tool
def search_memories(query: str) -> str:
    """Search previously stored memories that are relevant to `query`."""
    results = store.search(MEMORY_NAMESPACE, query=query, limit=5)
    if not results:
        return "No stored memories found."
    return "\n".join(f"- {item.value.get('memory', '')}" for item in results)


memory_tool_node = ToolNode([store_memory, search_memories], name="memory_tools")


# ── 3. Application steps (dedicated nodes) ───────────────────────────
def list_tables(state: SqlAgentState):
    """Predetermined tool call: force listing the available tables.

    The per-call database / connection are forwarded from the state.
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
    response = AIMessage(f"Available tables: {tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema(state: SqlAgentState):
    """Force the model to emit a sql_db_schema tool call (tool_choice='any')."""
    llm_with_tools = model.bind_tools([get_schema_tool], tool_choice="any")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


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


def generate_query(state: SqlAgentState):
    """Ask the model for a SQL query; not forced, so it can answer directly
    or use the memory tools first.

    Where the semantics go is a real decision, and it is measured: appended to the
    system prompt it competes with the schema the agent just fetched and loses
    (the model writes the obvious query), whereas a trailing message lands AFTER
    that schema and wins. `SEM_TAIL=1` selects the trailing form.
    """
    prompt = _semantics_prompt(state)
    tail = bool(prompt) and os.getenv("SEM_TAIL") == "1"
    system_message = {
        "role": "system",
        "content": GENERATE_QUERY_SYSTEM_PROMPT + ("" if tail else prompt),
    }
    messages = [system_message] + list(state["messages"])
    if tail:
        messages.append({"role": "system", "content": "REMINDER — these rules override what you just learned:\n" + prompt})
    llm_with_tools = model.bind_tools([run_query_tool, store_memory, search_memories])
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


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


def check_query(state: SqlAgentState):
    """SQL expert reviews the last generated query before it is executed."""
    _p = _semantics_prompt(state)
    _tail = bool(_p) and os.getenv("SEM_TAIL") == "1"
    system_message = {"role": "system", "content": CHECK_QUERY_SYSTEM_PROMPT + ("" if _tail else _p)}

    # The model may emit a tool call with empty/malformed args; only review
    # calls that actually target the query tool and carry a query string.
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
    msgs = [system_message, user_message]
    if _tail:
        msgs.append({"role": "system", "content": "REMINDER — check the query against these rules:\n" + _p})
    response = llm_with_tools.invoke(msgs)
    response.id = last_message.id
    return {"messages": [response]}


# ── 4. Graph ────────────────────────────────────────────────────────
def should_continue(state: SqlAgentState) -> Literal[END, "check_query", "memory_tools"]:
    """Route generated tool calls: memory calls to the memory node,
    SQL queries to the checker, and plain answers to the end."""
    last_message = state["messages"][-1]
    tool_names = {call.get("name") for call in last_message.tool_calls}
    if not tool_names:
        return END
    if tool_names <= {store_memory.name, search_memories.name}:
        return "memory_tools"
    return "check_query"


SEMANTICS_ROOT = Path(__file__).resolve().parent.parent / "semantics"


# One definition, shared with the semantics editor (api/semantics/routes.py) so the
# editor cannot promise blocks the loader does not find.
from semantics_blocks import semantic_blocks as _semantic_blocks  # noqa: E402


def load_semantics(state: SqlAgentState):
    """Deterministic node: read the run's SKILL.md and keep its three blocks.

    This is the ONLY path business meaning takes into the prompts below — they are
    constants, so without this node a SEMANTICS.md cannot influence the SQL. Nothing
    configured means empty blocks, i.e. exactly the previous behaviour.
    """
    path = (state.get("semantics_path") or os.getenv("SQL_AGENT_SEMANTICS") or "").strip()
    if not path:
        # Prefer the database the tools will actually query: a named target (tpch)
        # selected in the studio is NOT `SQL_POSTGRES_DB`, so reading only the env
        # would ship Chinook's rules into a TPC-H answer — measured: the graph
        # loaded `chinook/SEMANTICS.md` while every tool hit :5432/tpch.
        from sql_setup_db import get_target_database
        db = (
            state.get("sql_database")
            or get_target_database()
            or os.getenv("SQL_POSTGRES_DB")
            or "chinook"
        ).strip()
        candidate = SEMANTICS_ROOT / db / "SEMANTICS.md"
        path = str(candidate) if db and candidate.is_file() else ""
    if not path or not Path(path).is_file():
        return {"semantics": {}}
    return {"semantics": _semantic_blocks(Path(path).read_text(encoding="utf-8"))}


def _semantics_prompt(state) -> str:
    """The semantics text appended to a node's system prompt (empty when none).

    `SEM_BLOCKS` selects which blocks go in. Measured: all three together is 5,766
    characters and the model ignores the rules inside it; the rules alone (≈2.7k)
    still lose; a single relevant rule wins. The schema is already in the thread
    from `get_schema`, so shipping it again is pure dilution.
    """
    skill = state.get("semantics") or {}
    wanted = (os.getenv("SEM_BLOCKS") or "all").lower()
    if wanted != "all":
        allow = {x.strip() for x in wanted.split(",") if x.strip()}
        skill = {k: v for k, v in skill.items() if k in allow}
    parts: list[str] = []
    # Order is deliberate: the business rules go FIRST. With schema ahead of them the
    # rules sat ~700 characters into a 3.5k prompt and the model ignored the one that
    # said revenue must filter billingcountry='USA'.
    if skill.get("semantic"):
        parts.append(
            "## Business rules — MUST follow, they define the numbers\n"
            "If a rule below contradicts what the data seems to suggest, the rule wins.\n\n"
            + skill["semantic"]
        )
    if skill.get("schema"):
        parts.append("## Database schema (authoritative — trust this over your memory)\n" + skill["schema"])
    if skill.get("examples"):
        parts.append("## Reference SQL (follow this style and these joins)\n" + skill["examples"])
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


def should_preamble(state: SqlAgentState) -> Literal["list_tables", "generate_query"]:
    """Skip the table/schema preamble once the schema is in the history.
    The list_tables node marks the schema dump with 'Available tables', so
    its presence means the tables and schema are already in the thread."""
    has_schema = any(
        "Available tables" in str(getattr(m, "content", "") or "")
        for m in state["messages"]
    )
    return "generate_query" if has_schema else "list_tables"


builder = StateGraph(SqlAgentState)
builder.add_node(load_semantics)
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")
builder.add_node(memory_tool_node, "memory_tools")

builder.add_edge(START, "load_semantics")
builder.add_conditional_edges("load_semantics", should_preamble)
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "generate_query")
builder.add_conditional_edges("generate_query", should_continue)
builder.add_edge("check_query", "run_query")
builder.add_edge("run_query", "generate_query")
builder.add_edge("memory_tools", "generate_query")

agent = builder.compile(checkpointer=checkpointer, store=store)


# ── 5. Visualize + run ──────────────────────────────────────────────
def main() -> None:
    print("Interactive SQL agent over the Chinook database.")
    print("Memory enabled: thread-scoped history + cross-thread store.")
    print("Type a question, or 'exit' / 'quit' / 'q' to stop.\n")

    # Same thread_id across turns => the checkpointer keeps the conversation;
    # the store additionally lets the agent remember facts across threads.
    config = {"configurable": {"thread_id": "sql-agent-demo"}}

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

        # Stream the answer token-by-token through the graph.
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
