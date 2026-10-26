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


def owned(query, model, db: Optional[Session] = None, column: str = "owner_id"):
    """Restrict ``query`` to rows belonging to whoever is asking.

    ``column`` is "owner_id" for file records and "user_id" for the conversation
    tables, which grew their column before this module existed.
    """
    uid = owner_id(db)
    field = getattr(model, column)
    if uid is None:
        return query.filter(field.is_(None))
    return query.filter(field == uid)


def same_owner(record, db: Optional[Session] = None, column: str = "owner_id") -> bool:
    """Does this already-fetched row belong to the caller?

    For the "by id" routes, which fetch first and must then answer 404 (not 403):
    telling someone "that exists but is not yours" is still telling them it exists.
    """
    uid = owner_id(db)
    value = getattr(record, column, None)
    if uid is None:
        return value is None
    return value == uid


def stamp(record, db: Optional[Session] = None, column: str = "owner_id"):
    """Set the owning column on a row about to be inserted. Returns the record."""
    setattr(record, column, owner_id(db))
    return record


def visible_skills(query, db: Optional[Session] = None):
    """The skills this caller may see: every builtin, plus their own personal ones.

    Skills are not like files — a personal skill is not merely unreadable to another
    account, it must not appear in their catalogue at all, because progressive disclosure
    puts every catalogue entry into every agent's prompt. Built-ins (``owner_id IS NULL``)
    are the product's and stay visible to everyone.
    """
    from sqlalchemy import or_

    uid = owner_id(db)
    if uid is None:
        return query
    from models.skill import Skill

    return query.filter(or_(Skill.owner_id.is_(None), Skill.owner_id == uid))
