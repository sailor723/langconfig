# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import pytest
import os
from services.encryption import encryption_service

def test_encryption_service_initialization():
    """Test that encryption service initializes correctly."""
    assert encryption_service._fernet is not None

def test_encrypt_decrypt_cycle():
    """Test that data can be encrypted and then decrypted back to original."""
    original_text = "sk-test-1234567890abcdef"
    encrypted = encryption_service.encrypt(original_text)

    assert encrypted != original_text
    assert len(encrypted) > 0

    decrypted = encryption_service.decrypt(encrypted)
    assert decrypted == original_text

def test_decrypt_invalid_data():
    """Test that decrypting invalid data returns the original data (backward compatibility)."""
    invalid_data = "not-encrypted-data"
    # The service logs an error but returns the original data
    result = encryption_service.decrypt(invalid_data)
    assert result == invalid_data

def test_encrypt_empty():
    """Test encrypting empty string or None."""
    assert encryption_service.encrypt("") == ""
    assert encryption_service.encrypt(None) is None

def test_decrypt_empty():
    """Test decrypting empty string or None."""
    assert encryption_service.decrypt("") == ""
    assert encryption_service.decrypt(None) is None


# ─────────────────────────────────────────────────────────────────────
# Regression tests: key source + fail-loud decrypt (codebase review fixes)
# ─────────────────────────────────────────────────────────────────────

from services.encryption import (  # noqa: E402
    DEV_FALLBACK_KEY,
    ENCRYPTION_KEY_ENV,
    ENCRYPTION_KEY_ENV_LEGACY,
    EncryptionService,
    _derive_fernet_key,
    _resolve_key_str,
)


@pytest.fixture
def reset_service():
    """Reset the singleton after each test so a changed key can't leak."""
    yield
    EncryptionService._instance = None


def test_roundtrip_with_explicit_key(reset_service):
    svc = EncryptionService()
    svc.reset("test-secret-key-12345")
    token = svc.encrypt("sk-ant-super-secret")
    assert token.startswith("gAAAA")  # Fernet version byte 0x80
    assert svc.decrypt(token) == "sk-ant-super-secret"


def test_decrypt_raises_on_foreign_key_token(reset_service):
    """A Fernet token encrypted under a different key must raise, not return
    the ciphertext (key-rotation / corruption case)."""
    svc = EncryptionService()
    svc.reset("key-A")
    token = svc.encrypt("secret")
    svc.reset("key-B")  # simulate key rotation
    with pytest.raises(ValueError, match="cannot be decrypted"):
        svc.decrypt(token)


def test_resolve_key_str_uses_documented_env_var(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", None)
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, "env-documented-key")
    monkeypatch.setenv(ENCRYPTION_KEY_ENV_LEGACY, "env-legacy-key")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert _resolve_key_str() == "env-documented-key"


def test_resolve_key_str_legacy_env_var_still_supported(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", None)
    monkeypatch.delenv(ENCRYPTION_KEY_ENV, raising=False)
    monkeypatch.setenv(ENCRYPTION_KEY_ENV_LEGACY, "env-legacy-key")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert _resolve_key_str() == "env-legacy-key"


def test_settings_value_takes_priority_over_env(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", "from-settings")
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, "from-env")
    assert _resolve_key_str() == "from-settings"


def test_dev_fallback_is_not_the_old_public_default(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", None)
    monkeypatch.delenv(ENCRYPTION_KEY_ENV, raising=False)
    monkeypatch.delenv(ENCRYPTION_KEY_ENV_LEGACY, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    key = _resolve_key_str()
    assert key == DEV_FALLBACK_KEY
    assert key != "langconfig-default-insecure-key-change-me"


def test_production_refuses_dev_fallback(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", None)
    monkeypatch.delenv(ENCRYPTION_KEY_ENV, raising=False)
    monkeypatch.delenv(ENCRYPTION_KEY_ENV_LEGACY, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="must be set in production"):
        _resolve_key_str()


def test_production_allows_explicit_key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_key_encryption_key", None)
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, "prod-key")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert _resolve_key_str() == "prod-key"


def test_different_keys_derive_different_fernet_keys():
    assert _derive_fernet_key("key-1") != _derive_fernet_key("key-2")
