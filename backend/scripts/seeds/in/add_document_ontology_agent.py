#!/usr/bin/env python3
"""Register a **Document Ontology Builder**: one command, six artefacts, and the database it will build.

The database-version registration (`add_ontology_builder.py`) assumes a dataset already exists; this one
assumes the opposite — the agent creates it from uploaded files. So it creates the target database EMPTY
first (so the sandbox's `PG*` variables and the profile's dsn point at something real), and then runs the
same six steps through the shared registration:

    1. the agent row          prompt, tools (incl. db_plan_from_file / db_build_from_file), skill params
    2. gates.json             a declaration with `pending_install`, so the repo suite reports NOT RUN
    3. Settings → Ontology    the namespace document (`items[]`)
    4. .env                   the password variable the profile's dsn references
    5. the tool rows          ontology_open / inspect / publish / ask — without them the agent cannot publish
    6. the profile directory  must not exist yet: the builder creates it

    cd backend && .venv/bin/python scripts/seeds/in/add_document_ontology_agent.py \\
        --key sales_docs --theme "销售文档本体"            # dry run: prints what it would write
    cd backend && .venv/bin/python scripts/seeds/in/add_document_ontology_agent.py \\
        --key sales_docs --theme "销售文档本体" --apply

Exit codes: 0 ok, 1 a step failed, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import re
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]   # scripts/seeds/in → backend
DOC_SEED = BACKEND / "scripts" / "seeds" / "in" / "seed_document_ontology_agent.py"


def _run_seed(key: str, database: str, theme: str) -> tuple[bool, str]:
    env = {**os.environ, "ONTOLOGY_KEY": key, "DOC_DATABASE": database, "DOC_THEME": theme}
    run = subprocess.run([sys.executable, str(DOC_SEED)], capture_output=True, text=True,
                         cwd=str(BACKEND), env=env)
    tail = [line for line in (run.stdout or "").splitlines() if line.strip()][-4:]
    return run.returncode == 0, " / ".join(tail) or (run.stderr or "")[-300:]


def _ensure_database(database: str, *, apply: bool) -> tuple[bool, str]:
    """An EMPTY database, so PG* and the dsn point at something real before any file is built."""
    from services import agent_database  # noqa: F401  (import check only)

    host = os.environ.get("PGHOST") or "127.0.0.1"
    port = os.environ.get("PGPORT") or "5432"
    user = os.environ.get("PGUSER") or "langconfig"
    run = subprocess.run(["psql", "-h", host, "-p", port, "-U", user, "-d", "postgres", "-Atc",
                          f"SELECT 1 FROM pg_database WHERE datname = '{database}'"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        return False, f"cannot reach the server: {(run.stderr or '').strip()[:160]}"
    if run.stdout.strip():
        return True, f"database {database} exists (left as it is)"
    if not apply:
        return True, f"would create an empty database {database}"
    made = subprocess.run(["createdb", "-h", host, "-p", port, "-U", user, database],
                          capture_output=True, text=True)
    if made.returncode != 0:
        return False, f"createdb failed: {(made.stderr or '').strip()[:160]}"
    return True, f"created an empty database {database}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="ontology key, e.g. sales_docs")
    ap.add_argument("--database", default="", help="target database (default doc_<key>)")
    ap.add_argument("--theme", default="", help="human label for Settings → Ontology")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--family", action="append", default=[], choices=["abox"],
                    help="extra gate families (abox adds check_abox + check_abox_sync)")
    args = ap.parse_args()

    key = args.key.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        print(f"[FATAL] key {key!r} must be lowercase letters/digits/underscore", file=sys.stderr)
        return 2
    database = (args.database or f"doc_{key}").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        print(f"[FATAL] database {database!r} is not a database name", file=sys.stderr)
        return 2
    theme = args.theme or key

    print(f"document ontology builder: key={key} database={database} theme={theme} "
          f"mode={'APPLY' if args.apply else 'DRY RUN'}")

    problems = 0
    ok, note = _ensure_database(database, apply=args.apply)
    print(f"\n[0] the target database\n  {'OK  ' if ok else 'FAIL'} {note}")
    if not ok:
        return 1

    ok, note = _run_seed(key, database, theme)
    print(f"\n[1] the agent row\n  {'OK  ' if ok else 'FAIL'} {note}")
    if not ok:
        problems += 1

    # the remaining artefacts are the shared registration's job — reusing it keeps ONE definition of
    # "a builder is registered" (the lesson from the missing tool rows on talent_v1)
    add = BACKEND / "scripts" / "seeds" / "in" / "add_ontology_builder.py"
    argv = [sys.executable, str(add), "--key", key, "--datasource", database, "--theme", theme]
    for family in args.family:
        argv += ["--family", family]
    if args.apply:
        argv.append("--apply")
    run = subprocess.run(argv, capture_output=True, text=True, cwd=str(BACKEND))
    tail = [line for line in (run.stdout or "").splitlines() if line.strip()][-3:]
    print("\n[2..6] gates / Settings / .env / tool rows / profile dir")
    print("  " + ("OK  " if run.returncode == 0 else "FAIL ") + " / ".join(tail))
    if run.returncode != 0:
        problems += 1

    print(f"\n{'ready' if not problems else f'{problems} problem(s)'}"
          + ("" if args.apply else " — re-run with --apply to write"))
    print(f"next: open the agent, drop MD/Excel/CSV into upload/, ask it to build `{key}`. "
          f"It proposes the mapping first (db_plan_from_file), builds `{database}` only after you agree, "
          "then walks the ladder and stops at staged.")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
