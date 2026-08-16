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

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
    local_provider: str = "ollama"
    local_base_url: str = "http://localhost:11434/v1"
    local_model_name: str = "llama3.2:latest"
    local_api_key: Optional[str] = Field(None, json_schema_extra={"role": "secret"})


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


# ── registry of v1 namespaces ────────────────────────────────────────────────
NAMESPACE_SCHEMAS: dict[str, type[BaseModel]] = {
    "general": GeneralSettings,
    "models": ModelsSettings,
    "workspace": WorkspaceSettings,
    "storage": StorageSettings,
    "rag": RagSettings,
    "search": SearchSettings,
    "onboarding": OnboardingSettings,
}
