#!/usr/bin/env python3
"""Every account may publish ontology declarations — declared as a seed, not a click.

The decision ("all users can see, operate and edit the ontology") is a ROLE in this platform:
`api/ontology/routes.py::_require_editor` accepts `admin` or `ontology_editor` for stage and apply.
This script grants `ontology_editor` to every non-admin account, and is safe to re-run.

What it does NOT do: it does not weaken the gates. A publish still stages a copy, re-runs the whole
suite, and refuses on a new refusal or a failing gate; apply still re-runs them on the installed
path. "Everyone may edit" never means "everything installs".

    cd backend
    .venv/bin/python scripts/seeds/in/ensure_ontology_editors.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db.database import SessionLocal
    from models.user import User, UserRole
    from services.user_service import ensure_userrole_enum

    added = ensure_userrole_enum()
    if added:
        print(f"userrole enum: added {', '.join(added)}")

    db = SessionLocal()
    try:
        members = db.query(User).filter(User.role == UserRole.MEMBER).all()
        if not members:
            print("every account already publishes (no `member` rows left)")
            return 0
        print(f"{len(members)} account(s) to grant ontology_editor: "
              + ", ".join(u.username for u in members))
        if args.dry_run:
            return 0
        for u in members:
            u.role = UserRole.ONTOLOGY_EDITOR
        db.commit()
        print("granted. Stage/apply now accept these accounts; the gates are unchanged.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
