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

            # SMART AUTO-EXPORT: Capture old values before applying updates
            # We need to compare old vs new to detect actual changes
            old_blueprint = db_workflow.blueprint
            old_configuration = db_workflow.configuration

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

            # SMART AUTO-EXPORT: Only trigger export if blueprint/config ACTUALLY changed
            # Compare old vs new values to detect meaningful changes
            needs_export = _detect_export_triggering_changes(
                old_blueprint=old_blueprint,
                new_blueprint=db_workflow.blueprint,
                old_configuration=old_configuration,
                new_configuration=db_workflow.configuration,
                workflow=db_workflow
            )

            if needs_export:
                # Mark export as pending within transaction
                db_workflow.export_status = 'pending'
                db_workflow.export_error = None
                logger.info(f"Workflow {workflow_id} needs export, marking as pending")

        # Transaction commits here - workflow update and export status saved together
        db.refresh(db_workflow)

        # Trigger export in background using task queue
        if needs_export:
            try:
                from core.task_queue import task_queue, TaskPriority

                # Enqueue auto-export task (non-blocking)
                task_id = await task_queue.enqueue(
                    "auto_export_workflow",
                    {"workflow_id": workflow_id},
                    priority=TaskPriority.NORMAL,
                    max_retries=3
                )

                logger.info(
                    f"Auto-export task enqueued for workflow {workflow_id} (task_id: {task_id})",
                    extra={
                        "workflow_id": workflow_id,
                        "task_id": task_id
                    }
                )

            except Exception as e:
                # Failed to enqueue task - update export status
                logger.error(
                    f"Failed to enqueue auto-export for workflow {workflow_id}: {e}",
                    exc_info=True
                )
                # Update status to failed
                try:
                    db_workflow.export_status = 'failed'
                    db_workflow.export_error = f"Failed to enqueue export: {str(e)}"
                    db.commit()
                    db.refresh(db_workflow)
                except Exception as update_error:
                    logger.error(f"Failed to update export status: {update_error}")

        logger.info(
            f"Updated workflow {workflow_id}",
            extra={
                "workflow_id": workflow_id,
                "needs_export": needs_export,
                "export_status": db_workflow.export_status
            }
        )

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


def _should_auto_export(workflow: WorkflowProfile) -> bool:
    """
    Determine if workflow needs auto-export.

    Checks if workflow contains DeepAgent nodes that require export.
    DeepAgents are identified by:
    - node.type == 'deepagent'
    - node.data.use_deepagents == True
    - node.data.config.use_deepagents == True
    - node.data.config.middleware (has DeepAgent middleware configured)
    - node.data.deepAgentId (references a DeepAgent template)
    - node.data.agentType == 'deep' (agent type selector)

    Args:
        workflow: WorkflowProfile instance

    Returns:
        bool: True if workflow needs export, False otherwise
    """
    if not workflow.blueprint:
        return False

    # Check for DeepAgent nodes
    if isinstance(workflow.blueprint, dict):
        nodes = workflow.blueprint.get('nodes', [])
        logger.debug(f"Checking {len(nodes)} nodes for DeepAgent indicators")
        for node in nodes:
            node_id = node.get('id', 'unknown')
            node_type = node.get('type', 'unknown')
            node_data = node.get('data', {})
            logger.debug(f"  Node {node_id}: type={node_type}, data_keys={list(node_data.keys())}")
            # Check explicit type
            if node.get('type') == 'deepagent':
                logger.debug(f"Node {node.get('id')} is deepagent type")
                return True

            # Check use_deepagents flag in data
            node_data = node.get('data', {})
            if node_data.get('use_deepagents'):
                logger.debug(f"Node {node.get('id')} has use_deepagents=True in data")
                return True

            # Check if node references a DeepAgent template (deepAgentId)
            if node_data.get('deepAgentId') or node_data.get('deep_agent_id'):
                logger.debug(f"Node {node.get('id')} references DeepAgent template")
                return True

            # Check agentType field (from agent builder)
            agent_type = node_data.get('agentType') or node_data.get('agent_type')
            if agent_type == 'deep':
                logger.debug(f"Node {node.get('id')} has agentType=deep")
                return True

            # Check use_deepagents in config
            config = node_data.get('config', {})
            if config.get('use_deepagents'):
                logger.debug(f"Node {node.get('id')} has use_deepagents=True in config")
                return True

            # Check agentType in config
            config_agent_type = config.get('agentType') or config.get('agent_type')
            if config_agent_type == 'deep':
                logger.debug(f"Node {node.get('id')} has config.agentType=deep")
                return True

            # Check for DeepAgent middleware (todo_list, filesystem, subagent)
            middleware = config.get('middleware', [])
            if middleware:
                # If middleware is configured, it's likely a DeepAgent
                middleware_types = [m.get('type') for m in middleware if isinstance(m, dict)]
                deepagent_middleware = {'todo_list', 'filesystem', 'subagent'}
                if set(middleware_types) & deepagent_middleware:
                    logger.debug(f"Node {node.get('id')} has DeepAgent middleware: {middleware_types}")
                    return True

            # Check for subagents configuration
            if config.get('subagents') or node_data.get('subagents'):
                logger.debug(f"Node {node.get('id')} has subagents configured")
                return True

    return False


def _detect_export_triggering_changes(
    old_blueprint: Optional[dict],
    new_blueprint: Optional[dict],
    old_configuration: Optional[dict],
    new_configuration: Optional[dict],
    workflow: WorkflowProfile
) -> bool:
    """
    Detect if blueprint or configuration changes require workflow export.

    Smart export triggering:
    - Only triggers if workflow has DeepAgent nodes
    - Only triggers if blueprint or configuration ACTUALLY changed
    - Prevents unnecessary exports when updating metadata fields (name, description, etc.)

    Args:
        old_blueprint: Previous blueprint value
        new_blueprint: New blueprint value
        old_configuration: Previous configuration value
        new_configuration: New configuration value
        workflow: WorkflowProfile instance (for checking if export is needed)

    Returns:
        bool: True if export should be triggered, False otherwise
    """
    # First check: Does this workflow even need export? (has DeepAgent nodes)
    if not _should_auto_export(workflow):
        logger.debug(f"Workflow {workflow.id} does not have DeepAgent nodes, skipping export")
        return False

    # Second check: Did blueprint actually change?
    blueprint_changed = False
    if old_blueprint != new_blueprint:
        blueprint_changed = True
        logger.info(
            f"Workflow {workflow.id} blueprint changed, export needed",
            extra={
                "workflow_id": workflow.id,
                "old_blueprint_keys": list(old_blueprint.keys()) if old_blueprint else [],
                "new_blueprint_keys": list(new_blueprint.keys()) if new_blueprint else []
            }
        )

    # Third check: Did configuration actually change?
    configuration_changed = False
    if old_configuration != new_configuration:
        configuration_changed = True
        logger.info(
            f"Workflow {workflow.id} configuration changed, export needed",
            extra={
                "workflow_id": workflow.id,
                "old_config_keys": list(old_configuration.keys()) if old_configuration else [],
                "new_config_keys": list(new_configuration.keys()) if new_configuration else []
            }
        )

    # Trigger export only if something actually changed
    if blueprint_changed or configuration_changed:
        logger.info(
            f"Export triggered for workflow {workflow.id}",
            extra={
                "blueprint_changed": blueprint_changed,
                "configuration_changed": configuration_changed
            }
        )
        return True

    # No meaningful changes detected
    logger.debug(
        f"No export-triggering changes for workflow {workflow.id}",
        extra={"blueprint_changed": False, "configuration_changed": False}
    )
    return False


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


# Helper function for auto-exporting DeepAgent workflows
async def auto_export_deepagent_workflow(workflow: WorkflowProfile, db: Session):
    """
    Automatically generate exports for workflows that contain DeepAgents.

    This checks if the workflow contains any DeepAgent configurations and
    generates both standalone and .langconfig exports automatically.
    """
    # Check if workflow has DeepAgent configurations in its blueprint
    if not workflow.blueprint:
        return

    # Look for DeepAgent nodes in the blueprint using same logic as _should_auto_export
    has_deepagent = False
    deepagent_nodes = []

    if isinstance(workflow.blueprint, dict):
        nodes = workflow.blueprint.get('nodes', [])
        for node in nodes:
            node_data = node.get('data', {})
            config = node_data.get('config', {})

            # Check all DeepAgent indicators
            is_deepagent = (
                node.get('type') == 'deepagent' or
                node_data.get('use_deepagents') or
                node_data.get('deepAgentId') or
                node_data.get('deep_agent_id') or
                node_data.get('agentType') == 'deep' or
                node_data.get('agent_type') == 'deep' or
                config.get('use_deepagents') or
                config.get('agentType') == 'deep' or
                config.get('agent_type') == 'deep' or
                config.get('subagents') or
                node_data.get('subagents')
            )

            # Also check middleware
            middleware = config.get('middleware', [])
            if middleware:
                middleware_types = [m.get('type') for m in middleware if isinstance(m, dict)]
                deepagent_middleware = {'todo_list', 'filesystem', 'subagent'}
                if set(middleware_types) & deepagent_middleware:
                    is_deepagent = True

            if is_deepagent:
                has_deepagent = True
                deepagent_nodes.append(node)

    if not has_deepagent:
        return

    logger.info(f"Auto-exporting DeepAgent workflow: {workflow.name}")

    # Import here to avoid circular dependencies
    from models.deep_agent import DeepAgentTemplate, DeepAgentConfig
    from services.export_service import ExportService

    # For each DeepAgent node, generate exports
    for node in deepagent_nodes:
        try:
            # Get agent configuration from node data
            agent_data = node.get('data', {})

            # Check if this agent is already in the database
            agent_name = agent_data.get('name', f"Workflow Agent - {workflow.name}")
            agent = db.query(DeepAgentTemplate).filter(
                DeepAgentTemplate.name == agent_name
            ).first()

            if agent:
                # Parse configuration
                config = DeepAgentConfig(**agent.config)

                # Generate both export formats
                try:
                    # Standalone export
                    await ExportService.export_standalone(agent, config)
                    logger.info(f"Generated standalone export for {agent.name}")
                except Exception as e:
                    logger.error(f"Standalone export failed: {e}")

                try:
                    # LangConfig export
                    await ExportService.export_langconfig(agent, config)
                    logger.info(f"Generated .langconfig export for {agent.name}")
                except Exception as e:
                    logger.error(f"LangConfig export failed: {e}")

        except Exception as e:
            logger.error(f"Error exporting DeepAgent node: {e}")
            continue

    logger.info(f"Auto-export complete for workflow: {workflow.name}")


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
