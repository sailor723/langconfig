# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for async_init_db / init_db schema parity.

The app startup path (async_init_db) previously did NOT pkgutil-register
every models.* module like the sync init_db() does, so a fresh database
booted via main.py was missing conversation_archives, user_profiles and
storage_objects (and the `vector` extension). These tests pin the shared
registration helper so the two paths cannot diverge again.
"""
import importlib

import pytest

import db.database as db_module


def test_register_all_models_registers_every_table():
    """After register_all_models(), Base.metadata must contain every model
    table — including the three that used to go missing on the async path."""
    from db.database import Base

    db_module.register_all_models()
    names = {t.name for t in Base.metadata.sorted_tables}

    for expected in (
        "deep_agent_templates",
        "custom_tools",
        "skills",
        "workflow_profiles",
        "models",
        "settings",
        "execution_events",
        "storage_objects",        # was missing on async path
        "conversation_archives",  # was missing on async path
        "user_profiles",          # was missing on async path
    ):
        assert expected in names, f"table {expected} not registered on Base.metadata"


def test_async_init_db_source_includes_vector_extension():
    """async_init_db must enable the `vector` extension (not just uuid-ossp)."""
    import inspect

    src = inspect.getsource(db_module.async_init_db)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in src
    assert 'register_all_models()' in src


def test_both_init_paths_share_registration_helper():
    import inspect

    sync_src = inspect.getsource(db_module.init_db)
    assert "register_all_models()" in sync_src


def test_models_init_does_not_import_everything():
    """Guard the premise: models/__init__ alone is insufficient, so the
    explicit registration helper is required."""
    import models
    missing = [
        name
        for name in ("ConversationArchive", "UserProfile", "StorageObject")
        if not hasattr(models, name)
    ]
    assert missing, "models/__init__ now exports everything — helper may be redundant"
