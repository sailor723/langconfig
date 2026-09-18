# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Classic LangGraph workflows: drag-and-drop builder that maps 1:1 onto
langgraph.graph.StateGraph primitives (state, nodes, edges, conditional edges,
reducers, path_map). Kept entirely separate from the LangConfig workflow model.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean
from db.database import Base


class ClassicGraph(Base):
    """A user-authored classic-LangGraph workflow.

    `spec` is a JSON document that maps directly to the langgraph.graph
    StateGraph API:
      {
        "state_fields": [
          {"name": "evens", "reducer": "add", "default": []},
          {"name": "odds",  "reducer": "add", "default": []},
          {"name": "last_number", "reducer": "last", "default": null}
        ],
        "nodes": [
          {"id": "generate", "kind": "function", "code": "..."},
          {"id": "llm",     "kind": "llm",      "model": "minimax-m3", "prompt": "..."},
          {"id": "tool",    "kind": "tool",     "tool_type": "custom", "tool_id": "x", "params": {...}}
        ],
        "edges": [
          {"source": "START", "target": "generate"},
          {"source": "generate", "kind": "conditional", "route": "int(state.get('last_number',0)) % 2 == 0", "path_map": {"true": "handle_even", "false": "handle_odd"}},
          {"source": "handle_even", "target": "END"}
        ]
      }
    """
    __tablename__ = "classic_graphs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    spec = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ClassicGraphRun(Base):
    """A single execution of a ClassicGraph. Persists inputs and final state."""
    __tablename__ = "classic_graph_runs"

    id = Column(Integer, primary_key=True, index=True)
    graph_id = Column(Integer, nullable=False, index=True)
    input_data = Column(JSON, nullable=False, default=dict)
    final_state = Column(JSON, nullable=True)
    steps = Column(JSON, nullable=True)  # list of {node, state_delta}
    status = Column(String(32), nullable=False, default="completed")  # completed | error
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)