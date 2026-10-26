#!/usr/bin/env python
"""Reclassify skills: generic → `builtin` (shared), business-specific → `personal`.

With progressive disclosure every skill's name + description sits in every agent's prompt,
so the catalogue has to be short and unambiguous. This install had 44 skills of which 25
were "personal" — in fact most were generic capabilities, and seven were empty shells
("Api Rate Limiter skill - auto-generated", 348 bytes) that only added noise.

Two kinds of change, kept distinct because only one of them destroys anything:

* **promote** — move `skills/personal/<owner>/<id>/` to `skills/builtin/<id>/`, set
  `source_type='builtin'`, `owner_id=NULL`. The skill becomes system-wide.
* **drop** — a shell with no content, or the redundant half of a duplicate pair. The row
  and the folder go; a JSON backup makes it reversible.

Kept personal on purpose (they are this company's, not generic capabilities):
`sunhing-analyst` (Sun Hing Vision Group), `a-share-research`, `global-equity-research`,
`erp-analyst`, `ai-agent-trends-research`.

Dry run by default. `--apply` acts. `--rollback <file>` restores the dropped rows and moves
the promoted folders back.

Usage::

    cd backend
    .venv/bin/python scripts/reclassify_skills.py              # show the plan
    .venv/bin/python scripts/reclassify_skills.py --apply
    .venv/bin/python scripts/reclassify_skills.py --rollback /tmp/skill-reclassify.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from services import user_roots  # noqa: E402

#: Skills that belong to this company's work and must stay per-account.
KEEP_PERSONAL = {
    "sunhing-analyst",          # Sun Hing Vision Group ROE / transformation KPIs
    "a-share-research",         # A-share market research
    "global-equity-research",   # cross-market equity research
    "erp-analyst",              # ERP financial analysis
    "ai-agent-trends-research", # a specific research assignment
}

#: Empty shells and redundant duplicates. Evidence in the report, not a guess:
#: the three "auto-generated" ones are 305-348 bytes with a placeholder description, and
#: each has a fuller counterpart or a builtin that already covers it.
DROP = {
    "pdf-chat":             "305 B 'auto-generated skill'; pdf-chat-assistant is the real one",
    "api-rate-limiter":     "348 B 'Api Rate Limiter skill - auto-generated'",
    "unit-test-writer":     "348 B 'Unit Test Writer skill - auto-generated'; python-testing is builtin",
    "ai-agent-trends-researcher": "5282 B duplicate of ai-agent-trends-research (near-identical description)",
}


def plan(db):
    from sqlalchemy import text

    owner = None
    from services.user_service import owner_user

    found = owner_user(db)
    owner = found.id if found else None
    personal = user_roots.personal_skills_dir_for(owner)
    builtin = BACKEND_DIR / "skills" / "builtin"

    rows = {
        r[0]: (r[1], r[2]) for r in db.execute(text(
            "SELECT skill_id, source_type, owner_id FROM skills"
        )).all()
    }
    promote, drop, keep = [], [], []
    for skill_id, (source_type, owner_id) in rows.items():
        if source_type == "builtin":
            continue
        if skill_id in DROP:
            drop.append(skill_id)
        elif skill_id in KEEP_PERSONAL:
            keep.append(skill_id)
        else:
            promote.append((skill_id, personal / skill_id, builtin / skill_id))
    return {"owner": owner, "promote": promote, "drop": drop, "keep": keep,
            "personal": personal, "builtin": builtin}


def report(data):
    print()
    print("  skill reclassification")
    print("  " + "─" * 72)
    print(f"  promote to builtin : {len(data['promote'])}")
    for skill_id, src, dst in data["promote"]:
        state = "ok" if src.is_dir() else "MISSING DIR"
        print(f"    {skill_id:<32} {state}")
    print(f"  drop               : {len(data['drop'])}")
    for skill_id in data["drop"]:
        print(f"    {skill_id:<32} {DROP[skill_id]}")
    print(f"  keep personal      : {len(data['keep'])}")
    for skill_id in data["keep"]:
        print(f"    {skill_id}")
    print()


def apply(data, backup_path):
    from sqlalchemy import text

    db = SessionLocal()
    try:
        backup = {"dropped": [], "promoted": []}
        for skill_id in data["drop"]:
            row = db.execute(text(
                "SELECT to_jsonb(t) FROM skills t WHERE skill_id = :s AND source_type = 'personal'"
            ), {"s": skill_id}).scalar()
            if row:
                backup["dropped"].append(row)
        Path(backup_path).write_text(json.dumps(backup, indent=1), encoding="utf-8")

        promoted = 0
        for skill_id, src, dst in data["promote"]:
            if dst.exists():
                print(f"  skip {skill_id} (builtin folder already exists)")
                continue
            if src.is_dir():
                shutil.move(str(src), str(dst))
                promoted += 1
            db.execute(text(
                "UPDATE skills SET source_type='builtin', owner_id=NULL, "
                "source_path=:p WHERE skill_id=:s AND source_type='personal'"
            ), {"p": f"skills/builtin/{skill_id}", "s": skill_id})
        db.commit()

        dropped = 0
        for skill_id in data["drop"]:
            db.execute(text("DELETE FROM skills WHERE skill_id=:s AND source_type='personal'"),
                       {"s": skill_id})
            folder = data["personal"] / skill_id
            if folder.is_dir():
                shutil.rmtree(folder)
            dropped += 1
        db.commit()

        print(f"  promoted {promoted} folder(s) → builtin, dropped {dropped} skill(s)")
        print(f"  backup: {backup_path}")
        return 0
    finally:
        db.close()


def rollback(path):
    from sqlalchemy import text

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        restored = 0
        for row in payload.get("dropped", []):
            keys = ", ".join(row.keys())
            values = ", ".join(f":{k}" for k in row.keys())
            db.execute(text(
                f"INSERT INTO skills ({keys}) VALUES ({values}) ON CONFLICT (id) DO NOTHING"
            ), row)
            restored += 1
        db.commit()
        print(f"  restored {restored} row(s); folders are not re-created — take them from git")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote generic skills to builtin, drop shells.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="/tmp/skill-reclassify.json")
    parser.add_argument("--rollback", default=None, metavar="FILE")
    args = parser.parse_args()

    if args.rollback:
        return rollback(args.rollback)

    db = SessionLocal()
    try:
        data = plan(db)
    finally:
        db.close()
    report(data)
    if not args.apply:
        print("  DRY RUN — nothing changed. Re-run with --apply.")
        return 0
    return apply(data, args.backup)


if __name__ == "__main__":
    raise SystemExit(main())
