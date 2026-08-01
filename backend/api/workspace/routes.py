# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
API endpoints for workspace file management.

Provides access to files created by agents during workflow execution.
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# Pydantic schemas live in schemas.py (extracted so the sub-router modules can
# import them without a circular dependency on this module). Re-exported here
# so `from api.workspace.routes import <Model>` keeps working for callers that
# referenced the models on this module.
from .schemas import (
    AllFilesResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkIndexRequest,
    BulkIndexResponse,
    FileContentResponse,
    FileDiffResponse,
    FileInfo,
    FileInfoWithContext,
    FileMetadataResponse,
    FileMetadataUpdateRequest,
    FileTreeResponse,
    FileVersionResponse,
    FileVersionsResponse,
    GroupedFilesResponse,
    IndexFileRequest,
    IndexFileResponse,
    RenameFileRequest,
    TreeNode,
    WorkspaceFilesResponse,
)


# ── Sub-routers (split from this god-module) ──
from .task_files import router as _task_files_router
from .files_routes import router as _files_router
from .tree_routes import router as _tree_router

router.include_router(_task_files_router)
router.include_router(_files_router)
router.include_router(_tree_router)
