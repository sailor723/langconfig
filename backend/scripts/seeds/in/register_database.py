"""Register a database in Settings → Databases, from the shell.

The `databases` settings document is what points an agent's `datasource` at a real
database: `services/deepagent_factory/assembly.py::_datasource_env` reads it and hands
the sandbox `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`, so `psql` and psycopg2 work
inside an agent's `execute` with no DSN in the prompt.

The Settings UI does the same thing through `/api/system/settings/databases` (admin
only). This script exists for the *provisioning* case — standing up a fresh target for
a new ontology build — so the run does not have to be five clicks in a browser.

    .venv/bin/python scripts/seeds/in/register_database.py \
        --name doc_demo --label "文档演示库 (doc_demo)" --dbname doc_demo \
        --host 127.0.0.1 --port 5432 --user weiping

Idempotent: an entry with the same `name` is replaced in place (revision bumped), other
entries are untouched. `--password` is optional — an empty password is what a local
trust-auth PostgreSQL expects.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND  # noqa: E402,F401

from core.settings import store  # noqa: E402
from db.database import SessionLocal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True, help="the name an agent's `datasource` uses")
    ap.add_argument("--label", default="", help="what a human sees in the Settings table")
    ap.add_argument("--dbname", default="", help="defaults to --name")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="5432")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="", help="empty = trust auth (local PostgreSQL)")
    ap.add_argument("--kind", default="target", help="target | platform | dashboard")
    ap.add_argument("--remove", action="store_true", help="delete the entry instead of adding it")
    args = ap.parse_args()

    name = args.name.strip()
    if not name:
        return _fail("--name is required")

    db = SessionLocal()
    try:
        doc = store.get_document(db, "databases") or {}
        items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
        before = [i.get("name") for i in items]
        items = [i for i in items if str(i.get("name") or "").strip().lower() != name.lower()]

        if args.remove:
            if len(items) == len(before):
                print(f"nothing to remove: no database named {name!r}")
                return 0
            store.put_document(db, "databases", {"items": items})
            print(f"removed {name!r} — databases now: {[i.get('name') for i in items]}")
            return 0

        entry = {
            "name": name,
            "label": args.label or name,
            "kind": args.kind,
            "host": args.host,
            "port": int(args.port),
            "dbname": args.dbname or name,
            "user": args.user,
            "password": args.password,
            "enabled": True,
        }
        items.append(entry)
        _normalized, revision = store.put_document(db, "databases", {"items": items})
        print(f"registered {name!r} → {entry['dbname']}@{entry['host']}:{entry['port']} "
              f"(revision {revision})")
        print(f"databases now: {[i.get('name') for i in items]}")
    finally:
        db.close()

    # prove the sandbox will actually be able to connect: run the resolver the factory runs
    try:
        from services.deepagent_factory.assembly import _datasource_env
        env, dsn = _datasource_env(name)
        print(f"resolver: {dsn}  (password {'set' if env.get('PGPASSWORD') else 'empty'})")
    except Exception as exc:                                   # noqa: BLE001 — reported, not raised
        print(f"resolver FAILED for {name!r}: {type(exc).__name__}: {exc}")
        return 1
    return 0


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
