# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
"Only my rows" as one filter, applied at the query instead of at every caller.

Filesystem isolation comes from the root a path is resolved against
(``services/user_roots.py``); this is the same boundary for the *database* records
that describe those files. Both are needed: a downloaded file needs its path checked,
and a metadata lookup, tag edit or delete needs its row checked.

Deliberately a filter and not a proxy: a query that forgets it is visible in review as
``db.query(WorkspaceFile)`` with no ``owned(...)`` around it, which is a much easier
thing to catch than a per-endpoint ownership check that simply is not there.

The unowned case (``owner_id IS NULL``) exists for installs with no accounts at all:
those rows were written before accounts existed, so they belong to the install rather
than to a person, and the rule "no user → unowned rows" keeps such a machine exactly
as it behaves today.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session


def owner_id(db: Optional[Session] = None) -> Optional[int]:
    """The account whose rows this query may see (None = the whole install)."""
    from services import user_roots

    return user_roots.subject_user_id(db)


def owned(query, model, db: Optional[Session] = None):
    """Restrict ``query`` to rows belonging to whoever is asking."""
    uid = owner_id(db)
    if uid is None:
        return query.filter(model.owner_id.is_(None))
    return query.filter(model.owner_id == uid)


def same_owner(record, db: Optional[Session] = None) -> bool:
    """Does this already-fetched row belong to the caller?

    For the "by id" routes, which fetch first and must then answer 404 (not 403):
    telling someone "that exists but is not yours" is still telling them it exists.
    """
    uid = owner_id(db)
    if uid is None:
        return getattr(record, "owner_id", None) is None
    return getattr(record, "owner_id", None) == uid


def stamp(record, db: Optional[Session] = None):
    """Set ``owner_id`` on a row about to be inserted. Returns the record."""
    record.owner_id = owner_id(db)
    return record
