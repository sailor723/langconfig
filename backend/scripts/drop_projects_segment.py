"""One-shot migration: drop the `projects/` segment from vault paths.

After the code change in commits `a723ad3` + `5e0cf9e`, every project-bound
agent and task lives under ``<base>/<slug>/...`` instead of the legacy
``<base>/projects/<slug>/...``. Any live files under ``<base>/projects/``
on a pre-migration install are now orphaned (the resolver no longer walks
that subtree). This script moves them to the new location, idempotently.

Idempotent
==========
* Skips a slug whose target already has content (unless ``--force``)
* Skips a slug whose source doesn't exist
* Prints a clear plan in ``--dry-run`` mode so the operator can preview
* Safe to run repeatedly; safe to run before/after the backend restarts

Usage
=====
    cd backend
    uv run python scripts/migrate_drop_projects_segment.py            # migrate
    uv run python scripts/migrate_drop_projects_segment.py --dry-run  # plan

The default base_dir is read from the ``workspace`` settings document
(``base_dir`` field, default ``backend/outputs`` — relative to the repo
root). Pass ``--base-dir`` to override (absolute path).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Allow `from core.settings...` when run as a script.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
_REPO = _BACKEND.parent


def _resolve_base_dir(override: str = "") -> Path:
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            p = _REPO / p
        return p.resolve()
    # Default: read from the workspace settings doc (with env fallback).
    try:
        from core.settings import runtime_get
        configured = runtime_get("workspace", "base_dir") or "backend/outputs"
    except Exception:
        configured = "backend/outputs"
    p = Path(configured).expanduser()
    if not p.is_absolute():
        p = _REPO / p
    return p.resolve()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan the moves; print what would change; no writes.")
    ap.add_argument("--force", action="store_true",
                    help="Move even when the target already exists (merges).")
    ap.add_argument("--base-dir", default="",
                    help="Override the base directory (absolute path or "
                         "relative to repo root). Defaults to the workspace "
                         "settings doc `base_dir` field.")
    args = ap.parse_args()

    base = _resolve_base_dir(args.base_dir)
    projects_dir = base / "projects"

    if not projects_dir.is_dir():
        print(f"Nothing to migrate: {projects_dir} does not exist.")
        return 0

    print(f"base_dir: {base}")
    print(f"source:   {projects_dir}/")
    print()

    moved = 0
    skipped_existing = 0
    skipped_empty = 0
    errors: list[str] = []

    for slug_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        slug = slug_dir.name
        target = base / slug
        # Skip if the target is the same as the source (shouldn't happen,
        # but defensive).
        if target.resolve() == slug_dir.resolve():
            print(f"  skip {slug!r} (target == source)")
            skipped_empty += 1
            continue
        if target.exists() and not args.force:
            print(f"  skip {slug!r} -> {target.relative_to(_REPO)} (target exists, "
                  f"pass --force to merge)")
            skipped_existing += 1
            continue
        try:
            if args.dry_run:
                print(f"  [dry-run] mv {slug_dir.relative_to(_REPO)}/  ->  "
                      f"{target.relative_to(_REPO)}/")
            else:
                shutil.move(str(slug_dir), str(target))
                print(f"  moved {slug!r}  ->  {target.relative_to(_REPO)}/")
                moved += 1
        except Exception as e:
            errors.append(f"{slug}: {e}")
            print(f"  ERROR moving {slug!r}: {e}")

    # If projects/ is now empty, remove it (cosmetic; also drops the legacy
    # namespace segment from the visible layout).
    if not args.dry_run and not any(p for p in projects_dir.iterdir()):
        try:
            projects_dir.rmdir()
            print(f"\nremoved empty source dir: {projects_dir}/")
        except Exception as e:
            print(f"\nwarning: could not remove empty source dir: {e}")

    print()
    if args.dry_run:
        print("DRY-RUN — no files moved.")
    else:
        print(f"moved: {moved}   skipped (existing): {skipped_existing}   "
              f"skipped (other): {skipped_empty}")
    if errors:
        print(f"errors: {len(errors)}")
        for e in errors:
            print(f"  ! {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
