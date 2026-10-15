# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings namespace schemas (DSH-style).

Each namespace owns one pydantic model — the analog of DeepSeek Harness's
schemastery schema per settings namespace. The schema defines:

- the user-document shape (validated on every write),
- the resolution defaults (schema defaults fill gaps left by the document),
- secret positions (fields marked ``role='secret'`` are encrypted at rest and
  redacted at the wire — see ``core/settings/secrets.py``).

The values here mirror the seed-time defaults in ``defaults.py`` so an empty
document and a seeded document resolve identically.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── general ──────────────────────────────────────────────────────────────────
class GeneralSettings(BaseModel):
    """App-level user preferences (mirrors models/settings.py general block)."""

    model_config = ConfigDict(extra="forbid")

    app_name: str = "LangConfig"
    language: str = "en"  # zh, en, etc.
    auto_save: bool = True
    auto_save_interval: int = 300  # seconds
    confirm_before_delete: bool = True
    show_notifications: bool = True
    check_updates: bool = True
    telemetry: bool = False
    log_level: str = "info"
    theme: str = "langconfig"
    # UI display mode for catalog activities (Tools, Agents, DeepAgents,
    # Skills, Knowledge, Prompt). 'verbose' shows the marketing-rich
    # HomePage on entry; 'direct' jumps straight into the most-recent
    # (or first) item's editor tab, hiding the catalog grid until the
    # user explicitly clicks back.
    display_mode: Literal["verbose", "direct"] = "verbose"


# ── models ───────────────────────────────────────────────────────────────────
class ApiKeys(BaseModel):
    """Provider credentials. Every *_api_key field is a secret: encrypted at
    rest (Fernet) and stripped from wire responses — the UI only sees
    set/missing dots (DSH ProviderEditor behavior)."""

    model_config = ConfigDict(extra="forbid")

    openai_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    openai_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    anthropic_base_url: Optional[str] = None
    google_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    google_base_url: Optional[str] = None
    cohere_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    cohere_base_url: Optional[str] = None
    replicate_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    replicate_base_url: Optional[str] = None
    deepseek_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    deepseek_api_base: Optional[str] = None
    glm_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    glm_api_base: Optional[str] = None
    minimax_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    minimax_api_base: Optional[str] = None
    qwen_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    qwen_api_base: Optional[str] = None
    kimi_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    kimi_api_base: Optional[str] = None
    tavily_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    serper_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    exa_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    brave_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    agnes_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    agnes_base_url: Optional[str] = None

    # Non-LLM-provider credentials (kept here for one-encrypted-store semantics).
    # All are stripped from wire responses (json_schema_extra={"role":"secret"})
    # unless overridden below.
    langsmith_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    google_client_id: Optional[str] = Field(None)
    google_client_secret: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    slack_webhook_url: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    discord_webhook_url: Optional[str] = Field(None, json_schema_extra={"role": "secret"})


class ModelsSettings(BaseModel):
    """LLM defaults + provider credentials + local-model config.

    ``default_model``/``default_temperature``/``max_tokens`` are NULL-able:
    absent from the document means "no override" (the seeded document carries
    the effective values; an empty document resolves to schema defaults).
    """

    model_config = ConfigDict(extra="forbid")

    api_keys: ApiKeys = ApiKeys()

    # Model defaults (NULL = "use the seeded/default value")
    default_model: Optional[str] = None
    default_temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    # Model Defaults Advanced
    primary_model: Optional[str] = None
    fallback_models: list[str] = []
    top_p: float = 1.0
    routing_strategy: str = "balanced"
    daily_token_limit: int = 0  # 0 = unlimited
    monthly_token_limit: int = 0  # 0 = unlimited
    alert_threshold: int = 80  # percentage

    # Local models
    # Defaults are sourced from .env (OLLAMA_BASE_URL / LOCAL_LLM_BASE_URL).
    # No hardcoded port: the centralized connection module is the source
    # of truth, so changing the host/port is a single-file .env edit.
    local_provider: str = "ollama"
    local_base_url: str = ""
    local_model_name: str = "llama3.2:latest"
    local_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})

    @model_validator(mode="after")
    def _fill_local_defaults(self):
        if not self.local_base_url:
            from langgraph.connection import OLLAMA_BASE_URL
            self.local_base_url = OLLAMA_BASE_URL + "/v1"
        return self


# ── workspace ────────────────────────────────────────────────────────────────
class WorkspaceSettings(BaseModel):
    """Per-install workspace (was settings.workspace_* + WORKSPACE_BASE_DIR)."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = ""
    allow_read: bool = True
    allow_write: bool = True
    require_approval: bool = True
    auto_detect_git: bool = True
    backup_before_edit: bool = True
    base_dir: str = "backend/outputs"  # was WORKSPACE_BASE_DIR in .env


# ── storage ──────────────────────────────────────────────────────────────────
class StorageSettings(BaseModel):
    """Storage backend (docs/system-architecture.md §15): local | db | s3(future)."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "local"
    base_dir: str = "./data/storage"  # was storage_base_dir in .env
    documents_base_dir: str = "./data/documents"  # was DOCUMENTS_BASE_DIR in .env


# ── rag ──────────────────────────────────────────────────────────────────────
class RagSettings(BaseModel):
    """RAG/vector pipeline defaults (was settings.embedding_model/chunk_*)."""

    model_config = ConfigDict(extra="forbid")

    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 1000
    chunk_overlap: int = 200


# ── search ───────────────────────────────────────────────────────────────────
class SearchSettings(BaseModel):
    """Search backends (Tavily/Serper keys are secrets; provider table stays
    in search_providers)."""

    model_config = ConfigDict(extra="forbid")

    tavily_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})
    serper_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})


# ── onboarding ───────────────────────────────────────────────────────────────
class OnboardingSettings(BaseModel):
    """First-run wizard state (was settings.setup_complete)."""

    model_config = ConfigDict(extra="forbid")

    setup_complete: bool = False
    api_key_set: bool = False
    workspace_set: bool = False


class RuntimeSettings(BaseModel):
    """User-adjustable runtime settings (was a long list of `.env` overrides
    in ``backend/config.py`` — the Settings panel is now the source of truth,
    with the values seeded from ``.env`` on first boot).

    The DB doc ``runtime`` is the live source. ``.env`` is only the bootstrap
    default (read by pydantic-settings into ``config.Settings`` on cold start).
    """

    model_config = ConfigDict(extra="forbid")

    # Workspace / backups
    langconfig_workspace_root: str = "backend/.workspace_data"
    backup_dir: str = "./backups"

    # Storage
    storage_mode: str = "local"

    # Local embeddings
    ollama_embed_model: str = "nomic-embed-text:latest"

    # Tracing (LangSmith key is a secret in models.api_keys; toggle + project are runtime)
    langsmith_tracing: bool = False
    langsmith_project: str = "langconfig"

    # DB pool tuning
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Agent runtime / analysis
    analysis_recursion_limit: int = 1000
    analysis_dashboard_timeout: int = 600
    analysis_chat_timeout: int = 120

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 1000

    # Performance / observability
    performance_monitoring_enabled: bool = True
    slow_request_threshold_ms: int = 1000
    log_slow_queries: bool = True
    slow_query_threshold: float = 1.0
    log_all_requests: bool = False

    # Execution history
    max_execution_history_per_workflow: int = 100
    execution_history_retention_days: int = 90
    auto_cleanup_execution_history: bool = True


# ── agents (create-time defaults) ────────────────────────────────────────────
def _agent_limits(recursion_limit: int) -> "AgentLimits":
    """Shared create-time limits, differing only in the step budget."""
    return AgentLimits(
        recursion_limit=recursion_limit,
        summarization_threshold=60000,
        keep_last_messages=20,
        max_total_tokens=100000,
        eviction_threshold=80000,
        enable_summarization=True,
        enable_auto_eviction=True,
    )


class AgentLimits(BaseModel):
    """Limits applied when an agent is created (per agent kind).

    ``recursion_limit`` counts LangGraph supersteps, not tool calls. Measured on
    this codebase: one LLM turn costs ~13 steps for a standard agent (each of the
    six default middleware contributes a ``before_model`` *and* an ``after_model``
    step) but only ~2 for a DeepAgent (its middleware runs inside the model node).
    Both kinds therefore need different numbers to express the same intent:

        standard agent : 400 steps  ~= 30 LLM turns
        DeepAgent      : 150 steps  ~= 75 tool turns

    ``summarization_threshold`` is compared against system prompt + tool schemas +
    conversation, so it must stay comfortably above an agent's own baseline
    (measured ~12,000 tokens for a 30-tool DeepAgent) or it compacts every turn.
    """

    model_config = ConfigDict(extra="forbid")

    recursion_limit: int = Field(
        ge=1, description="LangGraph supersteps allowed in one chat run"
    )
    summarization_threshold: int = Field(
        ge=1, description="Compact when the model call would exceed this many tokens"
    )
    keep_last_messages: int = Field(
        ge=1, description="Messages kept verbatim after compaction"
    )
    max_total_tokens: int = Field(
        ge=1, description="Context budget for workflow nodes / exported apps (not enforced in chat)"
    )
    eviction_threshold: int = Field(
        ge=1, description="Declared threshold; must satisfy summarization < eviction < max_total"
    )
    enable_summarization: bool = True
    enable_auto_eviction: bool = True

    @model_validator(mode="after")
    def _validate_ordering(self) -> "AgentLimits":
        if not (
            self.summarization_threshold < self.eviction_threshold < self.max_total_tokens
        ):
            raise ValueError(
                "agent limits must satisfy summarization_threshold "
                f"({self.summarization_threshold}) < eviction_threshold "
                f"({self.eviction_threshold}) < max_total_tokens ({self.max_total_tokens})"
            )
        return self


class AgentsSettings(BaseModel):
    """Create-time defaults, one set per agent kind (Settings → Agents)."""

    model_config = ConfigDict(extra="forbid")

    agent: AgentLimits = Field(default_factory=lambda: _agent_limits(400))
    deepagent: AgentLimits = Field(default_factory=lambda: _agent_limits(150))


# ── registry of v1 namespaces ────────────────────────────────────────────────
# ── knowledge ────────────────────────────────────────────────────────────────
class KnowledgeSettings(BaseModel):
    """Knowledge-base behaviour: which model doc chat answers with.

    Doc Chat used to carry an LLM dropdown of its own, which is the wrong place for it — the
    choice belongs with the knowledge base, set once, not re-made in a chat panel every time. It
    lives here rather than in `models` because it is a knowledge setting: a knowledge base can be
    pointed at a different model without changing what every agent in the app uses.

    NULL means "follow the app default" (`models.default_model`), so an install that never opens
    this setting behaves exactly as before.
    """

    model_config = ConfigDict(extra="forbid")

    doc_chat_model: Optional[str] = None
    doc_chat_temperature: Optional[float] = None


NAMESPACE_SCHEMAS: dict[str, type[BaseModel]] = {
    "general": GeneralSettings,
    "models": ModelsSettings,
    "workspace": WorkspaceSettings,
    "storage": StorageSettings,
    "rag": RagSettings,
    "search": SearchSettings,
    "onboarding": OnboardingSettings,
    "runtime": RuntimeSettings,
    "agents": AgentsSettings,
    "knowledge": KnowledgeSettings,
}
