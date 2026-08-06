"""Custom SQL agent built with LangGraph primitives (no human-in-the-loop).

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
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore

from sql_setup_db import ensure_chinook_db, sql_db_list_tables, sql_db_schema, sql_db_query

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


# ── 1. Select an LLM ────────────────────────────────────────────────
# Local Ollama via its OpenAI-compatible endpoint (no extra install needed).
# Pull the model first if missing:  ollama pull qwen2.5:14b
# model = init_chat_model(
#     "qwen2.5:14b",
#     model_provider="openai",
#     base_url="http://localhost:11434/v1",
#     api_key="ollama",  # placeholder; Ollama ignores the key
#     temperature=0,
# )
# Cloud fallback (DeepSeek via the langchain-deepseek provider):
model = init_chat_model(
    "deepseek-chat",
    model_provider="deepseek",
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    temperature=0,
)
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
def list_tables(state: MessagesState):
    """Predetermined tool call: force listing the available tables."""
    tool_call = {
        "name": "sql_db_list_tables",
        "args": {},
        "id": "abc123",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])

    list_tables_tool = next(t for t in tools if t.name == "sql_db_list_tables")
    tool_message = list_tables_tool.invoke(tool_call)
    response = AIMessage(f"Available tables: {tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema(state: MessagesState):
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
""".format(dialect="sqlite", top_k=5)


def generate_query(state: MessagesState):
    """Ask the model for a SQL query; not forced, so it can answer directly
    or use the memory tools first."""
    system_message = {"role": "system", "content": GENERATE_QUERY_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools([run_query_tool, store_memory, search_memories])
    response = llm_with_tools.invoke([system_message] + state["messages"])
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
""".format(dialect="sqlite")


def check_query(state: MessagesState):
    """SQL expert reviews the last generated query before it is executed."""
    system_message = {"role": "system", "content": CHECK_QUERY_SYSTEM_PROMPT}

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
    response = llm_with_tools.invoke([system_message, user_message])
    response.id = last_message.id
    return {"messages": [response]}


# ── 4. Graph ────────────────────────────────────────────────────────
def should_continue(state: MessagesState) -> Literal[END, "check_query", "memory_tools"]:
    """Route generated tool calls: memory calls to the memory node,
    SQL queries to the checker, and plain answers to the end."""
    last_message = state["messages"][-1]
    tool_names = {call.get("name") for call in last_message.tool_calls}
    if not tool_names:
        return END
    if tool_names <= {store_memory.name, search_memories.name}:
        return "memory_tools"
    return "check_query"


def should_preamble(state: MessagesState) -> Literal["list_tables", "generate_query"]:
    """Skip the table/schema preamble once the schema is in the history.
    The list_tables node marks the schema dump with 'Available tables', so
    its presence means the tables and schema are already in the thread."""
    has_schema = any(
        "Available tables" in str(getattr(m, "content", "") or "")
        for m in state["messages"]
    )
    return "generate_query" if has_schema else "list_tables"


builder = StateGraph(MessagesState)
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")
builder.add_node(memory_tool_node, "memory_tools")

builder.add_conditional_edges(START, should_preamble)
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
    # import pathlib

    # graph_png = pathlib.Path(__file__).with_name("sql_agent_graph.png")
    # graph_png.write_bytes(agent.get_graph().draw_mermaid_png())
    # print(f"Graph saved to {graph_png}\n")

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
