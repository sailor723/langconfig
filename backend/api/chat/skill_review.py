"""
Skill Review API — allows user to review, edit, approve, or reject
auto-generated .skill.md companion files before they enter the agent context.

Endpoints:
    GET    /api/chat/{session_id}/skill-pending/{csv_stem}
           Returns the pending .skill.md content as plain text.

    POST   /api/chat/{session_id}/skill-pending/{csv_stem}
           Body: {"action": "approve" | "edit" | "reject"}
                 {"action": "edit", "content": "edited markdown..."}
           Approves, replaces, or rejects the pending companion.
"""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from services.workspace_manager import get_workspace_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class SkillReviewAction(BaseModel):
    action: Literal["approve", "edit", "reject"]
    content: Optional[str] = None  # Required for "edit"


def _sanitize_csv_stem(csv_stem: str) -> str:
    """Validate a csv_stem path segment.

    csv_stem arrives from the URL and is interpolated into sandbox file
    names. Reject anything that could escape the sandbox directory:
    separators, traversal components, absolute paths, and empty/whitespace.
    """
    if not csv_stem or csv_stem != csv_stem.strip():
        raise HTTPException(status_code=400, detail="csv_stem must not be empty")
    if "/" in csv_stem or "\\" in csv_stem or ".." in csv_stem:
        raise HTTPException(
            status_code=400,
            detail="csv_stem must be a plain file name (no separators or '..')",
        )
    if csv_stem in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid csv_stem")
    return csv_stem


def _get_sandbox_dir() -> Path:
    """Get the sandbox base directory."""
    ws_mgr = get_workspace_manager()
    return ws_mgr.base_dir / "default"


def _pending_path(csv_stem: str) -> Path:
    return _get_sandbox_dir() / f"{csv_stem}.skill.md.pending"


def _active_path(csv_stem: str) -> Path:
    return _get_sandbox_dir() / f"{csv_stem}.skill.md"


def _resolve_inside_sandbox(path: Path) -> Path:
    """Resolve path and assert it stays inside the sandbox dir.

    Defense in depth: even after sanitizing csv_stem, confirm the final
    resolved path is still within the sandbox (catches symlink tricks and
    any future caller that skips validation).
    """
    resolved = path.resolve()
    sandbox = _get_sandbox_dir().resolve()
    if not resolved.is_relative_to(sandbox):
        raise HTTPException(
            status_code=400,
            detail="Invalid path: must stay within the skill sandbox",
        )
    return resolved


@router.get("/api/chat/{session_id}/skill-pending/{csv_stem}")
async def get_pending_skill(session_id: str, csv_stem: str):
    """Return the auto-generated .skill.md.pending content for review."""
    csv_stem = _sanitize_csv_stem(csv_stem)
    pending = _resolve_inside_sandbox(_pending_path(csv_stem))
    if not pending.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No pending skill found for '{csv_stem}'. "
                   f"Upload a CSV file first to generate one."
        )
    content = pending.read_text(encoding="utf-8")
    return {
        "csv_stem": csv_stem,
        "content": content,
        "status": "pending",
    }


@router.post("/api/chat/{session_id}/skill-pending/{csv_stem}")
async def review_pending_skill(session_id: str, csv_stem: str, body: SkillReviewAction):
    """Approve, edit, or reject the auto-generated .skill.md companion."""
    csv_stem = _sanitize_csv_stem(csv_stem)
    pending = _resolve_inside_sandbox(_pending_path(csv_stem))
    active = _resolve_inside_sandbox(_active_path(csv_stem))

    if not pending.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No pending skill found for '{csv_stem}'. "
                   f"Upload a CSV file first to generate one."
        )

    if body.action == "approve":
        # Rename .skill.md.pending -> .skill.md
        pending.rename(active)
        logger.info(f"User approved companion skill: {csv_stem}.skill.md")
        return {
            "status": "approved",
            "csv_stem": csv_stem,
            "file": str(active),
        }

    elif body.action == "edit":
        if not body.content:
            raise HTTPException(
                status_code=400,
                detail="'content' field is required when action='edit'."
            )
        # Write user's edited content as .skill.md, remove pending
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(body.content, encoding="utf-8")
        if pending.exists():
            pending.unlink()
        logger.info(f"User edited companion skill: {csv_stem}.skill.md")
        return {
            "status": "edited",
            "csv_stem": csv_stem,
            "file": str(active),
        }

    elif body.action == "reject":
        # Delete the pending file
        pending.unlink()
        logger.info(f"User rejected companion skill: {csv_stem}.skill.md.pending")
        return {
            "status": "rejected",
            "csv_stem": csv_stem,
        }

    raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")
