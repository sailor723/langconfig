# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Seed-time defaults for settings documents.

These are the "effective defaults" a fresh install receives: written into the
DB user documents by ``seed_settings.py`` / the boot auto-seed, and used by
``core/settings/runtime.py`` as the pre-migration fallback so behavior is
identical before and after migration. The values mirror the old root ``.env``
(``DEFAULT_MODEL=deepseek-chat``, ``DEFAULT_TEMPERATURE=0``,
``MAX_TOKENS=256000``, ``FALLBACK_MODELS=local-ollama-qwen25-14b``,
``DEFAULT_EMBEDDING_MODEL=ollama-nomic-embed-text:latest``, storage/workspace
roots, local-LLM endpoint). Phase 5b: fully hardcoded — the corresponding
``config.Settings`` fields and ``.env`` keys are gone.

Namespaces with no ``.env`` source (``general``, ``search``, ``onboarding``)
resolve entirely from their schema defaults.
"""

from __future__ import annotations

import os


def _fallback_list(value: str) -> list[str]:
    return [m.strip() for m in (value or "").split(",") if m.strip()]


def get_defaults() -> dict[str, dict]:
    """Default documents for a fresh install (mirrors the old root .env)."""
    return {
        "models": {
            "default_model": "deepseek-chat",
            "default_temperature": 0.0,
            "max_tokens": 256000,
            "fallback_models": _fallback_list("local-ollama-qwen25-14b"),
            "primary_model": "deepseek-chat",
            "local_provider": "ollama",
            # Source of truth: OLLAMA_BASE_URL / LOCAL_LLM_BASE_URL in .env.
            # No hardcoded port here: the centralized connection module
            # provides the fallback when the seeded runtime block is empty.
            "local_base_url": os.getenv("LOCAL_LLM_BASE_URL")
                or os.getenv("OLLAMA_BASE_URL", "") + "/v1",
            "local_model_name": "llama3.2:latest",
        },
        "workspace": {
            "base_dir": "backend/outputs",
        },
        "storage": {
            # STORAGE_MODE is a kept optional override (runtime base default) —
            # honor it so a fresh seed preserves the operator's choice.
            "mode": os.getenv("STORAGE_MODE") or "local",
            "base_dir": "./data/storage",
            "documents_base_dir": "./data/documents",
        },
        "rag": {
            "embedding_model": "ollama-nomic-embed-text:latest",
        },
        # Create-time agent limits, one set per agent kind. The numbers come from
        # measurement on this codebase: recursion_limit counts LangGraph
        # supersteps, and one LLM turn costs ~13 steps for a standard agent (six
        # default middleware × before_model + after_model) but only ~2 for a
        # DeepAgent (its middleware runs inside the model node). So 400 steps is
        # ~30 LLM turns for a standard agent and 150 steps ~75 tool turns for a
        # DeepAgent. summarization_threshold must stay above the agent's own
        # baseline (system prompt + tool schemas, measured ~12,000 tokens) or it
        # compacts on every single turn.
        "agents": {
            "agent": {
                "recursion_limit": 400,
                "summarization_threshold": 60000,
                "keep_last_messages": 20,
                "max_total_tokens": 100000,
                "eviction_threshold": 80000,
                "enable_summarization": True,
                "enable_auto_eviction": True,
            },
            "deepagent": {
                "recursion_limit": 150,
                "summarization_threshold": 60000,
                "keep_last_messages": 20,
                "max_total_tokens": 100000,
                "eviction_threshold": 80000,
                "enable_summarization": True,
                "enable_auto_eviction": True,
            },
        },
        # Runtime user-adjustable settings (was the long list of overrides in
        # backend/config.py + the root .env — now the Settings panel owns
        # the values; this seed is the bootstrap default on first boot).
        "runtime": {
            "langconfig_workspace_root": os.getenv("LANGCONFIG_WORKSPACE_ROOT") or "backend/.workspace_data",
            "backup_dir": os.getenv("BACKUP_DIR") or "./backups",
            "storage_mode": os.getenv("STORAGE_MODE") or "local",
            "ollama_embed_model": os.getenv("OLLAMA_EMBED_MODEL") or "nomic-embed-text:latest",
            "langsmith_tracing": (os.getenv("LANGSMITH_TRACING") or "false").lower() == "true",
            "langsmith_project": os.getenv("LANGSMITH_PROJECT") or "langconfig",
            "db_pool_size": int(os.getenv("DB_POOL_SIZE") or "10"),
            "db_max_overflow": int(os.getenv("DB_MAX_OVERFLOW") or "20"),
            "analysis_recursion_limit": int(os.getenv("ANALYSIS_RECURSION_LIMIT") or "1000"),
            "analysis_dashboard_timeout": int(os.getenv("ANALYSIS_DASHBOARD_TIMEOUT") or "600"),
            "analysis_chat_timeout": int(os.getenv("ANALYSIS_CHAT_TIMEOUT") or "120"),
            "rate_limit_enabled": (os.getenv("RATE_LIMIT_ENABLED") or "true").lower() == "true",
            "rate_limit_requests_per_minute": int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE") or "1000"),
            "performance_monitoring_enabled": (os.getenv("PERFORMANCE_MONITORING_ENABLED") or "true").lower() == "true",
            "slow_request_threshold_ms": int(os.getenv("SLOW_REQUEST_THRESHOLD_MS") or "1000"),
            "log_slow_queries": (os.getenv("LOG_SLOW_QUERIES") or "true").lower() == "true",
            "slow_query_threshold": float(os.getenv("SLOW_QUERY_THRESHOLD") or "1.0"),
            "log_all_requests": (os.getenv("LOG_ALL_REQUESTS") or "false").lower() == "true",
            "max_execution_history_per_workflow": int(os.getenv("MAX_EXECUTION_HISTORY_PER_WORKFLOW") or "100"),
            "execution_history_retention_days": int(os.getenv("EXECUTION_HISTORY_RETENTION_DAYS") or "90"),
            "auto_cleanup_execution_history": (os.getenv("AUTO_CLEANUP_EXECUTION_HISTORY") or "true").lower() == "true",
        },
    }
