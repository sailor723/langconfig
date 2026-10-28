# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings document store — PostgreSQL persistence for the DSH-style seam.

One row per namespace in ``settings_documents``:

    ns          VARCHAR(64)  PRIMARY KEY      -- 'models', 'general', …
    document    JSON         NOT NULL         -- user layer section (secrets encrypted)
    revision    INTEGER      NOT NULL         -- monotonic per namespace
    updated_at  TIMESTAMPTZ  NOT NULL

Semantics mirror DSH's ``settings.mutate``:

- ``mutate(db, ns, ops, expected_revision)`` applies path ops (set/unset) to the
  user section, validates the result against the namespace schema, encrypts
  secret fields at rest, and bumps the revision. A stale ``expected_revision``
  raises ``SettingsConflict`` (the API maps it to 409).
- ``get_document`` / ``get_revision`` return the *decrypted* user section and
  revision — consumers never see ciphertext. The wire layer (``resolve.wire``)
  redacts secrets for the UI.

The table is created lazily via ``ensure_table`` (process-wide flag, mirroring
the ``_SETTINGS_MIGRATED`` pattern in api/system/settings.py) so the engine
works before alembic 028 lands; once the ORM model is imported the table is
also part of ``Base.metadata`` for ``init_db()``/``async_init_db()``.
"""

from __future__ import annotations

import copy
import datetime
import logging
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Integer, JSON, String, text
from sqlalchemy.orm import Session

from db.database import Base
from . import registry
from .secrets import (
    decrypt_document_secrets,
    delete_at_path,
    encrypt_document_secrets,
    set_at_path,
)

logger = logging.getLogger(__name__)

_TABLE_ENSURE_DONE = False


class SettingsDocument(Base):
    """One settings namespace's user-layer document, **per account**.

    Migration 037 made this per-account: the key is ``(user_id, ns)`` instead of
    ``ns``. Every account therefore carries its own provider credentials and
    model defaults, which is what "each user has their own keys" needs.

    ``user_id`` defaults to the owner (1) so a call site that does not pass one
    keeps the pre-037 behaviour, and so the owner's row doubles as the **shared**
    layer that other accounts inherit when they set nothing.
    """

    __tablename__ = "settings_documents"

    user_id = Column(Integer, primary_key=True, default=1)
    ns = Column(String(64), primary_key=True)
    document = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SettingsConflict(Exception):
    """Optimistic-concurrency failure: the namespace revision moved on."""

    def __init__(self, ns: str, current: int, expected: Optional[int]):
        self.ns = ns
        self.current = current
        self.expected = expected
        super().__init__(
            f"settings namespace {ns!r} revision changed ({current}); "
            f"expected {expected}"
        )


#: The account whose row is also the **shared** layer. Accounts that have not
#: set a field inherit it from here, so an existing single-account install keeps
#: working after 037 and a new account is usable on day one.
OWNER_USER_ID = 1

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS settings_documents ("
    " user_id INTEGER NOT NULL DEFAULT 1,"
    " ns VARCHAR(64) NOT NULL,"
    " document JSON NOT NULL,"
    " revision INTEGER NOT NULL,"
    " updated_at TIMESTAMPTZ NOT NULL,"
    " PRIMARY KEY (user_id, ns))"
)


def ensure_table(db: Session) -> None:
    """Create ``settings_documents`` if missing, and upgrade a pre-037 shape.

    Idempotent, once per process. The upgrade path matters for databases that
    were booted via ``create_all`` / ``alembic stamp head`` (the test database is
    one): they never replay migration 037, so the table can still be keyed by
    ``ns`` alone. Adding ``user_id`` with a default of 1 turns those rows into
    the owner's — exactly what 037's backfill does.
    """
    global _TABLE_ENSURE_DONE
    if _TABLE_ENSURE_DONE:
        return
    db.execute(text(TABLE_DDL))
    # Dialect-neutral introspection: this store also runs on SQLite (tests,
    # single-file installs), where ``information_schema`` does not exist.
    try:
        from sqlalchemy import inspect

        cols = {c["name"] for c in inspect(db.connection()).get_columns("settings_documents")}
    except Exception:  # noqa: BLE001 — introspection failure must not block a read
        cols = {"user_id", "ns"}
    if "user_id" not in cols:
        logger.info("settings_documents: upgrading to per-account key (user_id, ns)")
        db.execute(
            text(
                "ALTER TABLE settings_documents "
                "ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
            )
        )
        db.execute(
            text("ALTER TABLE settings_documents DROP CONSTRAINT IF EXISTS settings_documents_pkey")
        )
        db.execute(text("ALTER TABLE settings_documents ADD PRIMARY KEY (user_id, ns)"))
        db.execute(text("ALTER TABLE settings_documents ALTER COLUMN user_id DROP DEFAULT"))
    db.commit()
    _TABLE_ENSURE_DONE = True


def _reset_table_ensure() -> None:
    """Test hook: forget that the table was ensured (new DB in the process)."""
    global _TABLE_ENSURE_DONE
    _TABLE_ENSURE_DONE = False


def _resolve_user_id(user_id: Optional[int]) -> int:
    """The account a read/write applies to.

    Explicit ``user_id`` wins; otherwise the identity of the current turn (the
    LAN gate / session cookie put it in a ContextVar); otherwise the owner. The
    last step is what keeps background jobs, seeds and tests working — they run
    with no caller and must act on the shared layer.
    """
    if user_id is not None:
        return int(user_id)
    try:
        from core.context.current_user import current_user_id

        uid = current_user_id()
    except Exception:  # noqa: BLE001 — identity is optional for settings I/O
        uid = None
    return int(uid) if uid else OWNER_USER_ID



# ── reads ────────────────────────────────────────────────────────────────────

def _row(db: Session, ns: str, user_id: Optional[int] = None) -> Optional[SettingsDocument]:
    return db.get(SettingsDocument, (_resolve_user_id(user_id), ns))


def row_exists(db: Session, ns: str, user_id: Optional[int] = None) -> bool:
    """Whether a document row exists for the namespace (no secret handling)."""
    return _row(db, ns, user_id) is not None


def get_document(db: Session, ns: str, user_id: Optional[int] = None) -> dict:
    """Decrypted user-layer section for a namespace ({} when absent).

    This is the account's **own** section — what it set, nothing inherited. Use
    :func:`get_effective_document` when you want the values the account actually
    runs with.
    """
    spec = registry.get(ns)
    row = _row(db, ns, user_id)
    if row is None or not row.document:
        return {}
    return decrypt_document_secrets(dict(row.document), spec.schema)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge ``override`` over ``base``, recursing into nested dicts.

    Per-field inheritance, not per-document: an account that sets only
    ``deepseek_api_key`` keeps inheriting the owner's ``openai_api_key``.
    """
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def get_effective_document(
    db: Session, ns: str, user_id: Optional[int] = None
) -> tuple[dict, dict]:
    """``(own_section, effective_section)`` for an account.

    ``effective`` = the owner's section with the account's own section merged
    over it, field by field. When the account **is** the owner the two are equal.
    """
    uid = _resolve_user_id(user_id)
    own = get_document(db, ns, uid)
    if uid == OWNER_USER_ID:
        return own, own
    shared = get_document(db, ns, OWNER_USER_ID)
    return own, _deep_merge(shared, own)


def get_revision(db: Session, ns: str, user_id: Optional[int] = None) -> int:
    row = _row(db, ns, user_id)
    return row.revision if row is not None else 0


# ── writes ───────────────────────────────────────────────────────────────────

def _project_validated(input_doc: dict, normalized: dict) -> dict:
    """Keep only the keys present in the incoming document, with pydantic-
    normalized values. Nested dicts recurse, so a partial ``api_keys`` update
    stays partial — the stored user section contains only user-set fields
    (DSH's raw-section semantics), while values are type-coerced."""
    out: dict = {}
    for key, value in input_doc.items():
        if key not in normalized:
            continue  # rejected by validation (extra="forbid") — unreachable
        nv = normalized[key]
        if isinstance(value, dict) and isinstance(nv, dict):
            out[key] = _project_validated(value, nv)
        else:
            out[key] = nv
    return out


def _validate_document(spec: registry.NamespaceSpec, doc: dict) -> dict:
    """Validate an incoming (sparse, decrypted) section against the namespace
    schema.

    Returns the sparse section with pydantic-normalized values for the keys
    that were provided (unknown fields rejected per the schema's ``extra``
    config; the ``validate`` callback sees the full resolved view).
    """
    validated = spec.schema.model_validate(doc)
    normalized = validated.model_dump(mode="json")
    if spec.validate is not None:
        spec.validate(normalized)
    return _project_validated(doc, normalized)


def _apply_op(doc: dict, op: dict) -> None:
    op_name = op.get("op")
    path = op.get("path")
    if not isinstance(path, list) or not path:
        raise ValueError(f"mutate op requires a non-empty 'path' list, got {path!r}")
    if op_name == "set":
        if "value" not in op:
            raise ValueError("mutate op 'set' requires a 'value'")
        set_at_path(doc, path, op["value"])
    elif op_name == "unset":
        delete_at_path(doc, path)
    else:
        raise ValueError(f"unknown mutate op {op_name!r}")


def _upsert(
    db: Session, ns: str, stored_doc: dict, revision: int, user_id: Optional[int] = None
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    uid = _resolve_user_id(user_id)
    row = _row(db, ns, uid)
    if row is None:
        db.add(
            SettingsDocument(
                user_id=uid, ns=ns, document=stored_doc, revision=revision, updated_at=now
            )
        )
    else:
        row.document = stored_doc
        row.revision = revision
        row.updated_at = now
    db.commit()


def mutate(
    db: Session,
    ns: str,
    ops: list[dict],
    expected_revision: Optional[int] = None,
    user_id: Optional[int] = None,
) -> tuple[dict, int]:
    """Apply path ops to a namespace's user section and persist.

    The write targets one account's row — by default the caller's (identity from
    the current request), else the owner. Returns
    ``(normalized_decrypted_doc, new_revision)``. Raises ``SettingsConflict``
    when ``expected_revision`` is stale, ``ValueError`` on malformed ops, and
    pydantic ``ValidationError`` on a schema-invalid result.
    """
    spec = registry.get(ns)
    ensure_table(db)
    row = _row(db, ns, user_id)
    current = dict(row.document) if row is not None and row.document else {}
    revision = row.revision if row is not None else 0

    if expected_revision is not None and revision != expected_revision:
        raise SettingsConflict(ns, revision, expected_revision)

    new_doc = decrypt_document_secrets(current, spec.schema)
    for op in ops:
        _apply_op(new_doc, op)

    normalized = _validate_document(spec, new_doc)
    stored = encrypt_document_secrets(normalized, spec.schema)
    new_revision = revision + 1
    _upsert(db, ns, stored, new_revision, user_id)
    logger.debug("settings %s mutate -> revision %d", ns, new_revision)
    return normalized, new_revision


def put_document(
    db: Session,
    ns: str,
    document: dict,
    expected_revision: Optional[int] = None,
    user_id: Optional[int] = None,
) -> tuple[dict, int]:
    """Replace a namespace's user section wholesale (seed/migration path).

    Same validation/encryption/revision semantics as ``mutate`` with a single
    implicit replace. Targets the caller's row by default; seeds and imports pass
    ``user_id=OWNER_USER_ID`` explicitly so a background job can never overwrite
    a member's personal settings.
    """
    spec = registry.get(ns)
    ensure_table(db)
    row = _row(db, ns, user_id)
    revision = row.revision if row is not None else 0
    if expected_revision is not None and revision != expected_revision:
        raise SettingsConflict(ns, revision, expected_revision)

    normalized = _validate_document(spec, dict(document or {}))
    stored = encrypt_document_secrets(normalized, spec.schema)
    new_revision = revision + 1
    _upsert(db, ns, stored, new_revision, user_id)
    return normalized, new_revision


def delete_document(db: Session, ns: str, user_id: Optional[int] = None) -> bool:
    """Remove a namespace's document row for one account (tests/cleanup)."""
    row = _row(db, ns, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def reset_documents(db: Session) -> None:
    """Delete every document row (tests)."""
    ensure_table(db)
    db.execute(text("DELETE FROM settings_documents"))
    db.commit()
