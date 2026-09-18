# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Settings document seeding — one idempotent entry point used by:

- ``scripts/seeds/seed_settings.py`` (explicit fresh-install bootstrap step),
- the backend boot hook in ``main.py`` (auto-seed, no-op when documents exist),
- tests.

Contract: write the ``get_defaults()`` documents (derived from the current
``.env`` via ``config.Settings``) only into namespaces that have NO document
row yet. Existing rows are never touched, so user edits (or a previous
backfill by alembic 028) survive re-runs. Only touches the
``settings_documents`` table — the legacy ``settings`` row is never read or
written here.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from . import store
from .defaults import get_defaults

logger = logging.getLogger(__name__)


def ensure_settings_seeded(db: Optional[Session] = None) -> int:
    """Write default documents for namespaces that have none.

    Returns how many documents were written. Safe to call on every boot:
    creates the table if missing, writes nothing when documents already exist.
    """
    own_session = db is None
    if own_session:
        from db.database import SessionLocal
        db = SessionLocal()
    try:
        store.ensure_table(db)
        written = 0
        for ns, doc in get_defaults().items():
            if not store.row_exists(db, ns):
                store.put_document(db, ns, doc)
                written += 1
        if written:
            logger.info("settings seed: wrote %d default document(s)", written)
        return written
    finally:
        if own_session:
            db.close()
