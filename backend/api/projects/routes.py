# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from db.database import get_db
from core.context.current_user import require_admin
from models.core import Project, ProjectStatus, IndexingStatus
from services.workspace_manager import get_workspace_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


# Pydantic Schemas
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    configuration: Optional[dict] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    configuration: Optional[dict] = None
    workflow_profile_id: Optional[int] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    status: ProjectStatus
    configuration: dict
    indexing_status: IndexingStatus
    workflow_profile_id: Optional[int]
    project_path: Optional[str] = None
    # Timestamps — the frontend renders created_at on project cards;
    # omitting them made every card show "Invalid Date".
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Endpoints
@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    status: Optional[ProjectStatus] = None,
    db: Session = Depends(get_db)
):
    """List all projects with optional status filter.

    Before answering, register any knowledge base that exists on disk but has no row. A documents
    folder copied onto this machine IS a complete knowledge base — the files plus their `.kvmeta`
    catalog are all it takes — but this endpoint is what the Knowledge panel lists, so without a
    row that knowledge base is present and unreachable, which is exactly how a copied one came to
    look lost. Registration is idempotent and never modifies an existing row.
    """
    try:
        from services.kb_discovery import register_missing
        created = register_missing(db)
        if created:
            logger.info("registered %d knowledge base(s) found on disk: %s", len(created), created)
    except Exception as exc:                  # noqa: BLE001 — listing must still answer
        logger.warning("could not scan the documents folder for unregistered projects: %s", exc)

    query = db.query(Project)
    if status:
        query = query.filter(Project.status == status)

    projects = query.offset(skip).limit(limit).all()

    # Attach project_path from workspace manager
    workspace_mgr = get_workspace_manager()
    for p in projects:
        try:
            workspace = workspace_mgr.get_project_workspace(p.id)
            p.project_path = str(workspace)
        except Exception:
            pass

    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific project by ID"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        workspace_mgr = get_workspace_manager()
        workspace = workspace_mgr.get_project_workspace(project.id)
        project.project_path = str(workspace)
    except Exception:
        pass

    return project


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db)
):
    """Create a new project"""
    # Check if name already exists
    existing = db.query(Project).filter(Project.name == project.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project with this name already exists")

    # Set default configuration if not provided
    config = project.configuration or {"default_model": "gpt-4o"}

    db_project = Project(
        name=project.name,
        description=project.description,
        configuration=config,
        status=ProjectStatus.IDLE,
        indexing_status=IndexingStatus.NOT_INDEXED,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    # Create project workspace directory
    try:
        workspace_mgr = get_workspace_manager()
        workspace_path = workspace_mgr.get_project_workspace(db_project.id)
        db_project.project_path = str(workspace_path)
    except Exception as e:
        # Non-critical: folder creation failure shouldn't block project creation
        pass

    return db_project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing project"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update only provided fields
    update_data = project.model_dump(exclude_unset=True)
    # Renaming: project names are unique — reject collisions (the vault
    # folder key is the sanitized name).
    if update_data.get("name"):
        clash = db.query(Project).filter(
            Project.name == update_data["name"],
            Project.id != project_id,
        ).first()
        if clash:
            raise HTTPException(
                status_code=400,
                detail=f"Project name {update_data['name']!r} is already in use",
            )
    for key, value in update_data.items():
        setattr(db_project, key, value)

    db.commit()
    db.refresh(db_project)
    return db_project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """
    Delete a project and all associated data. Admin only.

    Why admin only: a project is a TEAM object — the `projects` row has no owner
    column, `GET /api/projects/` returns the same list to every account, and the
    knowledge documents and the per-project vector index (`data_project_index_<id>`)
    are shared too. Without a gate any signed-in account could delete another
    team's project and its knowledge index, which is not a permission this app
    hands out implicitly.

    Cascades in the database: workflows → versions → executions → tasks →
    execution events, then the project row and its vector index table.

    Files are NOT deleted: every account's vault (`users/<id>/<slug>/`) plus the
    project's AGENTS.md are MOVED into `backups/deleted_projects/<stamp>_<slug>/`,
    so a mistaken delete is recoverable and no one has to trust a docstring that
    promises an rmtree. The slug comes from the project's name, so it is captured
    before the row disappears.
    """
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Capture the on-disk identity BEFORE the row is deleted: the vault key is
    # derived from the project NAME, and there is no name left after the commit.
    try:
        from services.workspace_manager import WorkspaceManager
        vault_key = WorkspaceManager.project_vault_key(db, project_id)
    except Exception:  # noqa: BLE001 — a naming problem must not block the delete
        vault_key = f"project_{project_id}"
    vault_key = vault_key or f"project_{project_id}"
    file_sources = _project_file_sources(project_id, vault_key)

    try:
        from models.workflow import WorkflowProfile, WorkflowVersion, WorkflowExecution
        from models.core import Task
        from models.execution_event import ExecutionEvent
        from sqlalchemy import text, create_engine

        # Get all workflow IDs for this project
        workflow_ids = [w.id for w in db.query(WorkflowProfile).filter(
            WorkflowProfile.project_id == project_id
        ).all()]

        # 1. Delete execution events for all workflows in this project
        if workflow_ids:
            db.query(ExecutionEvent).filter(
                ExecutionEvent.workflow_id.in_(workflow_ids)
            ).delete(synchronize_session=False)

        # 2. Delete tasks for all workflows in this project
        # Use workflow_profile_id (the actual foreign key), not workflow_id (tracking string)
        if workflow_ids:
            db.query(Task).filter(
                Task.workflow_profile_id.in_(workflow_ids)
            ).delete(synchronize_session=False)

        # 3. Memory is stored in LangGraph's store system (not a separate table)
        # It's managed per-thread and doesn't need explicit cleanup

        # 4. Delete workflow executions for all workflows in this project
        if workflow_ids:
            db.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_id.in_(workflow_ids)
            ).delete(synchronize_session=False)

        # 5. Delete workflow versions for all workflows in this project
        if workflow_ids:
            db.query(WorkflowVersion).filter(
                WorkflowVersion.workflow_id.in_(workflow_ids)
            ).delete(synchronize_session=False)

        # 6. Delete all workflows in this project
        db.query(WorkflowProfile).filter(
            WorkflowProfile.project_id == project_id
        ).delete(synchronize_session=False)

        # 7. Drop the project's vector index table if it exists
        try:
            from config import settings as app_settings
            engine = create_engine(app_settings.database_url)
            table_name = f"data_project_index_{project_id}"
            with engine.connect() as conn:
                # Check if table exists
                check_query = text(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = '{table_name}'
                    )
                """)
                exists = conn.execute(check_query).scalar()

                if exists:
                    # Drop the table
                    drop_query = text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                    conn.execute(drop_query)
                    conn.commit()
                    logger.info(f"Dropped vector index table: {table_name}")
        except Exception as e:
            logger.warning(f"Failed to drop vector index table for project {project_id}: {e}")
            # Continue even if vector table deletion fails

        # 8. Finally, delete the project itself
        db.delete(db_project)
        db.commit()

        # 9. Move the files aside (every account's vault + the project's AGENTS.md).
        # After the commit, so a failed delete never leaves the files moved with the
        # row still present; and best-effort, because a half-deleted project with a
        # clear log line beats a request that fails after the rows are already gone.
        _archive_project_files(file_sources, vault_key)

        logger.info(f"Successfully deleted project {project_id} and all related data")
        return None

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete project {project_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete project: {str(e)}"
        )


def _project_file_sources(project_id: int, vault_key: str) -> list[tuple]:
    """`[(source_dir, archive_subpath)]` for one project — resolved BEFORE the delete.

    Three shapes exist on disk for one project and all of them are archived:

      * `<root>/users/<user id>/<slug>/`  — per-account vault (the normal case: the
        `projects` row is shared, the files under it are not);
      * `<root>/<slug>/`                  — the pre-account flat layout;
      * `<backend>/.workspace_data/<slug>/` — the project's shared `AGENTS.md`.

    Resolved before the row disappears: the slug comes from the project NAME, and
    `agents_md_service` re-derives it from the DB, so after the commit every lookup
    would fall back to the numeric id and miss the directory.
    """
    out: list[tuple] = []
    try:
        from services import user_roots

        root = user_roots.install_root()  # …/outputs
    except Exception:  # noqa: BLE001
        logger.warning("project %s: cannot resolve the workspace root", vault_key)
        return out

    users_dir = root / "users"
    if users_dir.is_dir():
        for uid_dir in users_dir.iterdir():
            candidate = uid_dir / vault_key
            if candidate.is_dir():
                out.append((candidate, Path("users") / uid_dir.name / vault_key))
    if (root / vault_key).is_dir():
        out.append((root / vault_key, Path(vault_key)))

    try:
        from services.agents_md_service import WORKSPACE_ROOT

        md_dir = WORKSPACE_ROOT / vault_key
        if md_dir.is_dir():
            out.append((md_dir, Path("workspace_data") / vault_key))
    except Exception:  # noqa: BLE001
        pass
    return out


def _archive_project_files(sources: list[tuple], vault_key: str) -> None:
    """Move a deleted project's directories into `backups/deleted_projects/`.

    Moving (not copying, not deleting) keeps a mistaken delete recoverable and
    stops files being silently orphaned under a slug that no longer exists in the
    UI. Best-effort: the DB rows are already gone, so a failure here is logged
    rather than raised.
    """
    import shutil
    import time

    if not sources:
        logger.info("project %s: nothing on disk to archive", vault_key)
        return

    try:
        from services import user_roots

        archive_root = user_roots.install_root().parent / "backups" / "deleted_projects"
    except Exception:  # noqa: BLE001
        logger.warning("project %s: cannot resolve the backup root; files left in place", vault_key)
        return

    archive = archive_root / f"{time.strftime('%Y%m%d_%H%M%S')}_{vault_key}"
    for src, rel in sources:
        dest = archive / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            logger.info("project %s: moved %s → %s", vault_key, src, dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("project %s: could not move %s (%s); left in place", vault_key, src, exc)
