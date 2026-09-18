#!/usr/bin/env python3
"""Provision any target PostgreSQL database for LangConfig.

When you run several Postgres databases, point LangConfig at one of them:

    1. pick a name (e.g. ``langconfig``, ``langconfig_dev``, ...),
    2. create/initialize it with this script,
    3. set DATABASE_URL to the printed line in the root ``.env``.

The script connects to the Postgres server using the credentials in the root
``.env`` (DATABASE_URL / POSTGRES_*), creates the target database when it is
missing, enables pgvector + uuid-ossp, then runs the same init path the
backend uses on startup (all LangConfig tables + hierarchy columns).

Usage:
    python db/setup_target_db.py [NAME]    # default: TARGET_DB or the db in DATABASE_URL
    python db/setup_target_db.py --list    # list existing databases and exit
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

# Make the backend package importable regardless of the cwd.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR.parent / ".env")  # root .env (same file the backend reads)

from sqlalchemy import create_engine, text  # noqa: E402

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_db_url(url: str) -> tuple:
    """Split ``postgresql://user:pass@host:port/db`` into (host, port, user, password, db)."""
    u = urlparse(url)
    return (u.hostname, u.port, unquote(u.username or ""), unquote(u.password or ""), (u.path or "/").lstrip("/"))


def _conn_url(user: str, password: str, host: str, port: int, db: str) -> str:
    """Build a URL with the user/password safely percent-encoded."""
    return f"postgresql://{quote(user)}:{quote(password)}@{host}:{port}/{db}"


def _list_databases(maintenance_url: str) -> None:
    with create_engine(maintenance_url, isolation_level="AUTOCOMMIT").connect() as conn:
        rows = conn.execute(
            text("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
        )
        for (dbname,) in rows:
            print(dbname)


def _create_target_db(maintenance_url: str, name: str) -> bool:
    """Create the target database when missing; return True if it already existed."""
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            ).scalar()
            if exists:
                print(f"· database '{name}' already exists — skipping create")
                return True
            quoted = '"' + name.replace('"', '""') + '"'
            conn.execute(text(f"CREATE DATABASE {quoted}"))
            print(f"· created database '{name}'")
            return False
    except Exception as exc:  # noqa: BLE001 - surface permission errors for manual fix
        print(f"✗ could not create '{name}': {exc}")
        print(f"  run manually as a superuser:  CREATE DATABASE {name};")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Create + initialize a LangConfig target database")
    parser.add_argument("name", nargs="?", help="target database name (default: TARGET_DB or DATABASE_URL's db)")
    parser.add_argument("--list", action="store_true", help="list existing databases and exit")
    args = parser.parse_args()

    # DATABASE_URL may be derived from POSTGRES_* (see db/db_url.py); reuse
    # the same fallback so this utility targets the configured server too.
    from db.db_url import compose_db_url
    url = os.getenv("DATABASE_URL") or compose_db_url()
    host, port, user, password, url_db = _parse_db_url(url)
    maintenance_url = _conn_url(user, password, host, port, "postgres")

    if args.list:
        _list_databases(maintenance_url)
        return 0

    name = args.name or os.getenv("TARGET_DB") or url_db
    if not IDENT_RE.match(name):
        print(f"✗ invalid database name: {name!r}")
        return 1

    print(f"Target database: {name} @ {host}:{port}")
    _create_target_db(maintenance_url, name)

    # Point the app machinery at the target DB, then run the exact init the
    # backend runs on startup (extensions + all tables + hierarchy columns).
    target_url = _conn_url(user, password, host, port, name)
    os.environ["DATABASE_URL"] = target_url
    from db import database  # noqa: E402 - must import after DATABASE_URL is set
    import models  # noqa: E402,F401 - registers every table on Base.metadata

    database.init_db()

    with database.engine.connect() as conn:
        tables = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        ).scalar()
    print(f"✓ '{name}' ready — {tables} tables (pgvector + uuid-ossp enabled)")
    print()
    print("Add this to the root .env to use this database:")
    print(f"  DATABASE_URL={target_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
