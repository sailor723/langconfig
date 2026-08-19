"""Custom Neo4j agent built with LangGraph primitives (human-in-the-loop).

Mirrors backend/langgraph/sql_agent_hitl.py — same interrupt pattern:
the run_query tool interrupts and asks a human to approve the model-generated
Cypher before it is executed. The graph still runs through
list_labels -> call_get_schema_details -> get_schema -> get_schema_details
-> generate_query (just like neo4j_agent.py), but the generated query is
interrupted for human approval instead of going straight to the query checker.

Run:  python backend/langgraph/neo4j_agent_hitl.py
"""
from __future__ import annotations

import json
import os
from typing import Literal

from dotenv import load_dotenv
from langchain.messages import AIMessage
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from llm import build_chat_model
from neo4j_setup_db import (
    ensure_neo4j_db,
    neo4j_graph_query,
    neo4j_graph_schema,
    neo4j_graph_schema_details,
)

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
    )
)


# ── 1. Select an LLM ────────────────────────────────────────────────
# Same pattern as neo4j_agent.py: the platform's default model from
# Settings > Model Cards > "Set Default" (.env DEFAULT_MODEL and
# deepseek-chat fallbacks).
model = build_chat_model(temperature=0)

# ── 2. Neo4j connection + tools ─────────────────────────────────────
ensure_neo4j_db()
tools = [neo4j_graph_schema, neo4j_graph_schema_details, neo4j_graph_query]

get_schema_tool = next(t for t in tools if t.name == "neo4j_graph_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

get_schema_details_tool = next(
    t for t in tools if t.name == "neo4j_graph_schema_details"
)

run_query_tool = next(t for t in tools if t.name == "neo4j_graph_query")


# ── 3. Wrap the query tool with human approval ───────────────────────
@tool(
    run_query_tool.name,
    description=run_query_tool.description,
    args_schema=run_query_tool.args_schema,
)
def run_query_with_review(config: RunnableConfig, **tool_input):
    """Run neo4j_graph_query only after a human reviews the generated Cypher."""
    request = {
        "action": run_query_tool.name,
        "args": tool_input,
        "description": "Please review the tool call",
    }
    response = interrupt([request])

    # approve the tool call
    if response["type"] == "accept":
        return run_query_tool.invoke(tool_input, config)
    # update tool call args, e.g. {"type": "edit", "args": {"args": {"cypher": "..."}}}
    if response["type"] == "edit":
        return run_query_tool.invoke(response["args"]["args"], config)
    # respond to the LLM with user feedback instead of executing
    if response["type"] == "response":
        return response["args"]
    raise ValueError(f"Unsupported interrupt response type: {response['type']}")


run_query_node = ToolNode([run_query_with_review], name="run_query")


# ── 4. Application steps (dedicated nodes) ───────────────────────────
def list_labels(state: MessagesState):
    """Predetermined tool call: force a compact schema dump (labels + rels)."""
    tool_call = {
        "name": "neo4j_graph_schema",
        "args": {},
        "id": "abc123",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])

    list_labels_tool = next(t for t in tools if t.name == "neo4j_graph_schema")
    tool_message = list_labels_tool.invoke(tool_call)
    response = AIMessage(f"Available schema:\n{tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema_details(state: MessagesState):
    """Force the model to emit a neo4j_graph_schema_details tool call
    (tool_choice='any')."""
    llm_with_tools = model.bind_tools(
        [get_schema_details_tool], tool_choice="any"
    )
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


GENERATE_CYPHER_SYSTEM_PROMPT = """
You are an agent designed to interact with a Neo4j graph database.
Given an input question, create a syntactically correct Cypher query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant property to return the most interesting
examples in the database. Never query for all the properties from a specific
node, only ask for the relevant ones given the question. Use backticks for
labels and relationship types in Cypher (e.g. `Person`, `ACTED_IN`).

DO NOT make any DML statements (CREATE, MERGE, SET, DELETE, REMOVE, etc.)
to the database — the tools reject writes by design. If you need to mutate
the graph, use the Neo4j Browser directly.
""".format(top_k=5)


def generate_query(state: MessagesState):
    """Ask the model for a Cypher query; not forced, so it can answer
    directly."""
    system_message = {"role": "system", "content": GENERATE_CYPHER_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


# ── 5. Graph (with checkpointer for the interrupt) ───────────────────
def should_continue(state: MessagesState) -> Literal[END, "run_query"]:
    """Route generated queries to the (reviewed) run_query node; end otherwise."""
    last_message = state["messages"][-1]
    return END if not last_message.tool_calls else "run_query"


builder = StateGraph(MessagesState)
builder.add_node(list_labels)
builder.add_node(call_get_schema_details)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(run_query_node, "run_query")

builder.add_edge(START, "list_labels")
builder.add_edge("list_labels", "call_get_schema_details")
builder.add_edge("call_get_schema_details", "get_schema")
builder.add_edge("get_schema", "generate_query")
builder.add_conditional_edges("generate_query", should_continue)
builder.add_edge("run_query", "generate_query")

checkpointer = InMemorySaver()
agent = builder.compile(checkpointer=checkpointer)


# ── 6. Run: first pass interrupts, then resume with approval ─────────
def main() -> None:
    """Smoke test: first pass runs until interrupt, then resumes with accept."""
    import pathlib

    graph_png = pathlib.Path(__file__).with_name("neo4j_agent_hitl_graph.png")
    graph_png.write_bytes(agent.get_graph().draw_mermaid_png())
    print(f"Graph saved to {graph_png}")

    config = {"configurable": {"thread_id": "1"}}
    question = "Which 5 movies has Tom Hanks acted in, sorted by year?"

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
    #   Command(resume={"type": "edit", "args": {"args": {"cypher": "..."}})
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
