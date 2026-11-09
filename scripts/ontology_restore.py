#!/usr/bin/env python3
"""Rebuild an ontology profile from the publish ledger.

The ledger row for a staged publish carries the **full text of every file** that was staged
(`ontology_publishes.files`, jsonb). That is the only place a published ontology is guaranteed to exist
besides the checkout it was applied to — which is how `new_coldchain_v5` was recovered after a
`git reset --hard` deleted the nine files that had been staged-but-never-committed.

    ./scripts/ontology_restore.py --key new_coldchain_v5                  # report what the last
                                                                          # applied publish contains
    ./scripts/ontology_restore.py --key new_coldchain_v5 --apply          # write the files
    ./scripts/ontology_restore.py --publish-id 1794212541-6afcb2 --apply  # a specific publish
    ./scripts/ontology_restore.py --key new_coldchain_v5 --apply --verify # …and compile + gate it

It refuses to write into a profile directory that already has files unless `--force` is given, because
the usual reason to run this is that the directory is empty.

Tests: backend/tests/test_ontology_restore.py (planning and writing, on a temp tree; no database).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

FEATURE = pathlib.Path(__file__).resolve().parents[1] / "backend" / "features" / "ontology"
PROFILES = FEATURE / "profiles"


def plan(files: dict, dest: pathlib.Path) -> tuple[list[str], list[str]]:
    """Split the ledger's files into (to write, refused) — pure, so it is testable without a database.

    A path is refused when it tries to leave the profile directory (a publish is a set of files under
    `<key>/`, never `../`), and when it is obviously not an ontology file.
    """
    write, refused = [], []
    for rel in sorted(files or {}):
        body = files[rel]
        if not isinstance(body, str):
            refused.append(f"{rel}: not text")
            continue
        parts = pathlib.PurePosixPath(str(rel)).parts
        if not parts or ".." in parts or str(rel).startswith("/"):
            refused.append(f"{rel}: outside the profile directory")
            continue
        if parts[0] in (".staging", ".backup"):
            refused.append(f"{rel}: staging/backup material is not a profile")
            continue
        write.append(str(rel))
    return write, refused


def write_profile(files: dict, dest: pathlib.Path, force: bool = False) -> tuple[list[str], list[str]]:
    """Write the planned files. Returns (written, refused)."""
    write, refused = plan(files, dest)
    if dest.exists() and any(dest.iterdir()) and not force:
        return [], refused + [f"{dest}: already has files (pass --force to overwrite)"]
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for rel in write:
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[rel], encoding="utf-8")
        written.append(rel)
    return written, refused


def ledger_files(key: str | None, publish_id: str | None) -> tuple[dict, dict]:
    """Read a publish row from the app's database. Returns (files, row-summary)."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
    from db.database import SessionLocal          # noqa: PLC0415
    from sqlalchemy import text                   # noqa: PLC0415

    db = SessionLocal()
    try:
        if publish_id:
            row = db.execute(text(
                "select id, key, status, files, created_at from ontology_publishes where id = :i"),
                {"i": publish_id}).fetchone()
        else:
            row = db.execute(text(
                "select id, key, status, files, created_at from ontology_publishes "
                "where key = :k and status = 'applied' order by created_at desc limit 1"),
                {"k": key}).fetchone()
        if row is None:
            raise SystemExit("no such publish in the ledger"
                             + (f" (id {publish_id})" if publish_id else f" (key {key}, applied)"))
        return (row[3] or {}), {"id": row[0], "key": row[1], "status": row[2],
                                "staged_at": str(row[4])}
    finally:
        db.close()


def verify(dest: pathlib.Path) -> int:
    """Compile and gate the restored profile the way `apply()` does."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
    from services import ontology_publish as op        # noqa: PLC0415

    profile = op._profile_for(dest.name)
    if profile is None:
        print("! no *_settings.json in the restored directory — it is not a loadable profile")
        return 1
    compile_report = op._compile_report(profile)
    gates = op._run_gates(profile)
    print(f"compiled {compile_report.get('compiled', 0)}/{compile_report.get('metrics', 0)} metrics, "
          f"{len(compile_report.get('refused') or [])} refused · gates "
          f"{'PASS' if gates.get('ok') else 'FAIL'}")
    for failure in (gates.get("fails") or [])[:10]:
        print("  -", str(failure)[:160])
    return 0 if gates.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rebuild an ontology profile from the publish ledger.")
    ap.add_argument("--key")
    ap.add_argument("--publish-id")
    ap.add_argument("--apply", action="store_true", help="write the files (default: report only)")
    ap.add_argument("--force", action="store_true", help="write even if the directory is not empty")
    ap.add_argument("--verify", action="store_true", help="compile and gate afterwards")
    ap.add_argument("--profiles", default=str(PROFILES))
    args = ap.parse_args(argv)
    if not args.key and not args.publish_id:
        ap.error("give --key or --publish-id")

    files, row = ledger_files(args.key, args.publish_id)
    key = row["key"]
    dest = pathlib.Path(args.profiles) / key
    write, refused = plan(files, dest)
    print(f"publish {row['id']} ({row['status']}, staged {row['staged_at']}) · key {key}")
    print(f"  {len(files)} file(s) in the ledger, {len(write)} restorable, {len(refused)} refused")
    for rel in write:
        print(f"    {len(files[rel]):8d} B  {rel}")
    for why in refused:
        print(f"    ! {why}")
    if not args.apply:
        print(f"\nreport only. Destination: {dest}")
        return 0

    written, problems = write_profile(files, dest, force=args.force)
    print(f"\nwrote {len(written)} file(s) into {dest}")
    for why in problems:
        print(f"  ! {why}")
    if args.verify and written:
        return verify(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
