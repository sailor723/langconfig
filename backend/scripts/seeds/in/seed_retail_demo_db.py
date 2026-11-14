#!/usr/bin/env python3
"""Create `retail_db` and load the demo dataset the retail tutorial reads.

The retail tutorial's eight chapters are not pictures: each one runs a real query against `retail_db`
(`GET /api/ontology/retail/wb/tutorial1/table` → `SELECT id, name, tier FROM customers`). On a deployment
where that database was never created, every chapter rendered its text and none of its data — measured
2026-11-14: `/wb/tutorial1/table` answered **500 database "retail_db" does not exist** while the page
itself was 200 and looked fine.

So the fixture travels with the repository:

    backend/fixtures/retail_db.sql     4 customers · 4 orders · 6 order lines · 3 products · 2 stores

Idempotent: the database is created only when missing, and the fixture is loaded only when `customers` is
empty — re-running never duplicates rows and never overwrites a database someone has been using.

Usage:
    cd backend && .venv/bin/python scripts/seeds/in/seed_retail_demo_db.py [--db retail_db] [--force]

Connection: PGHOST/PGPORT/PGUSER/PGPASSWORD from the environment (the deployment's own settings), then the
repo `.env`, so this works inside an agent sandbox as well as on the host.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]  # scripts/seeds/in → backend
REPO = BACKEND.parent
FIXTURE = BACKEND / "fixtures" / "retail_db.sql"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = REPO / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
    out = {
        "PGHOST": os.environ.get("PGHOST") or values.get("POSTGRES_HOST") or "127.0.0.1",
        "PGPORT": os.environ.get("PGPORT") or values.get("POSTGRES_PORT") or "5432",
        "PGUSER": os.environ.get("PGUSER") or values.get("POSTGRES_USER") or "langconfig",
        "PGPASSWORD": os.environ.get("PGPASSWORD") or values.get("POSTGRES_PASSWORD") or "",
    }
    return out


def _psql(env: dict[str, str], db: str, sql: str) -> tuple[int, str]:
    run = subprocess.run(["psql", "-h", env["PGHOST"], "-p", env["PGPORT"], "-U", env["PGUSER"],
                          "-d", db, "-Atc", sql], capture_output=True, text=True, env={**os.environ, **env})
    return run.returncode, (run.stdout or run.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="retail_db")
    ap.add_argument("--force", action="store_true", help="load the fixture even if customers has rows")
    args = ap.parse_args()

    if not FIXTURE.is_file():
        print(f"FAIL no fixture at {FIXTURE}")
        return 2
    env = _env()
    print(f"server: {env['PGUSER']}@{env['PGHOST']}:{env['PGPORT']}")

    code, out = _psql(env, "postgres", f"SELECT 1 FROM pg_database WHERE datname = '{args.db}'")
    if code != 0:
        print(f"FAIL cannot reach the server: {out}")
        return 2
    if not out.strip():
        run = subprocess.run(["createdb", "-h", env["PGHOST"], "-p", env["PGPORT"],
                              "-U", env["PGUSER"], args.db],
                             capture_output=True, text=True, env={**os.environ, **env})
        if run.returncode != 0:
            print(f"FAIL createdb: {run.stderr.strip()}")
            return 2
        print(f"created {args.db}")
    else:
        print(f"{args.db} exists")

    code, out = _psql(env, args.db, "SELECT count(*) FROM customers")
    if code == 0 and out.strip() not in ("", "0") and not args.force:
        print(f"{args.db}.customers already holds {out.strip()} row(s) — nothing to do")
        return 0

    run = subprocess.run(["psql", "-h", env["PGHOST"], "-p", env["PGPORT"], "-U", env["PGUSER"],
                          "-d", args.db, "-q", "-f", str(FIXTURE)],
                         capture_output=True, text=True, env={**os.environ, **env})
    if run.returncode != 0:
        print(f"FAIL loading {FIXTURE.name}: {(run.stderr or '')[-400:]}")
        return 2
    counts = {}
    for table in ("customers", "orders", "order_lines", "products", "stores"):
        code, out = _psql(env, args.db, f"SELECT count(*) FROM {table}")
        counts[table] = out if code == 0 else "?"
    print("loaded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("next: the retail tutorial's chapters read this database — open "
          "/api/ontology/retail/tutorial/chapter/1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
