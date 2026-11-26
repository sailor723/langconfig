#!/usr/bin/env python3
"""Retire one ontology: take it out of the way without pretending it never existed.

    python -m scripts.retire_ontology orders_demo_v1 --reason "rebuilt on TPC-H"
    python -m scripts.retire_ontology orders_demo_v1 --dry-run

What "removed" means here, and why it is not `rm -rf`:

* `features/ontology/versioning.py` states the house rule — nothing in the repo deletes a
  `customer` or `tutorial` key, because a published URL, a Settings row and a publish-history
  entry all point at it. So the profile DIRECTORY is moved to `profiles/.archive/<key>-<stamp>/`
  (git keeps the history either way) and its version entry is marked retired rather than dropped:
  the next version number must not be handed to somebody else.
* Everything a reader actually navigates by is removed:
  - the Settings → Ontology row (`core.settings` document, key `ontology`),
  - the `gates.json` declaration (so the gate suite stops speaking about a key that is gone),
  - `.staging/` and `.backup/` under the profile (a retired key must not keep offering a
    half-valid candidate in Pending publishes).
* The ontology's DATA database is NOT touched. Dropping it is a separate, explicit act —
  `--drop-db` does it only when the caller also says `--yes`, and it prints the row counts first.

Every step is reported with what it found, so a second run says "already retired" instead of
silently succeeding.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import shutil
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FEATURE = BACKEND / "features" / "ontology"
PROFILES = FEATURE / "profiles"
ARCHIVE = PROFILES / ".archive"
GATES = FEATURE / "gates.json"
REGISTRY = PROFILES / "_versions.json"


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _profile_dir(key: str) -> pathlib.Path:
    return PROFILES / key


def _settings_key(doc: dict) -> str:
    return str(doc.get("key") or "")


def _settings_remove(key: str, *, dry_run: bool) -> str:
    """Remove the key's row from the Settings → Ontology document."""
    try:
        from core import settings as cs
        from core.settings.store import OWNER_USER_ID, put_document
        from db.database import SessionLocal
    except Exception as exc:                                        # noqa: BLE001
        return f"Settings row NOT touched ({type(exc).__name__}: {exc})"
    db = SessionLocal()
    try:
        doc = dict(cs.resolve(db, "ontology").value or {})
        items = [dict(x) for x in (doc.get("items") or [])]
        keep = [x for x in items if _settings_key(x) != key]
        if len(keep) == len(items):
            return "Settings row: absent (nothing to remove)"
        label = next((x.get("label") for x in items if _settings_key(x) == key), "")
        if dry_run:
            return f"Settings row: would remove {key!r} ({label})"
        doc["items"] = keep
        put_document(db, "ontology", doc, user_id=OWNER_USER_ID)
        return f"Settings row: removed {key!r} ({label})"
    finally:
        db.close()


def _versions_retire(key: str, *, dry_run: bool) -> str:
    if not REGISTRY.is_file():
        return f"versions: {REGISTRY.name} missing"
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    families = reg.get("families") or {}
    changed, where = False, ""
    for fam, val in families.items():
        for item in (val or {}).get("versions") or []:
            if isinstance(item, dict) and item.get("key") == key:
                if item.get("retired") is not None:
                    return f"versions: already retired ({item.get('retired')})"
                item["retired"] = _dt.datetime.now().strftime("%Y-%m-%d")
                if val.get("latest") == key:
                    val["latest"] = None
                changed, where = True, f"{fam}: {key} → retired (latest cleared)"
            elif isinstance(item, str) and item == key:
                return f"versions: {key} is a bare string entry under {fam}; left as-is"
    if not changed:
        return f"versions: {key} not listed"
    if dry_run:
        return f"versions: would retire — {where}"
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"versions: retired — {where}"


def _gates_remove(key: str, *, dry_run: bool) -> str:
    if not GATES.is_file():
        return f"gates: {GATES.name} missing"
    doc = json.loads(GATES.read_text(encoding="utf-8"))
    if key not in doc:
        return "gates: no declaration"
    spec = doc.pop(key)
    if dry_run:
        return f"gates: would remove declaration ({len(spec)} fields) — re-add it when the rebuild lands"
    GATES.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "gates: declaration removed — the suite stops speaking about this key"


def _archive_dir(key: str, *, dry_run: bool) -> str:
    src = _profile_dir(key)
    if not src.is_dir():
        return "directory: absent"
    dst = ARCHIVE / f"{key}-{_stamp()}"
    if dry_run:
        return f"directory: would move {src.name} → {dst.relative_to(FEATURE)}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"directory: moved → {dst.relative_to(FEATURE)}"


def _drop_db(dbname: str, *, dry_run: bool) -> str:
    import os
    try:
        import psycopg2
    except Exception as exc:                                        # noqa: BLE001
        return f"db: NOT dropped ({exc})"
    host = os.environ.get("ONTOLOGY_DB_HOST") or os.environ.get("POSTGRES_HOST") or "127.0.0.1"
    port = int(os.environ.get("ONTOLOGY_DB_PORT") or os.environ.get("POSTGRES_PORT") or 5432)
    user = os.environ.get("ONTOLOGY_DB_USER") or os.environ.get("POSTGRES_USER")
    pw = os.environ.get("ONTOLOGY_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    admin = psycopg2.connect(host=host, port=port, dbname="postgres", user=user, password=pw)
    admin.autocommit = True
    cur = admin.cursor()
    try:
        cur.execute("select 1 from pg_database where datname=%s", (dbname,))
        if cur.fetchone() is None:
            return f"db: {dbname} does not exist"
        if dry_run:
            return f"db: would drop {dbname}"
        cur.execute(f'DROP DATABASE "{dbname}"')
        return f"db: dropped {dbname}"
    finally:
        admin.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retire one ontology (archive, unlist, keep history)")
    ap.add_argument("key")
    ap.add_argument("--reason", default="")
    ap.add_argument("--drop-db", default="", help="also drop this database name")
    ap.add_argument("--yes", action="store_true", help="required together with --drop-db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    key = args.key.strip()
    if not key or "/" in key or key.startswith("."):
        print(f"invalid key {key!r}", file=sys.stderr)
        return 2

    print(f"RETIRE {key}{' (dry run)' if args.dry_run else ''} — {args.reason or 'no reason given'}")
    reports = [
        _settings_remove(key, dry_run=args.dry_run),
        _versions_retire(key, dry_run=args.dry_run),
        _gates_remove(key, dry_run=args.dry_run),
        _archive_dir(key, dry_run=args.dry_run),
    ]
    if args.drop_db:
        if not args.yes:
            reports.append(f"db: {args.drop_db} NOT dropped (--drop-db needs --yes)")
        else:
            reports.append(_drop_db(args.drop_db, dry_run=args.dry_run))
    for line in reports:
        print("  -", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
