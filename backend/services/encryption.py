# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Encryption Service for Securing Sensitive Data

Handles encryption and decryption of sensitive information like API keys
using Fernet symmetric encryption.
"""
import os
import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

# Documented env var (root .env / env_example). Legacy name kept for
# backward compatibility with deployments that set APP_ENCRYPTION_KEY.
ENCRYPTION_KEY_ENV = "API_KEY_ENCRYPTION_KEY"
ENCRYPTION_KEY_ENV_LEGACY = "APP_ENCRYPTION_KEY"
# Dev-only fallback. Never used when ENVIRONMENT=production.
DEV_FALLBACK_KEY = "langconfig-dev-insecure-key-change-me"

# The sentinel shipped in `env_example`. It is the *absence* of a key, but it is
# non-empty, so a naive check would accept it as one — and an unedited `.env`
# would then encrypt real secrets under a key that matches no other machine,
# making them unreadable as soon as that line is edited or blanked. Treated as
# unset below. See backend/scripts/audit_settings_secrets.py.
TEMPLATE_PLACEHOLDER_KEY = "PASTE-THE-64-HEX-OUTPUT-OF-OPENSSL-RAND-HEX-32"

# Fernet tokens always start with the version byte 0x80, base64-encoded as
# "gAAAA". Used to distinguish encrypted values from legacy plaintext.
_FERNET_PREFIX = "gAAAA"


def _reject_placeholder(value: "str | None") -> "str | None":
    """Return ``value`` unless it is the env_example placeholder, which counts as unset."""
    if value and value.strip() == TEMPLATE_PLACEHOLDER_KEY:
        logger.warning(
            "%s is still the env_example placeholder — ignoring it and using the DEV "
            "fallback key. Replace it with a real key or leave it blank. Any secret "
            "already encrypted with the placeholder needs "
            "backend/scripts/audit_settings_secrets.py --rekey-from.",
            ENCRYPTION_KEY_ENV,
        )
        return None
    return value


def _resolve_key_str() -> str:
    """Resolve the Fernet key seed.

    Priority: settings (pydantic, from .env) → documented env var →
    legacy env var → dev fallback. In production the fallback is refused.
    The env_example placeholder counts as unset at every step.
    """
    try:
        from config import settings
        configured = _reject_placeholder(getattr(settings, "api_key_encryption_key", None))
        if configured:
            return configured
    except Exception:
        pass

    key_str = _reject_placeholder(os.getenv(ENCRYPTION_KEY_ENV) or os.getenv(ENCRYPTION_KEY_ENV_LEGACY))
    if key_str:
        return key_str

    env = os.getenv("ENVIRONMENT", "development")
    if env == "production":
        raise RuntimeError(
            f"{ENCRYPTION_KEY_ENV} must be set in production — refusing to "
            "encrypt secrets with a well-known fallback key"
        )
    logger.warning(
        "%s not set — using a DEV fallback encryption key. Set it in the "
        "root .env before storing real secrets.", ENCRYPTION_KEY_ENV
    )
    return DEV_FALLBACK_KEY


def _derive_fernet_key(key_str: str) -> bytes:
    salt = b'langconfig_salt'  # Fixed salt for deterministic key derivation
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(key_str.encode()))


class EncryptionService:
    _instance = None
    _fernet = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EncryptionService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self, key_str: str = None):
        """Initialize the encryption key from environment or a dev default.

        key_str is only used by tests/reset; production always resolves from
        the environment.
        """
        try:
            source = key_str if key_str is not None else _resolve_key_str()
            self._fernet = Fernet(_derive_fernet_key(source))
            logger.info("Encryption service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize encryption service: {e}")
            raise

    def reset(self, key_str: str = None):
        """Re-initialize the singleton with a specific key (tests only)."""
        self._initialize(key_str=key_str)

    def encrypt(self, data: str) -> str:
        """Encrypt a string value."""
        if not data:
            return data
        try:
            return self._fernet.encrypt(data.encode()).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt an encrypted string value.

        Legacy plaintext values (not Fernet tokens) pass through unchanged for
        backward compatibility. A Fernet-shaped value that fails to decrypt
        raises instead of silently returning ciphertext — otherwise a key
        rotation would feed undecryptable tokens to consumers as if they were
        the real secrets.
        """
        if not encrypted_data:
            return encrypted_data
        if not encrypted_data.startswith(_FERNET_PREFIX):
            # Legacy plaintext (or an empty/malformed value) — pass through.
            return encrypted_data
        try:
            return self._fernet.decrypt(encrypted_data.encode()).decode()
        except InvalidToken:
            logger.error(
                "Failed to decrypt Fernet token — the encryption key has "
                "changed since this value was stored, or the value is corrupt"
            )
            raise ValueError(
                "Stored secret cannot be decrypted with the current "
                f"{ENCRYPTION_KEY_ENV}. If the key was rotated, re-encrypt the "
                "stored secrets (or clear the affected DB rows)."
            ) from None
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

# Global instance
encryption_service = EncryptionService()
