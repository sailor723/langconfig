# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent Models for LangConfig.

Extends the agent template system with DeepAgents-specific configuration.
Supports middleware, subagents, backends, and advanced context management.
"""

from typing import Dict, List, Any, Optional
from sqlalchemy import Column, Integer, String, JSON, Boolean, ForeignKey, DateTime, Text, Float, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pydantic import BaseModel, Field, model_validator, field_validator
from db.database import Base
from core.versioning import OptimisticLockMixin
from models.enums import SubAgentType, MiddlewareType, BackendType, ReasoningEffort
from models.core import DocumentType, IndexingStatus
import datetime


# =============================================================================
# Pydantic Models for Configuration
# =============================================================================

class SubAgentConfig(BaseModel):
    """Configuration for a specialized subagent."""
    name: str = Field(..., description="Unique subagent identifier")
    description: str = Field(default="", description="What this subagent does")

    # Type of subagent: "dictionary" (simple) or "compiled" (workflow-based)
    # Use string with validator to handle edge cases where type might be missing/invalid
    type: SubAgentType = Field(
        default=SubAgentType.DICTIONARY,
        description="Subagent type: 'dictionary' for simple agents, 'compiled' for workflow-based"
    )

    @field_validator('type', mode='before')
    @classmethod
    def coerce_type(cls, v):
        """Coerce type to SubAgentType enum; reject unknown values.

        Missing/empty stays lenient (defaults to DICTIONARY) so legacy rows
        load, but an explicitly invalid value raises instead of silently
        changing the agent's behavior.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[SubAgentConfig] Coercing type from: {v!r} (type={type(v).__name__})")

        if v is None or v == '':
            logger.info("[SubAgentConfig] Type is None/empty, defaulting to DICTIONARY")
            return SubAgentType.DICTIONARY
        if isinstance(v, SubAgentType):
            return v
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower == 'dictionary':
                return SubAgentType.DICTIONARY
            elif v_lower == 'compiled':
                return SubAgentType.COMPILED
            raise ValueError(
                f"[SubAgentConfig] Unknown subagent type '{v}'. "
                "Expected 'dictionary' or 'compiled'."
            )
        raise ValueError(
            f"[SubAgentConfig] Unexpected type value {v!r} for subagent type. "
            "Expected 'dictionary' or 'compiled'."
        )

    # For dictionary-based subagents
    template_id: Optional[str] = Field(None, description="Base template to use from AgentTemplateRegistry")
    model: Optional[str] = Field(None, description="Override model (inherits from parent if not set)")
    system_prompt: Optional[str] = Field(None, description="Subagent-specific system prompt (required for custom subagents)")
    tools: List[str] = Field(default_factory=list, description="Tool names for this subagent (overrides parent tools)")
    middleware: List[str] = Field(default_factory=list, description="Middleware to enable")
    interrupt_on: Dict[str, Any] = Field(default_factory=dict, description="HITL configuration (overrides parent default)")
    skills: List[str] = Field(default_factory=list, description="Skills source paths (does not inherit from parent)")
    response_format: Optional[Dict[str, Any]] = Field(None, description="Structured output schema for the subagent")

    # For compiled subagents (workflow-based)
    workflow_id: Optional[int] = Field(None, description="ID of workflow to use as compiled subagent")
    workflow_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Override configuration for the workflow (input mapping, etc.)"
    )

    @model_validator(mode='after')
    def validate_subagent_consistency(self) -> 'SubAgentConfig':
        """Ensure compiled subagents have workflow_id and dictionary subagents don't."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[SubAgentConfig] Validating '{self.name}': type={self.type}, type_value={self.type.value if hasattr(self.type, 'value') else self.type}, workflow_id={self.workflow_id}")

        if self.type == SubAgentType.COMPILED:
            if not self.workflow_id:
                raise ValueError(
                    f"Compiled subagent '{self.name}' requires workflow_id. "
                    f"Set type='dictionary' for simple subagents or provide a workflow_id."
                )
        elif self.type == SubAgentType.DICTIONARY:
            if self.workflow_id:
                raise ValueError(
                    f"Dictionary subagent '{self.name}' cannot have workflow_id. "
                    f"Set type='compiled' to use workflow-based subagents."
                )
        return self


class MiddlewareConfig(BaseModel):
    """Configuration for DeepAgents middleware."""
    type: MiddlewareType = Field(..., description="Middleware type: todo_list, filesystem, subagent")
    enabled: bool = Field(default=True, description="Whether this middleware is active")
    config: Dict[str, Any] = Field(default_factory=dict, description="Middleware-specific configuration")


class BackendConfig(BaseModel):
    """Configuration for DeepAgents backend storage."""
    type: BackendType = Field(
        default=BackendType.STATE,
        description="Backend type: state, store, filesystem, vectordb, composite"
    )
    config: Dict[str, Any] = Field(default_factory=dict, description="Backend-specific settings")
    mappings: Optional[Dict[str, Dict[str, Any]]] = Field(
        None,
        description="Path mappings for composite backends"
    )

    @model_validator(mode='after')
    def validate_composite_backend(self) -> 'BackendConfig':
        """Ensure composite backends have path mappings."""
        if self.type == BackendType.COMPOSITE:
            if not self.mappings or len(self.mappings) == 0:
                raise ValueError(
                    "Composite backend requires 'mappings' configuration. "
                    "Provide path mappings like {'/memory/': {'type': 'vectordb', 'config': {}}}."
                )
        return self


class GuardrailsConfig(BaseModel):
    """Guardrails and safety configuration."""
    interrupts: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific interrupt configuration (bool or InterruptOnConfig dict)"
    )
    token_limits: Dict[str, int] = Field(
        default={
            "max_total_tokens": 100000,
            "eviction_threshold": 80000,
            "summarization_threshold": 60000
        },
        description="Token management thresholds"
    )
    enable_auto_eviction: bool = Field(
        default=True,
        description="Automatically evict large tool results to filesystem"
    )
    enable_summarization: bool = Field(
        default=True,
        description="Automatically summarize conversation history"
    )
    long_term_memory: bool = Field(
        default=False,
        description="Enable workflow-scoped long-term memory via LangGraph Store"
    )

    @model_validator(mode='after')
    def validate_token_limits_ordering(self) -> 'GuardrailsConfig':
        """Ensure token limits are in correct order: summarization < eviction < max_total."""
        limits = self.token_limits
        summarization = limits.get("summarization_threshold", 0)
        eviction = limits.get("eviction_threshold", 0)
        max_total = limits.get("max_total_tokens", 0)

        if not (summarization < eviction < max_total):
            raise ValueError(
                f"Token limits must satisfy: summarization_threshold ({summarization}) < "
                f"eviction_threshold ({eviction}) < max_total_tokens ({max_total}). "
                f"Current order is invalid."
            )
        return self


class DeepAgentConfig(BaseModel):
    """Complete DeepAgent configuration (Pydantic model for validation)."""
    # Base agent settings
    model: Optional[str] = Field(default=None, description="Model to use; falls back to settings.default_model from DB if not set")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[ReasoningEffort] = Field(
        default=ReasoningEffort.LOW,
        description="Reasoning effort for Gemini models: none (96% cheaper), low, medium, or high"
    )
    modalities: Optional[List[str]] = Field(
        default=None,
        description="Modalities for multimodal models (e.g., ['image', 'text'] for Gemini image generation)"
    )
    system_prompt: str = Field(..., description="Agent system prompt")

    # Tools
    tools: List[str] = Field(default_factory=list, description="Tool names")
    native_tools: List[str] = Field(default_factory=list, description="Native Python tool categories")
    cli_tools: List[str] = Field(default_factory=list, description="CLI tool categories")
    custom_tools: List[str] = Field(default_factory=list, description="User-created custom tools")
    mcp_tools: List[str] = Field(
        default_factory=list,
        description="Names of MCP tools to attach (resolved against running MCP servers)",
    )

    # DeepAgents-specific
    use_deepagents: bool = Field(
        default=True,
        description="Whether to use DeepAgents framework"
    )
    use_phase9_graphindex: bool = Field(
        default=False,
        description=(
            "When True, the chat stream endpoint routes this agent through "
            "phase9.graphindex_chat_agent (the proven 5-tool + progressive-"
            "disclosure deepagent) instead of building a generic langconfig "
            "agent. Use this for any agent template that wraps graphindex_* tools."
        )
    )
    enable_compiled_subagents: bool = Field(
        default=True,
        description="Enable CompiledSubAgent support (workflow-based subagents). Set to False to disable."
    )
    use_local_sandbox: bool = Field(
        default=False,
        description=(
            "If True, creates a LocalShellBackend sandbox rooted at the task workspace. "
            "The agent gains an `execute` tool for running shell commands (e.g. Python scripts), "
            "and file operations are scoped to the sandbox directory. "
            "WARNING: shell commands run on the host machine with no security isolation."
        )
    )
    middleware: List[MiddlewareConfig] = Field(
        default_factory=list,
        description="Middleware configurations"
    )
    subagents: List[SubAgentConfig] = Field(
        default_factory=list,
        description="Specialized subagent configurations"
    )
    backend: BackendConfig = Field(
        default_factory=BackendConfig,
        description="Storage backend configuration"
    )
    guardrails: GuardrailsConfig = Field(
        default_factory=GuardrailsConfig,
        description="Safety and context management"
    )

    # Skills (from PostgreSQL skills table, synced to sandbox at runtime)
    skills: List[str] = Field(
        default_factory=list,
        description="Skill IDs to load from the database and make available to the agent. "
                    "Skills are synced to the sandbox filesystem at agent creation time "
                    "and loaded via create_deep_agent(skills=[...]) for progressive disclosure."
    )
    # Plugins (LangChain-style declarative plugins, backend/plugins/<name>).
    # Each plugin contributes skills (+ optional MCP servers / hooks) that are
    # mounted into this agent at build time. Plugin skills are staged into the
    # same skill catalog as builtin/personal skills (progressive disclosure).
    plugins: List[str] = Field(
        default_factory=list,
        description="Plugin names/ids to mount into this agent (e.g. 'meeting-minutes' "
                    "or 'meeting-minutes@langconfig-builtin'). Plugin skills become "
                    "discoverable skills; plugin MCP servers / hooks are applied when "
                    "the corresponding seams are enabled."
    )
    skill_router_model: Optional[str] = Field(
        default=None,
        description="Optional separate model for skill routing. If set, this model is "
                    "called first to classify which skill matches the user's request, "
                    "and only the matched skill is passed to the main agent. "
                    "If None, all equipped skills are passed directly (LLM auto-selects)."
    )
    disable_memory_middleware: bool = Field(
        default=False,
        description=(
            "If True, do NOT load the project's AGENTS.md into the system prompt via "
            "deepagents.MemoryMiddleware. Default is False (MemoryMiddleware is ON). "
            "Each project has its own AGENTS.md at "
            ".workspace_data/projects/{project_id}/AGENTS.md, editable via the API."
        )
    )

    # Normal agent config (used when use_deepagents=False)
    interrupt_before: Optional[List[str]] = Field(
        default=None,
        description="HITL: pause before specified nodes (['tools'] or ['agent']). Used when use_deepagents=False."
    )
    interrupt_after: Optional[List[str]] = Field(
        default=None,
        description="HITL: pause after specified nodes. Used when use_deepagents=False."
    )

    # Export settings
    export_format: str = Field(
        default="standalone",
        description="Export format: standalone or langconfig"
    )
    include_chat_ui: bool = Field(
        default=True,
        description="Include chat interface in standalone export"
    )
    include_docker: bool = Field(
        default=False,
        description="Include Docker support in export"
    )


# =============================================================================
# SQLAlchemy Database Models
# =============================================================================

class DeepAgentTemplate(Base, OptimisticLockMixin):
    """
    Database model for DeepAgent configurations.
    Extends agent templates with DeepAgents-specific features.
    """
    __tablename__ = "deep_agent_templates"

    id = Column(Integer, primary_key=True, index=True)

    # Basic metadata
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, index=True)

    # References to base agent template (if extends one)
    base_template_id = Column(String(100), nullable=True, index=True)

    # User-defined workspace path (PostgreSQL). When set, chat uploads and
    # generated files for this agent live under this directory instead of the
    # default outputs/agents/agent_{id}/ convention. Null → default.
    workspace_path = Column(String(500), nullable=True)

    # User-authored agent instruction docs — e.g. {"AGENTS.md": "...",
    # "CLAUDE.md": "..."}. PostgreSQL is the source of truth; the files are
    # materialized into the agent workspace at chat build time so
    # MemoryMiddleware and the Files panel can use them.
    agent_docs = Column(JSON, nullable=True)

    # DeepAgents configuration (stored as JSON)
    config = Column(JSON, nullable=False)

    # Middleware configuration
    middleware_config = Column(JSON, nullable=False, default=list)

    # Subagents configuration
    subagents_config = Column(JSON, nullable=False, default=list)

    # Backend configuration
    backend_config = Column(JSON, nullable=False, default=dict)

    # Guardrails configuration
    guardrails_config = Column(JSON, nullable=False, default=dict)

    # Export settings
    export_settings = Column(JSON, nullable=True, default=dict)

    # Usage tracking
    usage_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Versioning
    version = Column(String(20), default="1.0.0", nullable=False)

    # Visibility
    is_public = Column(Boolean, default=True, nullable=False)
    is_community = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    chat_sessions = relationship("ChatSession", back_populates="agent", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DeepAgentTemplate(id={self.id}, name='{self.name}')>"


class ChatSession(Base):
    """
    Stores chat testing sessions for DeepAgents.
    Allows users to test agents before exporting.
    """
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)

    # Reference to agent
    agent_id = Column(Integer, ForeignKey("deep_agent_templates.id"), nullable=False, index=True)

    # Reference to the vault (project) this session runs in — scopes the
    # agent workspace (uploads + generated files) per (vault, agent).
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    # Session metadata
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)  # Optional user tracking

    # Conversation data
    messages = Column(JSON, nullable=False, default=list)  # List of messages

    # Performance metrics
    metrics = Column(JSON, nullable=True, default=dict)  # Token usage, tool calls, etc.

    # Execution metadata
    tool_calls = Column(JSON, nullable=True, default=list)  # History of tool invocations
    subagent_spawns = Column(JSON, nullable=True, default=list)  # Subagent activity
    context_operations = Column(JSON, nullable=True, default=list)  # Evictions, summarizations

    # Cost tracking
    total_cost_usd = Column(Float, default=0.0, nullable=False)  # Total USD cost for this session
    rag_context_tokens = Column(Integer, default=0, nullable=False)  # RAG-specific token usage

    # Session state
    is_active = Column(Boolean, default=True, nullable=False)
    checkpoint_id = Column(String(200), nullable=True)  # LangGraph checkpoint reference

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent = relationship("DeepAgentTemplate", back_populates="chat_sessions")
    documents = relationship("SessionDocument", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ChatSession(id={self.id}, session_id='{self.session_id}', active={self.is_active})>"


class SessionDocument(Base):
    """
    Links uploaded documents to chat sessions.
    Session-scoped documents for agent RAG retrieval.
    """
    __tablename__ = "session_documents"

    id = Column(Integer, primary_key=True, index=True)

    # Reference to chat session
    session_id = Column(
        String(100),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # File metadata
    file_path = Column(String(500), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=True)
    document_type = Column(
        Enum(DocumentType, values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )

    # Upload metadata
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    message_index = Column(Integer, nullable=True)  # Which message this was attached to

    # Indexing status
    indexing_status = Column(
        Enum(IndexingStatus, values_callable=lambda x: [e.value for e in x]),
        default=IndexingStatus.NOT_INDEXED,
        nullable=False
    )
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    indexed_chunks_count = Column(Integer, nullable=True)

    # Relationships
    session = relationship("ChatSession", back_populates="documents")

    def __repr__(self):
        return f"<SessionDocument(id={self.id}, filename='{self.filename}', session_id='{self.session_id}')>"


# =============================================================================
# Helper Functions
# =============================================================================

def create_default_middleware_config() -> List[MiddlewareConfig]:
    """Create default middleware configuration for DeepAgents."""
    return [
        MiddlewareConfig(
            type=MiddlewareType.TODO_LIST,
            enabled=True,
            config={"auto_track": True}
        ),
        MiddlewareConfig(
            type=MiddlewareType.FILESYSTEM,
            enabled=True,
            config={
                "auto_eviction": True,
                "eviction_threshold_bytes": 1000000  # 1MB
            }
        ),
        MiddlewareConfig(
            type=MiddlewareType.SUBAGENT,
            enabled=True,
            config={"max_depth": 3, "max_concurrent": 5}
        )
    ]


def create_default_backend_config() -> BackendConfig:
    """Create default backend configuration."""
    return BackendConfig(
        type=BackendType.COMPOSITE,
        config={},
        mappings={
            "/memory/": {"type": "vectordb", "config": {}},
            "/filesystem/": {"type": "filesystem", "config": {}},
            "/state/": {"type": "state", "config": {}}
        }
    )


def create_default_guardrails_config() -> GuardrailsConfig:
    """Create default guardrails configuration."""
    return GuardrailsConfig(
        interrupts={},
        token_limits={
            "max_total_tokens": 100000,
            "eviction_threshold": 80000,
            "summarization_threshold": 60000
        },
        enable_auto_eviction=True,
        enable_summarization=True
    )
