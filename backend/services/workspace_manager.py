# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Workspace Manager for Organized File Storage

Manages output folders for projects, workflows, and tasks.
Creates a clean directory structure: outputs/project_{id}/workflow_{id}/task_{id}/

This allows:
- Easy browsing of project outputs
- Automatic cleanup of old task outputs
- Better organization for multi-project setups
"""
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import mimetypes
import shutil

logger = logging.getLogger(__name__)


# Per-agent workspace subfolders: uploaded files and agent-generated files are
# kept in separate, clearly-named folders inside each agent's workspace so the
# Files panel and the on-disk layout stay organized.
AGENT_UPLOADS_DIR = "upload"   # files the user uploads (RAG knowledge)
AGENT_GENERATED_DIR = "generated"      # files the agent produces
# Skills are staged into <workspace>/skills/ by the deepagents SDK staging step
# (the SDK's SkillsMiddleware hardcodes the plural "/skills/..." virtual path).
# "other" is the documented scratch/misc folder for anything that is neither an
# upload, a deliverable, nor a skill.
AGENT_OTHER_DIR = "other"
AGENT_SKILLS_DIR = "skills"

# The canonical per-agent subfolder layout (in display order).
AGENT_WORKSPACE_SUBDIRS = (
    AGENT_UPLOADS_DIR,
    AGENT_GENERATED_DIR,
    AGENT_SKILLS_DIR,
    AGENT_OTHER_DIR,
)


def ensure_agent_workspace_layout(root: Path) -> Path:
    """Create the canonical subfolder layout (upload/ generated/ skills/ other/)
    inside an agent workspace root. Returns the root. Idempotent."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for sub in AGENT_WORKSPACE_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _is_within(path: Path, root: Path) -> bool:
    """True if the resolved `path` is strictly inside `root`.

    Uses Path.is_relative_to, NOT a string prefix check: a prefix check
    without a trailing separator lets sibling paths through (e.g.
    ``task_1`` vs ``task_10``), enabling cross-task/cross-tenant access.
    """
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (ValueError, OSError):
        return False


class WorkspaceManager:
    """Manages workspace directories for project/workflow/task outputs"""

    def __init__(self, base_dir: str = None):
        """
        Initialize workspace manager.

        Args:
            base_dir: Base directory for all outputs. If None, uses backend/outputs.
        """
        if base_dir is None:
            # Default to backend/outputs, overridable via the workspace settings
            # document (base_dir, seeded from the old WORKSPACE_BASE_DIR).
            # Relative values resolve against the repo root (backend/..). The
            # user-chosen workspace path from Settings / first-run setup
            # (workspace.workspace_path) wins over the base default when set.
            backend_dir = Path(__file__).parent.parent  # services/ -> backend/
            try:
                from core.settings import runtime_get
                configured = runtime_get("workspace", "base_dir") or "backend/outputs"
                try:
                    # User-chosen workspace path from Settings / first-run setup
                    # (settings documents, workspace.workspace_path) wins over the
                    # base default when set.
                    from core.settings import resolve_value
                    from db.database import SessionLocal
                    _db = SessionLocal()
                    try:
                        _ws = (resolve_value(_db, "workspace").get("workspace_path") or "").strip()
                        if _ws:
                            configured = _ws
                    finally:
                        _db.close()
                except Exception:
                    pass
            except Exception:
                configured = "backend/outputs"
            p = Path(configured).expanduser()
            if not p.is_absolute():
                p = backend_dir.parent / p
            self.base_dir = p.resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

        self.base_dir.mkdir(exist_ok=True)
        logger.info(f"Workspace manager initialized: {self.base_dir}")
    
    def get_task_workspace(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int
    ) -> Path:
        """
        Get workspace directory for a specific task.
        
        Creates directory structure: outputs/project_{id}/workflow_{id}/task_{id}/
        If project_id is None, uses "standalone" as the project folder.
        
        Args:
            project_id: Project ID (can be None for standalone workflows)
            workflow_id: Workflow ID
            task_id: Task ID
            
        Returns:
            Path to task workspace directory
        """
        # Handle standalone workflows (no project)
        project_folder = f"project_{project_id}" if project_id else "standalone"
        
        # Build path: outputs/project_X/workflow_Y/task_Z/
        workspace = self.base_dir / project_folder / f"workflow_{workflow_id}" / f"task_{task_id}"
        
        # Create directory if it doesn't exist
        workspace.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Task workspace: {workspace}")
        return workspace

    def get_task_workspace_with_override(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int,
        custom_output_path: Optional[str] = None
    ) -> Path:
        """
        Get workspace directory with optional custom base directory override.

        If custom_output_path is provided, uses: {custom_path}/workflow_{id}/task_{id}/
        Otherwise falls back to the default workspace structure.

        Args:
            project_id: Project ID (used only when custom_output_path is None)
            workflow_id: Workflow ID
            task_id: Task ID
            custom_output_path: Custom base directory path (overrides default)

        Returns:
            Path to task workspace directory
        """
        if custom_output_path:
            # Use custom path as base
            base = Path(custom_output_path).resolve()
            workspace = base / f"workflow_{workflow_id}" / f"task_{task_id}"
            workspace.mkdir(parents=True, exist_ok=True)
            logger.info(f"Task workspace (custom): {workspace}")
            return workspace
        else:
            # Fall back to default structure
            return self.get_task_workspace(project_id, workflow_id, task_id)

    def get_workflow_workspace(
        self,
        project_id: Optional[int],
        workflow_id: int
    ) -> Path:
        """
        Get workspace directory for all tasks in a workflow.
        
        Args:
            project_id: Project ID
            workflow_id: Workflow ID
            
        Returns:
            Path to workflow workspace directory
        """
        project_folder = f"project_{project_id}" if project_id else "standalone"
        workspace = self.base_dir / project_folder / f"workflow_{workflow_id}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace
    
    def get_project_workspace(self, project_id: int) -> Path:
        """
        Get workspace directory for all workflows in a project.
        
        Args:
            project_id: Project ID
            
        Returns:
            Path to project workspace directory
        """
        workspace = self.base_dir / f"project_{project_id}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def get_agent_workspace(self, agent_id: int) -> Path:
        """
        Get the per-agent workspace root: outputs/agents/agent_{id}/.

        Every chat session of an agent shares this directory, so all of the
        agent's files (uploads + generated output) live under one root and
        are trivial to list. This is the canonical location for chat runs,
        replacing the shared standalone/workflow_None/task_0 default.
        """
        workspace = self.base_dir / "agents" / f"agent_{agent_id}"
        ensure_agent_workspace_layout(workspace)
        logger.info(f"Agent workspace: {workspace}")
        return workspace

    def resolve_agent_workspace(
        self,
        agent,
        project_id: Optional[int] = None,
        vault_key: Optional[str] = None,
        agent_key: Optional[str] = None,
    ) -> Path:
        """Resolve an agent's workspace root.

        Priority (per the product rule that workspace is user-defined and
        persisted in PostgreSQL, anchored to the active vault/project):
          1. ``agent.workspace_path`` (deep_agent_templates.workspace_path) —
             a user-defined directory. Absolute paths are used as-is;
             relative paths resolve against the vault root
             (``outputs/{vault_key}/``) when a project is bound, else
             against ``base_dir``.
          2. Vault-scoped default ``outputs/{vault_key}/agents/{agent_key}/``
             when a project is bound.
          3. Legacy default ``outputs/agents/agent_{id}/`` when neither is
             available.

        ``vault_key`` is the project's sanitized name (or its id) and
        ``agent_key`` the agent's sanitized name (or ``agent_{id}``) — pass
        them when you have the rows; callers without a DB handle may pass
        just the ids and the raw ids are used as keys.

        The directory is created if missing so uploads + generated files
        always have a home.
        """
        key = vault_key if vault_key is not None else (
            str(project_id) if project_id is not None else None
        )
        agent_folder = agent_key or f"agent_{getattr(agent, 'id', 'unknown')}"
        custom = getattr(agent, "workspace_path", None)
        if custom and str(custom).strip():
            p = Path(str(custom).strip()).expanduser()
            if not p.is_absolute():
                if key is not None:
                    p = self.base_dir / key / p
                else:
                    p = self.base_dir / p
            ensure_agent_workspace_layout(p)
            logger.info(f"Agent workspace (custom): {p}")
            return p
        if key is not None:
            vault_root = self.base_dir / key / "agents" / agent_folder
            ensure_agent_workspace_layout(vault_root)
            logger.info(f"Agent workspace (vault-scoped): {vault_root}")
            return vault_root
        return self.get_agent_workspace(agent.id)

    @staticmethod
    def project_vault_key(db, project_id: Optional[int]) -> str:
        """Folder key for a project: its sanitized NAME (so users can find
        it), falling back to the DB id when the row is missing.

        e.g. project 'my-project' → 'my-project'; 'my demo project 1' →
        'my-demo-project-1'. Slugs are unique among projects; on a collision
        the id is appended. Pass the request DB session (or any session);
        falls back to the raw id when the row is missing or the session is
        unavailable (tests, non-DB callers).
        """
        if project_id is None:
            return ""
        try:
            from models.core import Project
            row = db.get(Project, project_id) if db is not None else None
            if row is not None:
                slug = WorkspaceManager._slugify(row.name)
                # Collision guard: another project with the same slug?
                clash = (
                    db.query(Project)
                    .filter(Project.id != project_id)
                    .all()
                    if db is not None else []
                )
                for other in clash:
                    if WorkspaceManager._slugify(other.name) == slug:
                        return f"{slug}-{project_id}"
                return slug
        except Exception:
            pass
        return str(project_id)

    @staticmethod
    def _slugify(name: str) -> str:
        """Filesystem-safe folder key from a project name.

        Lowercases, keeps ASCII word chars + CJK + '-' and turns everything
        else (spaces, '/'…) into single dashes. Never empty.
        """
        import re
        import unicodedata
        s = unicodedata.normalize("NFKC", name or "")
        s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", s.lower(), flags=re.UNICODE)
        s = re.sub(r"-+", "-", s).strip("-")
        return s or "project"

    @staticmethod
    def agent_vault_key(db, agent) -> str:
        """Folder key for an agent: its sanitized NAME (so users can find
        it), falling back to ``agent_{id}`` when the row/name is missing.

        e.g. agent 'hello' → 'hello'; 'My Research Agent' →
        'my-research-agent'. Collision-guarded across all agents (id appended
        on a duplicate slug). Pass the request DB session.
        """
        name = getattr(agent, "name", None)
        if not name:
            return f"agent_{getattr(agent, 'id', 'unknown')}"
        try:
            from models.deep_agent import DeepAgentTemplate
            agent_id = getattr(agent, "id", None)
            slug = WorkspaceManager._slugify(name)
            if db is not None and agent_id is not None:
                others = db.query(DeepAgentTemplate).filter(
                    DeepAgentTemplate.id != agent_id
                ).all()
                for other in others:
                    if WorkspaceManager._slugify(other.name or "") == slug:
                        return f"{slug}-{agent_id}"
            return slug
        except Exception:
            return f"agent_{getattr(agent, 'id', 'unknown')}"

    def persist_output(self, file_path: Path, content: bytes, mime_type: Optional[str] = None) -> Optional[str]:
        """
        Phase 2 write-through (docs/system-architecture.md §15): persist an
        agent output file to the storage backend when STORAGE_MODE=db. The
        on-disk workspace file remains the operational copy, so this is a
        no-op in local mode (default) and behavior is unchanged.

        Args:
            file_path: Full path of the output file (usually under base_dir)
            content: File content bytes
            mime_type: Optional MIME type; guessed from the filename if None

        Returns:
            Storage key when persisted, else None
        """
        from config import settings
        if settings.storage_mode != "db":
            return None

        import mimetypes
        try:
            rel = Path(file_path).resolve().relative_to(Path(self.base_dir).resolve())
        except ValueError:
            # File lives outside the workspace root; keep it addressable by
            # bare name. Path.name returns a str (posix-safe, no separators).
            rel = Path(file_path).name
        key = f"outputs/{rel if isinstance(rel, str) else rel.as_posix()}"

        try:
            from services.storage import get_storage
            mime = mime_type or mimetypes.guess_type(file_path.name)[0]
            get_storage().save(key, content, mime)
            logger.info(f"Persisted output to storage: {key}")
            return key
        except Exception as e:
            logger.warning(f"Failed to persist output {key}: {e}")
            return None
    
    def list_task_files(self, project_id: Optional[int], workflow_id: int, task_id: int) -> list[dict]:
        """
        List all files in a task's workspace.
        
        Returns:
            List of file info dicts with name, size, modified_at, extension
        """
        workspace = self.get_task_workspace(project_id, workflow_id, task_id)
        
        files = []
        for file_path in workspace.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "filename": file_path.name,
                    "path": str(file_path.relative_to(self.base_dir)),
                    "size_bytes": stat.st_size,
                    "size_human": self._format_size(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "extension": file_path.suffix,
                })
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified_at'], reverse=True)
        return files
    
    def get_file_path(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int,
        filename: str
    ) -> Optional[Path]:
        """
        Get full path to a file in task workspace.

        Returns None if file doesn't exist or is outside workspace (security).
        """
        workspace = self.get_task_workspace(project_id, workflow_id, task_id)
        file_path = (workspace / filename).resolve()

        # Security: Ensure file is within workspace
        if not _is_within(file_path, workspace):
            logger.warning(f"Path traversal attempt blocked: {filename}")
            return None

        if not file_path.exists() or not file_path.is_file():
            return None

        return file_path

    def get_default_file_path(self, filename: str) -> Optional[Path]:
        """
        Get full path to a file in the default workspace.

        Returns None if file doesn't exist or is outside workspace (security).
        """
        default_dir = self.base_dir / "default"
        file_path = (default_dir / filename).resolve()

        # Security: Ensure file is within default directory
        if not _is_within(file_path, default_dir):
            logger.warning(f"Path traversal attempt blocked: {filename}")
            return None

        if not file_path.exists() or not file_path.is_file():
            return None

        return file_path

    def list_default_files(self) -> list[dict]:
        """
        List all files in the default workspace.

        Returns:
            List of file info dicts
        """
        default_dir = self.base_dir / "default"

        if not default_dir.exists():
            return []

        files = []
        for file_path in default_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files.append({
                    "filename": file_path.name,
                    "path": str(file_path.relative_to(self.base_dir)),
                    "size_bytes": stat.st_size,
                    "size_human": self._format_size(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "extension": file_path.suffix,
                })

        files.sort(key=lambda x: x['modified_at'], reverse=True)
        return files

    def get_default_file_content(
        self,
        filename: str,
        max_size: int = 1024 * 1024
    ) -> Optional[dict]:
        """Get content of a file in the default workspace."""
        file_path = self.get_default_file_path(filename)

        if not file_path:
            return None

        # Determine mime type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "text/plain"

        # Check if text-based
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
        if file_path.suffix.lower() in text_extensions:
            is_text = True

        if not is_text:
            return {
                "content": None,
                "mime_type": mime_type,
                "is_binary": True,
                "truncated": False,
                "size_bytes": file_path.stat().st_size
            }

        try:
            file_size = file_path.stat().st_size
            truncated = file_size > max_size

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(max_size)

            return {
                "content": content,
                "mime_type": mime_type,
                "is_binary": False,
                "truncated": truncated,
                "size_bytes": file_size
            }
        except Exception as e:
            logger.error(f"Error reading file content: {e}")
            return None

    def delete_default_file(self, filename: str) -> bool:
        """Delete a file from the default workspace."""
        file_path = self.get_default_file_path(filename)

        if not file_path:
            return False

        try:
            file_path.unlink()
            logger.info(f"Deleted default file: {filename}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False

    def rename_default_file(self, old_name: str, new_name: str) -> bool:
        """Rename a file in the default workspace."""
        default_dir = self.base_dir / "default"
        old_path = (default_dir / old_name).resolve()
        new_path = (default_dir / new_name).resolve()

        # Security checks
        if not _is_within(old_path, default_dir):
            return False
        if not _is_within(new_path, default_dir):
            return False

        if not old_path.exists():
            return False
        if new_path.exists():
            return False

        try:
            old_path.rename(new_path)
            logger.info(f"Renamed default file: {old_name} -> {new_name}")
            return True
        except Exception as e:
            logger.error(f"Error renaming file: {e}")
            return False
    
    def rename_file(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int,
        old_name: str,
        new_name: str
    ) -> bool:
        """
        Rename a file in the task workspace.

        Args:
            project_id: Project ID
            workflow_id: Workflow ID
            task_id: Task ID
            old_name: Current filename
            new_name: New filename

        Returns:
            True if renamed successfully, False otherwise
        """
        workspace = self.get_task_workspace(project_id, workflow_id, task_id)
        old_path = (workspace / old_name).resolve()
        new_path = (workspace / new_name).resolve()

        # Security: Ensure both paths are within workspace
        if not _is_within(old_path, workspace):
            logger.warning(f"Path traversal attempt blocked (old): {old_name}")
            return False
        if not _is_within(new_path, workspace):
            logger.warning(f"Path traversal attempt blocked (new): {new_name}")
            return False

        if not old_path.exists():
            logger.warning(f"File not found: {old_path}")
            return False

        if new_path.exists():
            logger.warning(f"Target file already exists: {new_path}")
            return False

        try:
            old_path.rename(new_path)
            logger.info(f"Renamed file: {old_name} -> {new_name}")
            return True
        except Exception as e:
            logger.error(f"Error renaming file: {e}")
            return False

    def delete_file(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int,
        filename: str
    ) -> bool:
        """
        Delete a file from the task workspace.

        Args:
            project_id: Project ID
            workflow_id: Workflow ID
            task_id: Task ID
            filename: Filename to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        file_path = self.get_file_path(project_id, workflow_id, task_id, filename)

        if not file_path:
            logger.warning(f"File not found or invalid path: {filename}")
            return False

        try:
            file_path.unlink()
            logger.info(f"Deleted file: {filename}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False

    def get_file_content(
        self,
        project_id: Optional[int],
        workflow_id: int,
        task_id: int,
        filename: str,
        max_size: int = 1024 * 1024  # 1MB default limit
    ) -> Optional[dict]:
        """
        Get the content of a file for preview.

        Args:
            project_id: Project ID
            workflow_id: Workflow ID
            task_id: Task ID
            filename: Filename to read
            max_size: Maximum file size to read (default 1MB)

        Returns:
            Dict with content, mime_type, truncated flag, or None if not found
        """
        file_path = self.get_file_path(project_id, workflow_id, task_id, filename)

        if not file_path:
            return None

        # Determine mime type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "text/plain"

        # Check if it's a text-based file we can preview
        text_types = [
            "text/", "application/json", "application/javascript",
            "application/xml", "application/yaml", "application/x-yaml"
        ]
        is_text = any(mime_type.startswith(t) for t in text_types)

        # Check file extension for common text files
        text_extensions = {
            '.md', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
            '.yaml', '.yml', '.xml', '.html', '.css', '.scss', '.sql',
            '.sh', '.bash', '.env', '.gitignore', '.csv', '.toml', '.ini',
            '.cfg', '.conf', '.log', '.rst', '.tex'
        }
        if file_path.suffix.lower() in text_extensions:
            is_text = True

        if not is_text:
            return {
                "content": None,
                "mime_type": mime_type,
                "is_binary": True,
                "truncated": False,
                "size_bytes": file_path.stat().st_size
            }

        try:
            file_size = file_path.stat().st_size
            truncated = file_size > max_size

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(max_size)

            return {
                "content": content,
                "mime_type": mime_type,
                "is_binary": False,
                "truncated": truncated,
                "size_bytes": file_size
            }
        except Exception as e:
            logger.error(f"Error reading file content: {e}")
            return None

    def list_all_files(
        self,
        project_id: Optional[int] = None,
        workflow_id: Optional[int] = None,
        search: Optional[str] = None,
        file_type: Optional[str] = None
    ) -> List[dict]:
        """
        List all files across projects/workflows.

        Args:
            project_id: Filter by project ID (optional)
            workflow_id: Filter by workflow ID (optional)
            search: Search term for filename (optional)
            file_type: Filter by file extension (optional)

        Returns:
            List of file info dicts with project/workflow/task context
        """
        all_files = []
        logger.info(f"Listing all files from base_dir: {self.base_dir}")

        def add_file(file_path: Path, proj_id: Optional[int], wf_id: Optional[int], t_id: Optional[int]):
            """Helper to add a file to the list with filters applied"""
            if not file_path.is_file():
                return

            # Apply filters
            if search and search.lower() not in file_path.name.lower():
                return

            if file_type and file_path.suffix.lower() != f".{file_type.lower()}":
                return

            try:
                stat = file_path.stat()
                all_files.append({
                    "filename": file_path.name,
                    "path": str(file_path.relative_to(self.base_dir)),
                    "full_path": str(file_path),
                    "project_id": proj_id,
                    "workflow_id": wf_id,
                    "task_id": t_id,
                    "size_bytes": stat.st_size,
                    "size_human": self._format_size(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "extension": file_path.suffix,
                })
            except Exception as e:
                logger.warning(f"Could not stat file {file_path}: {e}")

        # Check if base_dir exists
        if not self.base_dir.exists():
            logger.warning(f"Base directory does not exist: {self.base_dir}")
            return all_files

        # First, scan for files directly in outputs/ (root level)
        if not project_id and not workflow_id:
            for item in self.base_dir.iterdir():
                if item.is_file():
                    add_file(item, None, None, None)

        # Determine which directories to scan
        if project_id:
            scan_dirs = [self.base_dir / f"project_{project_id}"]
        else:
            # Scan all subdirectories
            scan_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]

        logger.info(f"list_all_files: Scanning directories: {[str(d) for d in scan_dirs]}")

        for project_dir in scan_dirs:
            if not project_dir.exists():
                continue

            # Extract project ID from folder name
            proj_name = project_dir.name
            proj_id = None

            if proj_name.startswith("project_"):
                try:
                    proj_id = int(proj_name.replace("project_", ""))
                except ValueError:
                    logger.warning(f"Skipping malformed project directory: {proj_name}")
                    continue
            elif proj_name in ("standalone", "default"):
                proj_id = None
            else:
                # Skip unknown directories at project level
                continue

            # For default folder, scan files directly (not in workflow/task structure)
            if proj_name == "default":
                for file_path in project_dir.iterdir():
                    add_file(file_path, None, None, None)
                continue

            # For project folders, scan workflow directories
            for workflow_dir in project_dir.iterdir():
                if not workflow_dir.is_dir():
                    # Could be a file directly in project folder
                    add_file(workflow_dir, proj_id, None, None)
                    continue

                if not workflow_dir.name.startswith("workflow_"):
                    continue

                # Extract workflow ID - handle "workflow_None" case
                wf_id_str = workflow_dir.name.replace("workflow_", "")
                if wf_id_str == "None" or wf_id_str == "":
                    wf_id = None
                else:
                    try:
                        wf_id = int(wf_id_str)
                    except ValueError:
                        logger.warning(f"Skipping malformed workflow directory: {workflow_dir.name}")
                        continue

                # Filter by workflow_id if specified
                if workflow_id and wf_id != workflow_id:
                    continue

                # Scan task directories
                for task_dir in workflow_dir.iterdir():
                    if not task_dir.is_dir():
                        # Could be a file directly in workflow folder
                        add_file(task_dir, proj_id, wf_id, None)
                        continue

                    if not task_dir.name.startswith("task_"):
                        continue

                    try:
                        t_id = int(task_dir.name.replace("task_", ""))
                    except ValueError:
                        logger.warning(f"Skipping malformed task directory: {task_dir.name}")
                        continue

                    # List files in this task
                    for file_path in task_dir.iterdir():
                        if file_path.is_file():
                            logger.debug(f"Found file: {file_path} (project={proj_id}, workflow={wf_id}, task={t_id})")
                            add_file(file_path, proj_id, wf_id, t_id)

        logger.info(f"list_all_files: Found {len(all_files)} files total")

        # Sort by modification time (newest first)
        all_files.sort(key=lambda x: x['modified_at'], reverse=True)
        return all_files

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes as human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


# Global instance
_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    """Get or create global workspace manager instance"""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


def reset_workspace_manager() -> None:
    """Drop the cached singleton so the next get_workspace_manager() call
    re-resolves the base dir. Call after the user changes the workspace path
    (Settings / first-run setup) so the new root takes effect immediately."""
    global _workspace_manager
    _workspace_manager = None
