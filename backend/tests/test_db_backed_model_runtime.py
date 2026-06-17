"""
Focused tests for DB-backed model runtime configuration.

These tests protect the GraphIndex/Playground model path so it reads:
- default model from PostgreSQL settings
- provider API keys from PostgreSQL settings
- no silent fallback to environment variables for runtime model config
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.models import routes


def test_resolve_model_name_uses_db_default():
    """When no model is provided, the DB default model must be used."""
    fake_settings = SimpleNamespace(default_model="deepseek-chat", api_keys={})

    db = MagicMock()
    routes_result = MagicMock()
    routes_result.filter.return_value.first.return_value = fake_settings
    db.query.return_value = routes_result

    assert routes._resolve_model_name(None, db) == "deepseek-chat"


def test_resolve_model_name_raises_without_db_default():
    """Missing DB default_model should fail instead of falling back to gpt-4o."""
    fake_settings = SimpleNamespace(default_model=None, api_keys={})

    db = MagicMock()
    routes_result = MagicMock()
    routes_result.filter.return_value.first.return_value = fake_settings
    db.query.return_value = routes_result

    with pytest.raises(HTTPException, match="Default model is not configured"):
        routes._resolve_model_name(None, db)


def test_create_llm_uses_db_api_key(monkeypatch: pytest.MonkeyPatch):
    """Provider API keys must come from PostgreSQL settings."""
    fake_settings = SimpleNamespace(
        default_model="gpt-4o-mini",
        api_keys={"openai": "enc-openai-key"},
    )
    fake_model = SimpleNamespace(
        model_id="gpt-4o-mini",
        provider="openai",
        source="cloud",
        base_url=None,
        api_model_name=None,
    )
    captured_kwargs = {}

    monkeypatch.setattr(routes, "_get_settings_row", lambda db: fake_settings)
    monkeypatch.setattr(routes, "_get_active_model_row", lambda db, model_name: fake_model)
    monkeypatch.setattr(
        routes.encryption_service,
        "decrypt",
        lambda value: "db-openai-key" if value == "enc-openai-key" else None,
    )

    def fake_init_chat_model(**kwargs):
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(routes, "init_chat_model", fake_init_chat_model)

    routes._create_llm_for_playground(
        model_name="gpt-4o-mini",
        temperature=0.2,
        max_tokens=256,
        db=MagicMock(),
    )

    assert captured_kwargs["api_key"] == "db-openai-key"
    assert captured_kwargs["model"] == "gpt-4o-mini"
    assert captured_kwargs["model_provider"] == "openai"


def test_create_llm_does_not_fallback_to_env_api_key(monkeypatch: pytest.MonkeyPatch):
    """An env var must not satisfy runtime model config when DB key is missing."""
    fake_settings = SimpleNamespace(default_model="gpt-4o-mini", api_keys={})
    fake_model = SimpleNamespace(
        model_id="gpt-4o-mini",
        provider="openai",
        source="cloud",
        base_url=None,
        api_model_name=None,
    )

    monkeypatch.setenv("OPENAI_API_KEY", "env-only-key")
    monkeypatch.setattr(routes, "_get_settings_row", lambda db: fake_settings)
    monkeypatch.setattr(routes, "_get_active_model_row", lambda db, model_name: fake_model)
    monkeypatch.setattr(routes.encryption_service, "decrypt", lambda value: None)

    with pytest.raises(HTTPException, match="Add it in Settings > API Keys"):
        routes._create_llm_for_playground(
            model_name="gpt-4o-mini",
            temperature=0.2,
            max_tokens=256,
            db=MagicMock(),
        )
