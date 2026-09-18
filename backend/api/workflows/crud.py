import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional

from db.database import get_db
from models.workflow import WorkflowProfile, WorkflowVersion, WorkflowExecution
from models.execution_event import ExecutionEvent
from models.core import Task
from core.codegen.langgraph import LangGraphCodeGenerator
from core.session_manager import managed_transaction
from core.validation import ValidationError as CoreValidationError, PermissionError as CorePermissionError
from core.model_validators import workflow_validator
from core.versioning import check_version_conflict, format_lock_version_error
from .schemas import (
    ValidatePathRequest,
    ValidatePathResponse,
    WorkflowProfileCreate,
    WorkflowProfileResponse,
    WorkflowProfileUpdate,
)

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workflows" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workflows"])


@router.get("/", response_model=List[WorkflowProfileResponse])
async def list_workflows(
    skip: int = 0,
    limit: int = 100,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List all workflow profiles, optionally filtered by project"""
    query = db.query(WorkflowProfile)

    if project_id is not None:
        query = query.filter(WorkflowProfile.project_id == project_id)

    workflows = query.order_by(desc(WorkflowProfile.updated_at)).offset(skip).limit(limit).all()
    return workflows


@router.get("/{workflow_id}", response_model=WorkflowProfileResponse)
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific workflow profile by ID"""
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("/", response_model=WorkflowProfileResponse, status_code=201)
async def create_workflow(
    workflow: WorkflowProfileCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new workflow profile.

    Checks for duplicate names (case-insensitive) to prevent confusion.

    Raises:
        HTTPException 400: Workflow with this name already exists
        HTTPException 500: Server error
    """
    try:
        with managed_transaction(db, "create_workflow"):
            # QUICK WIN: Case-insensitive duplicate check
            # Prevents "MyWorkflow" and "myworkflow" as separate workflows
            existing = db.query(WorkflowProfile).filter(
                WorkflowProfile.name.ilike(workflow.name)
            ).first()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Workflow with name '{workflow.name}' already exists (case-insensitive match)"
                )

            db_workflow = WorkflowProfile(**workflow.model_dump())
            db.add(db_workflow)

        # Transaction commits here
        db.refresh(db_workflow)

        logger.info(
            f"Created workflow: {db_workflow.name}",
            extra={"workflow_id": db_workflow.id, "workflow_name": db_workflow.name}
        )

        return db_workflow

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        # Unexpected error
        logger.error(f"Failed to create workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create workflow: {str(e)}"
        )


@router.patch("/{workflow_id}", response_model=WorkflowProfileResponse)
async def update_workflow(
    workflow_id: int,
    workflow: WorkflowProfileUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing workflow profile.

    Uses transaction safety to ensure workflow update succeeds even if auto-export fails.
    Export status is tracked in the database.

    Raises:
        HTTPException 404: Workflow not found
        HTTPException 500: Server error
    """
    try:
        with managed_transaction(db, f"update_workflow_{workflow_id}") as tx:
            db_workflow = db.query(WorkflowProfile).filter(
                WorkflowProfile.id == workflow_id
            ).first()

            if not db_workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # Optimistic locking - check lock version conflict
            if workflow.lock_version is not None:
                if check_version_conflict(db_workflow, workflow.lock_version):
                    error_msg = format_lock_version_error(
                        "Workflow",
                        workflow_id,
                        workflow.lock_version,
                        db_workflow.lock_version
                    )
                    raise HTTPException(status_code=409, detail=error_msg)

            # Update only provided fields
            update_data = workflow.model_dump(exclude_unset=True)

            # DEBUG: Log what we're receiving in configuration
            if "configuration" in update_data:
                config = update_data["configuration"]
                if isinstance(config, dict) and "nodes" in config:
                    for node in config.get("nodes", []):
                        node_id = node.get("id", "unknown")
                        node_config = node.get("config", {})
                        mcp_tools = node_config.get("mcp_tools", [])
                        cli_tools = node_config.get("cli_tools", [])
                        custom_tools = node_config.get("custom_tools", [])
                        logger.info(f"[PATCH /workflows/{workflow_id}] Node {node_id}:")
                        logger.info(f"  - mcp_tools: {mcp_tools}")
                        logger.info(f"  - cli_tools: {cli_tools}")
                        logger.info(f"  - custom_tools: {custom_tools}")
                        logger.info(f"  - config keys received: {list(node_config.keys())}")

            # CRITICAL FIX: Validate and filter updates using validation framework
            # This prevents unauthorized field updates (e.g., id, created_at, usage_count)
            try:
                validated_data = workflow_validator.validate_update(
                    update_data,
                    strict=True  # Reject unknown fields
                )
            except CoreValidationError as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation failed for field '{e.field}': {e.message}"
                )
            except CorePermissionError as e:
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied for field '{e.field}': requires {e.permission.value} level"
                )

            # Apply validated updates (safe - only allowed fields)
            workflow_validator.apply_update(db_workflow, validated_data)

        # Transaction commits here
        db.refresh(db_workflow)

        logger.info(f"Updated workflow {workflow_id}", extra={"workflow_id": workflow_id})

        return db_workflow

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        # Unexpected error
        logger.error(
            f"Failed to update workflow {workflow_id}: {e}",
            exc_info=True,
            extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update workflow: {str(e)}"
        )


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a workflow profile and all related data.

    Cascades to delete:
    - Tasks associated with the workflow
    - Execution events from those tasks
    - Generated files in the workspace

    Note: Memory is managed by LangGraph's store system (per-thread)
    and doesn't require explicit cleanup.
    """
    db_workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not db_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        # Delete related data in order of dependencies

        # 1. Delete execution events for all tasks in this workflow
        db.query(ExecutionEvent).filter(
            ExecutionEvent.workflow_id == workflow_id
        ).delete(synchronize_session=False)

        # 2. Delete tasks associated with this workflow
        # Use workflow_profile_id (the actual foreign key), not workflow_id (tracking string)
        db.query(Task).filter(
            Task.workflow_profile_id == workflow_id
        ).delete(synchronize_session=False)

        # 3. Memory is stored in LangGraph's store system (not a separate table)
        # It's managed per-thread and doesn't need explicit cleanup

        # 4. Delete workflow executions (must come before workflow versions)
        db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == workflow_id
        ).delete(synchronize_session=False)

        # 5. Delete workflow versions
        db.query(WorkflowVersion).filter(
            WorkflowVersion.workflow_id == workflow_id
        ).delete(synchronize_session=False)

        # 6. Finally, delete the workflow itself
        db.delete(db_workflow)

        db.commit()
        logger.info(f"Successfully deleted workflow {workflow_id} and all related data")
        return None

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete workflow {workflow_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete workflow: {str(e)}"
        )


@router.get("/{workflow_id}/code", response_class=PlainTextResponse)
async def generate_workflow_code(
    workflow_id: int,
    db: Session = Depends(get_db)
):
    """Generate standalone LangGraph Python code for a workflow"""
    # Get the workflow
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Convert workflow to dict
    workflow_dict = {
        'id': workflow.id,
        'name': workflow.name,
        'description': f'Auto-generated workflow from {workflow.name}',
        'strategy_type': workflow.strategy_type.value if hasattr(workflow.strategy_type, 'value') else str(workflow.strategy_type),
        'blueprint': workflow.blueprint or {},
        'configuration': workflow.configuration or {}
    }

    # Generate code
    generator = LangGraphCodeGenerator()
    generated_code = generator.generate_from_workflow(workflow_dict)

    return generated_code


# Blocked path patterns for security
BLOCKED_PATH_PATTERNS = [
    # Windows system directories
    r'^[A-Za-z]:\\Windows',
    r'^[A-Za-z]:\\Program Files',
    r'^[A-Za-z]:\\Program Files \(x86\)',
    # Unix system directories
    r'^/usr',
    r'^/bin',
    r'^/sbin',
    r'^/etc',
    r'^/var(?!/tmp)',  # Allow /var/tmp but block other /var paths
    r'^/root',
    r'^/boot',
    r'^/sys',
    r'^/proc',
    # Project directories (prevent writing into codebase)
    r'langconfig[\\/]backend',
    r'langconfig[\\/]src',
    r'[\\/]node_modules[\\/]',
    r'[\\/]\.git[\\/]',
]


def _validate_output_path(path: str) -> tuple[bool, str, Optional[str]]:
    """
    Validate a custom output path for security and writability.

    Returns:
        (is_valid, error_message, resolved_path)
    """
    from pathlib import Path as PathLib
    import os
    import re

    if not path or not path.strip():
        return False, "Path cannot be empty", None

    # Resolve to absolute path
    try:
        resolved = PathLib(path).resolve()
        resolved_str = str(resolved)
    except Exception as e:
        return False, f"Invalid path format: {str(e)}", None

    # Check for blocked patterns
    for pattern in BLOCKED_PATH_PATTERNS:
        if re.search(pattern, resolved_str, re.IGNORECASE):
            return False, f"Access to this directory is not allowed for security reasons", None

    # Check for path traversal attempts
    if '..' in path:
        return False, "Path traversal (..) is not allowed", None

    # Check if path can be created or exists
    try:
        if resolved.exists():
            if not resolved.is_dir():
                return False, "Path exists but is not a directory", None
            # Check write permissions
            test_file = resolved / ".langconfig_write_test"
            try:
                test_file.touch()
                test_file.unlink()
            except PermissionError:
                return False, "No write permission for this directory", None
            except Exception as e:
                return False, f"Cannot write to directory: {str(e)}", None
        else:
            # Try to create parent directories
            try:
                resolved.mkdir(parents=True, exist_ok=True)
                # Clean up if we just created it
                if not any(resolved.iterdir()):
                    resolved.rmdir()
            except PermissionError:
                return False, "No permission to create this directory", None
            except Exception as e:
                return False, f"Cannot create directory: {str(e)}", None

    except Exception as e:
        return False, f"Path validation error: {str(e)}", None

    return True, "", resolved_str


@router.post("/{workflow_id}/validate-output-path", response_model=ValidatePathResponse)
async def validate_output_path(
    workflow_id: int,
    request: ValidatePathRequest,
    db: Session = Depends(get_db)
):
    """
    Validate a custom output path for a workflow.

    Checks that the path:
    - Is not a system directory
    - Is not inside the project codebase
    - Can be created or already exists
    - Has write permissions

    Returns validation result with resolved absolute path.
    """
    from pathlib import Path as PathLib

    # Verify workflow exists
    workflow = db.query(WorkflowProfile).filter(
        WorkflowProfile.id == workflow_id
    ).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Validate the path
    is_valid, error, resolved_path = _validate_output_path(request.path)

    if is_valid:
        resolved = PathLib(resolved_path)
        return ValidatePathResponse(
            valid=True,
            resolved_path=resolved_path,
            error=None,
            writable=True,
            exists=resolved.exists()
        )
    else:
        return ValidatePathResponse(
            valid=False,
            resolved_path=None,
            error=error,
            writable=False,
            exists=False
        )
