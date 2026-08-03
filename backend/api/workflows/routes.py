# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Pydantic schemas live in schemas.py (extracted so the sub-router modules can
# import them without a circular dependency on this module). Re-exported here
# so `from api.workflows.routes import <Model>` keeps working for callers that
# referenced the models on this module.
from .schemas import (
    AgentCostBreakdown,
    ExecutionHistoryEntry,
    ToolUsageBreakdown,
    ValidatePathRequest,
    ValidatePathResponse,
    VersionComparisonResponse,
    WorkflowCostMetrics,
    WorkflowExecutionCreate,
    WorkflowExecutionResponse,
    WorkflowExportOptions,
    WorkflowImportRequest,
    WorkflowProfileCreate,
    WorkflowProfileResponse,
    WorkflowProfileUpdate,
    WorkflowVersionCreate,
    WorkflowVersionResponse,
)


# ── Sub-routers (split from this god-module) ──
from .crud import router as _crud_router
from .versions import router as _versions_router
from .executions import router as _executions_router
from .exports import router as _exports_router

router.include_router(_crud_router)
router.include_router(_versions_router)
router.include_router(_executions_router)
router.include_router(_exports_router)


def __getattr__(name: str):
    """Lazily re-export sub-module functions.

    External code imports `update_workflow`, `create_workflow_version`,
    and `create_workflow_execution` from this module
    (tests/test_critical_safety.py). Resolving them on demand (PEP 562)
    instead of eagerly at the bottom of this file avoids ImportError when
    a sub-module is imported directly before this parent module has
    finished initializing.
    """
    if name == "update_workflow":
        from .crud import update_workflow
        return update_workflow
    if name == "create_workflow_version":
        from .versions import create_workflow_version
        return create_workflow_version
    if name == "create_workflow_execution":
        from .executions import create_workflow_execution
        return create_workflow_execution
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
