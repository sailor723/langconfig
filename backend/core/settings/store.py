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
    """One settings namespace's user-layer document (created by alembic 028
    or lazily via ``ensure_table``)."""

    __tablename__ = "settings_documents"

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


TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS settings_documents ("
    " ns VARCHAR(64) PRIMARY KEY,"
    " document JSON NOT NULL,"
    " revision INTEGER NOT NULL,"
    " updated_at TIMESTAMPTZ NOT NULL)"
)


def ensure_table(db: Session) -> None:
    """Create ``settings_documents`` if missing (idempotent, once per process)."""
    global _TABLE_ENSURE_DONE
    if _TABLE_ENSURE_DONE:
        return
    db.execute(text(TABLE_DDL))
    db.commit()
    _TABLE_ENSURE_DONE = True


def _reset_table_ensure() -> None:
    """Test hook: forget that the table was ensured (new DB in the process)."""
    global _TABLE_ENSURE_DONE
    _TABLE_ENSURE_DONE = False


# ── reads ────────────────────────────────────────────────────────────────────

def _row(db: Session, ns: str) -> Optional[SettingsDocument]:
    return db.get(SettingsDocument, ns)


def row_exists(db: Session, ns: str) -> bool:
    """Whether a document row exists for the namespace (no secret handling)."""
    return _row(db, ns) is not None


def get_document(db: Session, ns: str) -> dict:
    """Decrypted user-layer section for a namespace ({} when absent)."""
    spec = registry.get(ns)
    row = _row(db, ns)
    if row is None or not row.document:
        return {}
    return decrypt_document_secrets(dict(row.document), spec.schema)


def get_revision(db: Session, ns: str) -> int:
    row = _row(db, ns)
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


def _upsert(db: Session, ns: str, stored_doc: dict, revision: int) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    row = _row(db, ns)
    if row is None:
        db.add(SettingsDocument(ns=ns, document=stored_doc, revision=revision, updated_at=now))
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
) -> tuple[dict, int]:
    """Apply path ops to a namespace's user section and persist.

    Returns ``(normalized_decrypted_doc, new_revision)``. Raises
    ``SettingsConflict`` when ``expected_revision`` is stale, ``ValueError`` on
    malformed ops, and pydantic ``ValidationError`` on a schema-invalid result.
    """
    spec = registry.get(ns)
    ensure_table(db)
    row = _row(db, ns)
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
    _upsert(db, ns, stored, new_revision)
    logger.debug("settings %s mutate -> revision %d", ns, new_revision)
    return normalized, new_revision


def put_document(
    db: Session,
    ns: str,
    document: dict,
    expected_revision: Optional[int] = None,
) -> tuple[dict, int]:
    """Replace a namespace's user section wholesale (seed/migration path).

    Same validation/encryption/revision semantics as ``mutate`` with a single
    implicit replace.
    """
    spec = registry.get(ns)
    ensure_table(db)
    row = _row(db, ns)
    revision = row.revision if row is not None else 0
    if expected_revision is not None and revision != expected_revision:
        raise SettingsConflict(ns, revision, expected_revision)

    normalized = _validate_document(spec, dict(document or {}))
    stored = encrypt_document_secrets(normalized, spec.schema)
    new_revision = revision + 1
    _upsert(db, ns, stored, new_revision)
    return normalized, new_revision


def delete_document(db: Session, ns: str) -> bool:
    """Remove a namespace's document row (used by tests/cleanup)."""
    row = _row(db, ns)
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
