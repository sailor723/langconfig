import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from typing import List

from db.database import get_db
from models.workflow import WorkflowProfile, WorkflowVersion
from core.session_manager import managed_transaction
from .schemas import (
    VersionComparisonResponse,
    WorkflowVersionCreate,
    WorkflowVersionResponse,
)

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workflows" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workflows"])


# Versioning Endpoints

@router.post("/{workflow_id}/versions", response_model=WorkflowVersionResponse, status_code=201)
async def create_workflow_version(
    workflow_id: int,
    version_data: WorkflowVersionCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new version of a workflow.

    Automatically increments version number and marks this as the current version.
    Uses row-level locking to prevent race conditions in concurrent version creation.

    Raises:
        HTTPException 404: Workflow not found
        HTTPException 409: Version conflict (concurrent creation detected)
        HTTPException 500: Server error
    """
    try:
        with managed_transaction(db, f"create_version_{workflow_id}") as tx:
            # Check if workflow exists AND lock the row to prevent concurrent version creation
            workflow = db.query(WorkflowProfile).filter(
                WorkflowProfile.id == workflow_id
            ).with_for_update().first()

            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")

            # CRITICAL: Get the next version number with row-level lock
            # This prevents concurrent requests from reading the same version number
            last_version = db.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow_id
            ).order_by(desc(WorkflowVersion.version_number)).with_for_update().first()

            next_version_number = (last_version.version_number + 1) if last_version else 1

            # Unmark all other versions as current (still within lock)
            db.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.is_current == True
            ).update({"is_current": False}, synchronize_session=False)

            # Create new version
            new_version = WorkflowVersion(
                workflow_id=workflow_id,
                version_number=next_version_number,
                config_snapshot=version_data.config_snapshot,
                notes=version_data.notes,
                created_by=version_data.created_by,
                is_current=True
            )

            db.add(new_version)

        # Transaction commits here and releases locks
        db.refresh(new_version)

        logger.info(
            f"Created version {next_version_number} for workflow {workflow_id}",
            extra={
                "workflow_id": workflow_id,
                "version_number": next_version_number,
                "version_id": new_version.id
            }
        )

        return new_version

    except HTTPException:
        # Re-raise HTTP exceptions (they're intentional)
        raise

    except IntegrityError as e:
        # Unique constraint violation - concurrent version creation detected
        logger.error(
            f"Version conflict for workflow {workflow_id}: {e}",
            extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=409,
            detail="Version conflict detected. Another version was created concurrently. Please retry."
        )

    except Exception as e:
        # Unexpected error
        logger.error(
            f"Failed to create version for workflow {workflow_id}: {e}",
            exc_info=True,
            extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create workflow version: {str(e)}"
        )


@router.get("/{workflow_id}/versions", response_model=List[WorkflowVersionResponse])
async def list_workflow_versions(
    workflow_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    List all versions of a workflow.

    Returns versions in reverse chronological order (newest first).
    """
    # Check if workflow exists
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    versions = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id
    ).order_by(desc(WorkflowVersion.version_number)).offset(skip).limit(limit).all()

    return versions


@router.get("/{workflow_id}/versions/{version_number}", response_model=WorkflowVersionResponse)
async def get_workflow_version(
    workflow_id: int,
    version_number: int,
    db: Session = Depends(get_db)
):
    """Get a specific version of a workflow."""
    version = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.version_number == version_number
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return version


@router.get("/{workflow_id}/versions/{v1}/compare/{v2}", response_model=VersionComparisonResponse)
async def compare_workflow_versions(
    workflow_id: int,
    v1: int,
    v2: int,
    db: Session = Depends(get_db)
):
    """
    Compare two versions of a workflow.

    Returns both versions and a structured diff highlighting changes.
    """
    version1 = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.version_number == v1
    ).first()

    version2 = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.version_number == v2
    ).first()

    if not version1 or not version2:
        raise HTTPException(status_code=404, detail="One or both versions not found")

    # Generate diff (simple approach - can be enhanced with proper diff algorithm)
    diff = _generate_config_diff(version1.config_snapshot, version2.config_snapshot)

    return {
        "version1": version1,
        "version2": version2,
        "diff": diff
    }


# Helper Functions

def _generate_config_diff(config1: dict, config2: dict) -> dict:
    """
    Generate a comprehensive nested diff between two workflow configurations.

    Uses DeepDiff library for accurate detection of changes at any depth,
    including nested nodes, edges, and configuration changes.

    Args:
        config1: First configuration (usually older version)
        config2: Second configuration (usually newer version)

    Returns:
        dict: Structured diff with added, removed, modified, type_changes, and summary

    Example:
        Old: {"nodes": [{"id": "1", "name": "Agent 1", "config": {"model": "gpt-4"}}]}
        New: {"nodes": [{"id": "1", "name": "Agent 1", "config": {"model": "gpt-4o"}}]}
        Diff detects: nodes[0].config.model changed from "gpt-4" to "gpt-4o"
    """
    try:
        from deepdiff import DeepDiff

        # Generate deep diff with comprehensive settings
        deep_diff = DeepDiff(
            config1,
            config2,
            ignore_order=False,  # Order matters for nodes/edges
            report_repetition=False,
            verbose_level=2,  # Detailed diff information
            view='tree'  # Tree view for better navigation
        )

        # Convert DeepDiff output to our API format (backward compatible)
        diff = {
            "added": {},
            "removed": {},
            "modified": {},
            "type_changes": {},
            "summary": {}
        }

        # Extract added items
        if 'dictionary_item_added' in deep_diff:
            for item in deep_diff['dictionary_item_added']:
                path = str(item.path(output_format='list'))
                diff["added"][path] = item.t2 if hasattr(item, 't2') else None

        # Extract removed items
        if 'dictionary_item_removed' in deep_diff:
            for item in deep_diff['dictionary_item_removed']:
                path = str(item.path(output_format='list'))
                diff["removed"][path] = item.t1 if hasattr(item, 't1') else None

        # Extract modified values
        if 'values_changed' in deep_diff:
            for item in deep_diff['values_changed']:
                path = str(item.path(output_format='list'))
                diff["modified"][path] = {
                    "old": item.t1 if hasattr(item, 't1') else None,
                    "new": item.t2 if hasattr(item, 't2') else None
                }

        # Extract type changes
        if 'type_changes' in deep_diff:
            for item in deep_diff['type_changes']:
                path = str(item.path(output_format='list'))
                diff["type_changes"][path] = {
                    "old_type": str(type(item.t1).__name__) if hasattr(item, 't1') else None,
                    "new_type": str(type(item.t2).__name__) if hasattr(item, 't2') else None,
                    "old_value": item.t1 if hasattr(item, 't1') else None,
                    "new_value": item.t2 if hasattr(item, 't2') else None
                }

        # Add summary statistics
        diff["summary"] = {
            "total_changes": (
                len(diff["added"]) +
                len(diff["removed"]) +
                len(diff["modified"]) +
                len(diff["type_changes"])
            ),
            "items_added": len(diff["added"]),
            "items_removed": len(diff["removed"]),
            "items_modified": len(diff["modified"]),
            "type_changes": len(diff["type_changes"]),
            "has_changes": bool(
                diff["added"] or
                diff["removed"] or
                diff["modified"] or
                diff["type_changes"]
            )
        }

        logger.info(
            f"Generated deep diff: {diff['summary']['total_changes']} changes detected",
            extra={"summary": diff["summary"]}
        )

        return diff

    except ImportError:
        # Fallback to simple diff if deepdiff not installed
        logger.warning("deepdiff not installed, using simple diff. Install with: pip install deepdiff")

        diff = {
            "added": {},
            "removed": {},
            "modified": {},
            "unchanged_keys": []
        }

        all_keys = set(config1.keys()) | set(config2.keys())

        for key in all_keys:
            if key not in config1:
                diff["added"][key] = config2[key]
            elif key not in config2:
                diff["removed"][key] = config1[key]
            elif config1[key] != config2[key]:
                diff["modified"][key] = {
                    "old": config1[key],
                    "new": config2[key]
                }
            else:
                diff["unchanged_keys"].append(key)

        return diff
