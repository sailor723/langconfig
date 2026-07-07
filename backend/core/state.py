# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""State management for deep agents with TODO tracking and virtual file systems.

Mirrors the DeepAgentState from the deep_agent_0530 reference notebooks:
- module-2/2.1_todo.ipynb (TODO tracking via write_todos / read_todos)
- module-2/2.2_files.ipynb (VFS via vfs_ls / vfs_read_file / vfs_write_file)

Passed as ``state_schema=DeepAgentState`` to ``create_agent()`` so that tools
using ``InjectedState`` can access ``todos`` and ``files`` fields.
"""

from typing import Annotated, Literal, Optional

from typing_extensions import NotRequired, TypedDict

from langchain.agents import AgentState


class Todo(TypedDict):
    """A structured task item for tracking progress through complex workflows.

    Attributes:
        content: Short, specific description of the task
        status: Current state - pending, in_progress, or completed
    """
    content: str
    status: Literal["pending", "in_progress", "completed"]


def file_reducer(left: Optional[dict], right: Optional[dict]) -> dict:
    """Merge two file dictionaries, with right side taking precedence.

    Used as a reducer function for the files field in agent state,
    allowing incremental updates to the virtual file system.

    Args:
        left: Left side dictionary (existing files)
        right: Right side dictionary (new/updated files)

    Returns:
        Merged dictionary with right values overriding left values
    """
    if left is None:
        return right or {}
    if right is None:
        return left
    return {**left, **right}


class DeepAgentState(AgentState):
    """Extended agent state that includes task tracking and virtual file system.

    Inherits from LangGraph's AgentState and adds:
    - todos: List of Todo items for task planning and progress tracking
    - files: Virtual file system stored as dict mapping filenames to content
    """
    todos: NotRequired[list[Todo]]
    files: Annotated[NotRequired[dict[str, str]], file_reducer]
