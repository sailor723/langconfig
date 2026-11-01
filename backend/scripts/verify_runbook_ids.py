#!/usr/bin/env python
"""Check that every agent named in the run book still exists, under that name, in this database.

The run book quotes agents as ``（`case-5-support`，id 325）``. Those ids are facts about
*this* database, and they rot: a reseed re-numbers them, housekeeping deletes them, and
the doc keeps reading fine while pointing at nothing. This script reads the pairs out of
the markdown and compares them with the live table — nothing is written, exit code is 1
on any mismatch, so it works in a pre-training checklist.

Three kinds of mismatch, and what each one means:

| Mismatch | Meaning | Fix |
|---|---|---|
| missing id | the agent was deleted or the DB was reseeded | fix the doc, or re-import the agent |
| name differs | the id now belongs to another agent | fix the id in the doc |
| not public | exists, but trainees cannot see it in the picker | `is_public=true`, or keep it out of the run book |

Usage::

    cd backend
    .venv/bin/python scripts/verify_runbook_ids.py              # local database
    .venv/bin/python scripts/verify_runbook_ids.py --ecs        # on the ECS, before class
    .venv/bin/python scripts/verify_runbook_ids.py --pairs      # just print what it parsed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_DOC = REPO_DIR / "docs/tutorial/agent-training-runbook.md"

# `case-5-support`，id 325   /   `acc-hitl`, id 321
PAIR_RE = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]*)`\s*[，,]\s*id\s+(\d+)")


def parse_pairs(doc: Path) -> list[tuple[str, int, int]]:
    """(slug, id, 1-based line number), de-duplicated, in document order."""
    seen: dict[tuple[str, int], int] = {}
    for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        for slug, id_text in PAIR_RE.findall(line):
            seen.setdefault((slug, int(id_text)), lineno)
    return [(slug, id_, line) for (slug, id_), line in seen.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    ap.add_argument("--pairs", action="store_true", help="print parsed pairs and stop")
    ap.add_argument("--ecs", action="store_true", help="label the run as the training server")
    args = ap.parse_args()

    if not args.doc.exists():
        print(f"❌ run book not found: {args.doc}")
        return 1

    pairs = parse_pairs(args.doc)
    if not pairs:
        print(f"❌ no `slug`，id N pairs found in {args.doc.name}")
        return 1
    if args.pairs:
        for slug, id_, line in pairs:
            print(f"{id_:>4}  {slug:<32} line {line}")
        print(f"\n{len(pairs)} pairs")
        return 0

    from db.database import SessionLocal
    from sqlalchemy import text

    ids = [id_ for _, id_, _ in pairs]
    db = SessionLocal()
    try:
        rows = db.execute(
            text("select id, name, is_public from deep_agent_templates where id = any(:ids)"),
            {"ids": ids},
        ).fetchall()
    finally:
        db.close()
    live = {r[0]: (r[1], r[2]) for r in rows}

    where = "training server (ECS)" if args.ecs else "local database"
    print(f"run book: {args.doc.name}  ·  {where}  ·  {len(pairs)} pairs\n")
    bad = 0
    for slug, id_, line in pairs:
        if id_ not in live:
            print(f"  ❌ line {line:<5} id {id_:<4} {slug:<32} missing")
            bad += 1
            continue
        name, is_public = live[id_]
        if name != slug:
            print(f"  ❌ line {line:<5} id {id_:<4} {slug:<32} that id is now {name!r}")
            bad += 1
        elif not is_public:
            print(f"  ⚠️  line {line:<5} id {id_:<4} {slug:<32} exists but is not public")
            bad += 1
        else:
            print(f"  ✅ line {line:<5} id {id_:<4} {slug}")

    print(f"\n{len(pairs) - bad}/{len(pairs)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
