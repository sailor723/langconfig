# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Execution Event Emission for Live Workflow Monitoring.

Enhanced with LangChain Callbacks for comprehensive agent observability.

This module provides event emission capabilities for the dynamic executor,
enabling real-time visualization of workflow execution in the frontend.

Events are published to in-memory event bus and consumed by SSE endpoints
for streaming to connected clients.

Key Enhancements:
- ExecutionEventCallbackHandler for LangChain/LangGraph integration
- Tool usage tracking (on_tool_start/end/error)
- Agent thought process capture (on_agent_action)
- Node lifecycle monitoring (on_chain_start/end/error)
- Sensitive data sanitization for security
- Token usage tracking
- Error capture and reporting
"""

from typing import Optional, Dict, Any, List

# LangChain callback imports
from langchain_core.callbacks import AsyncCallbackHandler

# Mixin modules split out of the former monolithic emitter
from .shared import logger
from .callbacks import _EventCallbacksMixin
from .internal import _EventHandlerMixin


# =============================================================================
# LangChain Callback Handler for Agent Observability
# =============================================================================

# NOTE: The mixins must precede AsyncCallbackHandler in the base list.
# langchain_core's AsyncCallbackHandler defines no-op on_chain_start/on_tool_start/
# on_agent_action/on_llm_end etc.; if it came first, those stubs would shadow the
# mixin implementations and the emitter would silently stop emitting events.
# super().__init__() is unaffected: neither AsyncCallbackHandler nor any ancestor
# defines __init__ (it resolves to object.__init__, a no-op), and the handler
# fully initializes its own state.
class ExecutionEventCallbackHandler(_EventCallbacksMixin, _EventHandlerMixin, AsyncCallbackHandler):
    """
    LangChain AsyncCallbackHandler for comprehensive agent execution monitoring.

    This callback handler integrates with LangChain/LangGraph workflows to emit
    real-time events for:
    - Node/chain lifecycle (start, end, error)
    - Tool invocations (start, end, error)
    - Agent reasoning (thoughts, actions, observations)
    - LLM token usage
    - Error tracking

    Events are published to event bus for consumption by SSE endpoints.

    Usage:
        callback_handler = ExecutionEventCallbackHandler(
            project_id=123,
            task_id=456,
            workflow_id=789  # Required for SSE channel routing
        )

        # Pass to LangGraph workflow invocation
        result = await agent_graph.ainvoke(
            {"messages": [...]},
            config={"callbacks": [callback_handler]}
        )
    """

    def __init__(
        self,
        project_id: int,
        task_id: int,
        workflow_id: Optional[int] = None,
        user_id: Optional[str] = None,
        enable_sanitization: bool = True,
        node_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        save_to_db: bool = True
    ):
        """
        Initialize the callback handler.

        Args:
            project_id: Project ID for event attribution
            task_id: Task ID for event attribution
            workflow_id: Workflow ID for channel routing (required for SSE streaming)
            user_id: Optional user ID for audit trails
            enable_sanitization: Whether to sanitize sensitive data (recommended)
            node_metadata: Map of node_id to {label, agent_type, config} for proper event labeling
            save_to_db: Whether to persist events to database for historical viewing
        """
        super().__init__()
        self.project_id = project_id
        self.task_id = task_id
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.node_metadata = node_metadata or {}
        self.enable_sanitization = enable_sanitization
        self.save_to_db = save_to_db

        # Track execution metrics
        self.tool_call_count = 0
        self.llm_call_count = 0
        self.total_tokens = 0
        self.error_count = 0

        # Collect artifacts (images, files, etc.) generated during execution
        # These are accumulated from tool results and included in final output
        self.collected_artifacts: List[Dict[str, Any]] = []

        # Track current executing node for agent_action event labeling
        self.current_node_info = {}  # {run_id: {agent_label, node_name, agent_type}}

        # Track current executing tools for on_tool_end events
        self.current_tool_info = {}  # {run_id: {tool_name, agent_label}}

        # Track active subagent runs for nested visualization
        # Maps run_id -> {subagent_name, parent_agent_label, parent_run_id}
        self.active_subagents = {}

        # Track pending database persist tasks to ensure completion on workflow end
        self._pending_persist_tasks: list = []

        logger.info(
            f"ExecutionEventCallbackHandler initialized "
            f"(project={project_id}, task={task_id}, workflow={workflow_id}, save_to_db={save_to_db})"
        )

        if save_to_db:
            logger.info("📝 Database persistence ENABLED - execution events will be saved for historical viewing")
        else:
            logger.warning("⚠️  Database persistence DISABLED - execution events will NOT be saved")


# =============================================================================
# Factory Function for Easy Integration
# =============================================================================

def create_execution_callback_handler(
    project_id: int,
    task_id: int,
    workflow_id: Optional[int] = None,
    user_id: Optional[str] = None,
    enable_sanitization: bool = True,
    node_metadata: Optional[Dict[str, Dict[str, Any]]] = None
) -> ExecutionEventCallbackHandler:
    """
    Factory function to create an ExecutionEventCallbackHandler.

    Usage:
        callback = create_execution_callback_handler(
            project_id=123,
            task_id=456,
            workflow_id=789,  # Required for SSE streaming
            node_metadata={...}  # For proper event labeling
        )

        result = await agent_graph.ainvoke(
            input_data,
            config={"callbacks": [callback]}
        )

    Args:
        project_id: Project ID for event attribution
        task_id: Task ID for event attribution
        workflow_id: Workflow ID for channel routing (required for SSE streaming)
        user_id: Optional user ID for audit trails
        enable_sanitization: Whether to sanitize sensitive data

    Returns:
        Configured callback handler
    """
    return ExecutionEventCallbackHandler(
        project_id=project_id,
        task_id=task_id,
        workflow_id=workflow_id,
        user_id=user_id,
        enable_sanitization=enable_sanitization,
        node_metadata=node_metadata,
        save_to_db=True  # Enable DB persistence for historical execution logs
    )


# =============================================================================
# Usage Example (Documentation)
# =============================================================================

"""
USAGE EXAMPLE: Integrating with LangGraph Workflow

from core.workflows.events.emitter import create_execution_callback_handler
from core.agents.factory import AgentFactory

async def execute_agent_workflow(project_id: int, task_id: int, user_input: str):
    # 1. Create callback handler for observability
    callback = create_execution_callback_handler(
        project_id=project_id,
        task_id=task_id
    )

    # 2. Create agent using AgentFactory
    agent_config = {
        "model": "gpt-4o",
        "temperature": 0.7,
        "system_prompt": "You are a helpful assistant.",
        "mcp_tools": ["filesystem", "web_search"],
        "enable_memory": True
    }

    agent_graph, tools, callbacks = await AgentFactory.create_agent(
        agent_config=agent_config,
        project_id=project_id,
        task_id=task_id,
        context="Execute user request with available tools."
    )

    # 3. Combine callbacks (AgentFactory + Execution Events)
    all_callbacks = callbacks + [callback]

    # 4. Execute workflow with full observability
    result = await agent_graph.ainvoke(
        {"messages": [{"role": "user", "content": user_input}]},
        config={"callbacks": all_callbacks}
    )

    # 5. Access execution metrics
    print(f"Tool calls: {callback.tool_call_count}")
    print(f"Total tokens: {callback.total_tokens}")
    print(f"Errors: {callback.error_count}")

    return result

# Frontend clients receive real-time events via SSE (Server-Sent Events):
# - CHAIN_START/END: Node lifecycle
# - TOOL_START/END/ERROR: Tool invocations
# - AGENT_ACTION: Agent reasoning steps
# - LLM_END: Token usage tracking
#
# Connect to SSE stream:
# GET /api/orchestration/workflows/{workflow_id}/stream
# new EventSource('/api/orchestration/workflows/123/stream')
"""
