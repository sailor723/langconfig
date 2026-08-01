import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from db.database import get_db

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workspace" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workspace"])

# Shared response models stay in routes.py (the parent router module).
# Imported AFTER `router` is defined so a direct import of this module cannot
# deadlock on the routes.py <-> sub-module circular import.
from .routes import (
    FileDiffResponse,
    FileTreeResponse,
    FileVersionResponse,
    FileVersionsResponse,
    GroupedFilesResponse,
    TreeNode,
)


@router.get("/files/tree", response_model=FileTreeResponse)
async def get_file_tree(
    workflow_id: int | None = None,
    db: Session = Depends(get_db)
):
    """
    Get a hierarchical file tree for folder navigation.

    Returns files organized by workflow/task structure.
    If workflow_id is provided, returns tree for that workflow only.
    """
    from models.workspace_file import WorkspaceFile
    from models.workflow import WorkflowProfile
    from models.core import Task

    query = db.query(WorkspaceFile)

    if workflow_id is not None:
        query = query.filter(WorkspaceFile.workflow_id == workflow_id)

    files = query.order_by(WorkspaceFile.created_at.desc()).all()

    # Build tree structure
    tree = []
    total_files = len(files)

    # Group files by workflow then task
    workflow_groups: dict = {}

    for file in files:
        wf_id = file.workflow_id or 0
        task_id = file.task_id or 0

        if wf_id not in workflow_groups:
            # Get workflow name
            wf_name = file.workflow_name or "Standalone Files"
            if wf_id and not file.workflow_name:
                wf = db.query(WorkflowProfile).filter(WorkflowProfile.id == wf_id).first()
                wf_name = wf.name if wf else f"Workflow {wf_id}"

            workflow_groups[wf_id] = {
                'name': wf_name,
                'tasks': {}
            }

        if task_id not in workflow_groups[wf_id]['tasks']:
            # Get task name
            task_name = f"Task {task_id}" if task_id else "Unassigned"
            if task_id:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task and task.description:
                    # Use first 50 chars of description as task name
                    task_name = task.description[:50] + ("..." if len(task.description) > 50 else "")

            workflow_groups[wf_id]['tasks'][task_id] = {
                'name': task_name,
                'files': []
            }

        workflow_groups[wf_id]['tasks'][task_id]['files'].append(file)

    # Convert to TreeNode structure
    for wf_id, wf_data in workflow_groups.items():
        task_nodes = []

        for task_id, task_data in wf_data['tasks'].items():
            file_nodes = [
                TreeNode(
                    id=f"file-{f.id}",
                    name=f.filename,
                    type='file',
                    path=f.file_path,
                    metadata={
                        'id': f.id,
                        'size_bytes': f.size_bytes,
                        'extension': f.extension,
                        'agent_label': f.agent_label,
                        'created_at': f.created_at.isoformat() if f.created_at else None
                    }
                )
                for f in task_data['files']
            ]

            task_nodes.append(TreeNode(
                id=f"task-{task_id}",
                name=task_data['name'],
                type='task',
                children=file_nodes,
                metadata={
                    'task_id': task_id if task_id else None,
                    'file_count': len(file_nodes)
                }
            ))

        tree.append(TreeNode(
            id=f"workflow-{wf_id}",
            name=wf_data['name'],
            type='workflow',
            children=task_nodes,
            metadata={
                'workflow_id': wf_id if wf_id else None,
                'task_count': len(task_nodes),
                'file_count': sum(len(t.children or []) for t in task_nodes)
            }
        ))

    return FileTreeResponse(tree=tree, total_files=total_files)


@router.get("/files/{file_id}/versions", response_model=FileVersionsResponse)
async def get_file_versions(
    file_id: int,
    db: Session = Depends(get_db)
):
    """
    Get version history for a specific file.

    Returns all versions with their metadata for timeline display.
    """
    from models.workspace_file import WorkspaceFile
    from models.file_version import FileVersion

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    versions = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id
    ).order_by(FileVersion.version_number.desc()).all()

    version_responses = [
        FileVersionResponse(
            id=v.id,
            version_number=v.version_number,
            operation=v.operation,
            change_summary=v.change_summary,
            agent_label=v.agent_label,
            node_id=v.node_id,
            lines_added=v.lines_added,
            lines_removed=v.lines_removed,
            created_at=v.created_at.isoformat() if v.created_at else None,
            has_content_snapshot=v.content_snapshot is not None
        )
        for v in versions
    ]

    return FileVersionsResponse(
        file_id=file_id,
        filename=file_record.filename,
        versions=version_responses,
        total_versions=len(versions)
    )


@router.get("/files/{file_id}/diff", response_model=FileDiffResponse)
async def get_file_diff(
    file_id: int,
    v1: int,
    v2: int,
    db: Session = Depends(get_db)
):
    """
    Get diff between two versions of a file.

    Args:
        file_id: The file ID
        v1: First version number (usually older)
        v2: Second version number (usually newer)

    Returns:
        Unified diff, side-by-side view, and statistics
    """
    from models.workspace_file import WorkspaceFile
    from models.file_version import FileVersion
    from services.diff_service import generate_unified_diff, generate_side_by_side, get_diff_stats

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Get both versions
    version1 = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id,
        FileVersion.version_number == v1
    ).first()

    version2 = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id,
        FileVersion.version_number == v2
    ).first()

    if not version1 or not version2:
        raise HTTPException(status_code=404, detail="Version not found")

    # Get content for comparison
    # For edit operations, we need to reconstruct content
    old_content = ""
    new_content = ""

    if version1.content_snapshot:
        old_content = version1.content_snapshot
    elif version1.operation == "edit":
        # For edits, we'd need to reconstruct from the chain
        # For now, use an empty string if no snapshot
        old_content = ""

    if version2.content_snapshot:
        new_content = version2.content_snapshot
    elif version2.operation == "edit" and version2.old_string and version2.new_string:
        # Apply the edit to previous content
        if old_content:
            new_content = old_content.replace(version2.old_string, version2.new_string, 1)
        else:
            new_content = ""

    # Generate diffs
    unified = generate_unified_diff(old_content, new_content, file_record.filename)
    side_by_side = generate_side_by_side(old_content, new_content)
    stats = get_diff_stats(old_content, new_content)

    return FileDiffResponse(
        file_id=file_id,
        filename=file_record.filename,
        v1=v1,
        v2=v2,
        unified_diff=unified,
        side_by_side=side_by_side,
        stats=stats
    )


@router.get("/files/{file_id}/version/{version_number}/content")
async def get_version_content(
    file_id: int,
    version_number: int,
    db: Session = Depends(get_db)
):
    """
    Get the content of a specific file version.

    Returns the full content snapshot if available.
    """
    from models.workspace_file import WorkspaceFile
    from models.file_version import FileVersion

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    version = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id,
        FileVersion.version_number == version_number
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if not version.content_snapshot:
        return {
            "file_id": file_id,
            "version_number": version_number,
            "has_content": False,
            "content": None,
            "message": "No content snapshot available for this version"
        }

    return {
        "file_id": file_id,
        "version_number": version_number,
        "has_content": True,
        "content": version.content_snapshot,
        "operation": version.operation,
        "agent_label": version.agent_label
    }


@router.get("/workflows/{workflow_id}/files/grouped", response_model=GroupedFilesResponse)
async def get_workflow_files_grouped(
    workflow_id: int,
    db: Session = Depends(get_db)
):
    """
    Get all files for a workflow, grouped by task.

    Useful for the folder tree navigation in the enhanced file viewer.
    """
    from models.workspace_file import WorkspaceFile
    from models.workflow import WorkflowProfile
    from models.core import Task

    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get all files for this workflow
    files = db.query(WorkspaceFile).filter(
        WorkspaceFile.workflow_id == workflow_id
    ).order_by(WorkspaceFile.task_id, WorkspaceFile.created_at.desc()).all()

    # Group by task
    task_groups: dict = {}
    for file in files:
        task_id = file.task_id or 0

        if task_id not in task_groups:
            task_name = "Unassigned"
            if task_id:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task and task.description:
                    task_name = task.description[:50] + ("..." if len(task.description) > 50 else "")
                elif task:
                    task_name = f"Task {task_id}"

            task_groups[task_id] = {
                'task_id': task_id if task_id else None,
                'task_name': task_name,
                'files': []
            }

        task_groups[task_id]['files'].append({
            'id': file.id,
            'filename': file.filename,
            'file_path': file.file_path,
            'size_bytes': file.size_bytes,
            'extension': file.extension,
            'agent_label': file.agent_label,
            'agent_type': file.agent_type,
            'node_id': file.node_id,
            'created_at': file.created_at.isoformat() if file.created_at else None,
        })

    tasks = list(task_groups.values())

    return GroupedFilesResponse(
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        tasks=tasks,
        total_files=len(files)
    )


@router.get("/files/{file_id}/metadata/full")
async def get_full_file_metadata(
    file_id: int,
    db: Session = Depends(get_db)
):
    """
    Get complete file metadata including version count.

    Enhanced version of get_file_metadata with version history stats.
    """
    from models.workspace_file import WorkspaceFile
    from models.file_version import FileVersion

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Count versions
    version_count = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id
    ).count()

    # Get latest version info
    latest_version = db.query(FileVersion).filter(
        FileVersion.workspace_file_id == file_id
    ).order_by(FileVersion.version_number.desc()).first()

    return {
        "id": file_record.id,
        "filename": file_record.filename,
        "file_path": file_record.file_path,
        "agent_label": file_record.agent_label,
        "agent_type": file_record.agent_type,
        "node_id": file_record.node_id,
        "workflow_id": file_record.workflow_id,
        "workflow_name": file_record.workflow_name,
        "task_id": file_record.task_id,
        "project_id": file_record.project_id,
        "execution_id": file_record.execution_id,
        "original_query": file_record.original_query,
        "description": file_record.description,
        "content_type": file_record.content_type,
        "tags": file_record.tags or [],
        "size_bytes": file_record.size_bytes,
        "mime_type": file_record.mime_type,
        "extension": file_record.extension,
        "created_at": file_record.created_at.isoformat() if file_record.created_at else None,
        "updated_at": file_record.updated_at.isoformat() if file_record.updated_at else None,
        # Version info
        "version_count": version_count,
        "latest_version": {
            "version_number": latest_version.version_number,
            "operation": latest_version.operation,
            "change_summary": latest_version.change_summary,
            "created_at": latest_version.created_at.isoformat() if latest_version and latest_version.created_at else None
        } if latest_version else None
    }
