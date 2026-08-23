"""Adapters that expose the code-defined LangGraph agents as tools.

The repo ships two hand-built LangGraph agents (``sql_agent.py``,
``neo4j_agent.py`` — forced pipeline: schema discovery -> query generation ->
query check -> execution). This module makes those compiled graphs usable
from the rest of the platform in two ways:

1. **As selectable native tools** — ``run_sql_agent()`` / ``run_neo4j_agent()``
   are plain-call adapters invoked by the seeded built-in tools
   (``sql_agent_tool`` / ``neo4j_agent_tool`` in ``tools/native_impl.py``).
   Because those are ordinary ``custom_tools`` rows, they appear in the tool
   picker and load for **both** normal agents (``AgentFactory``) and
   DeepAgents (``DeepAgentFactory._load_base_tools``) — both go through the
   same ``load_agent_tools`` -> ``ToolLoader.load_native`` pipeline.

2. **As deepagents subagents** — ``get_sql_agent_graph()`` /
   ``get_neo4j_agent_graph()`` return the compiled ``CompiledStateGraph``,
   which can be handed to ``create_deep_agent(subagents=[...])`` as a
   ``CompiledSubAgent`` (isolated context window behind the ``task`` tool).

Loading mirrors ``api/graph_studio/routes.py::_load_compiled``: the graph
modules import each other by plain name (``from llm import ...``,
``from sql_setup_db import ...``), so ``backend/langgraph/`` is placed on
``sys.path`` and each module is loaded once via ``spec_from_file_location``
and cached. Module-level side effects of the graphs (model build + DB
connectivity check) therefore run at most once per process.

Thread semantics: each call uses a fresh ``thread_id`` by default, so the
graph's in-memory checkpointer/store never bleeds state between unrelated
tool calls (stateless tool). Pass a stable ``thread_id`` to opt into
conversation memory across calls.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LANGGRAPH_DIR = Path(__file__).resolve().parent

# Compiled-graph cache: name -> module (module-level `agent` is the graph).
_GRAPH_MODULES: Dict[str, Any] = {}


def _load_graph_module(name: str) -> Any:
    """Import (once) a graph module from backend/langgraph and return it.

    Same technique as ``api/graph_studio/routes.py::_load_compiled``: the
    graph modules import each other by plain name (``from llm import ...``),
    which only resolves when ``backend/langgraph/`` is on ``sys.path``.
    """
    if name in _GRAPH_MODULES:
        return _GRAPH_MODULES[name]

    if str(_LANGGRAPH_DIR) not in sys.path:
        sys.path.insert(0, str(_LANGGRAPH_DIR))

    module_path = _LANGGRAPH_DIR / f"{name}.py"
    if not module_path.exists():
        raise ImportError(f"graph module '{module_path}' not found")

    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load graph module '{module_path}'")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "agent"):
        raise ImportError(f"graph module '{module_path}' does not expose 'agent'")

    _GRAPH_MODULES[name] = module
    return module


def run_sql_agent(
    question: str,
    database: Optional[str] = None,
    connection: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> str:
    """Answer a natural-language question against a SQL database.

    Runs the full hand-built LangGraph pipeline (list tables -> schema ->
    generate query -> check query -> execute) with read-only Postgres
    transactions. ``database`` selects the target database for this call
    (falls back to the studio override / env SQL_POSTGRES_DB); ``connection``
    optionally overrides the server (dsn or host/port/dbname/user/password).
    Returns the final answer text.
    """
    module = _load_graph_module("sql_agent")
    config = {
        "configurable": {
            "thread_id": thread_id or f"sql-agent-tool-{uuid.uuid4().hex}"
        }
    }
    graph_input: Dict[str, Any] = {
        "messages": [{"role": "user", "content": question}]
    }
    if database:
        graph_input["sql_database"] = database
    if connection:
        graph_input["sql_connection"] = connection
    result = module.agent.invoke(graph_input, config=config)
    return result["messages"][-1].content or ""


def run_sql_agent_advanced(
    question: str,
    database: Optional[str] = None,
    connection: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> str:
    """Answer a natural-language question against a SQL database (planner).

    Same read-only pipeline as ``run_sql_agent`` but with the planner layer
    (``sql_agent_advanced``): the question is analyzed, multi-hop questions
    get an action plan whose steps run one query each, a monitor checks
    progress after every result, and the final answer is synthesized from the
    collected results. Simple questions take the classic one-shot loop.
    """
    module = _load_graph_module("sql_agent_advanced")
    config = {
        "configurable": {
            "thread_id": thread_id or f"sql-agent-advanced-tool-{uuid.uuid4().hex}"
        }
    }
    graph_input: Dict[str, Any] = {
        "messages": [{"role": "user", "content": question}]
    }
    if database:
        graph_input["sql_database"] = database
    if connection:
        graph_input["sql_connection"] = connection
    result = module.agent.invoke(graph_input, config=config)
    return result["messages"][-1].content or ""


def run_neo4j_agent(
    question: str,
    database: Optional[str] = None,
    connection: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> str:
    """Answer a natural-language question against a Neo4j graph database.

    Runs the hand-built LangGraph pipeline (labels -> schema details ->
    generate Cypher -> check Cypher -> execute) with read-only Cypher tools.
    ``database`` selects the target database for this call (falls back to the
    studio override / env ``NEO4J_DATABASE``); ``connection`` optionally
    overrides the server (uri / user / password / encrypted). Returns the
    final answer text.
    """
    module = _load_graph_module("neo4j_agent")
    config = {
        "configurable": {
            "thread_id": thread_id or f"neo4j-agent-tool-{uuid.uuid4().hex}"
        }
    }
    graph_input: Dict[str, Any] = {
        "messages": [{"role": "user", "content": question}]
    }
    if database:
        graph_input["neo4j_database"] = database
    if connection:
        graph_input["neo4j_connection"] = connection
    result = module.agent.invoke(graph_input, config=config)
    return result["messages"][-1].content or ""


def run_neo4j_agent_advanced(
    question: str,
    database: Optional[str] = None,
    connection: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> str:
    """Answer a natural-language question against a Neo4j graph (planner).

    Same read-only pipeline as ``run_neo4j_agent`` but with the planner layer
    (``neo4j_agent_advanced``): the question is analyzed, multi-hop questions
    get an action plan whose steps run one Cypher query each, a monitor
    checks progress after every result, and the final answer is synthesized
    from the collected results. Simple questions take the classic one-shot
    loop. Database-agnostic: works against whatever graph the connection
    points at.
    """
    module = _load_graph_module("neo4j_agent_advanced")
    config = {
        "configurable": {
            "thread_id": thread_id or f"neo4j-agent-advanced-tool-{uuid.uuid4().hex}"
        }
    }
    graph_input: Dict[str, Any] = {
        "messages": [{"role": "user", "content": question}]
    }
    if database:
        graph_input["neo4j_database"] = database
    if connection:
        graph_input["neo4j_connection"] = connection
    result = module.agent.invoke(graph_input, config=config)
    return result["messages"][-1].content or ""


def get_sql_agent_graph() -> Any:
    """The compiled ``sql_agent`` graph — for ``CompiledSubAgent`` usage."""
    return _load_graph_module("sql_agent").agent


def get_sql_agent_advanced_graph() -> Any:
    """The compiled ``sql_agent_advanced`` (planner) graph — for subagents."""
    return _load_graph_module("sql_agent_advanced").agent


def get_neo4j_agent_graph() -> Any:
    """The compiled ``neo4j_agent`` graph — for ``CompiledSubAgent`` usage."""
    return _load_graph_module("neo4j_agent").agent


def get_neo4j_agent_advanced_graph() -> Any:
    """The compiled ``neo4j_agent_advanced`` (planner) graph — for subagents."""
    return _load_graph_module("neo4j_agent_advanced").agent


# Known code-defined LangGraph agents that may be used as DeepAgent
# subagents. graph_id values are stored in SubAgentConfig.graph_id.
_GRAPH_RUNNABLES: Dict[str, Any] = {
    "sql_agent": get_sql_agent_graph,
    "sql_agent_advanced": get_sql_agent_advanced_graph,
    "neo4j_agent": get_neo4j_agent_graph,
    "neo4j_agent_advanced": get_neo4j_agent_advanced_graph,
}


def get_graph_runnable(graph_id: str) -> Any:
    """Return the compiled graph runnable for a known ``graph_id``.

    Raises KeyError for unknown ids — the caller (DeepAgentFactory
    ``_prepare_subagents``) surfaces it as a config error.
    """
    try:
        getter = _GRAPH_RUNNABLES[graph_id]
    except KeyError:
        raise KeyError(
            f"unknown LangGraph agent graph_id '{graph_id}'; "
            f"known: {sorted(_GRAPH_RUNNABLES)}"
        ) from None
    return getter()
