import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path

from db.database import get_db
from services.workspace_manager import get_workspace_manager
from services.document_type import resolve_document_type
from models.core import Task
from .schemas import (
    AllFilesResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkIndexRequest,
    BulkIndexResponse,
    FileContentResponse,
    FileMetadataResponse,
    FileMetadataUpdateRequest,
    IndexFileRequest,
    IndexFileResponse,
    RenameFileRequest,
)

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/workspace" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["workspace"])


def _validate_path_in_workspace(file_path: str, workspace_mgr) -> Path:
    """
    Validate that a file path is within the workspace directory.

    Uses Path.relative_to() for robust cross-platform path comparison
    that handles Windows case differences and path separator issues.

    Returns the resolved full path if valid.
    Raises HTTPException(403) if path traversal is attempted.
    Raises HTTPException(404) if file doesn't exist.
    """
    full_path = (workspace_mgr.base_dir / file_path).resolve()
    workspace_resolved = workspace_mgr.base_dir.resolve()

    # Security: Use relative_to() for robust path comparison
    try:
        full_path.relative_to(workspace_resolved)
    except ValueError:
        logger.warning(f"Path traversal attempt blocked: {file_path}")
        raise HTTPException(status_code=403, detail="Invalid path")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return full_path


# =============================================================================
# All Files (for Library)
# =============================================================================

@router.get("/files", response_model=AllFilesResponse)
async def list_all_files(
    project_id: int | None = None,
    workflow_id: int | None = None,
    search: str | None = None,
    file_type: str | None = None,
    db: Session = Depends(get_db)
):
    """
    List all files across workspace.

    Use for Library Files browser. Supports filtering by project, workflow,
    search term, and file type.
    """
    from models.core import Project
    from models.workflow import WorkflowProfile

    workspace_mgr = get_workspace_manager()

    files = workspace_mgr.list_all_files(
        project_id=project_id,
        workflow_id=workflow_id,
        search=search,
        file_type=file_type
    )

    # Collect unique project and workflow IDs for batch lookup
    project_ids = set(f.get('project_id') for f in files if f.get('project_id'))
    workflow_ids = set(f.get('workflow_id') for f in files if f.get('workflow_id'))

    # Batch fetch project names
    project_names = {}
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        project_names = {p.id: p.name for p in projects}

    # Batch fetch workflow names
    workflow_names = {}
    if workflow_ids:
        workflows = db.query(WorkflowProfile).filter(WorkflowProfile.id.in_(workflow_ids)).all()
        workflow_names = {w.id: w.name for w in workflows}

    # Enrich files with names
    for file in files:
        if file.get('project_id'):
            file['project_name'] = project_names.get(file['project_id'])
        if file.get('workflow_id'):
            file['workflow_name'] = workflow_names.get(file['workflow_id'])

    return AllFilesResponse(
        files=files,
        total_files=len(files)
    )


@router.post("/files/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_files(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db)
):
    """
    Delete multiple files at once.

    Request body: { "files": [{ "task_id": 1, "filename": "x.md" }, ...] }
    For default files, task_id should be null/None.
    """
    workspace_mgr = get_workspace_manager()
    deleted = 0
    failed = 0
    errors = []

    for file_info in request.files:
        task_id = file_info.get("task_id")
        filename = file_info.get("filename")

        if not filename:
            failed += 1
            errors.append(f"Invalid file info: {file_info}")
            continue

        # Handle default files (no task_id)
        if task_id is None:
            success = workspace_mgr.delete_default_file(filename)
            if success:
                deleted += 1
            else:
                failed += 1
                errors.append(f"Could not delete default file {filename}")
            continue

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            failed += 1
            errors.append(f"Task {task_id} not found")
            continue

        success = workspace_mgr.delete_file(
            project_id=task.project_id,
            workflow_id=task.workflow_id,
            task_id=task.id,
            filename=filename
        )

        if success:
            deleted += 1
        else:
            failed += 1
            errors.append(f"Could not delete {filename} from task {task_id}")

    logger.info(f"Bulk delete: {deleted} deleted, {failed} failed")

    return BulkDeleteResponse(
        deleted=deleted,
        failed=failed,
        errors=errors
    )


@router.post("/tasks/{task_id}/files/{filename}/index", response_model=IndexFileResponse)
async def index_file_to_knowledge_base(
    task_id: int,
    filename: str,
    request: IndexFileRequest,
    db: Session = Depends(get_db)
):
    """
    Index a workspace file into the project's knowledge base (vector store).

    This makes the file's content searchable via RAG queries.
    Also creates a ContextDocument record so the file appears in the Knowledge Base UI.
    """
    from pathlib import Path
    from models.core import ContextDocument, IndexingStatus, DocumentType
    import os
    import mimetypes

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
        raise HTTPException(status_code=404, detail="File not found")

    try:
        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.strip():
            return IndexFileResponse(
                status="error",
                message="File is empty - nothing to index"
            )

        # Index directly using the text content
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from llama_index.core.schema import TextNode
        from llama_index.core import Settings
        from datetime import datetime, timezone

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1024,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunks = text_splitter.split_text(content)

        if not chunks:
            return IndexFileResponse(
                status="error",
                message="Could not split file into chunks"
            )

        # Get vector store for the project
        from services.llama_config import get_vector_store
        vector_store = get_vector_store(request.project_id)

        # Create embeddings and store
        embed_model = Settings.embed_model
        nodes = []

        for i, chunk_text in enumerate(chunks):
            node_id = f"workspace_file_{task_id}_{filename}_{i}"
            metadata = {
                "source": "workspace_file",
                "task_id": task_id,
                "filename": filename,
                "project_id": request.project_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "indexed_at": datetime.now(timezone.utc).isoformat()
            }

            text_node = TextNode(
                id_=node_id,
                text=chunk_text,
                metadata=metadata
            )

            # Generate embedding synchronously
            embedding = embed_model.get_text_embedding(chunk_text)
            text_node.embedding = embedding

            nodes.append(text_node)

        # Store in vector database
        vector_store.add(nodes)

        # Determine document type from extension
        doc_type = resolve_document_type(filename)

        # Get mime type
        mime_type, _ = mimetypes.guess_type(filename)

        # Create a ContextDocument record so it shows in the Knowledge Base UI
        context_doc = ContextDocument(
            filename=filename,
            original_filename=filename,
            file_path=str(file_path),
            file_size=os.path.getsize(file_path),
            mime_type=mime_type or 'text/plain',
            document_type=doc_type,
            indexing_status=IndexingStatus.READY,
            indexed_at=datetime.now(timezone.utc),
            indexed_chunks_count=len(nodes),
            description=f"Workspace file from task {task_id}",
            content_preview=content[:500] if len(content) > 500 else content,
            project_id=request.project_id,
        )
        db.add(context_doc)
        db.commit()

        logger.info(f"Indexed {len(nodes)} chunks from {filename} to project {request.project_id} knowledge base")

        return IndexFileResponse(
            status="success",
            message=f"Successfully indexed {len(nodes)} chunks into the knowledge base",
            chunks_created=len(nodes)
        )

    except Exception as e:
        logger.error(f"Error indexing file to knowledge base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/default/files/{filename}/index", response_model=IndexFileResponse)
async def index_default_file_to_knowledge_base(
    filename: str,
    request: IndexFileRequest,
    db: Session = Depends(get_db)
):
    """
    Index a default workspace file into the project's knowledge base.

    Also creates a ContextDocument record so the file appears in the Knowledge Base UI.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from llama_index.core.schema import TextNode
    from llama_index.core import Settings
    from datetime import datetime, timezone
    from models.core import ContextDocument, IndexingStatus, DocumentType
    import os
    import mimetypes

    workspace_mgr = get_workspace_manager()
    file_path = workspace_mgr.get_default_file_path(filename)

    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.strip():
            return IndexFileResponse(
                status="error",
                message="File is empty - nothing to index"
            )

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1024,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunks = text_splitter.split_text(content)

        if not chunks:
            return IndexFileResponse(
                status="error",
                message="Could not split file into chunks"
            )

        # Get vector store for the project
        from services.llama_config import get_vector_store
        vector_store = get_vector_store(request.project_id)

        # Create embeddings and store
        embed_model = Settings.embed_model
        nodes = []

        for i, chunk_text in enumerate(chunks):
            node_id = f"workspace_file_default_{filename}_{i}"
            metadata = {
                "source": "workspace_file",
                "filename": filename,
                "project_id": request.project_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "indexed_at": datetime.now(timezone.utc).isoformat()
            }

            text_node = TextNode(
                id_=node_id,
                text=chunk_text,
                metadata=metadata
            )

            embedding = embed_model.get_text_embedding(chunk_text)
            text_node.embedding = embedding

            nodes.append(text_node)

        vector_store.add(nodes)

        # Determine document type from extension
        doc_type = resolve_document_type(filename)

        # Get mime type
        mime_type, _ = mimetypes.guess_type(filename)

        # Create a ContextDocument record so it shows in the Knowledge Base UI
        context_doc = ContextDocument(
            filename=filename,
            original_filename=filename,
            file_path=str(file_path),
            file_size=os.path.getsize(file_path),
            mime_type=mime_type or 'text/plain',
            document_type=doc_type,
            indexing_status=IndexingStatus.READY,
            indexed_at=datetime.now(timezone.utc),
            indexed_chunks_count=len(nodes),
            description="Workspace file from default folder",
            content_preview=content[:500] if len(content) > 500 else content,
            project_id=request.project_id,
        )
        db.add(context_doc)
        db.commit()

        logger.info(f"Indexed {len(nodes)} chunks from default/{filename} to project {request.project_id} knowledge base")

        return IndexFileResponse(
            status="success",
            message=f"Successfully indexed {len(nodes)} chunks into the knowledge base",
            chunks_created=len(nodes)
        )

    except Exception as e:
        logger.error(f"Error indexing default file to knowledge base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# File Metadata (for tracking agent context, tags, etc.)
# =============================================================================

@router.get("/files/metadata/{file_id}", response_model=FileMetadataResponse)
async def get_file_metadata(
    file_id: int,
    db: Session = Depends(get_db)
):
    """
    Get full metadata for a specific file.

    Returns agent context, workflow info, tags, and other metadata.
    """
    from models.workspace_file import WorkspaceFile

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File metadata not found")

    return FileMetadataResponse(
        id=file_record.id,
        filename=file_record.filename,
        file_path=file_record.file_path,
        agent_label=file_record.agent_label,
        agent_type=file_record.agent_type,
        node_id=file_record.node_id,
        workflow_id=file_record.workflow_id,
        workflow_name=file_record.workflow_name,
        task_id=file_record.task_id,
        project_id=file_record.project_id,
        execution_id=file_record.execution_id,
        original_query=file_record.original_query,
        description=file_record.description,
        content_type=file_record.content_type,
        tags=file_record.tags or [],
        size_bytes=file_record.size_bytes,
        mime_type=file_record.mime_type,
        extension=file_record.extension,
        created_at=file_record.created_at.isoformat() if file_record.created_at else None,
        updated_at=file_record.updated_at.isoformat() if file_record.updated_at else None,
    )


@router.patch("/files/metadata/{file_id}", response_model=FileMetadataResponse)
async def update_file_metadata(
    file_id: int,
    request: FileMetadataUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Update file metadata (tags, description, content_type).

    Only user-editable fields can be updated. Agent context is read-only.
    """
    from models.workspace_file import WorkspaceFile

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File metadata not found")

    # Update editable fields
    if request.description is not None:
        file_record.description = request.description
    if request.content_type is not None:
        file_record.content_type = request.content_type
    if request.tags is not None:
        file_record.tags = request.tags

    db.commit()
    db.refresh(file_record)

    logger.info(f"Updated metadata for file {file_id}: {file_record.filename}")

    return FileMetadataResponse(
        id=file_record.id,
        filename=file_record.filename,
        file_path=file_record.file_path,
        agent_label=file_record.agent_label,
        agent_type=file_record.agent_type,
        node_id=file_record.node_id,
        workflow_id=file_record.workflow_id,
        workflow_name=file_record.workflow_name,
        task_id=file_record.task_id,
        project_id=file_record.project_id,
        execution_id=file_record.execution_id,
        original_query=file_record.original_query,
        description=file_record.description,
        content_type=file_record.content_type,
        tags=file_record.tags or [],
        size_bytes=file_record.size_bytes,
        mime_type=file_record.mime_type,
        extension=file_record.extension,
        created_at=file_record.created_at.isoformat() if file_record.created_at else None,
        updated_at=file_record.updated_at.isoformat() if file_record.updated_at else None,
    )


@router.get("/files/by-path")
async def get_file_metadata_by_path(
    file_path: str,
    db: Session = Depends(get_db)
):
    """
    Get file metadata by file path.

    Useful when you have the file path from the filesystem listing
    but need to look up the database metadata.
    """
    from models.workspace_file import WorkspaceFile

    file_record = db.query(WorkspaceFile).filter(WorkspaceFile.file_path == file_path).first()
    if not file_record:
        return {"metadata": None, "has_metadata": False}

    return {
        "metadata": FileMetadataResponse(
            id=file_record.id,
            filename=file_record.filename,
            file_path=file_record.file_path,
            agent_label=file_record.agent_label,
            agent_type=file_record.agent_type,
            node_id=file_record.node_id,
            workflow_id=file_record.workflow_id,
            workflow_name=file_record.workflow_name,
            task_id=file_record.task_id,
            project_id=file_record.project_id,
            execution_id=file_record.execution_id,
            original_query=file_record.original_query,
            description=file_record.description,
            content_type=file_record.content_type,
            tags=file_record.tags or [],
            size_bytes=file_record.size_bytes,
            mime_type=file_record.mime_type,
            extension=file_record.extension,
            created_at=file_record.created_at.isoformat() if file_record.created_at else None,
            updated_at=file_record.updated_at.isoformat() if file_record.updated_at else None,
        ),
        "has_metadata": True
    }


@router.get("/files/with-metadata")
async def list_files_with_metadata(
    project_id: int | None = None,
    workflow_id: int | None = None,
    agent_label: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db)
):
    """
    List all files with their metadata from the database.

    Supports filtering by project, workflow, agent, or search term.
    This returns richer metadata than the filesystem-based listing.
    """
    from models.workspace_file import WorkspaceFile

    query = db.query(WorkspaceFile)

    if project_id is not None:
        query = query.filter(WorkspaceFile.project_id == project_id)
    if workflow_id is not None:
        query = query.filter(WorkspaceFile.workflow_id == workflow_id)
    if agent_label is not None:
        query = query.filter(WorkspaceFile.agent_label.ilike(f"%{agent_label}%"))
    if search is not None:
        query = query.filter(
            WorkspaceFile.filename.ilike(f"%{search}%") |
            WorkspaceFile.description.ilike(f"%{search}%")
        )

    # Order by most recent first
    query = query.order_by(WorkspaceFile.created_at.desc())

    files = query.all()

    return {
        "files": [
            FileMetadataResponse(
                id=f.id,
                filename=f.filename,
                file_path=f.file_path,
                agent_label=f.agent_label,
                agent_type=f.agent_type,
                node_id=f.node_id,
                workflow_id=f.workflow_id,
                workflow_name=f.workflow_name,
                task_id=f.task_id,
                project_id=f.project_id,
                execution_id=f.execution_id,
                original_query=f.original_query,
                description=f.description,
                content_type=f.content_type,
                tags=f.tags or [],
                size_bytes=f.size_bytes,
                mime_type=f.mime_type,
                extension=f.extension,
                created_at=f.created_at.isoformat() if f.created_at else None,
                updated_at=f.updated_at.isoformat() if f.updated_at else None,
            )
            for f in files
        ],
        "total_files": len(files)
    }


# =============================================================================
# Default Folder Files (standalone/chat execution outputs)
# =============================================================================

@router.get("/default/files")
async def list_default_files():
    """
    List all files in the default workspace.

    These are files created during standalone/chat execution (no workflow context).
    """
    workspace_mgr = get_workspace_manager()
    files = workspace_mgr.list_default_files()

    return {
        "files": files,
        "total_files": len(files)
    }


@router.get("/default/files/{filename}")
async def download_default_file(filename: str):
    """Download a file from the default workspace."""
    from fastapi.responses import FileResponse

    workspace_mgr = get_workspace_manager()
    file_path = workspace_mgr.get_default_file_path(filename)

    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/default/files/{filename}/content", response_model=FileContentResponse)
async def get_default_file_content(filename: str):
    """Get content of a file in the default workspace for preview."""
    workspace_mgr = get_workspace_manager()

    content_data = workspace_mgr.get_default_file_content(filename)

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


@router.put("/default/files/{filename}")
async def rename_default_file(filename: str, request: RenameFileRequest):
    """Rename a file in the default workspace."""
    workspace_mgr = get_workspace_manager()

    success = workspace_mgr.rename_default_file(filename, request.new_name)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not rename file. It may not exist, or target name already exists."
        )

    return {
        "status": "success",
        "old_name": filename,
        "new_name": request.new_name
    }


@router.delete("/default/files/{filename}")
async def delete_default_file(filename: str):
    """Delete a file from the default workspace."""
    workspace_mgr = get_workspace_manager()

    success = workspace_mgr.delete_default_file(filename)

    if not success:
        raise HTTPException(status_code=404, detail="File not found or could not be deleted")

    return {"status": "success", "filename": filename}


# =============================================================================
# Path-Based File Access (for files anywhere in outputs/)
# =============================================================================

@router.get("/by-path/content")
async def get_file_content_by_path(file_path: str):
    """
    Get file content by relative path within outputs/.

    This is the most flexible way to access files - works for:
    - Root level files: email_agent.py
    - Default folder: default/report.md
    - Project/workflow/task: project_1/workflow_2/task_3/output.md

    The file_path should be the relative path as returned by list_all_files.
    """
    import mimetypes

    workspace_mgr = get_workspace_manager()

    # Security: Validate path is within outputs/
    full_path = _validate_path_in_workspace(file_path, workspace_mgr)

    # Determine if text or binary
    mime_type, _ = mimetypes.guess_type(str(full_path))
    if mime_type is None:
        mime_type = "text/plain"

    text_types = [
        "text/", "application/json", "application/javascript",
        "application/xml", "application/yaml", "application/x-yaml"
    ]
    is_text = any(mime_type.startswith(t) for t in text_types)

    text_extensions = {
        '.md', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
        '.yaml', '.yml', '.xml', '.html', '.css', '.scss', '.sql',
        '.sh', '.bash', '.env', '.gitignore', '.csv', '.toml', '.ini',
        '.cfg', '.conf', '.log', '.rst', '.tex'
    }
    if full_path.suffix.lower() in text_extensions:
        is_text = True

    file_size = full_path.stat().st_size
    max_size = 1024 * 1024  # 1MB

    if not is_text:
        return FileContentResponse(
            filename=full_path.name,
            content=None,
            mime_type=mime_type,
            is_binary=True,
            truncated=False,
            size_bytes=file_size
        )

    try:
        truncated = file_size > max_size
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(max_size)

        return FileContentResponse(
            filename=full_path.name,
            content=content,
            mime_type=mime_type,
            is_binary=False,
            truncated=truncated,
            size_bytes=file_size
        )
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=500, detail="Error reading file")


@router.get("/by-path/download")
async def download_file_by_path(file_path: str):
    """
    Download a file by relative path within outputs/.
    """
    workspace_mgr = get_workspace_manager()

    # Security: Validate path is within outputs/
    full_path = _validate_path_in_workspace(file_path, workspace_mgr)

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.delete("/by-path")
async def delete_file_by_path(file_path: str):
    """
    Delete a file by relative path within outputs/.
    """
    workspace_mgr = get_workspace_manager()

    # Security: Validate path is within outputs/
    full_path = _validate_path_in_workspace(file_path, workspace_mgr)

    try:
        full_path.unlink()
        logger.info(f"Deleted file: {file_path}")
        return {"status": "success", "path": file_path}
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail="Error deleting file")


@router.post("/by-path/index", response_model=IndexFileResponse)
async def index_file_by_path(
    file_path: str,
    request: IndexFileRequest,
    db: Session = Depends(get_db)
):
    """
    Index a file by relative path into the project's knowledge base.

    Works for files anywhere in outputs/ directory.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from llama_index.core.schema import TextNode
    from llama_index.core import Settings
    from datetime import datetime, timezone
    from models.core import ContextDocument, IndexingStatus, DocumentType
    import os
    import mimetypes as mt

    workspace_mgr = get_workspace_manager()

    # Security: Validate path is within outputs/
    full_path = _validate_path_in_workspace(file_path, workspace_mgr)

    try:
        # Read file content
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.strip():
            return IndexFileResponse(
                status="error",
                message="File is empty - nothing to index"
            )

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1024,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunks = text_splitter.split_text(content)

        if not chunks:
            return IndexFileResponse(
                status="error",
                message="Could not split file into chunks"
            )

        # Get vector store for the project
        from services.llama_config import get_vector_store
        vector_store = get_vector_store(request.project_id)

        # Create embeddings and store
        embed_model = Settings.embed_model
        nodes = []
        filename = full_path.name

        for i, chunk_text in enumerate(chunks):
            node_id = f"workspace_file_path_{file_path}_{i}"
            metadata = {
                "source": "workspace_file",
                "file_path": file_path,
                "filename": filename,
                "project_id": request.project_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "indexed_at": datetime.now(timezone.utc).isoformat()
            }

            text_node = TextNode(
                id_=node_id,
                text=chunk_text,
                metadata=metadata
            )

            embedding = embed_model.get_text_embedding(chunk_text)
            text_node.embedding = embedding

            nodes.append(text_node)

        vector_store.add(nodes)

        # Determine document type from extension
        doc_type = resolve_document_type(filename)

        # Get mime type
        mime_type, _ = mt.guess_type(filename)

        # Create a ContextDocument record
        context_doc = ContextDocument(
            filename=filename,
            original_filename=filename,
            file_path=str(full_path),
            file_size=os.path.getsize(full_path),
            mime_type=mime_type or 'text/plain',
            document_type=doc_type,
            indexing_status=IndexingStatus.READY,
            indexed_at=datetime.now(timezone.utc),
            indexed_chunks_count=len(nodes),
            description=f"Workspace file: {file_path}",
            content_preview=content[:500] if len(content) > 500 else content,
            project_id=request.project_id,
        )
        db.add(context_doc)
        db.commit()

        logger.info(f"Indexed {len(nodes)} chunks from {file_path} to project {request.project_id}")

        return IndexFileResponse(
            status="success",
            message=f"Successfully indexed {len(nodes)} chunks into the knowledge base",
            chunks_created=len(nodes)
        )

    except Exception as e:
        logger.error(f"Error indexing file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/by-path/bulk-index", response_model=BulkIndexResponse)
async def bulk_index_files_by_path(
    request: BulkIndexRequest,
    db: Session = Depends(get_db)
):
    """
    Index multiple files into a project's knowledge base.

    Useful for indexing an entire folder of files at once.
    Skips binary files and files that fail to read.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from llama_index.core.schema import TextNode
    from llama_index.core import Settings
    from datetime import datetime, timezone
    from models.core import ContextDocument, IndexingStatus, DocumentType
    import os
    import mimetypes as mt

    workspace_mgr = get_workspace_manager()

    # Text file extensions we can index
    text_extensions = {
        '.md', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
        '.yaml', '.yml', '.xml', '.html', '.css', '.scss', '.sql',
        '.sh', '.bash', '.csv', '.toml', '.ini', '.cfg', '.conf',
        '.log', '.rst', '.tex'
    }

    indexed_count = 0
    failed_count = 0
    total_chunks = 0
    errors = []

    # Get vector store for the project
    from services.llama_config import get_vector_store
    vector_store = get_vector_store(request.project_id)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1024,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    embed_model = Settings.embed_model

    for file_path in request.file_paths:
        try:
            # Validate path is within workspace
            full_path = (workspace_mgr.base_dir / file_path).resolve()
            workspace_resolved = workspace_mgr.base_dir.resolve()

            try:
                full_path.relative_to(workspace_resolved)
            except ValueError:
                errors.append(f"{file_path}: Invalid path")
                failed_count += 1
                continue

            if not full_path.exists() or not full_path.is_file():
                errors.append(f"{file_path}: File not found")
                failed_count += 1
                continue

            # Check if it's a text file we can index
            ext = full_path.suffix.lower()
            if ext not in text_extensions:
                errors.append(f"{file_path}: Skipped (binary or unsupported type)")
                failed_count += 1
                continue

            # Read file content
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as read_err:
                errors.append(f"{file_path}: Could not read ({str(read_err)})")
                failed_count += 1
                continue

            if not content.strip():
                errors.append(f"{file_path}: Empty file")
                failed_count += 1
                continue

            # Split into chunks
            chunks = text_splitter.split_text(content)
            if not chunks:
                errors.append(f"{file_path}: Could not split into chunks")
                failed_count += 1
                continue

            # Create embeddings and store
            filename = full_path.name
            nodes = []

            for i, chunk_text in enumerate(chunks):
                node_id = f"workspace_file_path_{file_path}_{i}"
                metadata = {
                    "source": "workspace_file",
                    "file_path": file_path,
                    "filename": filename,
                    "project_id": request.project_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "indexed_at": datetime.now(timezone.utc).isoformat()
                }

                text_node = TextNode(
                    id_=node_id,
                    text=chunk_text,
                    metadata=metadata
                )

                embedding = embed_model.get_text_embedding(chunk_text)
                text_node.embedding = embedding

                nodes.append(text_node)

            vector_store.add(nodes)
            total_chunks += len(nodes)

            # Determine document type from extension
            doc_type = resolve_document_type(full_path.name)

            # Get mime type
            mime_type, _ = mt.guess_type(filename)

            # Create a ContextDocument record
            context_doc = ContextDocument(
                filename=filename,
                original_filename=filename,
                file_path=str(full_path),
                file_size=os.path.getsize(full_path),
                mime_type=mime_type or 'text/plain',
                document_type=doc_type,
                indexing_status=IndexingStatus.READY,
                indexed_at=datetime.now(timezone.utc),
                indexed_chunks_count=len(nodes),
                description=f"Workspace file: {file_path}",
                content_preview=content[:500] if len(content) > 500 else content,
                project_id=request.project_id,
            )
            db.add(context_doc)

            indexed_count += 1
            logger.info(f"Indexed {len(nodes)} chunks from {file_path}")

        except Exception as e:
            errors.append(f"{file_path}: {str(e)}")
            failed_count += 1
            logger.error(f"Error indexing {file_path}: {e}")

    # Commit all ContextDocument records
    db.commit()

    logger.info(f"Bulk index complete: {indexed_count} indexed, {failed_count} failed, {total_chunks} total chunks")

    return BulkIndexResponse(
        status="success" if indexed_count > 0 else "error",
        indexed=indexed_count,
        failed=failed_count,
        total_chunks=total_chunks,
        errors=errors[:10]  # Limit error messages to first 10
    )


# =============================================================================
# Custom Output Path File Listing
# =============================================================================

@router.get("/files/from-path")
async def list_files_from_custom_path(
    directory: str,
    search: str | None = None,
    file_type: str | None = None
):
    """
    List all files from a custom directory path.

    Used when workflows have a custom_output_path configured.
    Returns files in the same format as list_all_files for frontend compatibility.
    """
    from pathlib import Path
    from datetime import datetime
    import mimetypes

    base_path = Path(directory).resolve()

    if not base_path.exists():
        return {"files": [], "total_files": 0, "directory": str(base_path), "exists": False}

    if not base_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    def format_size(size_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    files = []

    # Recursively scan the directory
    for file_path in base_path.rglob('*'):
        if not file_path.is_file():
            continue

        # Apply filters
        if search and search.lower() not in file_path.name.lower():
            continue

        if file_type and file_path.suffix.lower() != f".{file_type.lower()}":
            continue

        try:
            stat = file_path.stat()

            # Extract workflow_id and task_id from path structure if present
            # Expected: {custom_path}/workflow_{id}/task_{id}/filename
            workflow_id = None
            task_id = None
            rel_path = file_path.relative_to(base_path)
            parts = rel_path.parts

            for part in parts:
                if part.startswith('workflow_'):
                    try:
                        wf_str = part.replace('workflow_', '')
                        if wf_str != 'None':
                            workflow_id = int(wf_str)
                    except ValueError:
                        pass
                elif part.startswith('task_'):
                    try:
                        task_id = int(part.replace('task_', ''))
                    except ValueError:
                        pass

            files.append({
                "filename": file_path.name,
                "path": str(file_path),  # Full absolute path for custom directories
                "full_path": str(file_path),
                "project_id": None,
                "project_name": None,
                "workflow_id": workflow_id,
                "workflow_name": None,
                "task_id": task_id,
                "size_bytes": stat.st_size,
                "size_human": format_size(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": file_path.suffix,
            })
        except Exception as e:
            logger.warning(f"Could not stat file {file_path}: {e}")

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x['modified_at'], reverse=True)

    return {
        "files": files,
        "total_files": len(files),
        "directory": str(base_path),
        "exists": True
    }


@router.get("/files/from-path/content")
async def get_file_content_from_custom_path(file_path: str):
    """
    Get file content from a custom path for preview.

    Used when files are stored outside the default outputs/ directory.
    """
    from pathlib import Path
    import mimetypes

    full_path = Path(file_path).resolve()

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine if text or binary
    mime_type, _ = mimetypes.guess_type(str(full_path))
    if mime_type is None:
        mime_type = "text/plain"

    text_types = [
        "text/", "application/json", "application/javascript",
        "application/xml", "application/yaml", "application/x-yaml"
    ]
    is_text = any(mime_type.startswith(t) for t in text_types)

    text_extensions = {
        '.md', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
        '.yaml', '.yml', '.xml', '.html', '.css', '.scss', '.sql',
        '.sh', '.bash', '.env', '.gitignore', '.csv', '.toml', '.ini',
        '.cfg', '.conf', '.log', '.rst', '.tex'
    }
    if full_path.suffix.lower() in text_extensions:
        is_text = True

    file_size = full_path.stat().st_size
    max_size = 1024 * 1024  # 1MB

    if not is_text:
        return FileContentResponse(
            filename=full_path.name,
            content=None,
            mime_type=mime_type,
            is_binary=True,
            truncated=False,
            size_bytes=file_size
        )

    try:
        truncated = file_size > max_size
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(max_size)

        return FileContentResponse(
            filename=full_path.name,
            content=content,
            mime_type=mime_type,
            is_binary=False,
            truncated=truncated,
            size_bytes=file_size
        )
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=500, detail="Error reading file")


@router.get("/files/from-path/download")
async def download_file_from_custom_path(file_path: str):
    """
    Download a file from a custom path.
    """
    from pathlib import Path

    full_path = Path(file_path).resolve()

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )
