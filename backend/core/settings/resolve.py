# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings resolution — merge schema defaults with the account's document.

Resolution order is ``schema defaults → shared (owner) section → own section``.
The shared layer exists because migration 037 made settings per-account without
breaking the installs that already had one: the owner's row doubles as the
site-wide default, and an account that sets only a single credential still
inherits the rest.

``value`` is the merged, decrypted section for internal consumers; ``user`` is
the account's **own** section (nothing inherited), which is what the Settings UI
must edit — otherwise "save" would copy the inherited values into the account's
own document. ``wire()`` adds the redacted view the API returns.
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
    value: dict  # merged defaults + shared + own, decrypted (internal)
    user: dict  # own section only, decrypted (what this account set)
    revision: int
    writable: bool = True
    #: True when some effective value came from the shared/owner layer, i.e. the
    #: account is inheriting rather than running entirely on its own settings.
    inherits: bool = False

    def wire(self) -> dict:
        """Wire-safe view: secrets stripped from value/user and enumerated.

        Each secret position carries ``source`` — ``own`` (this account set it),
        ``shared`` (it is inherited from the shared/owner layer) or ``unset``.
        Without it the Settings UI cannot tell a credential the user configured
        from one the whole install is spending, and both render as "set".
        """
        from .secrets import secret_sources

        redacted_value, _ = redact(self.value, self.schema)
        redacted_user, _ = redact(self.user, self.schema)
        return {
            "ns": self.ns,
            "schema": self.schema.model_json_schema(),
            "value": redacted_value,
            "user": redacted_user,
            "revision": self.revision,
            "writable": self.writable,
            "inherit": self.inherits,
            "secrets": secret_sources(self.user, self.value, self.schema),
        }


def resolve(
    db: Optional[Session], ns: str, user_id: Optional[int] = None
) -> ResolvedNamespace:
    """Resolve one namespace for an account (default: the caller).

    ``db=None`` yields the pure schema-defaults view (user={}, revision=0) —
    useful for defaults-only consumers and tests.
    """
    spec = registry.get(ns)
    if db is None:
        own, effective = {}, {}
    else:
        own, effective = store.get_effective_document(db, ns, user_id)
    defaults = spec.schema().model_dump()
    merged = {**defaults, **effective}
    value = spec.schema.model_validate(merged).model_dump()
    revision = store.get_revision(db, ns, user_id) if db is not None else 0
    return ResolvedNamespace(
        ns=ns,
        schema=spec.schema,
        value=value,
        user=own,
        revision=revision,
        inherits=bool(effective) and effective != own,
    )


def resolve_all(db: Optional[Session], user_id: Optional[int] = None) -> list[ResolvedNamespace]:
    """Resolve every registered namespace, in registration order."""
    return [resolve(db, ns, user_id) for ns in registry.namespaces()]


def resolve_value(
    db: Optional[Session], ns: str, user_id: Optional[int] = None
) -> dict:
    """Convenience: just the merged value dict."""
    return resolve(db, ns, user_id).value
