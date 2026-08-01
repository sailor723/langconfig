# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Pydantic schemas for the workspace API.

Moved out of api/workspace/routes.py so the sub-router modules (task_files,
files_routes, tree_routes) can import their models without a circular
dependency on the parent module. Re-exported by routes.py to keep
`from api.workspace.routes import <Model>` working for existing callers.
"""
from typing import List

from pydantic import BaseModel


class FileInfo(BaseModel):
    """Information about a file in the workspace"""
    filename: str
    path: str
    size_bytes: int
    size_human: str
    modified_at: str
    extension: str


class FileInfoWithContext(FileInfo):
    """File info with project/workflow/task context"""
    project_id: int | None = None
    project_name: str | None = None
    workflow_id: int | None = None
    workflow_name: str | None = None
    task_id: int | None = None
    full_path: str | None = None


class RenameFileRequest(BaseModel):
    """Request to rename a file"""
    new_name: str


class FileContentResponse(BaseModel):
    """Response with file content for preview"""
    filename: str
    content: str | None
    mime_type: str
    is_binary: bool
    truncated: bool
    size_bytes: int


class AllFilesResponse(BaseModel):
    """Response with list of all files across workspace"""
    files: List[FileInfoWithContext]
    total_files: int


class BulkDeleteRequest(BaseModel):
    """Request to delete multiple files"""
    files: List[dict]  # [{ "task_id": 1, "filename": "x.md" }]


class BulkDeleteResponse(BaseModel):
    """Response from bulk delete operation"""
    deleted: int
    failed: int
    errors: List[str]


class BulkIndexRequest(BaseModel):
    """Request to index multiple files at once"""
    file_paths: List[str]  # List of relative paths within outputs/
    project_id: int


class BulkIndexResponse(BaseModel):
    """Response from bulk index operation"""
    status: str
    indexed: int
    failed: int
    total_chunks: int
    errors: List[str]


class FileMetadataResponse(BaseModel):
    """Full file metadata including agent context"""
    id: int
    filename: str
    file_path: str
    # Agent context
    agent_label: str | None = None
    agent_type: str | None = None
    node_id: str | None = None
    # Workflow context
    workflow_id: int | None = None
    workflow_name: str | None = None
    task_id: int | None = None
    project_id: int | None = None
    execution_id: str | None = None
    # Content metadata
    original_query: str | None = None
    description: str | None = None
    content_type: str | None = None
    tags: List[str] = []
    # File info
    size_bytes: int | None = None
    mime_type: str | None = None
    extension: str | None = None
    # Timestamps
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class FileMetadataUpdateRequest(BaseModel):
    """Request to update file metadata"""
    description: str | None = None
    content_type: str | None = None
    tags: List[str] | None = None


class WorkspaceFilesResponse(BaseModel):
    """Response with list of files in a task's workspace"""
    task_id: int
    workflow_id: int | None  # Can be None for tasks created outside workflow context
    project_id: int | None
    files: List[FileInfo]
    total_files: int
    workspace_path: str


# =============================================================================
# Knowledge Base Integration
# =============================================================================

class IndexFileRequest(BaseModel):
    """Request to index a file into the knowledge base"""
    project_id: int


class IndexFileResponse(BaseModel):
    """Response from indexing a file"""
    status: str
    message: str
    chunks_created: int | None = None


# =============================================================================
# File Tree & Version History (Enhanced File Viewer)
# =============================================================================

class TreeNode(BaseModel):
    """A node in the file tree structure."""
    id: str
    name: str
    type: str  # 'workflow', 'task', 'file'
    path: str | None = None
    children: List['TreeNode'] | None = None
    metadata: dict | None = None


class FileTreeResponse(BaseModel):
    """Response with file tree structure."""
    tree: List[TreeNode]
    total_files: int


class FileVersionResponse(BaseModel):
    """A single file version."""
    id: int
    version_number: int
    operation: str
    change_summary: str | None = None
    agent_label: str | None = None
    node_id: str | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    created_at: str | None = None
    has_content_snapshot: bool = False


class FileVersionsResponse(BaseModel):
    """Response with file version history."""
    file_id: int
    filename: str
    versions: List[FileVersionResponse]
    total_versions: int


class FileDiffResponse(BaseModel):
    """Response with diff between versions."""
    file_id: int
    filename: str
    v1: int
    v2: int
    unified_diff: str
    side_by_side: List[dict]
    stats: dict


class GroupedFilesResponse(BaseModel):
    """Response with files grouped by task."""
    workflow_id: int
    workflow_name: str
    tasks: List[dict]
    total_files: int
