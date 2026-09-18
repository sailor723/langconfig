# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings resolution — merge schema defaults with the user document.

DSH resolution order is ``schema defaults → base layer → user section``; with
the base layer folded into the seeded document (see docs/settings-refactor.md),
LangConfig resolves ``schema defaults → DB user document``. ``value`` is the
merged, decrypted section for internal consumers; ``wire()`` is the redacted
view the API returns (secrets stripped + enumerated).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import registry, store
from .secrets import redact


@dataclass
class ResolvedNamespace:
    """One namespace's resolved view (DSH ``SettingsDescriptor`` analog)."""

    ns: str
    schema: type[BaseModel]
    value: dict  # merged defaults + user section, decrypted (internal)
    user: dict  # raw user section, decrypted
    revision: int
    writable: bool = True

    def wire(self) -> dict:
        """Wire-safe view: secrets stripped from value/user and enumerated."""
        redacted_value, secrets = redact(self.value, self.schema)
        redacted_user, _ = redact(self.user, self.schema)
        return {
            "ns": self.ns,
            "schema": self.schema.model_json_schema(),
            "value": redacted_value,
            "user": redacted_user,
            "revision": self.revision,
            "writable": self.writable,
            "secrets": secrets,
        }


def resolve(db: Optional[Session], ns: str) -> ResolvedNamespace:
    """Resolve one namespace: schema defaults overlaid with the user document.

    ``db=None`` yields the pure schema-defaults view (user={}, revision=0) —
    useful for defaults-only consumers and tests.
    """
    spec = registry.get(ns)
    user = store.get_document(db, ns) if db is not None else {}
    defaults = spec.schema().model_dump()
    merged = {**defaults, **user}
    value = spec.schema.model_validate(merged).model_dump()
    revision = store.get_revision(db, ns) if db is not None else 0
    return ResolvedNamespace(
        ns=ns,
        schema=spec.schema,
        value=value,
        user=user,
        revision=revision,
    )


def resolve_all(db: Optional[Session]) -> list[ResolvedNamespace]:
    """Resolve every registered namespace, in registration order."""
    return [resolve(db, ns) for ns in registry.namespaces()]


def resolve_value(db: Optional[Session], ns: str) -> dict:
    """Convenience: just the merged value dict."""
    return resolve(db, ns).value
