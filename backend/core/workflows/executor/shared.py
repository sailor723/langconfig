# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared state definition and reducers for the workflow executor.

Extracted from the former monolithic executor.py so that the mixin
modules (execution, builder, nodes) share one copy of the state type
without importing the package ``__init__`` (which would create a
circular import).
"""

import logging
import operator
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage

# Task 14: interrupt()-based HITL for APPROVAL_NODE
try:
    from langgraph.types import interrupt, Command
    INTERRUPT_AVAILABLE = True
except ImportError:
    INTERRUPT_AVAILABLE = False

# Preserve the original logger identity so log filters keyed on
# "core.workflows.executor" keep working after the split.
logger = logging.getLogger("core.workflows.executor")


# Simple state for user-created workflows
def pick_last(left: Any, right: Any) -> Any:
    """Reducer that picks the latest (right) value if it's not None."""
    return right if right is not None else left


class SimpleWorkflowState(TypedDict):
    """
    State for user-created workflows from the frontend.

    This state supports all core workflow features including:
    - Multi-agent collaboration via message passing
    - RAG/vector store integration
    - MCP tool access
    - Execution history and timing metrics
    """
    # Core identifiers
    workflow_id: int
    task_id: Optional[int]
    project_id: Optional[int]

    # LangChain messages (with reducer for automatic accumulation)
    messages: Annotated[List[BaseMessage], operator.add]

    # User input
    query: str

    # Execution context (for RAG)
    context_documents: Optional[List[int]]

    # Node tracking
    current_node: Annotated[Optional[str], pick_last]
    agent_type: Annotated[Optional[str], pick_last]
    last_agent_type: Annotated[Optional[str], pick_last]

    # Execution history (with reducer)
    step_history: Annotated[List[Dict[str, Any]], operator.add]

    # Results
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]

    # Timing metrics
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    execution_duration_seconds: Optional[float]

    # Control flow state
    conditional_route: Optional[str]  # For CONDITIONAL_NODE routing
    loop_route: Optional[str]  # For LOOP_NODE routing
    loop_iterations: Optional[Dict[str, int]]  # Track iterations per loop node
    loop_iteration: Optional[int]  # Current iteration of active loop
    loop_should_exit: Optional[bool]  # Whether loop should exit
    loop_exit_reason: Optional[str]  # Reason for loop exit

    # CONDITIONAL_NODE internals - both are written by the node executor and
    # must be declared or LangGraph v1 drops them from state between nodes:
    #  - condition_hits powers the reflection-loop guard (max 5 iterations).
    #    The executor returns it, but without a declared channel LangGraph
    #    silently discards it, so the guard would never accumulate.
    #  - decision holds the parsed [DECISION: PASS|REVISE] marker.
    condition_hits: Optional[Dict[str, int]]  # Iteration count per CONDITIONAL_NODE id
    decision: Optional[str]  # Parsed decision marker from agent messages

    # TOOL_NODE outputs - written by execute_tool_node, read by the
    # output_formatter and by CONDITIONAL_NODE/LOOP_NODE conditions.
    # Must be declared or LangGraph v1 drops them from state entirely.
    tool_result: Optional[Any]  # Raw result returned by the last executed tool
    last_tool_output: Optional[str]  # String form of the last tool output

    # Multimodal attachments (images, documents, videos, audio)
    # workflow_attachments: Provided at workflow start, passed to all agents
    # agent_attachments: Retrieved per-agent from node config
    workflow_attachments: Optional[List[Dict[str, Any]]]
    agent_attachments: Optional[Dict[str, List[Dict[str, Any]]]]  # {node_id: [attachments]}

    # Deferred node support: parallel branch outputs merged here
    branch_results: Annotated[Dict[str, Any], operator.ior]

    # Named handoff values written by nodes so later nodes can consume them,
    # e.g. LLM_NODE with config["output_key"] writes node_outputs[key], and a
    # TOOL_NODE tool_params value like "{{my_key}}" is resolved from here.
    # Declared channel required or LangGraph v1 silently drops the writes.
    node_outputs: Annotated[Dict[str, Any], operator.ior]

    # Critic output for conditional routing
    critic_output: Annotated[Optional[str], pick_last]
