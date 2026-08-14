# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
AGENTS.md Service — manages per-project AGENTS.md files for MemoryMiddleware.

The deepagents library's MemoryMiddleware loads AGENTS.md files (per the
agents.md spec) and injects them into the system prompt. Each project gets
its own AGENTS.md file stored on the filesystem at:

    {WORKSPACE_ROOT}/projects/{project_id}/AGENTS.md

Files are git-friendly Markdown. Agents can read/edit them via the
`read_file` / `edit_file` tools (provided by FilesystemMiddleware).

This service provides:
- get_agents_md_path(project_id) -> Path
- read_agents_md(project_id) -> str
- write_agents_md(project_id, content) -> None
- delete_agents_md(project_id) -> None
- ensure_agents_md_exists(project_id) -> Path (creates default if missing)
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default workspace root - can be overridden via env var
# LANGCONFIG_WORKSPACE_ROOT (default: backend/.workspace_data). Like the
# BUILTIN_SKILLS_ROOT / PERSONAL_SKILLS_ROOT env vars, a relative value is
# anchored at the project root (repo root), not the process CWD.
_BACKEND_DIR = Path(__file__).resolve().parent.parent  # services/ -> backend/
_PROJECT_ROOT = _BACKEND_DIR.parent

_env_workspace_root = os.getenv("LANGCONFIG_WORKSPACE_ROOT")
if _env_workspace_root:
    _p = Path(_env_workspace_root).expanduser()
    if not _p.is_absolute():
        _p = _PROJECT_ROOT / _p
    WORKSPACE_ROOT = _p.resolve()
else:
    WORKSPACE_ROOT = _BACKEND_DIR / ".workspace_data"

# Default content for a new AGENTS.md
DEFAULT_AGENTS_MD = """# Project {project_id} Conventions

**Project ID: {project_id}**

<!-- This file is loaded into every DeepAgent's system prompt via MemoryMiddleware. -->
<!-- Edit it to share project-level context (build commands, code style, architecture, etc.) -->
<!-- Agents can also update it at runtime via the `edit_file` tool. -->

## Overview

(Add a brief project overview here)

## Build & Test

(Add common build/test commands)

## Code Style

(Add code conventions)
"""


def _project_vault_key(project_id: int) -> str:
    """Folder key for a project: its user-visible ``number`` when set, else
    the DB ``id`` (consistent with WorkspaceManager.project_vault_key)."""
    try:
        from db.database import SessionLocal
        from models.core import Project
        db = SessionLocal()
        try:
            row = db.get(Project, project_id)
            if row is not None and row.number:
                return str(row.number)
        finally:
            db.close()
    except Exception:
        pass
    return str(project_id)


def get_agents_md_path(project_id: int) -> Path:
    """Get the filesystem path for a project's AGENTS.md.

    Does NOT create the file. Use ensure_agents_md_exists() for that.
    """
    return WORKSPACE_ROOT / "projects" / _project_vault_key(project_id) / "AGENTS.md"


def ensure_agents_md_exists(project_id: int) -> Path:
    """Ensure the project's AGENTS.md file exists, creating a default if needed.

    Returns the path to the file. Safe to call multiple times.
    """
    path = get_agents_md_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Include project_id so the DeepAgent knows which project it's
        # working on without having to infer it from context.
        content = DEFAULT_AGENTS_MD.replace("{project_id}", str(project_id))
        path.write_text(content, encoding="utf-8")
        logger.info(f"Created default AGENTS.md for project {project_id} at {path}")
    return path


def read_agents_md(project_id: int) -> Optional[str]:
    """Read a project's AGENTS.md content. Returns None if not found."""
    path = get_agents_md_path(project_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_agents_md(project_id: int, content: str) -> Path:
    """Write content to a project's AGENTS.md. Creates the file if needed.

    Returns the path that was written.
    """
    path = ensure_agents_md_exists(project_id)
    path.write_text(content, encoding="utf-8")
    logger.info(f"Updated AGENTS.md for project {project_id} ({len(content)} chars)")
    return path


def delete_agents_md(project_id: int) -> bool:
    """Delete a project's AGENTS.md. Returns True if deleted, False if not found."""
    path = get_agents_md_path(project_id)
    if path.exists():
        path.unlink()
        logger.info(f"Deleted AGENTS.md for project {project_id}")
        return True
    return False
