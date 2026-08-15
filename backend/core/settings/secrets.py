# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Secret handling for settings documents (DSH ``redact.ts`` analog).

Two concerns:

1. **At rest** — every schema-declared secret field is Fernet-encrypted before
   the document row is written and decrypted when read back (legacy plaintext
   passes through unchanged, per ``services/encryption.py``).
2. **At the wire** — ``redact()`` strips secret fields from the value the API
   returns and enumerates their positions with a ``set`` flag, so the UI can
   render write-only inputs with set/missing dots without ever receiving the
   secret itself.

Also hosts the tiny JSON-path helpers shared by ``store.py`` (op application)
and this module (redaction/encryption walks).
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from pydantic import BaseModel

# Fernet tokens always start with this prefix (services/encryption.py) — used
# to recognize encrypted values when decrypting a document.
_FERNET_PREFIX = "gAAAA"


# ── JSON path helpers ────────────────────────────────────────────────────────

def get_at_path(doc: dict, path: list[str]) -> Any:
    """Return the value at a JSON path, or a MISSING sentinel."""
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return _MISSING
        cur = cur[key]
    return cur


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<MISSING>"


_MISSING = _Missing()


def set_at_path(doc: dict, path: list[str], value: Any) -> None:
    """Set a value at a JSON path, creating intermediate dicts as needed."""
    if not path:
        raise ValueError("empty path")
    cur = doc
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def delete_at_path(doc: dict, path: list[str]) -> bool:
    """Delete a value at a JSON path. Returns True if it existed."""
    if not path:
        raise ValueError("empty path")
    cur = doc
    for key in path[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    if isinstance(cur, dict) and path[-1] in cur:
        del cur[path[-1]]
        return True
    return False


# ── schema walking ───────────────────────────────────────────────────────────

def is_secret_field(model_field: Any) -> bool:
    """Whether a pydantic model field is declared ``role='secret'``."""
    extra = model_field.json_schema_extra
    if isinstance(extra, dict):
        return extra.get("role") == "secret"
    return False


def _field_schema_type(model_field: Any) -> Optional[type[BaseModel]]:
    """The nested pydantic model class for a field, if it has one."""
    annotation = model_field.annotation
    # Optional[Nested] and plain Nested both unwrap here.
    while hasattr(annotation, "__args__"):
        args = [a for a in annotation.__args__ if a is not type(None)]
        if not args:
            return None
        annotation = args[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def secret_paths(schema: type[BaseModel], prefix: Optional[list[str]] = None) -> list[list[str]]:
    """All JSON paths (from the section root) whose fields are secrets.

    Walks nested pydantic models so ``models.api_keys.openai_api_key`` yields
    ``["api_keys", "openai_api_key"]``.
    """
    prefix = prefix or []
    paths: list[list[str]] = []
    for name, model_field in schema.model_fields.items():
        path = [*prefix, name]
        if is_secret_field(model_field):
            paths.append(path)
        nested = _field_schema_type(model_field)
        if nested is not None:
            paths.extend(secret_paths(nested, path))
    return paths


# ── at-rest encryption ───────────────────────────────────────────────────────

def _encryption():
    # Lazy: services.encryption pulls in config/.env at import time; keep
    # importing core.settings light (registry/schemas are import-safe).
    from services.encryption import encryption_service
    return encryption_service


def encrypt_document_secrets(doc: dict, schema: type[BaseModel]) -> dict:
    """Deep-copy ``doc`` with every secret field encrypted (missing ones left
    absent). The result is what gets stored in the DB row."""
    encrypted = copy.deepcopy(doc)
    svc = _encryption()
    for path in secret_paths(schema):
        value = get_at_path(encrypted, path)
        if value is _MISSING or value is None:
            continue
        if isinstance(value, str) and value.startswith(_FERNET_PREFIX):
            continue  # already encrypted
        set_at_path(encrypted, path, svc.encrypt(str(value)))
    return encrypted


def decrypt_document_secrets(doc: dict, schema: type[BaseModel]) -> dict:
    """Deep-copy ``doc`` with every encrypted secret field decrypted. Legacy
    plaintext values pass through unchanged (encryption_service contract)."""
    decrypted = copy.deepcopy(doc)
    svc = _encryption()
    for path in secret_paths(schema):
        value = get_at_path(decrypted, path)
        if value is _MISSING or value is None:
            continue
        if isinstance(value, str) and value.startswith(_FERNET_PREFIX):
            set_at_path(decrypted, path, svc.decrypt(value))
    return decrypted


# ── wire redaction ───────────────────────────────────────────────────────────

def redact(doc: dict, schema: type[BaseModel]) -> tuple[dict, list[dict]]:
    """Strip every secret field from a deep copy of ``doc``.

    Returns ``(redacted_value, secrets)`` where each secret entry is
    ``{"path": [...], "set": bool}`` — positions are always enumerated (even
    unset, so a form knows the slot exists), exactly like DSH's redactor.
    """
    redacted = copy.deepcopy(doc)
    secrets: list[dict] = []
    for path in secret_paths(schema):
        value = get_at_path(redacted, path)
        secrets.append({"path": path, "set": value is not _MISSING and value is not None})
        delete_at_path(redacted, path)
    return redacted, secrets
