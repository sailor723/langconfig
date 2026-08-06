"""Custom SQL agent built with LangGraph primitives (human-in-the-loop).

Mimics https://docs.langchain.com/oss/python/langgraph/sql-agent section 6.
The run_query tool interrupts and asks a human to approve the model-generated
SQL before it is executed. Requires a checkpointer so the graph can pause
and resume at the interrupt.

Run:  python backend/langgraph/sql_agent_hitl.py
"""
import json
import os
from typing import Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from sql_setup_db import ensure_chinook_db, sql_db_list_tables, sql_db_schema, sql_db_query

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


# ── 1. Select an LLM ────────────────────────────────────────────────
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


# ── 3. Wrap the query tool with human approval ───────────────────────
@tool(
    run_query_tool.name,
    description=run_query_tool.description,
    args_schema=run_query_tool.args_schema,
)
def run_query_with_review(config: RunnableConfig, **tool_input):
    """Run sql_db_query only after a human reviews the generated SQL."""
    request = {
        "action": run_query_tool.name,
        "args": tool_input,
        "description": "Please review the tool call",
    }
    response = interrupt([request])

    # approve the tool call
    if response["type"] == "accept":
        return run_query_tool.invoke(tool_input, config)
    # update tool call args, e.g. {"type": "edit", "args": {"args": {"query": "..."}}}
    if response["type"] == "edit":
        return run_query_tool.invoke(response["args"]["args"], config)
    # respond to the LLM with user feedback instead of executing
    if response["type"] == "response":
        return response["args"]
    raise ValueError(f"Unsupported interrupt response type: {response['type']}")


run_query_node = ToolNode([run_query_with_review], name="run_query")


# ── 4. Application steps (dedicated nodes) ───────────────────────────
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
    """Ask the model for a SQL query; not forced, so it can answer directly."""
    system_message = {"role": "system", "content": GENERATE_QUERY_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


# ── 5. Graph (with checkpointer for the interrupt) ───────────────────
def should_continue(state: MessagesState) -> Literal[END, "run_query"]:
    """Route generated queries to the (reviewed) run_query node; end otherwise."""
    last_message = state["messages"][-1]
    return END if not last_message.tool_calls else "run_query"


builder = StateGraph(MessagesState)
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(run_query_node, "run_query")

builder.add_edge(START, "list_tables")
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "generate_query")
builder.add_conditional_edges("generate_query", should_continue)
builder.add_edge("run_query", "generate_query")

checkpointer = InMemorySaver()
agent = builder.compile(checkpointer=checkpointer)


# ── 6. Run: first pass interrupts, then resume with approval ─────────
def main() -> None:
    import pathlib

    graph_png = pathlib.Path(__file__).with_name("sql_agent_hitl_graph.png")
    graph_png.write_bytes(agent.get_graph().draw_mermaid_png())
    print(f"Graph saved to {graph_png}")

    config = {"configurable": {"thread_id": "1"}}
    question = "Which genre on average has the longest tracks?"

    # Pass 1: the graph runs until run_query interrupts for human approval.
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": question}]},
        config,
        version="v3",
    )
    for message in stream.messages:
        for token in message.text:
            print(token, end="", flush=True)
    print()
    if stream.interrupted:
        print("INTERRUPTED - waiting for human approval:")
        for request in stream.interrupts[0].value:
            print(json.dumps(request, indent=2))

    # Pass 2: resume with approval. Alternatives:
    #   Command(resume={"type": "edit", "args": {"args": {"query": "..."}}})
    #   Command(resume={"type": "response", "args": "your feedback"})
    stream = agent.stream_events(
        Command(resume={"type": "accept"}),
        config,
        version="v3",
    )
    for message in stream.messages:
        for token in message.text:
            print(token, end="", flush=True)
    print()
    print("Still interrupted - inspect again" if stream.interrupted else "[done]")


if __name__ == "__main__":
    main()
