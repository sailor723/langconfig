#!/usr/bin/env python
"""Move personal skills into per-account folders.

`backend/skills/personal/<skill>/` becomes `backend/skills/personal/<user id>/<skill>/`,
the layout the loader now reads and the only one that keeps one account's skills out of
another's catalogue.

Two sources exist today and they disagree, so this is a *choice*, not a tidy-up:

* `backend/skills/personal/<skill>/` — the current store, newer (Sep 2026 for every
  duplicate sampled);
* `backend/skills/<skill>/` — the flat root the loader used to read, older (Jul/Aug), and
  the one whose content actually reached the database before this change.

Rules, in order:

1. every `personal/<skill>/` moves to `personal/<owner>/<skill>/`;
2. a root-level skill that has **no** copy under `personal/` moves in too (6 of them:
   erp-analyst, market-wizard, report-generator, sql-analyst, sunhing-analyst,
   web-content-analyzer);
3. a root-level skill that **does** have a `personal/` copy is **left where it is** and
   reported — the two files differ, and silently deleting the older one would throw away
   whatever only it contains. Whoever reviews the report decides; the loader no longer
   reads that location either way.
4. `builtin/` is never touched.

Dry run by default; `--apply` moves; `--rollback` puts everything back.

Usage::

    cd backend
    .venv/bin/python scripts/adopt_personal_skills.py                 # dry run
    .venv/bin/python scripts/adopt_personal_skills.py --apply
    .venv/bin/python scripts/adopt_personal_skills.py --rollback
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from services import user_roots  # noqa: E402

SKILLS_ROOT = BACKEND_DIR / "skills"


def _owner_id(db) -> int:
    from services.user_service import owner_user

    owner = owner_user(db)
    if owner is None:
        raise SystemExit("no active admin — run scripts/create_user.py first")
    return owner.id


def plan(owner_id: int) -> dict:
    personal = user_roots.personal_skills_dir()
    target = user_roots.personal_skills_dir_for(owner_id)

    current = [p for p in personal.iterdir() if p.is_dir()] if personal.is_dir() else []
    # Folders that are already per-account (`1`, `1071`, …) are not skills.
    current = [p for p in current if not p.name.isdigit()]

    legs = [("personal", p) for p in sorted(current)]

    personal_names = {p.name for p in current}
    for path in sorted(SKILLS_ROOT.iterdir()):
        if not path.is_dir() or path.name in ("builtin", "personal"):
            continue
        if not (path / "SKILL.md").exists():
            continue
        if path.name in personal_names:
            legs.append(("duplicate", path))
        else:
            legs.append(("root-only", path))
    return {"target": target, "legs": legs}


def report(plan_data: dict) -> None:
    print()
    print("  personal skills → per-account folders")
    print("  " + "─" * 70)
    print(f"  target: {plan_data['target']}")
    print()
    for kind, path in plan_data["legs"]:
        note = {
            "personal": "move",
            "root-only": "move  (only copy)",
            "duplicate": "KEEP  (older duplicate; personal/ copy wins)",
        }[kind]
        print(f"    {note:<46} {path.name}")
    print()


def apply(plan_data: dict) -> int:
    target = plan_data["target"]
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for kind, path in plan_data["legs"]:
        if kind == "duplicate":
            continue
        destination = target / path.name
        if destination.exists():
            print(f"  skip {path.name} (already at the destination)")
            continue
        shutil.move(str(path), str(destination))
        print(f"  moved {path.name}")
        moved += 1
    print(f"\n  {moved} skill folder(s) moved into {target}")
    return 0


def rollback(owner_id: int) -> int:
    target = user_roots.personal_skills_dir_for(owner_id)
    personal = user_roots.personal_skills_dir()
    if not target.is_dir():
        raise SystemExit(f"{target} does not exist — nothing to roll back")
    moved = 0
    for path in sorted(target.iterdir()):
        destination = personal / path.name
        if destination.exists():
            print(f"  skip {path.name} (already back)")
            continue
        shutil.move(str(path), str(destination))
        moved += 1
    print(f"  {moved} folder(s) restored; the {target} folder is left in place")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Move personal skills into per-account folders.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--owner", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        owner_id = args.owner or _owner_id(db)
        if args.rollback:
            return rollback(owner_id)

        data = plan(owner_id)
        report(data)
        if not args.apply:
            print("  DRY RUN — nothing moved. Re-run with --apply.")
            return 0
        status = apply(data)
        print("\n  next: restart the backend so the registry re-scans, then")
        print("        .venv/bin/python scripts/seeds/out/export_baseline.py --check")
        return status
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
