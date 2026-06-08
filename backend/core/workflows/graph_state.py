"""
Compatibility alias for the historical `graph_state` module name.

The state definitions for the LangGraph workflow engine live in `state.py`.
Several modules historically imported them from a module named
`graph_state.py`, which was renamed during a refactor. To avoid touching
every import site, this module re-exports the public symbols that the
historical API exposed.

Prefer importing directly from `.state` in new code.
"""

from .state import (
    # Types
    HandoffSummary,
    WorkflowState,
    WorkflowStatus,
    ClassificationType,
    ExecutorType,
    # Factory / mutator helpers
    create_initial_state,
    update_workflow_status,
    add_retry_attempt,
    create_handoff_summary,
    add_handoff_to_state,
    get_context_for_prompt,
)

__all__ = [
    "HandoffSummary",
    "WorkflowState",
    "WorkflowStatus",
    "ClassificationType",
    "ExecutorType",
    "create_initial_state",
    "update_workflow_status",
    "add_retry_attempt",
    "create_handoff_summary",
    "add_handoff_to_state",
    "get_context_for_prompt",
]
