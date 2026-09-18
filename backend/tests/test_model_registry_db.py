# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the DB-driven model registry.

core/models/registry.py hardcoded ~12 OpenAI/Anthropic/Google models and
never read the PostgreSQL `models` table — a parallel legacy registry that
contradicts §16.1 ("the models table is the single source of truth").
The registry now augments the hardcoded fallback with DB rows.
"""
import pytest

from core.models.registry import (
    ModelCapability,
    ModelInfo,
    ModelProvider,
    ModelRegistry,
)


class _FakeRow:
    """Minimal stand-in for a models.Model row."""

    def __init__(self, model_id, provider, display_name, capabilities, is_active=True):
        self.model_id = model_id
        self.provider = provider
        self.display_name = display_name
        self.capabilities = capabilities
        self.is_active = is_active


def test_db_models_registered(monkeypatch):
    """DB rows must land in the registry with mapped provider/capabilities."""

    class _FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass
        def query(self, *a, **kw):
            return self
        def filter(self, *a, **kw):
            return self
        def all(self):
            return [
                _FakeRow("deepseek-chat", "deepseek", "DeepSeek Chat",
                         {"streaming": True, "tools": True, "max_context": 128000}),
                _FakeRow("claude-4-5-sonnet", "anthropic", "Claude 4.5",
                         {"streaming": True, "vision": True}),
            ]

    monkeypatch.setattr("db.database.SessionLocal", lambda: _FakeSession())

    reg = ModelRegistry()
    reg._load_db_models()

    ds = reg.get_model("deepseek-chat")
    assert ds is not None
    assert ds.provider == ModelProvider.DEEPSEEK
    assert ModelCapability.STREAMING in ds.capabilities
    assert ModelCapability.TOOLS in ds.capabilities
    assert ds.max_context_tokens == 128000

    claude = reg.get_model("claude-4-5-sonnet")
    assert claude is not None
    assert ModelCapability.VISION in claude.capabilities


def test_db_overrides_hardcoded_fallback(monkeypatch):
    """A DB row with the same model_id must override the hardcoded entry."""
    from core.models.registry import model_registry as _unused  # noqa: F401

    class _FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass
        def query(self, *a, **kw): return self
        def filter(self, *a, **kw): return self
        def all(self):
            return [_FakeRow("gpt-4o-mini", "openai", "GPT-4o Mini (DB)", {})]

    monkeypatch.setattr("db.database.SessionLocal", lambda: _FakeSession())
    reg = ModelRegistry()
    reg._load_db_models()
    assert reg.get_model("gpt-4o-mini").display_name == "GPT-4o Mini (DB)"


def test_db_failure_keeps_fallback(monkeypatch):
    """When the DB is unavailable the hardcoded fallback must survive."""

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("db.database.SessionLocal", boom)
    reg = ModelRegistry()  # __init__ catches the DB error internally
    assert len(reg._models) > 0  # fallback models still registered
