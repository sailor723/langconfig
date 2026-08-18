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
from fastapi import APIRouter, HTTPException, Depends
from starlette.responses import Response, FileResponse

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from db.database import get_db
from models.deep_agent import (
    DeepAgentTemplate,
    DeepAgentConfig,
    SubAgentConfig,
    MiddlewareConfig,
    BackendConfig,
    GuardrailsConfig,
    create_default_middleware_config,
    create_default_backend_config,
    create_default_guardrails_config,
)
from core.versioning import check_version_conflict, format_lock_version_error
from services.agent_bundle import build_agent_bundle, import_agent_bundle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deepagents", tags=["deepagents"])


# =============================================================================
# Standalone codegen helpers (used by download_agent_code)
# =============================================================================

# Legacy-only built-in tools that agents may request but which have no
# custom_tools row (their real implementations live in
# backend/tools/native_tools.py). The codegen inlines real in-session
# implementations so the generated script stays fully standalone — no
# backend repo, no PostgreSQL. memory_store/memory_recall share the
# process-scoped `_MEMORY` dict (emitted once by the generator).
_CODEGEN_LEGACY_TOOLS: Dict[str, str] = {
    "memory_store": (
        'def memory_store(key: str, value: str, context: str = "general") -> str:\n'
        '    """Store a fact in in-memory agent memory for later recall.\n'
        '\n'
        '    Standalone replacement for the backend SimpleMemory service.\n'
        '    Data lives only for the lifetime of this process.\n'
        '    """\n'
        '    _MEMORY[f"{context}:{key}"] = value\n'
        '    return f"Stored memory: {key} in context \'{context}\'"\n'
    ),
    "memory_recall": (
        'def memory_recall(key: str, context: str = "general") -> str:\n'
        '    """Recall a previously stored fact from in-memory agent memory."""\n'
        '    return _MEMORY.get(\n'
        '        f"{context}:{key}",\n'
        '        f"No memory found for \'{key}\' in context \'{context}\'",\n'
        '    )\n'
    ),
}

# Trivial stateless built-ins with no custom_tools row (safe in any build path).
_CODEGEN_SIMPLE_TOOLS: Dict[str, str] = {
    "think_tool": (
        "def think_tool(reflection: str) -> str:\n"
        '    """Record a strategic reflection on research progress and decision-making."""\n'
        '    return f"Thought recorded: {reflection}"\n'
    ),
}

# Stateful harness tools (write_todos / read_todos) that have no
# custom_tools row either. They operate on agent state via InjectedState and
# Command — the same machinery the backend uses in
# backend/tools/native_tools.py — so the generated script must define the
# state schema (Todo / DeepAgentState) BEFORE these tool defs. Only emitted
# for the LangGraph (non-deep) build path, which passes state_schema.
_CODEGEN_FS_TOOLS: Dict[str, str] = {
    "write_todos": (
        'def write_todos(\n'
        '    todos: list[Todo],\n'
        '    tool_call_id: Annotated[str, InjectedToolCallId],\n'
        ') -> Command:\n'
        '    """Create or update the agent\'s TODO list for task planning and tracking."""\n'
        '    return Command(\n'
        '        update={\n'
        '            "todos": todos,\n'
        '            "messages": [ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id)],\n'
        '        }\n'
        '    )\n'
    ),
    "read_todos": (
        'def read_todos(\n'
        '    state: Annotated[DeepAgentState, InjectedState],\n'
        '    tool_call_id: Annotated[str, InjectedToolCallId],\n'
        ') -> str:\n'
        '    """Read the current TODO list from the agent state."""\n'
        '    todos = state.get("todos", [])\n'
        '    if not todos:\n'
        '        return "No todos currently in the list."\n'
        '    result = "Current TODO List:\\n"\n'
        '    for i, todo in enumerate(todos, 1):\n'
        '        emoji = {"pending": "\\u23f3", "in_progress": "\\U0001f504", "completed": "\\u2705"}.get(\n'
        '            todo.get("status", ""), "\\u2753"\n'
        '        )\n'
        '        result += f"{i}. {emoji} {todo[\'content\']} ({todo[\'status\']})\\n"\n'
        '    return result.strip()\n'
    ),
}

# JSON Schema type -> Python type hint, used when inlining API tool signatures.
_PY_TYPE_HINTS: Dict[str, str] = {
    "float": "float",
    "int": "int",
    "str": "str",
    "bool": "bool",
    "number": "float",
    "integer": "int",
    "string": "str",
    "boolean": "bool",
}


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
    Normalize the config returned to the frontend.

    Respects config.use_deepagents as the source of truth — if the user
    has explicitly set it to False (Regular Agent), preserve that.
    If the key is missing (legacy data), default to True for backward
    compatibility with pre-framework-toggle agents.

    Also injects dynamic skill subagents into config.subagents when db is provided.
    """
    config = dict(config)  # Make a copy to avoid mutating
    # Respect the stored value if set; default to True only when absent
    # (backward compat with agents created before the framework toggle existed).
    if "use_deepagents" not in config:
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
    workspace_path: Optional[str] = None
    agent_docs: Optional[Dict[str, str]] = None  # User-defined workspace; None → default
    agent_docs: Optional[Dict[str, str]] = None  # {"AGENTS.md": "...", "CLAUDE.md": "..."}
    # Initial project binding — used at creation time to bake the agent's
    # identity block (so the system_prompt mentions the right workspace path).
    # NOT stored long-term: the agent is project-agnostic; chat sessions
    # carry the actual project binding (chat_sessions.project_id).
    project_id: Optional[int] = None


class UpdateDeepAgentRequest(BaseModel):
    """Request to update a DeepAgent."""
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[DeepAgentConfig] = None
    lock_version: Optional[int] = None  # For optimistic locking
    workspace_path: Optional[str] = None  # None → leave unchanged
    agent_docs: Optional[Dict[str, str]] = None  # None → leave unchanged


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
    # User-defined workspace path (None → default outputs/agents/agent_{id}/)
    workspace_path: Optional[str] = None
    # Always true for DeepAgents - helps frontend identify this as a DeepAgent
    use_deepagents: bool = True

    class Config:
        from_attributes = True

    @field_validator("middleware_config", mode="before")
    @classmethod
    def ensure_middleware_config_is_list(cls, v):
        """Handle DB records where middleware_config is stored as {} instead of []."""
        if isinstance(v, dict):
            return []
        return v or []

    @field_validator("subagents_config", mode="before")
    @classmethod
    def ensure_subagents_config_is_list(cls, v):
        """Handle DB records where subagents_config is stored as {} instead of []."""
        if isinstance(v, dict):
            return []
        return v or []


# =============================================================================
# Built-in Template Endpoints
# =============================================================================

@router.get("/templates")
async def list_builtin_deep_templates() -> List[Dict[str, Any]]:
    """
    Get all built-in DeepAgent templates (preset configurations).

    Returns pre-configured DeepAgent templates from the DeepAgentTemplateRegistry,
    similar to how /api/agents/templates serves built-in regular agent templates.
    Each template includes full config, model, tools, middleware, and subagents.
    """
    from core.templates.deep_agent import DeepAgentTemplateRegistry

    templates = DeepAgentTemplateRegistry.list_all()
    result = []
    for tpl in templates:
        # Resolve full config via factory
        config = DeepAgentTemplateRegistry.get_template(tpl["template_id"])
        result.append({
            "template_id": tpl["template_id"],
            "name": tpl["name"],
            "description": tpl["description"],
            "category": tpl["category"],
            "capabilities": tpl["capabilities"],
            "use_cases": tpl["use_cases"],
            "model": config.model,
            "temperature": config.temperature,
            "system_prompt": config.system_prompt,
            "native_tools": config.native_tools,
            "cli_tools": config.cli_tools,
            "custom_tools": config.custom_tools,
            "middleware": [m.dict() for m in config.middleware],
            "subagents": [s.dict() for s in config.subagents],
            "use_deepagents": True,
        })
    return result


# =============================================================================
# CRUD Endpoints
# =============================================================================

def _resolve_model(config: DeepAgentConfig, db: Session) -> Optional[str]:
    """Resolve model from config or read default_model from the settings
    documents (models namespace, seeded from .env)."""
    if config.model:
        return config.model
    from core.settings import resolve_value
    return resolve_value(db, "models").get("default_model")


@router.post("/", response_model=DeepAgentResponse)
async def create_deepagent(
    request: CreateDeepAgentRequest,
    db: Session = Depends(get_db)
):
    """Create a new DeepAgent template."""
    try:
        config_dict = request.config.dict()
        config_dict["model"] = config_dict.get("model") or _resolve_model(request.config, db)
        # Default tool set: agents with no configured tools get the universal
        # base materialized into their Postgres config (docs/tools-audit.md).
        if not config_dict.get("native_tools"):
            from core.tools.defaults import DEFAULT_NATIVE_TOOLS
            config_dict["native_tools"] = list(DEFAULT_NATIVE_TOOLS)

        agent = DeepAgentTemplate(
            name=request.name,
            description=request.description,
            category=request.category,
            base_template_id=request.base_template_id,
            workspace_path=request.workspace_path,
            agent_docs=request.agent_docs,
            config=config_dict,
            middleware_config=[m.dict() for m in request.config.middleware],
            subagents_config=[s.dict() for s in request.config.subagents],
            backend_config=request.config.backend.dict(),
            guardrails_config=request.config.guardrails.dict(),
        )

        db.add(agent)
        db.commit()
        db.refresh(agent)

        # Bake identity into the persisted system prompt so the agent always
        # knows who it is and where its workspace is (real values, resolved at
        # creation). Also embed the instruction docs (AGENTS.md / CLAUDE.md)
        # inline so the agent can quickly compile its role, workspace, and
        # rules from the prompt alone — and persist the docs to the DB row.
        # The workspace path reflects request.project_id at creation time
        # (so the agent starts with a sensible home). The chat path re-bakes
        # on every turn with the session's project_id, so the agent's
        # identity stays correct even if the session moves to a different
        # project later. The agent itself is project-agnostic — no FK is
        # stored on deep_agent_templates.
        from core.agents.identity import build_identity_system_prompt, default_agent_docs
        from services.workspace_manager import get_workspace_manager, WorkspaceManager
        _ws_root = str(get_workspace_manager().resolve_agent_workspace(
            agent, request.project_id,
            vault_key=WorkspaceManager.project_vault_key(db, request.project_id) or None,
            agent_key=None,
        ))
        _docs = request.agent_docs or default_agent_docs(agent, _ws_root)
        config_dict["system_prompt"] = build_identity_system_prompt(
            config_dict.get("system_prompt", ""), agent.id, _ws_root, _docs
        )
        agent.config = config_dict
        agent.agent_docs = _docs
        flag_modified(agent, "config")
        flag_modified(agent, "agent_docs")
        db.commit()

        logger.info(
            f"Created DeepAgent: {agent.name} (id={agent.id}, "
            f"project_id={request.project_id}, "
            f"workspace_root={_ws_root})"
        )

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
            workspace_path=agent.workspace_path,
            agent_docs=agent.agent_docs,
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
        # Default tool set: an agent saved without tools gets the universal base
        # materialized into Postgres (docs/tools-audit.md), matching the runtime.
        if not merged_config.get("native_tools"):
            from core.tools.defaults import DEFAULT_NATIVE_TOOLS
            merged_config["native_tools"] = list(DEFAULT_NATIVE_TOOLS)
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

    # User-defined workspace path (None in the request → leave unchanged;
    # empty string clears it back to the default).
    if "workspace_path" in request.model_fields_set:
        agent.workspace_path = request.workspace_path or None
    if "agent_docs" in request.model_fields_set:
        agent.agent_docs = request.agent_docs or None

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
        workspace_path=agent.workspace_path,
        agent_docs=agent.agent_docs,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat()
    )


class AgentDocsUpdate(BaseModel):
    """Payload for updating a specific agent's instruction docs."""
    docs: Dict[str, str] = Field(
        default_factory=dict,
        description='Filename → content, e.g. {"AGENTS.md": "...", "CLAUDE.md": "..."}',
    )


@router.get("/{agent_id}/agents-md", response_model=dict)
async def get_agent_agents_md(
    agent_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific agent's instruction docs (AGENTS.md / CLAUDE.md / …)."""
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_id": agent.id, "docs": agent.agent_docs or {}}


@router.put("/{agent_id}/agents-md", response_model=dict)
async def update_agent_agents_md(
    agent_id: int,
    payload: AgentDocsUpdate,
    db: Session = Depends(get_db),
):
    """Set a specific agent's instruction docs (PostgreSQL is source of truth;
    materialized into the agent workspace at chat build time)."""
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.agent_docs = payload.docs or None
    db.commit()
    db.refresh(agent)
    logger.info(f"Updated agent docs for agent {agent_id}: {list((agent.agent_docs or {}).keys())}")
    return {"agent_id": agent.id, "docs": agent.agent_docs or {}}


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

        # Bake identity (real agent id + resolved workspace root) and embed the
        # instruction docs (AGENTS.md / CLAUDE.md) into the persisted system
        # prompt, and persist the docs to the DB row (see create_deepagent).
        from core.agents.identity import build_identity_system_prompt, default_agent_docs
        from services.workspace_manager import get_workspace_manager
        _ws_root = str(get_workspace_manager().resolve_agent_workspace(
            agent, None, vault_key=None, agent_key=None,
        ))
        _docs = default_agent_docs(agent, _ws_root)
        full_config.system_prompt = build_identity_system_prompt(
            full_config.system_prompt, agent.id, _ws_root, _docs
        )
        agent.config = full_config.dict()
        agent.agent_docs = _docs
        flag_modified(agent, "config")
        flag_modified(agent, "agent_docs")
        db.commit()

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


class QuickCreateRequest(BaseModel):
    """Quick-create a DeepAgent from the UI (fallback for Agent Creator workflow)."""
    name: str
    system_prompt: str
    native_tools: list[str] = []
    skills: list[str] = []
    description: str = ""
    category: str = "Custom"
    model: str = "minimax-m3"
    temperature: float = 0.7


@router.post("/quick-create")
async def quick_create_agent(
    request: QuickCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Quick-create a DeepAgent from the UI (backup for Agent Creator workflow).

    Replaces the legacy file-based /from-creator endpoint.
    Accepts agent config directly and writes to PostgreSQL.
    """
    try:
        cfg = DeepAgentConfig(
            model=request.model,
            system_prompt=request.system_prompt.strip(),
            native_tools=request.native_tools or [],
            skills=request.skills or [],
            tools=[],
            cli_tools=[],
            custom_tools=[],
            temperature=request.temperature,
            use_deepagents=True,
            middleware=create_default_middleware_config(),
            subagents=[],
            backend=create_default_backend_config(),
            guardrails=create_default_guardrails_config(),
        )
        agent = DeepAgentTemplate(
            name=request.name.strip(),
            description=request.description.strip(),
            category=request.category,
            config=cfg.dict(),
            middleware_config=[m.dict() for m in cfg.middleware],
            subagents_config=[],
            backend_config=cfg.backend.dict(),
            guardrails_config=cfg.guardrails.dict(),
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        # Bake identity (real agent id + resolved workspace root) and embed the
        # instruction docs (AGENTS.md / CLAUDE.md) into the persisted system
        # prompt, and persist the docs to the DB row (see create_deepagent).
        from core.agents.identity import build_identity_system_prompt, default_agent_docs
        from services.workspace_manager import get_workspace_manager
        _ws_root = str(get_workspace_manager().resolve_agent_workspace(
            agent, None, vault_key=None, agent_key=None,
        ))
        _docs = default_agent_docs(agent, _ws_root)
        cfg.system_prompt = build_identity_system_prompt(
            cfg.system_prompt, agent.id, _ws_root, _docs
        )
        agent.config = cfg.dict()
        agent.agent_docs = _docs
        flag_modified(agent, "config")
        flag_modified(agent, "agent_docs")
        db.commit()

        logger.info(f"Quick-create DeepAgent: {agent.name} (id={agent.id})")
        return {
            "status": "success",
            "message": f"Agent '{agent.name}' created successfully (id={agent.id})",
            "agent_id": agent.id,
            "name": agent.name,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Quick-create failed: {e}")
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
        from deepagents.profiles.harness.harness_profiles import (
            _harness_profile_for_model,
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="DeepAgents SDK not available")

    segments = []
    # deepagents >= 0.7 changed _harness_profile_for_model to take a resolved
    # model instance first; a bare model string goes in the `spec` position.
    profile = _harness_profile_for_model(None, request.model)
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

    # Base content: user CUSTOM > harness-profile base > none.
    # NOTE: deepagents >= 0.7 no longer ships an SDK-authored base prompt
    # (the old BASE_AGENT_PROMPT constant was removed), so when no profile
    # base exists the BASE segment is simply empty.
    base_content = ""
    base_source = "sdk_default"
    if request.custom_prompt:
        # User provided custom prompt → CUSTOM segment, replaces BASE
        base_content = request.custom_prompt
        base_source = "custom"
    elif has_base_override:
        base_content = profile.base_system_prompt
        base_source = "harness_profile"
    if base_content:
        segments.append(PromptSegment(
            name="CUSTOM" if base_source == "custom" else "BASE",
            source=base_source,
            content=base_content,
            editable=base_source == "custom",
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

    # Assemble the final prompt: USER -> BASE -> SUFFIX (each part optional)
    parts = []
    if user_content:
        parts.append(user_content)
    if base_content:
        parts.append(base_content)
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
    """Import a DeepAgent from .langconfig format (v1.0 or v1.1)."""
    try:
        langconfig = json.loads(request.langconfig_content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    # v1.1 bundles also create any embedded custom tools + skills (reusing
    # same-name ones) before the agent row; all in one transaction.
    try:
        agent = import_agent_bundle(langconfig, db)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error importing .langconfig: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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


@router.get("/{agent_id}/export")
async def export_deepagent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    """
    Export a DeepAgent as a self-contained .langconfig (v1.1) file.

    Bundles the full config (system_prompt + custom_prompt + custom_suffix,
    tools, middleware, subagents, guardrails, skills, runtime flags) plus the
    definitions of every referenced custom tool and skill. Secrets in tool
    config are redacted.
    """
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    bundle = build_agent_bundle(agent, db)

    # Safe download filename derived from the agent name.
    safe_name = agent.name.replace(" ", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-") or "agent"
    return Response(
        content=json.dumps(bundle, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.langconfig.json"'
        }
    )


@router.get("/{agent_id}/code")
async def download_agent_code(agent_id: int, db: Session = Depends(get_db)):
    """Download a runnable, fully standalone Python file for this agent.

    The generated script embeds everything needed at runtime — LLM config
    (env vars), system prompt (with any attached skill instructions inlined),
    tool source code (inlined from the
    custom_tools table at generation time), and the agent state schema — so
    it runs with just:

        pip install langchain-openai langgraph langchain-community python-dotenv httpx
        python agent.py "your question"

    It has no dependency on PostgreSQL or the LangConfig backend repo.
    """
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    config = agent.config or {}
    model = config.get("model", "gpt-4o")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens") or 4000
    system_prompt = config.get("system_prompt", "You are a helpful AI assistant.")
    native_tools = config.get("native_tools", []) or []
    custom_tools = config.get("custom_tools", []) or []

    # Inline attached skills into the system prompt so the standalone script
    # carries the skill instructions with no DB dependency at runtime.
    skill_ids = config.get("skills", []) or []
    if skill_ids:
        from models.skill import Skill as SkillModel
        skill_rows = db.query(SkillModel).filter(SkillModel.skill_id.in_(skill_ids)).all()
        skill_by_id = {s.skill_id: s for s in skill_rows}
        skill_sections = []
        for sid in skill_ids:
            s = skill_by_id.get(sid)
            if s is None:
                continue
            body = s.instructions or s.description or ''
            skill_sections.append(f"## Skill: {sid}\n\n{body}")
        if skill_sections:
            system_prompt = (
                f"{system_prompt}\n\n# Attached Skills\n\n"
                + "\n\n".join(skill_sections)
            )

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

    # ── Tool resolution: inline every enabled tool as Python source ───────
    # The DB is needed only here, at generation time. The emitted script
    # contains the tool code verbatim, so it never touches PostgreSQL.
    from models.custom_tool import CustomTool

    tool_ids = list(dict.fromkeys([*native_tools, *custom_tools]))
    tool_rows: Dict[str, Any] = {}
    if tool_ids:
        rows = db.query(CustomTool).filter(CustomTool.tool_id.in_(tool_ids)).all()
        tool_rows = {r.tool_id: r for r in rows}

    def _emit_python_tool(row) -> str:
        """Emit a python_function tool: its raw source + a registration line."""
        ic = row.implementation_config or {}
        code = ic.get("code") or ""
        fn = ic.get("function_name") or "run"
        # The built-in Tavily tool reads its key via the backend's `config`
        # module. Rewrite it to read the env var directly, so the generated
        # script needs no backend import and no shim.
        code = code.replace("from config import get_api_key_from_db", "")
        code = code.replace(
            'get_api_key_from_db("tavily_api_key")',
            'os.environ.get("TAVILY_API_KEY", "")',
        )
        desc = (row.description or "").replace("\n", " ")
        return (
            f"# ── Tool: {row.tool_id} ({row.name}) ─────────────────────────────\n"
            f"{code}\n"
            f"# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool(\n"
            f"    {json.dumps(row.tool_id)},\n"
            f"    {fn},\n"
            f"    description={json.dumps(desc)},\n"
            f"))\n"
        )

    def _emit_api_tool(row) -> str:
        """Emit an api tool as an httpx-based async function (mirrors backend).

        Mirrors ToolFactory._create_api_tool: URL/header template substitution,
        auth headers (api_key/bearer), request body for POST/PUT/PATCH, and
        optional json_path response parsing.
        """
        ic = row.implementation_config or {}
        url = ic.get("url", "")
        method = ic.get("method", "GET")
        headers = ic.get("headers") or {}
        auth = ic.get("auth") or {}
        body_template = ic.get("body_template")
        timeout = ic.get("timeout", 30)
        response_parser = ic.get("response_parser") or {}
        props = (row.input_schema or {}).get("properties") or {}
        arg_defs = ", ".join(
            f"{k}: {_PY_TYPE_HINTS.get(v.get('type', 'string'), 'str')}"
            for k, v in props.items()
        )
        # Named params dict used for {param} substitution in url/headers/body.
        params_literal = ", ".join(f"{json.dumps(k)}: {k}" for k in props)
        desc = (row.description or "").replace("\n", " ")

        # Auth headers (api_key / bearer), matching _build_auth_headers.
        auth_lines = []
        if auth.get("type") == "api_key" and auth.get("location") == "header":
            auth_lines.append(
                f"    _headers[{json.dumps(auth.get('key', 'Authorization'))}] = "
                f"{json.dumps(auth.get('value', ''))}"
            )
        elif auth.get("type") == "bearer":
            auth_lines.append(
                f"    _headers['Authorization'] = f\"Bearer {auth.get('token', '')}\""
            )
        auth_block = "\n".join(auth_lines)

        # Request body for POST/PUT/PATCH (template substitution like backend).
        body_block = ""
        if method.upper() in ("POST", "PUT", "PATCH") and body_template is not None:
            tpl_literal = json.dumps(body_template)
            if isinstance(body_template, str):
                body_block = f"    _body = {tpl_literal}.format(**_params)"
            else:
                body_block = f"    _body = json.dumps({tpl_literal})"

        # Response parsing (json_path support, mirrors backend response_parser).
        if response_parser.get("type") == "json_path":
            path_literal = json.dumps(response_parser.get("path", ""))
            resp_block = (
                "            _data = _resp.json()\n"
                "            _result = _data\n"
                f"            for _k in {path_literal}.split('.'):\n"
                "                _result = _result.get(_k) if isinstance(_result, dict) else None\n"
                "                if _result is None:\n"
                "                    break\n"
                "            return str(_result)\n"
            )
        else:
            resp_block = "            return _resp.text\n"

        fn_body = (
            f"async def {row.tool_id}({arg_defs}) -> str:\n"
            f'    """{desc}"""\n'
            "    import httpx\n"
            "    import json\n"
            f"    _params = {{{params_literal}}}\n"
            f"    _url = {json.dumps(url)}.format(**_params)\n"
            f"    _headers = {json.dumps(headers)}\n"
            "    for _hk, _hv in list(_headers.items()):\n"
            "        if isinstance(_hv, str):\n"
            "            _headers[_hk] = _hv.format(**_params)\n"
        )
        if auth_block:
            fn_body += auth_block + "\n"
        fn_body += "    _body = None\n"
        if body_block:
            fn_body += body_block + "\n"
        fn_body += (
            "    try:\n"
            f"        async with httpx.AsyncClient(timeout={timeout}) as _client:\n"
            f"            _resp = await _client.request(\n"
            f"                {json.dumps(method)}, _url, headers=_headers,\n"
            "                content=_body if isinstance(_body, str) else None,\n"
            "                json=_body if isinstance(_body, dict) else None,\n"
            "            )\n"
            "            _resp.raise_for_status()\n"
        )
        fn_body += resp_block
        fn_body += '    except Exception as _e:\n        return f"Error: {_e}"\n'

        return (
            f"# ── Tool: {row.tool_id} ({row.name}) ─────────────────────────────\n"
            f"{fn_body}\n"
            "# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool({json.dumps(row.tool_id)}, {row.tool_id}, "
            f"description={json.dumps(desc)}))\n"
        )

    def _emit_legacy_tool(tool_id: str) -> str:
        """Emit a legacy-only built-in stub (memory_store / memory_recall)."""
        desc = f"Legacy built-in tool ({tool_id}), inlined standalone stub."
        return (
            f"# ── Tool: {tool_id} (legacy standalone stub) ─────────────────────\n"
            f"{_CODEGEN_LEGACY_TOOLS[tool_id]}\n"
            f"# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool({json.dumps(tool_id)}, {tool_id}, "
            f"description={json.dumps(desc)}))\n"
        )

    def _emit_missing_tool(tool_id: str) -> str:
        """Emit a harmless stub for a tool that could not be inlined."""
        return (
            f"# ── Tool: {tool_id} (NOT available in standalone mode) ───────────\n"
            f"def {tool_id}(*args, **kwargs) -> str:\n"
            f'    return "Tool {json.dumps(tool_id)} is not available in this standalone script."\n\n'
            f"# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool({json.dumps(tool_id)}, {tool_id}))\n"
        )

    is_deep = config.get("use_deepagents", False)

    def _emit_simple_tool(tool_id: str) -> str:
        """Emit a trivial stateless built-in (think_tool)."""
        desc = f"Built-in tool ({tool_id}), inlined standalone implementation."
        return (
            f"# ── Tool: {tool_id} (inlined standalone) ─────────────────────────\n"
            f"{_CODEGEN_SIMPLE_TOOLS[tool_id]}\n"
            f"# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool({json.dumps(tool_id)}, {tool_id}, "
            f"description={json.dumps(desc)}))\n"
        )

    def _emit_fs_tool(tool_id: str) -> str:
        """Emit a stateful harness tool (write_todos / read_todos).

        These operate on DeepAgentState via InjectedState/Command, exactly like
        the backend's native_tools.py. Only used in the LangGraph build path.
        """
        desc = (f"Harness tool ({tool_id}), inlined standalone implementation "
                f"operating on agent state.")
        return (
            f"# ── Tool: {tool_id} (stateful harness — inlined) ────────────────\n"
            f"{_CODEGEN_FS_TOOLS[tool_id]}\n"
            f"# register as a LangChain tool (name must be the tool_id)\n"
            f"_tools.append(tool({json.dumps(tool_id)}, {tool_id}, "
            f"description={json.dumps(desc)}))\n"
        )

    tool_blocks = []
    for tid in tool_ids:
        row = tool_rows.get(tid)
        if row is not None and row.tool_type.value == "api":
            tool_blocks.append(_emit_api_tool(row))
        elif row is not None:
            tool_blocks.append(_emit_python_tool(row))
        elif tid in _CODEGEN_LEGACY_TOOLS:
            tool_blocks.append(_emit_legacy_tool(tid))
        elif tid in _CODEGEN_SIMPLE_TOOLS:
            tool_blocks.append(_emit_simple_tool(tid))
        elif tid in _CODEGEN_FS_TOOLS and not is_deep:
            tool_blocks.append(_emit_fs_tool(tid))
        else:
            tool_blocks.append(_emit_missing_tool(tid))
    tools_block = "\n".join(tool_blocks)

    if is_deep:
        build_section = '''
# Build DeepAgent (deepagents pip package — stateless, no PostgreSQL)
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=llm,
    system_prompt=system_prompt,
    tools=tools,
)
'''
    else:
        build_section = '''
# Build LangGraph agent (LangChain v1.0 API — stateless, no PostgreSQL)
from langchain.agents import create_agent

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=system_prompt,
    state_schema=DeepAgentState,
)
'''

    # The state schema must be defined BEFORE the harness tool defs below
    # (write_todos / read_todos) because their annotations reference
    # DeepAgentState eagerly (Annotated[...] evaluates its arguments at def
    # time). Deep agents build via create_deep_agent and skip this section.
    if is_deep:
        state_section = ''
    else:
        state_section = (
            '# ── Agent state schema + tool runtime imports ────────────────────\n'
            '# The harness tools below (write_todos / read_todos) operate\n'
            '# on agent state via InjectedState/Command — the same machinery the\n'
            '# backend uses. Todo lists and scratch files are TRANSIENT (they live\n'
            '# only in this run\'s state, i.e. the file system during execution);\n'
            '# formal documents are produced as the agent\'s final answer (explicit\n'
            '# state) and persisted by the runner. No PostgreSQL involved.\n'
            'from typing import Annotated, Literal, Optional\n'
            'from typing_extensions import NotRequired, TypedDict\n'
            'from langchain.agents import AgentState\n'
            'from langchain_core.messages import ToolMessage\n'
            'from langchain_core.tools import InjectedToolCallId\n'
            'from langgraph.prebuilt import InjectedState\n'
            'from langgraph.types import Command\n'
            '\n'
            'class Todo(TypedDict):\n'
            '    """A structured task item for tracking progress through complex workflows."""\n'
            '    content: str\n'
            '    status: Literal["pending", "in_progress", "completed"]\n'
            '\n'
            'def file_reducer(left: Optional[dict], right: Optional[dict]) -> dict:\n'
            '    """Merge two file dictionaries, with right side taking precedence."""\n'
            '    if left is None:\n'
            '        return right or {}\n'
            '    if right is None:\n'
            '        return left\n'
            '    return {**left, **right}\n'
            '\n'
            'class DeepAgentState(AgentState):\n'
            '    """Extended agent state with TODO tracking and a virtual file system."""\n'
            '    todos: NotRequired[list[Todo]]\n'
            '    files: Annotated[NotRequired[dict[str, str]], file_reducer]\n'
            '\n'
        )

    # Escape single-quotes in system prompt for the generated code
    escaped_prompt = system_prompt.replace("\\", "\\\\").replace("'", "\\'")

    source = (
        '#!/usr/bin/env python3\n'
        f'"""Runnable agent: {agent.name} (generated by LangConfig) — fully standalone.\n'
        '\n'
        'Everything needed at runtime is inlined below: LLM config, prompt,\n'
        'tools, and agent state. No PostgreSQL or LangConfig backend required.\n'
        '\n'
        'Usage:\n'
        '    pip install langchain-openai langgraph langchain-community python-dotenv httpx\n'
        '    python agent.py                     # interactive chat\n'
        '    python agent.py "your question"     # one-shot answer\n'
        '"""\n'
        '\n'
        'import os\n'
        'import sys\n'
        'import asyncio\n'
        '# Same namespaces the backend preloads into each tool\'s exec() scope,\n'
        '# so inlined python_function tools that reference them work as-is.\n'
        'import math, json, re, collections, datetime, pathlib, io, typing\n'
        '\n'
        '# ── Env ──────────────────────────────────────────────────────────────\n'
        'from dotenv import load_dotenv\n'
        'load_dotenv()  # loads .env from the current directory\n'
        '_LANGCFG_ROOT = os.environ.get("LANGCFG_ROOT", "")\n'
        'if _LANGCFG_ROOT and os.path.isfile(os.path.join(_LANGCFG_ROOT, ".env")):\n'
        '    load_dotenv(os.path.join(_LANGCFG_ROOT, ".env"))\n'
        '\n'
        '# Default project id (kept for compatibility with inlined tool code)\n'
        'project_id = int(os.environ.get("GRAPHINDEX_PROJECT_ID", "1"))\n'
        '\n'
        f'{model_import}\n'
        '\n'
        '# ── 1. LLM ───────────────────────────────────────────────────────────\n'
        f'{llm_init}\n'
        '\n'
        '# ── 2. System prompt ─────────────────────────────────────────────────\n'
        f"system_prompt = '''{escaped_prompt}'''\n"
        '\n'
        f'{state_section}'
        '# ── 3. Tools (all inlined — no DB lookup at runtime) ─────────────────\n'
        'from langchain_core.tools import tool\n'
        '_tools: list = []\n'
        '# Process-scoped memory store used by the memory_store/memory_recall\n'
        '# built-ins (standalone replacement for the PG-backed SimpleMemory).\n'
        '_MEMORY: dict = {}\n'
        f'{tools_block}\n'
        '\n'
        'tools = _tools\n'
        '\n'
        '# ── 4. Build agent ───────────────────────────────────────────────────\n'
        f'{build_section}'
        '\n'
        '# ── 5. CLI entry point ───────────────────────────────────────────────\n'
        'async def _run_turn(user_input: str) -> str:\n'
        '    """Run a single user turn and return the agent reply text."""\n'
        '    from langchain_core.messages import HumanMessage\n'
        '    # Stateless: every turn starts a fresh run, so only the new message\n'
        '    # is passed (the conversation is not checkpointed).\n'
        '    result = await agent.ainvoke(\n'
        '        {"messages": [HumanMessage(content=user_input)]},\n'
        '        config={"recursion_limit": 500},\n'
        '    )\n'
        '    msgs = result.get("messages", [])\n'
        '    # AIMessage always has a `tool_calls` attr (default []), so use\n'
        '    # getattr() — text replies are picked, pure tool-call turns skipped.\n'
        '    for m in reversed(msgs):\n'
        '        if m.content and not getattr(m, "tool_calls", None):\n'
        '            return m.content\n'
        '    return str(result)\n'
        '\n'
        'def main(query: str | None = None):\n'
        '    # One-shot mode: `python agent.py "your question"`\n'
        '    if query:\n'
        '        print(asyncio.run(_run_turn(query)))\n'
        '        return\n'
        f'    print(f"=== {agent.name} ===")\n'
        '    print("Type \'exit\' to quit.\\n")\n'
        '    while True:\n'
        '        user_input = input("You: ").strip()\n'
        '        if user_input.lower() in ("exit", "quit"):\n'
        '            break\n'
        '        print(f"\\nAgent: {asyncio.run(_run_turn(user_input))}\\n")\n'
        '\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    main(sys.argv[1] if len(sys.argv) > 1 else None)\n'
    )

    return Response(
        content=source,
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{agent.name.replace(" ", "_")}.py"',
        },
    )
