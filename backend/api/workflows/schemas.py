# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Pydantic schemas for the workflow API.

Moved out of api/workflows/routes.py so the sub-router modules (crud,
versions, executions, exports) can import their models without a circular
dependency on the parent module. Re-exported by routes.py to keep
`from api.workflows.routes import <Model>` working for existing callers.
"""
import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from models.workflow import WorkflowStrategy

logger = logging.getLogger(__name__)


class WorkflowProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[int] = None  # Project association
    strategy_type: Optional[WorkflowStrategy] = None  # Optional - only needed for predefined strategy workflows
    configuration: dict = Field(...)  # Required - contains nodes and edges
    schema_output_config: Optional[dict] = None
    output_schema: Optional[str] = None
    blueprint: Optional[dict] = None
    custom_output_path: Optional[str] = None  # Custom output directory for file writes


class WorkflowProfileUpdate(BaseModel):
    name: Optional[str] = None
    project_id: Optional[int] = None
    strategy_type: Optional[WorkflowStrategy] = None
    configuration: Optional[dict] = None
    schema_output_config: Optional[dict] = None
    output_schema: Optional[str] = None
    blueprint: Optional[dict] = None
    lock_version: Optional[int] = Field(None, description="Current lock version for optimistic locking")
    custom_output_path: Optional[str] = None  # Custom output directory for file writes


class WorkflowProfileResponse(BaseModel):
    id: int
    name: str
    project_id: Optional[int]
    strategy_type: Optional[WorkflowStrategy]  # Optional - studio workflows don't need this
    configuration: dict
    schema_output_config: Optional[dict]
    output_schema: Optional[str]
    blueprint: Optional[dict]
    lock_version: int  # For optimistic locking
    custom_output_path: Optional[str]  # Custom output directory for file writes
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Output Path Configuration Endpoints
# =============================================================================

class ValidatePathRequest(BaseModel):
    path: str = Field(..., description="The custom output path to validate")


class ValidatePathResponse(BaseModel):
    valid: bool
    resolved_path: Optional[str] = None
    error: Optional[str] = None
    writable: bool = False
    exists: bool = False


# =============================================================================
# Workflow Versioning Endpoints
# =============================================================================

# Pydantic Schemas for Versioning
class WorkflowVersionCreate(BaseModel):
    config_snapshot: dict = Field(..., description="Complete workflow configuration snapshot")
    notes: Optional[str] = Field(None, description="User notes about this version")
    created_by: Optional[str] = Field(None, description="User ID or name")


class WorkflowVersionResponse(BaseModel):
    id: int
    workflow_id: int
    version_number: int
    config_snapshot: dict
    notes: Optional[str]
    changelog: Optional[str]
    is_current: bool
    created_by: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecutionCreate(BaseModel):
    version_id: int
    execution_results: dict
    token_usage: Optional[dict] = None
    cost: Optional[float] = None
    execution_time: Optional[float] = None
    status: str = "success"
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None

    @field_validator('token_usage')
    @classmethod
    def validate_token_usage(cls, v):
        """
        Validate token usage structure and values.

        Metrics data validation
        - Ensures token_usage has correct structure
        - Validates token counts are non-negative integers
        - Checks total_tokens matches sum of input + output
        """
        if v is None:
            return v

        if not isinstance(v, dict):
            raise ValueError("token_usage must be a dictionary")

        # Expected keys
        valid_keys = {"input_tokens", "output_tokens", "total_tokens"}
        provided_keys = set(v.keys())

        # Check for unexpected keys
        unexpected = provided_keys - valid_keys
        if unexpected:
            logger.warning(f"Unexpected keys in token_usage: {unexpected}")

        # Validate individual token counts
        for key in ["input_tokens", "output_tokens", "total_tokens"]:
            if key in v:
                value = v[key]
                if not isinstance(value, (int, float)):
                    raise ValueError(f"{key} must be a number, got {type(value).__name__}")
                if value < 0:
                    raise ValueError(f"{key} cannot be negative, got {value}")
                # Convert to int if it's a whole number
                if isinstance(value, float) and value.is_integer():
                    v[key] = int(value)

        # Validate total matches sum (if all fields present)
        if all(k in v for k in ["input_tokens", "output_tokens", "total_tokens"]):
            expected_total = v["input_tokens"] + v["output_tokens"]
            actual_total = v["total_tokens"]
            if abs(expected_total - actual_total) > 0.01:  # Allow small floating point errors
                logger.warning(
                    f"Token usage mismatch: expected total={expected_total}, "
                    f"got total={actual_total}. Auto-correcting."
                )
                # Auto-correct the total
                v["total_tokens"] = expected_total

        return v

    @field_validator('cost')
    @classmethod
    def validate_cost(cls, v):
        """
        Validate cost is non-negative.

        Metrics data validation
        - Ensures cost is a non-negative number
        - Prevents invalid cost data
        """
        if v is None:
            return v

        if not isinstance(v, (int, float)):
            raise ValueError(f"cost must be a number, got {type(v).__name__}")

        if v < 0:
            raise ValueError(f"cost cannot be negative, got {v}")

        # Reasonable upper bound check (costs > $100 per execution seem suspicious)
        if v > 100.0:
            logger.warning(f"Unusually high execution cost: ${v:.2f}")

        return v

    @field_validator('execution_time')
    @classmethod
    def validate_execution_time(cls, v):
        """
        Validate execution time is non-negative.

        Metrics data validation
        - Ensures execution_time is a non-negative number
        - Prevents invalid timing data
        """
        if v is None:
            return v

        if not isinstance(v, (int, float)):
            raise ValueError(f"execution_time must be a number, got {type(v).__name__}")

        if v < 0:
            raise ValueError(f"execution_time cannot be negative, got {v}")

        # Reasonable upper bound check (executions > 1 hour seem suspicious)
        if v > 3600.0:
            logger.warning(f"Unusually long execution time: {v:.2f}s ({v/60:.2f}min)")

        return v


class WorkflowExecutionResponse(BaseModel):
    id: int
    workflow_id: int
    version_id: int
    execution_results: dict
    token_usage: Optional[dict]
    cost: Optional[float]
    execution_time: Optional[float]
    status: str
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: datetime

    class Config:
        from_attributes = True


class VersionComparisonResponse(BaseModel):
    version1: WorkflowVersionResponse
    version2: WorkflowVersionResponse
    diff: dict  # Structured diff between the two versions


class AgentCostBreakdown(BaseModel):
    name: str
    cost: float
    tokens: int


class ToolUsageBreakdown(BaseModel):
    name: str
    count: int


class ExecutionHistoryEntry(BaseModel):
    timestamp: str
    cost: float
    tokens: int


class WorkflowCostMetrics(BaseModel):
    workflow_id: int
    workflow_name: str
    totalCost: float
    totalTokens: int
    promptTokens: int
    completionTokens: int
    executionCount: int
    agents: List[AgentCostBreakdown]
    tools: List[ToolUsageBreakdown]
    executionHistory: List[ExecutionHistoryEntry]
    period_days: int = 30  # Default period for metrics


# =============================================================================
# Workflow Export/Import Endpoints
# =============================================================================

class WorkflowExportOptions(BaseModel):
    """Options for workflow export."""
    include_custom_tools: bool = True
    include_metadata: bool = True


class WorkflowImportRequest(BaseModel):
    """Request body for workflow import."""
    config: dict = Field(..., description="The .langconfig JSON content")
    project_id: int = Field(..., description="Project to import into")
    name_override: Optional[str] = Field(None, description="Optional name override")
    create_custom_tools: bool = Field(True, description="Create custom tools from config")
