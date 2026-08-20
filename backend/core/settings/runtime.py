# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Runtime settings accessors (Phase 5b of docs/settings-refactor.md).

Application code used to read ``config.Settings`` fields (populated from the
root ``.env``). After 5b it reads the DSH-style documents instead:

    runtime_value(ns)  -> resolved value = schema defaults + user document
                          (the document was seeded from .env / migration 028)

Read-only: never creates the ``settings_documents`` table. When the table is
unavailable (a pre-migration database) the value falls back to the seed
defaults in ``defaults.py`` — which mirror the old ``.env`` values — so
behavior is identical before and after migration.
"""

from __future__ import annotations

from typing import Any, Optional


def runtime_value(ns: str) -> dict:
    """Resolve a namespace with a short-lived session (app-runtime use).

    Falls back to the seed defaults (``get_defaults()``) when the documents
    table is missing or unreadable, so pre-migration databases behave exactly
    like the old ``.env`` config.
    """
    from db.database import SessionLocal
    from .defaults import get_defaults
    from .resolve import resolve_value

    db = SessionLocal()
    try:
        return resolve_value(db, ns)
    except Exception:
        return get_defaults().get(ns, {})
    finally:
        db.close()


def runtime_get(ns: str, field: str, fallback: Any = None) -> Any:
    """Resolve one field of a namespace (None values fall through to fallback)."""
    value = runtime_value(ns).get(field)
    return value if value is not None else fallback


def runtime_models() -> dict:
    """Convenience: resolved models namespace (LLM defaults + local models)."""
    return runtime_value("models")


def runtime_storage() -> dict:
    """Convenience: resolved storage namespace."""
    return runtime_value("storage")


def runtime_rag() -> dict:
    """Convenience: resolved rag namespace."""
    return runtime_value("rag")


def runtime_workspace() -> dict:
    """Convenience: resolved workspace namespace."""
    return runtime_value("workspace")


def local_llm_config() -> dict:
    """Local LLM endpoint config (was config.local_llm_* from .env)."""
    from langgraph.connection import OLLAMA_BASE_URL
    models = runtime_value("models")
    return {
        "provider": models.get("local_provider") or "ollama",
        "base_url": models.get("local_base_url") or (OLLAMA_BASE_URL + "/v1"),
        "model_name": models.get("local_model_name") or "llama3.2:latest",
        "api_key": models.get("local_api_key"),
    }
