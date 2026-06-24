# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
AGENTS.md API routes — read/write project AGENTS.md files for MemoryMiddleware.

Endpoints:
    GET    /api/projects/{project_id}/agents-md       — get current content
    PUT    /api/projects/{project_id}/agents-md       — update content
    DELETE /api/projects/{project_id}/agents-md       — delete file (resets to default on next agent run)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.agents_md_service import (
    delete_agents_md,
    read_agents_md,
    write_agents_md,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["agents-md"])


class AGENTSMDResponse(BaseModel):
    """Response for GET /api/projects/{id}/agents-md"""
    project_id: int
    content: str
    exists: bool


class AGENTSMDUpdate(BaseModel):
    """Request body for PUT /api/projects/{id}/agents-md"""
    content: str = Field(..., min_length=0, max_length=1_000_000)


class AGENTSMDDeleteResponse(BaseModel):
    """Response for DELETE /api/projects/{id}/agents-md"""
    project_id: int
    deleted: bool


@router.get("/{project_id}/agents-md", response_model=AGENTSMDResponse)
async def get_agents_md(project_id: int) -> AGENTSMDResponse:
    """Get the AGENTS.md content for a project.

    Returns the current content (or empty string if not yet created).
    The `exists` field tells you whether the file actually exists on disk.
    """
    content = read_agents_md(project_id)
    return AGENTSMDResponse(
        project_id=project_id,
        content=content or "",
        exists=content is not None,
    )


@router.put("/{project_id}/agents-md", response_model=AGENTSMDResponse)
async def update_agents_md(project_id: int, body: AGENTSMDUpdate) -> AGENTSMDResponse:
    """Update the AGENTS.md content for a project.

    Creates the file if it doesn't exist. The next time a DeepAgent runs
    for this project, it will load this content into its system prompt.
    """
    try:
        write_agents_md(project_id, body.content)
    except Exception as e:
        logger.error(f"Failed to write AGENTS.md for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write AGENTS.md: {e}")

    return AGENTSMDResponse(
        project_id=project_id,
        content=body.content,
        exists=True,
    )


@router.delete("/{project_id}/agents-md", response_model=AGENTSMDDeleteResponse)
async def delete_project_agents_md(project_id: int) -> AGENTSMDDeleteResponse:
    """Delete the AGENTS.md file for a project.

    The next time a DeepAgent runs, a default AGENTS.md will be created.
    """
    deleted = delete_agents_md(project_id)
    return AGENTSMDDeleteResponse(project_id=project_id, deleted=deleted)
