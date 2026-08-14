"""
Focused tests for DB-backed model runtime configuration.

These tests protect the Playground model path:
- default model resolution (config-driven, explicit model wins, missing → 400)
- provider API keys resolved via the config seam (`_get_decrypted_setting_value`)
- missing key → 400, never a silent wrong-key invocation
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.models import routes


def test_resolve_model_name_uses_default(monkeypatch):
    """When no model is provided, the configured default model must be used."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "default_model", "deepseek-chat")
    assert routes._resolve_model_name(None, MagicMock()) == "deepseek-chat"


def test_resolve_model_name_explicit_model_wins(monkeypatch):
    """An explicit model must win over the default."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "default_model", "fallback-model")
    assert routes._resolve_model_name("gpt-4o-mini", MagicMock()) == "gpt-4o-mini"


def test_resolve_model_name_raises_without_default(monkeypatch):
    """Missing default model should fail instead of silently falling back."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "default_model", None)
    with pytest.raises(HTTPException, match="Default model is not configured"):
        routes._resolve_model_name(None, MagicMock())


def test_create_llm_uses_provider_api_key(monkeypatch):
    """The playground LLM must be built with the provider API key."""
    fake_settings = SimpleNamespace()
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
        routes,
        "_get_decrypted_setting_value",
        lambda settings_row, key: "resolved-openai-key" if key == "openai" else None,
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

    assert captured_kwargs["api_key"] == "resolved-openai-key"
    assert captured_kwargs["model"] == "gpt-4o-mini"
    assert captured_kwargs["model_provider"] == "openai"


def test_create_llm_raises_without_api_key(monkeypatch):
    """A missing provider key must 400, never invoke with a wrong key."""
    fake_settings = SimpleNamespace()
    fake_model = SimpleNamespace(
        model_id="gpt-4o-mini",
        provider="openai",
        source="cloud",
        base_url=None,
        api_model_name=None,
    )

    monkeypatch.setattr(routes, "_get_settings_row", lambda db: fake_settings)
    monkeypatch.setattr(routes, "_get_active_model_row", lambda db, model_name: fake_model)
    monkeypatch.setattr(routes, "_get_decrypted_setting_value", lambda settings_row, key: None)
    monkeypatch.setenv("OPENAI_API_KEY", "env-only-key")  # must NOT satisfy the path

    with pytest.raises(HTTPException, match="Add it in Settings > API Keys"):
        routes._create_llm_for_playground(
            model_name="gpt-4o-mini",
            temperature=0.2,
            max_tokens=256,
            db=MagicMock(),
        )
