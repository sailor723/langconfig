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
            "local_base_url": "http://localhost:11434/v1",
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
    }
