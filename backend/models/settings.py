# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings Database Model
Stores all user preferences and configuration in PostgreSQL
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float
from db.database import Base
import datetime
import os

# Single source of truth: OLLAMA_BASE_URL in .env. No hardcoded default.
from langgraph.connection import OLLAMA_BASE_URL


class Settings(Base):
    """
    Single-row settings table for storing all application configuration
    There should only ever be one row (id=1) in this table
    """
    __tablename__ = 'settings'

    id = Column(Integer, primary_key=True, default=1)  # Always 1

    # First-run onboarding: set to True once the user completes the setup
    # wizard (API key + workspace). False → the app shows the wizard on boot.
    setup_complete = Column(Boolean, default=False)

    # API Keys (encrypted in production)
    # Note: Should be moved to OS keychain via Tauri for security
    api_keys = Column(JSON, default=dict)  # {"openai": "sk-...", "anthropic": "sk-ant-..."}

    # General Settings
    app_name = Column(String, default="LangConfig")
    language = Column(String, default="en")  # zh, en, etc.
    auto_save = Column(Boolean, default=True)
    auto_save_interval = Column(Integer, default=300)  # seconds
    confirm_before_delete = Column(Boolean, default=True)
    show_notifications = Column(Boolean, default=True)
    check_updates = Column(Boolean, default=True)
    telemetry = Column(Boolean, default=False)
    log_level = Column(String, default="info")
    theme = Column(String, default="langconfig")

    # RAG/Vector Database Settings
    storage_path = Column(String, nullable=True)
    # Storage mode runtime override (docs/system-architecture.md §15): 'local'
    # (disk, default) | 'db' (Postgres BYTEA). Nullable — None means "use the
    # .env / default value". Set via Settings UI -> GET/PUT /api/settings/storage-mode.
    storage_mode = Column(String, nullable=True)
    embedding_model = Column(String, default="text-embedding-3-small")
    chunk_size = Column(Integer, default=1000)
    chunk_overlap = Column(Integer, default=200)

    # Model Defaults
    # NULL = "use .env" (config.Settings is the single source of truth).
    # The settings UI only overrides these when the user explicitly sets them.
    default_model = Column(String, default=None)
    default_temperature = Column(Float, default=None)
    max_tokens = Column(Integer, default=None)

    # Local Models Settings
    local_provider = Column(String, default="ollama")
    # Source of truth: OLLAMA_BASE_URL in .env (or LOCAL_LLM_BASE_URL).
    # The +"/v1" suffix is added by the caller that consumes this URL.
    local_base_url = Column(String, default=os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL) + "/v1")
    local_model_name = Column(String, default="llama3.2:latest")
    local_api_key = Column(String, nullable=True)

    # Workspace Settings
    workspace_path = Column(String, default="")
    workspace_allow_read = Column(Boolean, default=True)
    workspace_allow_write = Column(Boolean, default=True)
    workspace_require_approval = Column(Boolean, default=True)
    workspace_auto_detect_git = Column(Boolean, default=True)
    workspace_backup_before_edit = Column(Boolean, default=True)

    # Model Defaults Advanced (NULL = fall back to .env / config defaults)
    primary_model = Column(String, default=None)
    fallback_models = Column(JSON, default=lambda: ["claude-sonnet-4-5"])
    temperature = Column(Float, default=None)
    max_tokens_default = Column(Integer, default=None)
    top_p = Column(Float, default=1.0)
    routing_strategy = Column(String, default="balanced")
    daily_token_limit = Column(Integer, default=0)  # 0 = unlimited
    monthly_token_limit = Column(Integer, default=0)  # 0 = unlimited
    alert_threshold = Column(Integer, default=80)  # percentage

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
