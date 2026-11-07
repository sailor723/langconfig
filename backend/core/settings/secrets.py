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
    """Return the value at a JSON path, or a MISSING sentinel.

    List indices are supported (``["items", 0, "password"]``) because settings
    documents hold lists of models — a secret inside a row is still a secret.
    """
    cur: Any = doc
    for key in path:
        if isinstance(cur, list):
            idx = key if isinstance(key, int) else (int(key) if str(key).isdigit() else None)
            if idx is None or not 0 <= idx < len(cur):
                return _MISSING
            cur = cur[idx]
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return _MISSING
    return cur


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<MISSING>"


_MISSING = _Missing()


def set_at_path(doc: dict, path: list[str], value: Any) -> None:
    """Set a value at a JSON path, creating intermediate dicts as needed.

    A list position must already exist when its parent chain runs through a list;
    callers get there via :func:`expand_path`, which only yields real indices.
    """
    if not path:
        raise ValueError("empty path")
    cur: Any = doc
    for key in path[:-1]:
        if isinstance(cur, list):
            idx = key if isinstance(key, int) else int(key)
            nxt = cur[idx]
            if not isinstance(nxt, (dict, list)):
                nxt = {}
                cur[idx] = nxt
            cur = nxt
            continue
        nxt = cur.get(key)
        if not isinstance(nxt, (dict, list)):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    if isinstance(cur, list):
        cur[path[-1] if isinstance(path[-1], int) else int(path[-1])] = value
    else:
        cur[path[-1]] = value


def delete_at_path(doc: dict, path: list[str]) -> bool:
    """Delete a value at a JSON path. Returns True if it existed."""
    if not path:
        raise ValueError("empty path")
    cur: Any = doc
    for key in path[:-1]:
        if isinstance(cur, list):
            idx = key if isinstance(key, int) else (int(key) if str(key).isdigit() else None)
            if idx is None or not 0 <= idx < len(cur):
                return False
            cur = cur[idx]
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return False
    last = path[-1] if isinstance(path[-1], int) else (
        int(path[-1]) if str(path[-1]).isdigit() else path[-1]
    )
    if isinstance(cur, list) and isinstance(last, int):
        # A secret inside a list row is deleted by clearing the field, not by
        # removing the row: dropping the item would shift every later index and
        # silently change which database the row describes.
        if 0 <= last < len(cur):
            cur[last] = None
            return True
        return False
    if isinstance(cur, dict) and last in cur:
        del cur[last]
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
            # A `list[Model]` field yields "<field>.*.<secret>": the "*" is
            # expanded per document (see `expand_path`), because the number of
            # rows is data, not schema. Without this a password on a list row
            # was stored (and returned) as plaintext while the UI showed it as a
            # secret slot.
            paths.extend(secret_paths(nested, [*path, "*"] if _is_list_of_models(model_field) else path))
    return paths


def _is_list_of_models(model_field: Any) -> bool:
    """True for a ``list[BaseModel]`` (or ``Optional[list[BaseModel]]``) field."""
    annotation = model_field.annotation
    while hasattr(annotation, "__args__"):
        # Check the origin BEFORE unwrapping: `list[X].__args__` is `(X,)`, so
        # unwrapping first walks straight past the list and answers False.
        if getattr(annotation, "__origin__", None) is list:
            args = getattr(annotation, "__args__", ())
            return bool(args) and _is_model_class(args[0])
        args = [a for a in annotation.__args__ if a is not type(None)]
        if len(args) != 1:
            return False
        annotation = args[0]
    return False


def _is_model_class(annotation: Any) -> bool:
    while hasattr(annotation, "__args__"):
        args = [a for a in annotation.__args__ if a is not type(None)]
        if not args:
            return False
        annotation = args[0]
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def expand_path(doc: dict, path: list[str]) -> list[list[str]]:
    """Concrete paths for a declared secret path — ``"*"`` matches list indices.

    A declared path is schema-shaped (``items.*.password``); a document is not
    (``items`` holds however many rows exist), so every reader/writer has to
    expand before touching values.
    """
    out: list[list[str]] = [[]]
    for seg in path:
        nxt: list[list[str]] = []
        for prefix in out:
            if seg != "*":
                nxt.append([*prefix, seg])
                continue
            cur = get_at_path(doc, prefix)
            if isinstance(cur, list):
                nxt.extend([*prefix, i] for i in range(len(cur)))
        out = nxt
    return out


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
    for declared in secret_paths(schema):
        for path in expand_path(encrypted, declared):
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
    for declared in secret_paths(schema):
        for path in expand_path(decrypted, declared):
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
    for declared in secret_paths(schema):
        concrete = expand_path(redacted, declared)
        if not concrete:
            # An empty list still reports the slot, so a form knows it exists.
            secrets.append({"path": declared, "set": False})
            continue
        for path in concrete:
            value = get_at_path(redacted, path)
            secrets.append({"path": path, "set": value is not _MISSING and value is not None})
            delete_at_path(redacted, path)
    return redacted, secrets


def _has_value(doc: dict, path: list[str]) -> bool:
    value = get_at_path(doc, path)
    return value is not _MISSING and value is not None and value != ""


def secret_sources(own: dict, effective: dict, schema: type[BaseModel]) -> list[dict]:
    """Every secret position with **who set it**: own / shared / unset.

    ``set`` alone cannot answer the question someone asks when they open Settings
    on an account that inherits: "is this credential mine, or am I spending
    somebody else's?" On the wire both look identical, because the value never
    crosses it — only the position does.

    ``own`` is the account's own section, ``effective`` the merged one, both
    decrypted and taken BEFORE redaction. A field the account set is ``own`` even
    when the shared layer has one too: the account's value is the one in use.
    """
    out: list[dict] = []
    for declared in secret_paths(schema):
        for path in expand_path(effective, declared) or [declared]:
            if _has_value(own, path):
                source = "own"
            elif _has_value(effective, path):
                source = "shared"
            else:
                source = "unset"
            out.append({"path": path, "set": source != "unset", "source": source})
    return out
