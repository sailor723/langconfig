# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Dependency-free DATABASE_URL composition.

Kept import-light (no SQLAlchemy) so any consumer — including config.py,
which must not trigger engine construction — can derive the runtime
DATABASE_URL from the POSTGRES_* .env block without side effects.
"""
import os


def compose_db_url() -> str:
    """Build the runtime DATABASE_URL from the POSTGRES_* .env parts.

    The POSTGRES_* block is the single source of truth (also read by
    docker-compose.yml and sql_setup_db.py), so switching between a native
    PostgreSQL install and the Docker one is a pure .env edit — no code
    changes. Set DATABASE_URL explicitly to fully override (e.g. a remote DB).
    """
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "langconfig")
    password = os.getenv("POSTGRES_PASSWORD", "langconfig_dev")
    dbname = os.getenv("POSTGRES_DB", "langconfig")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
