"""Custom Neo4j agent built with LangGraph primitives (no human-in-the-loop).

Mirrors backend/langgraph/sql_agent.py — same graph shape (list -> schema ->
generate -> check -> run -> generate), same memory tools, same standalone
main() entrypoint. Differences are Cypher-specific:
  - Dialect is "Cypher on a graph database" instead of postgresql.
  - Preamble calls neo4j_graph_schema once (labels + rel types); the model
    then drills into specific labels via neo4j_graph_schema_details when
    it needs columns/sample nodes (the SQL agent's get_schema tool does
    this in one call; for Cypher we split into 2 because the schema is
    typically larger).
  - The check_query step runs the model over the Cypher before execution
    with the same "review for common mistakes" prompt style as the SQL
    agent.

Run:  python backend/langgraph/neo4j_agent.py
"""
from __future__ import annotations

import os
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from langchain.messages import AIMessage
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

# Best-effort: pick up the repo-root .env if the keys live there.
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
    )
)


# ── 1. Select an LLM ────────────────────────────────────────────────
# Same pattern as sql_agent.py: use the platform's default model from
# Settings > Model Cards > "Set Default" (with .env DEFAULT_MODEL and
# deepseek-chat fallback). A local Ollama default is served through its
# OpenAI-compatible endpoint; cloud models go through their provider.
model = build_chat_model(temperature=0)

# ── 2. Neo4j connection + tools ─────────────────────────────────────
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


# ── 2b. Memory: thread checkpoint + cross-thread store ──────────────
# Same shape as sql_agent.py: short-term thread-scoped history via
# InMemorySaver, long-term cross-thread store via InMemoryStore + 2
# memory tools the model can call between Cypher queries.
MEMORY_NAMESPACE = ("memories", "user")

checkpointer = InMemorySaver()
store = InMemoryStore()


@tool
def store_memory(memory: str, key: str | None = None) -> str:
    """Save a durable fact or user detail that may be useful later.

    Args:
        memory: the fact to remember, e.g. "user prefers Cypher RETURN clauses".
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
def list_labels(state: MessagesState):
    """Predetermined tool call: force a compact schema dump (labels + rels).

    Mirrors sql_agent.list_tables — fixed tool call so the LLM doesn't
    have to decide on its own to call the schema tool first.
    """
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
    """Force the model to emit a neo4j_graph_schema_details tool call.

    Once the labels/rels are in the history, force the model to drill
    into the labels it cares about. We use tool_choice='any' so the LLM
    picks the labels (vs. hardcoding).
    """
    llm_with_tools = model.bind_tools([get_schema_details_tool], tool_choice="any")
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
    directly or use the memory tools first."""
    system_message = {"role": "system", "content": GENERATE_CYPHER_SYSTEM_PROMPT}
    llm_with_tools = model.bind_tools(
        [run_query_tool, store_memory, search_memories]
    )
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


CHECK_CYPHER_SYSTEM_PROMPT = """
You are a Cypher expert with a strong attention to detail.
Double check the Cypher query for common mistakes, including:
- Using NOT IN with NULL values
- Missing backticks around labels and relationship types (e.g. `Person`)
- Mismatched parentheses or brackets
- Data type mismatch in predicates (string vs int)
- Missing LIMIT when the result set could be large
- Returning the wrong variable or property
- Using the wrong relationship direction

If there are any of the above mistakes, rewrite the query. If there are no
mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check.
"""


def check_query(state: MessagesState):
    """Cypher expert reviews the last generated query before it is executed.

    Mirrors sql_agent.check_query: only review calls that target the query
    tool with a non-empty cypher arg; tolerate malformed/empty calls.
    """
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


# ── 4. Graph ────────────────────────────────────────────────────────
def should_continue(state: MessagesState) -> Literal[END, "check_query", "memory_tools"]:
    """Route generated tool calls: memory calls to the memory node,
    Cypher queries to the checker, and plain answers to the end."""
    last_message = state["messages"][-1]
    tool_names = {call.get("name") for call in last_message.tool_calls}
    if not tool_names:
        return END
    if tool_names <= {store_memory.name, search_memories.name}:
        return "memory_tools"
    return "check_query"


def should_preamble(state: MessagesState) -> Literal["list_labels", "generate_query"]:
    """Skip the labels/schema preamble once the schema is in the history.

    The list_labels node marks the schema dump with 'Available schema:', so
    its presence means the labels/rels are already in the thread.
    """
    has_schema = any(
        "Available schema:" in str(getattr(m, "content", "") or "")
        for m in state["messages"]
    )
    return "generate_query" if has_schema else "list_labels"


builder = StateGraph(MessagesState)
builder.add_node(list_labels)
builder.add_node(call_get_schema_details)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(get_schema_details_node, "get_schema_details")
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")
builder.add_node(memory_tool_node, "memory_tools")

builder.add_conditional_edges(START, should_preamble)
builder.add_edge("list_labels", "call_get_schema_details")
builder.add_edge("call_get_schema_details", "get_schema_details")
builder.add_edge("get_schema_details", "generate_query")
builder.add_conditional_edges("generate_query", should_continue)
builder.add_edge("check_query", "run_query")
builder.add_edge("run_query", "generate_query")
builder.add_edge("memory_tools", "generate_query")

agent = builder.compile(checkpointer=checkpointer, store=store)


# ── 5. Run ──────────────────────────────────────────────────────────
def main() -> None:
    """Interactive Neo4j agent over the active graph database."""
    print("Interactive Neo4j graph agent.")
    print("Memory enabled: thread-scoped history + cross-thread store.")
    print("Type a question, or 'exit' / 'quit' / 'q' to stop.\n")

    # Same thread_id across turns => the checkpointer keeps the conversation;
    # the store additionally lets the agent remember facts across threads.
    config = {"configurable": {"thread_id": "neo4j-agent-demo"}}

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
