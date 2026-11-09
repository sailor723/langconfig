import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from db.database import get_db
from models.workflow import WorkflowProfile
from core.utils.http import content_disposition
from .schemas import (
    WorkflowExportOptions,
    WorkflowImportRequest,
)

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workflows" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workflows"])


@router.post("/{workflow_id}/export/package")
async def export_workflow_package(
    workflow_id: int,
    export_mode: str = "standard",
    db: Session = Depends(get_db)
):
    """
    Export workflow as a complete, executable Python package (ZIP).

    Returns a ZIP file containing all necessary code, configuration,
    and dependencies to run the workflow standalone.

    Uses LangChain v1.1 / LangGraph v1.x / DeepAgents v2.x patterns.

    Args:
        workflow_id: ID of the workflow to export
        export_mode: Export mode - 'standard' (fixed config) or 'configurable' (runtime config UI)
    """
    from core.codegen.workflow_exporter import ExecutableWorkflowExporter

    # Get workflow
    workflow = db.query(WorkflowProfile).filter(
        WorkflowProfile.id == workflow_id
    ).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Convert to dict for exporter
    workflow_dict = {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "strategy_type": workflow.strategy_type.value if hasattr(workflow.strategy_type, "value") else str(workflow.strategy_type),
        "configuration": workflow.configuration or {},
        "blueprint": workflow.blueprint or {},
    }

    # DEBUG: Log what's being passed to the exporter
    config = workflow.configuration or {}
    nodes = config.get("nodes", [])
    logger.info(f"[EXPORT DEBUG] Workflow {workflow_id} has {len(nodes)} nodes in configuration")
    logger.info(f"[EXPORT DEBUG] Export mode: {export_mode}")
    for i, node in enumerate(nodes[:3]):  # First 3 nodes
        node_config = node.get("config", {})
        logger.info(f"[EXPORT DEBUG] Node {i} ({node.get('id')}): config.model={node_config.get('model')}")
        logger.info(f"[EXPORT DEBUG] Node {i} ({node.get('id')}): config.system_prompt={node_config.get('system_prompt', '')[:50]}...")

    try:
        # Generate export with specified mode
        exporter = ExecutableWorkflowExporter(
            workflow=workflow_dict,
            project_id=workflow.project_id or 0,
            export_mode=export_mode
        )

        zip_bytes = await exporter.export_to_zip()

        # Return as downloadable file
        safe_name = workflow.name.lower().replace(" ", "_").replace("-", "_")
        filename = f"workflow_{safe_name}_{workflow_id}.zip"

        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": content_disposition(filename)
            }
        )

    except Exception as e:
        logger.error(f"Failed to export workflow {workflow_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )


