#!/usr/bin/env python
"""Make every `skills.source_path` point at a directory that exists.

`source_path` is not decoration: `agent_bundle` collects a skill's files from it,
`skill_row_to_markdown` resolves the skill directory from it, and the registry writes it
when a skill is created. A stale value means an export silently ships no skill files.

Two kinds of staleness were found on this install, both from the layout change:

* **personal** rows still named `backend/skills/<skill>` — the pre-isolation flat root,
  whose folders this install deleted, so all five pointed at nothing;
* **builtin** rows were split between absolute and relative paths (`skills/builtin/x`
  resolves only when the process runs from `backend/`, which is an assumption, not a
  guarantee).

This rewrites them to the canonical absolute location for their kind:
`skills/builtin/<id>` and `skills/personal/<owner>/<id>`. Dry run by default; a row whose
target directory is missing is reported and left alone rather than "fixed" into another
broken path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402

SKILLS = BACKEND_DIR / "skills"


def _expected(source_type: str, skill_id: str, owner_id) -> Path | None:
    if source_type == "builtin":
        return (SKILLS / "builtin" / skill_id).resolve()
    if owner_id is None:
        return None
    return (SKILLS / "personal" / str(owner_id) / skill_id).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Repoint skills.source_path at real folders.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import text

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT skill_id, source_type, owner_id, source_path FROM skills "
            "ORDER BY source_type, skill_id"
        )).all()

        changes, broken = [], []
        for skill_id, source_type, owner_id, current in rows:
            expected = _expected(source_type, skill_id, owner_id)
            if expected is None:
                broken.append((skill_id, source_type, "no owner to resolve a folder from"))
                continue
            if not expected.is_dir():
                broken.append((skill_id, source_type, f"missing folder {expected}"))
                continue
            current_path = Path(current).resolve() if current else None
            if current_path != expected:
                changes.append((skill_id, source_type, current, str(expected)))

        print()
        print("  skill source_path normalisation")
        print("  " + "─" * 68)
        print(f"  rows: {len(rows)}   to rewrite: {len(changes)}   unresolvable: {len(broken)}")
        print()
        for skill_id, source_type, before, after in changes:
            print(f"    {skill_id:<32} {source_type:<8} {str(before)[-46:]}")
            print(f"    {'':<32} {'':<8} → {after[-46:]}")
        for skill_id, source_type, why in broken:
            print(f"    SKIP {skill_id:<28} {source_type:<8} {why}")

        if not args.apply:
            print("\n  DRY RUN — nothing written. Re-run with --apply.")
            return 0
        for skill_id, source_type, _before, after in changes:
            db.execute(text(
                "UPDATE skills SET source_path = :p WHERE skill_id = :s AND source_type = :t"
            ), {"p": after, "s": skill_id, "t": source_type})
        db.commit()
        print(f"\n  rewrote {len(changes)} row(s)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
