# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DSH-style settings engine for LangConfig (docs/settings-refactor.md).

Namespaces (schemas.py) + registry (registry.py) + resolution (resolve.py) +
Postgres document store (store.py) + secret redaction/encryption (secrets.py)
+ seed defaults (defaults.py). The wire API (describe/mutate endpoints) and
the shims over the legacy settings router land in a later phase.
"""

from __future__ import annotations

from . import defaults, registry, resolve, runtime, schemas, secrets, seed, store
from .defaults import get_defaults
from .registry import NamespaceSpec, get, is_registered, namespaces, register, specs
from .resolve import ResolvedNamespace, resolve, resolve_all, resolve_value
from .runtime import local_llm_config, runtime_get, runtime_models, runtime_rag, runtime_storage, runtime_value, runtime_workspace
from .seed import ensure_settings_seeded
from .schemas import (
    NAMESPACE_SCHEMAS,
    ApiKeys,
    GeneralSettings,
    ModelsSettings,
    OnboardingSettings,
    RagSettings,
    SearchSettings,
    StorageSettings,
    WorkspaceSettings,
)
from .secrets import (
    decrypt_document_secrets,
    delete_at_path,
    encrypt_document_secrets,
    get_at_path,
    redact,
    secret_paths,
    set_at_path,
)
from .store import (
    SettingsConflict,
    SettingsDocument,
    _reset_table_ensure,
    delete_document,
    ensure_table,
    get_document,
    get_revision,
    mutate,
    put_document,
    reset_documents,
    row_exists,
)

__all__ = [
    # registry
    "NamespaceSpec", "get", "is_registered", "namespaces", "register", "specs",
    # resolve
    "ResolvedNamespace", "resolve", "resolve_all", "resolve_value",
    # schemas
    "NAMESPACE_SCHEMAS",
    "ApiKeys", "GeneralSettings", "KnowledgeSettings", "ModelsSettings",
    "OnboardingSettings", "RagSettings", "SearchSettings", "StorageSettings",
    "WorkspaceSettings",
    # secrets
    "decrypt_document_secrets", "delete_at_path", "encrypt_document_secrets",
    "get_at_path", "redact", "secret_paths", "set_at_path",
    # store
    "SettingsConflict", "SettingsDocument", "delete_document", "ensure_table",
    "get_document", "get_revision", "mutate", "put_document", "reset_documents",
    "row_exists",
    # defaults
    "get_defaults",
    # runtime accessors (Phase 5b)
    "local_llm_config", "runtime_get", "runtime_models", "runtime_rag",
    "runtime_storage", "runtime_value", "runtime_workspace",
    # seed
    "ensure_settings_seeded",
]


def _register_v1() -> None:
    """Register the v1 namespaces at import time (idempotent)."""
    for ns, schema in schemas.NAMESPACE_SCHEMAS.items():
        register(ns, schema)


_register_v1()
