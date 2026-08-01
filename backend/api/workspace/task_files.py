import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db.database import get_db
from services.workspace_manager import get_workspace_manager
from models.core import Task
from .schemas import FileContentResponse, RenameFileRequest, WorkspaceFilesResponse

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workspace" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workspace"])


@router.get("/tasks/{task_id}/files", response_model=WorkspaceFilesResponse)
async def list_task_files(
    task_id: int,
    db: Session = Depends(get_db)
):
    """
    List all files created by a task.

    Files are organized in: outputs/project_X/workflow_Y/task_Z/
    """
    # Get task to find workflow_id and project_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_mgr = get_workspace_manager()

    try:
        files = workspace_mgr.list_task_files(
            project_id=task.project_id,
            workflow_id=task.workflow_id,
            task_id=task.id
        )

        workspace_path = str(workspace_mgr.get_task_workspace(
            project_id=task.project_id,
            workflow_id=task.workflow_id,
            task_id=task.id
        ))

        return WorkspaceFilesResponse(
            task_id=task.id,
            workflow_id=task.workflow_id,
            project_id=task.project_id,
            files=files,
            total_files=len(files),
            workspace_path=workspace_path
        )
    except Exception as e:
        logger.error(f"Error listing task files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/files/{filename}")
async def download_task_file(
    task_id: int,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    Download a specific file from a task's workspace.

    Security: Path traversal attempts are blocked.
    """
    # Get task to find workflow_id and project_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_mgr = get_workspace_manager()

    file_path = workspace_mgr.get_file_path(
        project_id=task.project_id,
        workflow_id=task.workflow_id,
        task_id=task.id,
        filename=filename
    )

    if not file_path:
        raise HTTPException(
            status_code=404,
            detail="File not found or invalid path"
        )

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/workflows/{workflow_id}/files")
async def list_workflow_files(
    workflow_id: int,
    db: Session = Depends(get_db)
):
    """
    List all files from all tasks in a workflow.

    Returns aggregated view of all files created during workflow execution.
    """
    from models.workflow import WorkflowProfile

    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get all tasks for this workflow
    # Note: Task.workflow_id is a String column, so cast to string for comparison
    tasks = db.query(Task).filter(Task.workflow_id == str(workflow_id)).all()

    workspace_mgr = get_workspace_manager()
    all_files = []

    for task in tasks:
        try:
            files = workspace_mgr.list_task_files(
                project_id=task.project_id,
                workflow_id=task.workflow_id,
                task_id=task.id
            )

            # Add task_id to each file for context
            for file_info in files:
                file_info['task_id'] = task.id

            all_files.extend(files)
        except Exception as e:
            logger.warning(f"Could not list files for task {task.id}: {e}")
            continue

    # Sort by modification time
    all_files.sort(key=lambda x: x['modified_at'], reverse=True)

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.name,
        "files": all_files,
        "total_files": len(all_files),
        "total_tasks": len(tasks)
    }


# =============================================================================
# File Content & Preview
# =============================================================================

@router.get("/tasks/{task_id}/files/{filename}/content", response_model=FileContentResponse)
async def get_file_content(
    task_id: int,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    Get file content for preview.

    Returns text content for text files, or binary indicator for non-text files.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_mgr = get_workspace_manager()

    content_data = workspace_mgr.get_file_content(
        project_id=task.project_id,
        workflow_id=task.workflow_id,
        task_id=task.id,
        filename=filename
    )

    if not content_data:
        raise HTTPException(status_code=404, detail="File not found")

    return FileContentResponse(
        filename=filename,
        content=content_data.get("content"),
        mime_type=content_data.get("mime_type", "text/plain"),
        is_binary=content_data.get("is_binary", False),
        truncated=content_data.get("truncated", False),
        size_bytes=content_data.get("size_bytes", 0)
    )


# =============================================================================
# Rename & Delete
# =============================================================================

@router.put("/tasks/{task_id}/files/{filename}")
async def rename_file(
    task_id: int,
    filename: str,
    request: RenameFileRequest,
    db: Session = Depends(get_db)
):
    """
    Rename a file in task workspace.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_mgr = get_workspace_manager()

    success = workspace_mgr.rename_file(
        project_id=task.project_id,
        workflow_id=task.workflow_id,
        task_id=task.id,
        old_name=filename,
        new_name=request.new_name
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not rename file. It may not exist, or target name already exists."
        )

    logger.info(f"Renamed file in task {task_id}: {filename} -> {request.new_name}")

    return {
        "status": "success",
        "old_name": filename,
        "new_name": request.new_name
    }


@router.delete("/tasks/{task_id}/files/{filename}")
async def delete_file(
    task_id: int,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    Delete a file from task workspace.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_mgr = get_workspace_manager()

    success = workspace_mgr.delete_file(
        project_id=task.project_id,
        workflow_id=task.workflow_id,
        task_id=task.id,
        filename=filename
    )

    if not success:
        raise HTTPException(status_code=404, detail="File not found or could not be deleted")

    logger.info(f"Deleted file from task {task_id}: {filename}")

    return {"status": "success", "filename": filename}
