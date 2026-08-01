# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Simple Workflow Executor for User-Created Workflows

This module executes workflows that users create in the frontend.
No blueprints, no strategies - just execute the workflow definition stored in the database.
"""

from typing import Any, Dict, Optional

from models.workflow import WorkflowProfile

from .shared import INTERRUPT_AVAILABLE, SimpleWorkflowState, pick_last, logger
from .execution import _WorkflowExecutionMixin
from .builder import _WorkflowBuilderMixin
from .nodes import _WorkflowNodesMixin


class SimpleWorkflowExecutor(_WorkflowExecutionMixin, _WorkflowBuilderMixin, _WorkflowNodesMixin):
    """
    Executes user-created workflows from the database.

    Takes a WorkflowProfile (which contains nodes/edges from React Flow)
    and executes it using LangGraph.
    """

    def __init__(self):
        self.node_metadata = {}  # Will be populated during graph building


# Global executor instance
_executor: Optional[SimpleWorkflowExecutor] = None


def get_executor() -> SimpleWorkflowExecutor:
    """Get or create the global executor instance."""
    global _executor
    if _executor is None:
        _executor = SimpleWorkflowExecutor()
    return _executor


async def execute_workflow_sync(
    workflow_id: int,
    input_data: Dict[str, Any],
    db: Any
) -> Dict[str, Any]:
    """
    Execute a workflow by ID. Used by task handlers for scheduled/triggered executions.

    Args:
        workflow_id: The workflow ID to execute
        input_data: Input data for the workflow
        db: Database session

    Returns:
        Execution result dict

    Raises:
        ValueError: If workflow not found
    """
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise ValueError(f"Workflow {workflow_id} not found")

    executor = get_executor()
    project_id = workflow.project_id if hasattr(workflow, 'project_id') else 0
    result = await executor.execute_workflow(
        workflow=workflow,
        input_data=input_data,
        project_id=project_id,
        task_id=0
    )
    return result
