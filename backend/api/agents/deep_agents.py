# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
API endpoints for DeepAgent configuration and management.
"""

import logging
import json
import os as _os
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from starlette.responses import Response, FileResponse

# Repo root — used by the codegen endpoint so generated scripts know where
# to find langconfig modules, even when run from a different directory.
_CODEGEN_REPO_ROOT = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "..")
)
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from pydantic import BaseModel

from db.database import get_db
from models.deep_agent import (
    DeepAgentTemplate,
    AgentExport,
    DeepAgentConfig,
    SubAgentConfig,
    MiddlewareConfig,
    BackendConfig,
    GuardrailsConfig,
    create_default_middleware_config,
    create_default_backend_config,
    create_default_guardrails_config,
)
from services.export_service import ExportService
from core.versioning import check_version_conflict, format_lock_version_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deepagents", tags=["deepagents"])


def _merge_skill_subagents(config: dict, db: Session) -> list:
    """
    Generate skill subagents from config.skills and merge into subagents_config.

    Skill subagents are generated dynamically at runtime (see deepagent_factory.py).
    This helper ensures they appear in the API response so the UI can display/edit them.
    """
    from models.skill import Skill as SkillModel

    skill_ids = config.get("skills", [])
    if not skill_ids:
        return config.get("subagents", []) or []

    # Query skills from DB
    skills = db.query(SkillModel).filter(SkillModel.skill_id.in_(skill_ids)).all()
    if not skills:
        return config.get("subagents", []) or []

    # Build skill subagent entries (mirrors deepagent_factory.py lines 447-456)
    skill_subagent_entries = []
    for s in skills:
        skill_subagent_entries.append({
            "name": s.skill_id,
            "description": s.description,
            "system_prompt": (
                f"You are a {s.skill_id} specialist. "
                "Read the SKILL.md and follow its instructions exactly. "
                "Return only the result."
            ),
        })

    # Merge with existing subagents (skill subagents take priority / dedup by name)
    existing_names = {s["name"] for s in skill_subagent_entries}
    merged = list(skill_subagent_entries)
    for s in (config.get("subagents", []) or []):
        if s.get("name") not in existing_names:
            merged.append(s)

    return merged


def _ensure_deep_agent_config(config: dict, db: Session = None) -> dict:
    """
    Ensure config has use_deepagents=true for DeepAgents.

    DeepAgents in the deep_agent_templates table should ALWAYS have
    use_deepagents=True, even if stored incorrectly in the database.
    This fixes frontend compatibility issues.

    For regular (non-deep) agents, use_deepagents is explicitly set to False
    and should be respected.

    If db is provided, also injects dynamic skill subagents into config.subagents.
    """
    config = dict(config)  # Make a copy to avoid mutating
    # BUGFIX: Previously this respected config.use_deepagents=False, but for deep
    # agents in deep_agent_templates table, the flag is sometimes incorrectly
    # saved as False in the DB. ALWAYS force True here to match the original
    # upstream fix from commit 3efc2bf — this is what enables native_tools
    # (web_search, tavily_search, web_fetch) to be loaded.
    config["use_deepagents"] = True
    # Inject merged skill subagents into config.subagents so frontend builder can see them
    if db is not None:
        merged = _merge_skill_subagents(config, db)
        config["subagents"] = merged
    return config

# =============================================================================
# Request/Response Models
# =============================================================================

class CreateDeepAgentRequest(BaseModel):
    """Request to create a new DeepAgent."""
    name: str
    description: Optional[str] = None
    category: str
    config: DeepAgentConfig
    base_template_id: Optional[str] = None


class UpdateDeepAgentRequest(BaseModel):
    """Request to update a DeepAgent."""
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[DeepAgentConfig] = None
    lock_version: Optional[int] = None  # For optimistic locking


class DeepAgentResponse(BaseModel):
    """Response with DeepAgent details."""
    id: int
    name: str
    description: Optional[str]
    category: str
    config: dict
    middleware_config: list
    subagents_config: list
    subagents: list = []  # Alias for subagents_config for frontend compatibility
    backend_config: dict
    guardrails_config: dict
    usage_count: int
    version: str  # Semantic version (e.g., "1.0.0")
    lock_version: int  # Optimistic locking version
    is_public: bool
    chat_sessions_count: Optional[int] = 0  # Number of chat sessions for this agent
    created_at: str
    updated_at: str
    # Always true for DeepAgents - helps frontend identify this as a DeepAgent
    use_deepagents: bool = True

    class Config:
        from_attributes = True


class ExportRequest(BaseModel):
    """Request to export a DeepAgent."""
    export_type: str  # 'standalone' or 'langconfig'
    include_chat_ui: bool = True
    include_docker: bool = False


class ExportResponse(BaseModel):
    """Response with export details."""
    export_id: int
    export_type: str
    file_path: Optional[str]
    download_url: Optional[str]
    created_at: str
    task_id: Optional[int] = None  # Background task ID
    status: Optional[str] = None  # Export status (pending, in_progress, completed, failed)


# =============================================================================
# CRUD Endpoints
# =============================================================================

def _resolve_model(config: DeepAgentConfig, db: Session) -> Optional[str]:
    """Resolve model from config or read default_model from DB settings (PostgreSQL)."""
    if config.model:
        return config.model
    from models.settings import Settings
    settings = db.query(Settings).filter(Settings.id == 1).first()
    return settings.default_model if settings else None


@router.post("/", response_model=DeepAgentResponse)
async def create_deepagent(
    request: CreateDeepAgentRequest,
    db: Session = Depends(get_db)
):
    """Create a new DeepAgent template."""
    try:
        config_dict = request.config.dict()
        config_dict["model"] = config_dict.get("model") or _resolve_model(request.config, db)

        agent = DeepAgentTemplate(
            name=request.name,
            description=request.description,
            category=request.category,
            base_template_id=request.base_template_id,
            config=config_dict,
            middleware_config=[m.dict() for m in request.config.middleware],
            subagents_config=[s.dict() for s in request.config.subagents],
            backend_config=request.config.backend.dict(),
            guardrails_config=request.config.guardrails.dict(),
        )

        db.add(agent)
        db.commit()
        db.refresh(agent)

        logger.info(f"Created DeepAgent: {agent.name} (id={agent.id})")

        cfg = _ensure_deep_agent_config(agent.config, db=db)
        merged_subs = cfg.get("subagents", [])
        return DeepAgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            category=agent.category,
            config=cfg,
            middleware_config=agent.middleware_config,
            subagents_config=merged_subs,
            subagents=merged_subs,
            backend_config=agent.backend_config,
            guardrails_config=agent.guardrails_config,
            usage_count=agent.usage_count,
            version=agent.version,
            lock_version=agent.lock_version,
            is_public=agent.is_public,
            created_at=agent.created_at.isoformat(),
            updated_at=agent.updated_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Error creating DeepAgent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[DeepAgentResponse])
async def list_deepagents(
    category: Optional[str] = None,
    public_only: bool = True,
    db: Session = Depends(get_db)
):
    """List all DeepAgent templates."""
    try:
        query = db.query(DeepAgentTemplate)

        if public_only:
            query = query.filter(DeepAgentTemplate.is_public == True)

        if category:
            query = query.filter(DeepAgentTemplate.category == category)

        agents = query.order_by(DeepAgentTemplate.created_at.desc()).all()

        # Get chat session counts for each agent
        from models.deep_agent import ChatSession
        from sqlalchemy import func

        session_counts = {}
        for agent in agents:
            count = db.query(func.count(ChatSession.id)).filter(
                ChatSession.agent_id == agent.id
            ).scalar()
            session_counts[agent.id] = count or 0

        def _build_response(agent):
            cfg = _ensure_deep_agent_config(agent.config, db=db)
            merged_subs = cfg.get("subagents", [])
            return DeepAgentResponse(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                category=agent.category,
                config=cfg,
                middleware_config=agent.middleware_config,
                subagents_config=merged_subs,
                subagents=merged_subs,
                backend_config=agent.backend_config,
                guardrails_config=agent.guardrails_config,
                usage_count=agent.usage_count,
                version=agent.version,
                lock_version=agent.lock_version,
                is_public=agent.is_public,
                chat_sessions_count=session_counts.get(agent.id, 0),
                created_at=agent.created_at.isoformat(),
                updated_at=agent.updated_at.isoformat()
            )

        return [_build_response(a) for a in agents]

    except Exception as e:
        logger.error(f"Error listing DeepAgents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}", response_model=DeepAgentResponse)
async def get_deepagent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific DeepAgent by ID."""
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()

    if not agent:
        raise HTTPException(status_code=404, detail="DeepAgent not found")

    # Get chat session count
    from models.deep_agent import ChatSession
    from sqlalchemy import func

    session_count = db.query(func.count(ChatSession.id)).filter(
        ChatSession.agent_id == agent.id
    ).scalar() or 0

    cfg = _ensure_deep_agent_config(agent.config, db=db)
    merged_subs = cfg.get("subagents", [])
    return DeepAgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        category=agent.category,
        config=cfg,
        middleware_config=agent.middleware_config,
        subagents_config=merged_subs,
        subagents=merged_subs,
        backend_config=agent.backend_config,
        guardrails_config=agent.guardrails_config,
        usage_count=agent.usage_count,
        version=agent.version,
        lock_version=agent.lock_version,
        is_public=agent.is_public,
        chat_sessions_count=session_count,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat()
    )


@router.put("/{agent_id}", response_model=DeepAgentResponse)
async def update_deepagent(
    agent_id: int,
    request: UpdateDeepAgentRequest,
    db: Session = Depends(get_db)
):
    """Update a DeepAgent template."""
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()

    if not agent:
        raise HTTPException(status_code=404, detail="DeepAgent not found")

    # Optimistic locking - check lock version conflict
    if request.lock_version is not None:
        if check_version_conflict(agent, request.lock_version):
            error_msg = format_lock_version_error(
                "DeepAgent",
                agent_id,
                request.lock_version,
                agent.lock_version
            )
            raise HTTPException(status_code=409, detail=error_msg)

    # Update fields
    if request.name:
        agent.name = request.name
    if request.description:
        agent.description = request.description
    if request.config:
        # Preserve prompt assembly fields that the Builder doesn't manage
        old_config = agent.config or {}
        custom_prompt = old_config.get("custom_prompt")
        custom_suffix = old_config.get("custom_suffix")

        # Only overwrite fields that were explicitly provided in the request
        new_config = request.config.model_dump(exclude_unset=True)

        # Resolve model: respect explicit request, fall back to DB settings or existing config
        if "model" in new_config and new_config["model"] is not None:
            pass  # Use the model from the request
        elif "model" not in new_config:
            new_config["model"] = old_config.get("model") or _resolve_model(request.config, db)

        # Merge: start from existing config, apply only the provided fields
        merged_config = dict(old_config)
        merged_config.update(new_config)
        agent.config = merged_config

        # Merge back prompt assembly fields
        if custom_prompt:
            agent.config["custom_prompt"] = custom_prompt
        if custom_suffix:
            agent.config["custom_suffix"] = custom_suffix

        flag_modified(agent, "config")

        agent.middleware_config = [m.dict() for m in request.config.middleware]
        agent.subagents_config = [s.dict() for s in request.config.subagents]
        agent.backend_config = request.config.backend.dict()
        agent.guardrails_config = request.config.guardrails.dict()

    db.commit()
    db.refresh(agent)

    logger.info(f"Updated DeepAgent: {agent.name} (id={agent.id})")

    cfg = _ensure_deep_agent_config(agent.config, db=db)
    merged_subs = cfg.get("subagents", [])
    return DeepAgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        category=agent.category,
        config=cfg,
        middleware_config=agent.middleware_config,
        subagents_config=merged_subs,
        subagents=merged_subs,
        backend_config=agent.backend_config,
        guardrails_config=agent.guardrails_config,
        usage_count=agent.usage_count,
        version=agent.version,
        lock_version=agent.lock_version,
        is_public=agent.is_public,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat()
    )


@router.delete("/{agent_id}")
async def delete_deepagent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    """Delete a DeepAgent template."""
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()

    if not agent:
        raise HTTPException(status_code=404, detail="DeepAgent not found")

    db.delete(agent)
    db.commit()

    logger.info(f"Deleted DeepAgent: {agent.name} (id={agent_id})")

    return {"status": "success", "message": f"DeepAgent {agent_id} deleted"}


# =============================================================================
# Agent Creator workflow support
# =============================================================================

CREATOR_OUTPUT_PATH = "/tmp/agent_creator_output.json"

class CreatorOutput(BaseModel):
    """Agent Creator saved config format (simplified)."""
    name: str
    category: Optional[str] = "Custom"
    description: Optional[str] = ""
    config: dict

@router.post("/from-creator")
async def create_from_agent_creator(
    db: Session = Depends(get_db)
):
    """
    Create a DeepAgent from the Agent Creator's saved output file.
    Reads /tmp/agent_creator_output.json and creates the agent.
    """
    try:
        if not _os.path.exists(CREATOR_OUTPUT_PATH):
            raise HTTPException(status_code=404, detail="No Agent Creator output found. Run Agent Creator first.")

        with open(CREATOR_OUTPUT_PATH, "r") as f:
            raw = json.load(f)

        data = CreatorOutput(**raw)

        # Build full config with defaults
        cfg = data.config
        full_config = DeepAgentConfig(
            model=cfg.get("model", "minimax-m3"),
            system_prompt=cfg.get("system_prompt", ""),
            native_tools=cfg.get("native_tools", ["web_search", "web_fetch"]),
            skills=cfg.get("skills", []),
            tools=cfg.get("tools", []),
            cli_tools=cfg.get("cli_tools", []),
            custom_tools=cfg.get("custom_tools", []),
            temperature=cfg.get("temperature", 0.7),
            use_deepagents=True,
            middleware=create_default_middleware_config(),
            subagents=[],
            backend=create_default_backend_config(),
            guardrails=create_default_guardrails_config(),
        )

        agent = DeepAgentTemplate(
            name=data.name,
            description=data.description,
            category=data.category or "Custom",
            config=full_config.dict(),
            middleware_config=[m.dict() for m in full_config.middleware],
            subagents_config=[],
            backend_config=full_config.backend.dict(),
            guardrails_config=full_config.guardrails.dict(),
        )

        db.add(agent)
        db.commit()
        db.refresh(agent)

        # Remove the temp file
        _os.remove(CREATOR_OUTPUT_PATH)

        logger.info(f"Agent Creator created DeepAgent: {agent.name} (id={agent.id})")

        return {
            "status": "success",
            "message": f"Agent '{data.name}' created successfully (id={agent.id})",
            "agent_id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "category": agent.category,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create from Agent Creator: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Prompt Assembly Preview
# =============================================================================

class PromptPreviewRequest(BaseModel):
    model: str = "deepseek:chat"
    system_prompt: Optional[str] = None
    custom_prompt: Optional[str] = None  # Replaces BASE with CUSTOM
    custom_suffix: Optional[str] = None  # Appended as SUFFIX after BASE/CUSTOM


class PromptSegment(BaseModel):
    name: str  # USER, BASE, CUSTOM, SUFFIX
    source: str  # "user_input", "sdk_default", "harness_profile", "custom"
    content: str
    editable: bool = False


class PromptPreviewResponse(BaseModel):
    segments: list[PromptSegment]
    assembled: str


@router.post("/prompt-preview", response_model=PromptPreviewResponse)
async def preview_prompt_assembly(request: PromptPreviewRequest):
    """
    Preview how the system prompt will be assembled from its components.

    The prompt assembly follows this order:
      USER → (BASE or CUSTOM) → SUFFIX

    Returns each segment separately plus the fully assembled prompt.
    Accepts optional custom_prompt (to replace BASE) and custom_suffix (appended last).
    """
    try:
        from deepagents.graph import BASE_AGENT_PROMPT
        from deepagents.profiles.harness.harness_profiles import (
            _harness_profile_for_model,
            _apply_profile_prompt,
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="DeepAgents SDK not available")

    segments = []
    profile = _harness_profile_for_model(request.model, None)
    has_base_override = profile.base_system_prompt is not None
    has_suffix = profile.system_prompt_suffix is not None

    # 1. USER segment
    user_content = request.system_prompt or ""
    if user_content:
        segments.append(PromptSegment(
            name="USER",
            source="user_input",
            content=user_content,
            editable=True,
        ))

    # Determine base content: CUSTOM (user override) > profile CUSTOM > SDK BASE
    if request.custom_prompt:
        # User provided custom prompt → CUSTOM segment, replaces BASE
        base_content = request.custom_prompt
        segments.append(PromptSegment(
            name="CUSTOM",
            source="custom",
            content=base_content,
            editable=True,
        ))
    elif has_base_override:
        base_content = profile.base_system_prompt
        segments.append(PromptSegment(
            name="CUSTOM",
            source="harness_profile",
            content=base_content,
            editable=False,
        ))
    else:
        base_content = BASE_AGENT_PROMPT
        segments.append(PromptSegment(
            name="BASE",
            source="sdk_default",
            content=base_content,
            editable=False,
        ))

    # 3. SUFFIX segment
    if request.custom_suffix:
        segments.append(PromptSegment(
            name="SUFFIX",
            source="custom",
            content=request.custom_suffix,
            editable=True,
        ))
    elif has_suffix:
        segments.append(PromptSegment(
            name="SUFFIX",
            source="harness_profile",
            content=profile.system_prompt_suffix,
            editable=False,
        ))

    # Assemble the final prompt
    parts = []
    if user_content:
        parts.append(user_content)
    if request.custom_prompt:
        parts.append(request.custom_prompt)
    else:
        base_for_assembly = _apply_profile_prompt(profile, BASE_AGENT_PROMPT)
        parts.append(base_for_assembly)
    if request.custom_suffix:
        parts.append(request.custom_suffix)
    elif has_suffix:
        parts.append(profile.system_prompt_suffix)

    assembled = "\n\n".join(parts)

    return PromptPreviewResponse(segments=segments, assembled=assembled)


# =============================================================================
# Save Prompt to Agent
# =============================================================================

class SavePromptRequest(BaseModel):
    custom_prompt: Optional[str] = None
    custom_suffix: Optional[str] = None


@router.patch("/{agent_id}/prompt")
async def save_agent_prompt(
    agent_id: int,
    request: SavePromptRequest,
    db: Session = Depends(get_db)
):
    """
    Save custom_prompt and custom_suffix to an existing deep agent's config.
    These fields are used by the factory to assemble the full system prompt.
    """
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()

    if not agent:
        raise HTTPException(status_code=404, detail="DeepAgent not found")

    # Get existing config or create new one
    config = agent.config or {}
    if request.custom_prompt is not None:
        config["custom_prompt"] = request.custom_prompt
    if request.custom_suffix is not None:
        config["custom_suffix"] = request.custom_suffix

    agent.config = config
    flag_modified(agent, "config")
    db.commit()
    db.refresh(agent)

    return {
        "status": "success",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "config": config
    }


# =============================================================================
# Export Endpoints
# =============================================================================

@router.post("/{agent_id}/export", response_model=ExportResponse)
async def export_deepagent(
    agent_id: int,
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Export a DeepAgent as standalone code or .langconfig format.

    Export now runs in background using task queue.
    - Returns immediately with export_id and task_id
    - Client polls /api/background-tasks/{task_id} for status
    - Export record is updated when task completes
    """
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()

    if not agent:
        raise HTTPException(status_code=404, detail="DeepAgent not found")

    try:
        # Create export record with pending status
        export = AgentExport(
            agent_id=agent.id,
            export_type=request.export_type,
            export_config={
                "include_chat_ui": request.include_chat_ui,
                "include_docker": request.include_docker
            }
        )
        db.add(export)
        db.commit()
        db.refresh(export)

        # Enqueue export task (non-blocking)
        from core.task_queue import task_queue, TaskPriority

        task_id = await task_queue.enqueue(
            "export_agent",
            {
                "agent_id": agent.id,
                "export_id": export.id,
                "export_type": request.export_type,
                "export_config": {
                    "include_chat_ui": request.include_chat_ui,
                    "include_docker": request.include_docker
                }
            },
            priority=TaskPriority.NORMAL,
            max_retries=2  # Exports can be expensive, limit retries
        )

        logger.info(
            f"Enqueued export task for DeepAgent {agent.name} (export_id: {export.id}, task_id: {task_id})",
            extra={
                "agent_id": agent.id,
                "export_id": export.id,
                "task_id": task_id,
                "export_type": request.export_type
            }
        )

        return ExportResponse(
            export_id=export.id,
            export_type=export.export_type,
            file_path=None,  # Will be set by background task
            download_url=None,  # Will be available after export completes
            created_at=export.created_at.isoformat(),
            task_id=task_id,
            status="pending"
        )

    except Exception as e:
        logger.error(f"Error exporting DeepAgent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: int,
    db: Session = Depends(get_db)
):
    """Download an exported DeepAgent."""
    from starlette.responses import FileResponse

    export = db.query(AgentExport).filter(AgentExport.id == export_id).first()

    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if not export.file_path or not _os.path.exists(export.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")

    # Update download count
    export.download_count += 1
    import datetime
    export.last_downloaded_at = datetime.datetime.utcnow()
    db.commit()

    return FileResponse(
        export.file_path,
        filename=_os.path.basename(export.file_path),
        media_type="application/octet-stream"
    )


@router.get("/{agent_id}/exports", response_model=List[ExportResponse])
async def list_exports(
    agent_id: int,
    db: Session = Depends(get_db)
):
    """List all exports for a DeepAgent."""
    exports = db.query(AgentExport).filter(
        AgentExport.agent_id == agent_id
    ).order_by(AgentExport.created_at.desc()).all()

    return [
        ExportResponse(
            export_id=export.id,
            export_type=export.export_type,
            file_path=export.file_path,
            download_url=f"/api/deepagents/exports/{export.id}/download",
            created_at=export.created_at.isoformat()
        )
        for export in exports
    ]


# =============================================================================
# Import Endpoint
# =============================================================================

class ImportRequest(BaseModel):
    """Request to import a .langconfig file."""
    langconfig_content: str


@router.post("/import", response_model=DeepAgentResponse)
async def import_langconfig(
    request: ImportRequest,
    db: Session = Depends(get_db)
):
    """Import a DeepAgent from .langconfig format."""
    try:
        import json
        langconfig = json.loads(request.langconfig_content)

        # Validate format
        if langconfig.get("version") != "1.0" or langconfig.get("export_type") != "deepagent":
            raise HTTPException(status_code=400, detail="Invalid .langconfig format")

        agent_data = langconfig["agent"]

        # Create agent
        config_dict = {
            "model": agent_data["model"],
            "temperature": agent_data["temperature"],
            "max_tokens": agent_data.get("max_tokens"),
            "system_prompt": agent_data["system_prompt"],
            "tools": agent_data.get("tools", []),
            "native_tools": agent_data.get("tools", []),  # same list for factory loading
            "mcp_tools": agent_data.get("mcp_tools", []),
            "cli_tools": agent_data.get("cli_tools", []),
            "middleware": agent_data.get("middleware", []),
            "subagents": agent_data.get("subagents", []),
            "backend": agent_data.get("backend", {}),
            "guardrails": agent_data.get("guardrails", {})
        }

        config = DeepAgentConfig(**config_dict)

        agent = DeepAgentTemplate(
            name=agent_data["name"],
            description=agent_data.get("description"),
            category=agent_data.get("category", "research"),
            config=config.dict(),
            middleware_config=[m.dict() for m in config.middleware],
            subagents_config=[s.dict() for s in config.subagents],
            backend_config=config.backend.dict(),
            guardrails_config=config.guardrails.dict(),
            is_community=True  # Mark as imported
        )

        db.add(agent)
        db.commit()
        db.refresh(agent)

        logger.info(f"Imported DeepAgent: {agent.name} (id={agent.id})")

        return DeepAgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            category=agent.category,
            config=_ensure_deep_agent_config(agent.config),
            middleware_config=agent.middleware_config,
            subagents_config=agent.subagents_config,
            subagents=agent.subagents_config,
            backend_config=agent.backend_config,
            guardrails_config=agent.guardrails_config,
            usage_count=agent.usage_count,
            version=agent.version,
            lock_version=agent.lock_version,
            is_public=agent.is_public,
            created_at=agent.created_at.isoformat(),
            updated_at=agent.updated_at.isoformat()
        )

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error importing .langconfig: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}/code")
async def download_agent_code(agent_id: int, db: Session = Depends(get_db)):
    """Download a runnable Python file for this agent.

    The generated code mirrors the backend's actual agent creation exactly:
    - sys.path setup with _REPO_ROOT + _PHASE9_DIR
    - ChatOpenAI with proper env vars (MINIMAX_API_KEY, MINIMAX_API_BASE, etc.)
    - load_native_tools() for tool loading
    - create_deep_agent() for DeepAgents / create_react_agent for regular agents
    - CLI entry point (python agent.py)
    """
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    config = agent.config or {}
    model = config.get("model", "gpt-4o")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens") or 4000
    system_prompt = config.get("system_prompt", "You are a helpful AI assistant.")
    native_tools = config.get("native_tools", [])
    custom_tools = config.get("custom_tools", [])
    middleware = config.get("middleware", [])

    # Determine model provider for env vars
    model_lower = model.lower()
    if model_lower.startswith("minimax"):
        model_import = "from langchain_openai import ChatOpenAI"
        llm_init = f"""
MODEL = os.environ.get("ACTUAL_MODEL", "{model}")
API_KEY = os.environ.get("MINIMAX_API_KEY", "")
BASE_URL = os.environ.get("MINIMAX_API_BASE", "https://api.minimaxi.com/v1")
llm = ChatOpenAI(
    model=MODEL,
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature={temperature},
    max_tokens={max_tokens},
)"""
    elif model_lower.startswith("deepseek"):
        model_import = "from langchain_openai import ChatOpenAI"
        llm_init = f"""
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
llm = ChatOpenAI(
    model="{model}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature={temperature},
    max_tokens={max_tokens},
)"""
    elif model_lower.startswith("agnes"):
        model_import = "from langchain_openai import ChatOpenAI"
        llm_init = f"""
API_KEY = os.environ.get("AGNES_API_KEY", "")
BASE_URL = os.environ.get("AGNES_BASE_URL", "")
llm = ChatOpenAI(
    model="{model}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature={temperature},
    max_tokens={max_tokens},
)"""
    else:
        model_import = "from langchain_openai import ChatOpenAI"
        llm_init = f"""
API_KEY = os.environ.get("OPENAI_API_KEY", "")
llm = ChatOpenAI(
    model="{model}",
    api_key=API_KEY,
    temperature={temperature},
    max_tokens={max_tokens},
)"""

    # Tool loading
    native_tools_lines = ""
    if native_tools:
        native_tools_lines = f"""
# Native tools (graphindex-backed document search)
from tools.native_tools import load_native_tools
tools.extend(load_native_tools({json.dumps(native_tools)}))
"""

    custom_tools_lines = ""
    if custom_tools:
        import_lines = "\n".join(
            f'tools.append(tool_factory.load_custom_tool("{t}"))' for t in custom_tools
        )
        custom_tools_lines = f"""
# Custom tools
from orchestration.tool_factory import ToolFactory
tool_factory = ToolFactory()
{import_lines}
"""

    is_deep = config.get("use_deepagents", False)

    if is_deep:
        build_section = '''
# Build DeepAgent with PostgreSQL checkpointer for conversation persistence
from langgraph.checkpoint.postgres import PostgresSaver
from deepagents import create_deep_agent

checkpointer = PostgresSaver.from_conn_string(
    os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/langconfig")
)
agent = create_deep_agent(
    model=llm,
    system_prompt=system_prompt,
    tools=tools,
    checkpointer=checkpointer,
)
'''
    else:
        build_section = '''
# Build LangGraph agent
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.prebuilt import create_react_agent

checkpointer = PostgresSaver.from_conn_string(
    os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/langconfig")
)
agent = create_react_agent(
    llm,
    tools,
    state_modifier=system_prompt,
    checkpointer=checkpointer,
)
'''

    # Escape single-quotes in system prompt for the generated code
    escaped_prompt = system_prompt.replace("\\", "\\\\").replace("'", "\\'")

    source = (
        '#!/usr/bin/env python3\n'
        f'"""Runnable agent: {agent.name} (generated by LangConfig)\n'
        '\n'
        'Usage:\n'
        '    pip install langchain-openai langgraph python-dotenv\n'
        '    python agent.py\n'
        '"""\n'
        '\n'
        'import os\n'
        'import sys\n'
        '\n'
        '# ── Path setup (mirrors backend/api/chat/routes.py) ──────────────────────\n'
        '# You can override this by setting LANGCFG_ROOT or placing this script\n'
        '# anywhere inside the repo (it walks up looking for backend/).\n'
        f'_REPO_ROOT = r"{_CODEGEN_REPO_ROOT}"\n'
        'if _REPO_ROOT not in sys.path:\n'
        '    sys.path.insert(0, _REPO_ROOT)\n'
        '_BACKEND_DIR = os.path.join(_REPO_ROOT, "backend")\n'
        'if _BACKEND_DIR not in sys.path:\n'
        '    sys.path.insert(0, _BACKEND_DIR)\n'
        '_PHASE9_DIR = os.path.join(_REPO_ROOT, "learning", "phase9")\n'
        'if _PHASE9_DIR not in sys.path and os.path.isdir(_PHASE9_DIR):\n'
        '    sys.path.insert(0, _PHASE9_DIR)\n'
        '\n'
        '# Default project ID for graphindex tools (override via env)\n'
        'if not os.environ.get("GRAPHINDEX_PROJECT_ID"):\n'
        '    os.environ["GRAPHINDEX_PROJECT_ID"] = "1"\n'
        '\n'
        '# ── Env ──────────────────────────────────────────────────────────────────\n'
        'from dotenv import load_dotenv\n'
        '_dotenv_path = os.path.join(_REPO_ROOT, ".env")\n'
        'if os.path.isfile(_dotenv_path):\n'
        '    load_dotenv(_dotenv_path)\n'
        'else:\n'
        '    load_dotenv()\n'
        '\n'
        f'{model_import}\n'
        '\n'
        '# ── 1. LLM ──────────────────────────────────────────────────────────────\n'
        f'{llm_init}\n'
        '\n'
        '# ── 2. System prompt ────────────────────────────────────────────────────\n'
        f"system_prompt = '''{escaped_prompt}'''\n"
        '\n'
        '# ── 3. Tools ────────────────────────────────────────────────────────────\n'
        'tools = []\n'
        f'{native_tools_lines}{custom_tools_lines}'
        '\n'
        '# ── 4. Build agent ──────────────────────────────────────────────────────\n'
        f'{build_section}'
        '\n'
        '# ── 5. CLI entry point ─────────────────────────────────────────────────\n'
        'def main():\n'
        f'    print(f"=== {agent.name} ===")\n'
        '    print("Type \'exit\' to quit.\\n")\n'
        '    from langchain_core.messages import HumanMessage, AIMessage\n'
        '    history = []\n'
        '    while True:\n'
        '        user_input = input("You: ").strip()\n'
        '        if user_input.lower() in ("exit", "quit"):\n'
        '            break\n'
        '        history.append(HumanMessage(content=user_input))\n'
        '        result = agent.invoke(\n'
        '            {"messages": history},\n'
        '            config={"configurable": {"thread_id": "cli"}, "recursion_limit": 500},\n'
        '        )\n'
        '        msgs = result.get("messages", [])\n'
        '        reply = ""\n'
        '        for m in reversed(msgs):\n'
        '            if hasattr(m, "content") and m.content and not hasattr(m, "tool_calls"):\n'
        '                reply = m.content\n'
        '                break\n'
        '        if not reply:\n'
        '            reply = str(result)\n'
        '        print(f"\\nAgent: {reply}\\n")\n'
        '        history.append(AIMessage(content=reply))\n'
        '\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )

    return Response(
        content=source,
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{agent.name.replace(" ", "_")}.py"',
        },
    )
