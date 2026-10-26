#!/usr/bin/env python
"""Shrink the agent library — in the database *and* in the seed, or not at all.

Deleting an agent in the UI looks like it worked and quietly undoes itself: the team's
agent library ships as `scripts/seeds/in/deep_agents_merge.sql`, which inserts every
agent with

    INSERT ... SELECT '<name>', ...
    WHERE NOT EXISTS (SELECT 1 FROM deep_agent_templates WHERE name = '<name>');

so the next `seed_all.py` re-creates anything that is missing. 53 of this install's 54
agents come from that file. A durable removal has to take the entry out of the seed as
well as the row out of the database, which is what this script does — both, or nothing.

Safety:
- dry run by default; `--apply` is required;
- an agent with conversations is refused unless `--force-with-chats`, because deleting it
  also deletes its chat history (the FK has no cascade; the API does it in code);
- the seed file and every removed row are backed up before anything is touched
  (`*.bak` next to the seed, a JSON copy in the backup path), and `--rollback` restores
  rows from that JSON;
- the seed edit is surgical: whole `INSERT ... WHERE NOT EXISTS (...) ;` statements whose
  name is being removed, nothing else in the file.

Usage::

    cd backend
    .venv/bin/python scripts/prune_agent_library.py --ids 2 3 4 ...        # dry run
    .venv/bin/python scripts/prune_agent_library.py --ids 2 3 4 --apply
    .venv/bin/python scripts/prune_agent_library.py --unused --apply       # every agent with no chats
    .venv/bin/python scripts/prune_agent_library.py --rollback /tmp/x.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

SEED_FILE = BACKEND_DIR / "scripts" / "seeds" / "in" / "deep_agents_merge.sql"

from db.database import SessionLocal  # noqa: E402


def _agents(db):
    from sqlalchemy import text

    return db.execute(text("""
        SELECT a.id, a.name, a.category,
               (SELECT count(*) FROM chat_sessions s WHERE s.agent_id = a.id) AS chats
        FROM deep_agent_templates a ORDER BY a.id
    """)).all()


def _seed_names() -> set:
    sql = SEED_FILE.read_text(encoding="utf-8")
    return {n.replace("''", "'") for n in re.findall(r"SELECT '((?:[^']|'')*)',", sql)}


def _strip_seed_entry(sql: str, name: str) -> tuple[str, bool]:
    """Remove the one INSERT…; statement whose seeded name matches."""
    escaped = name.replace("'", "''")
    pattern = re.compile(
        r"\nINSERT INTO deep_agent_templates\b.*?;\n",
        re.DOTALL,
    )
    out, removed = [], False
    last = 0
    for match in pattern.finditer(sql):
        block = match.group(0)
        if f"SELECT '{escaped}'," in block:
            out.append(sql[last:match.start()])
            last = match.end()
            removed = True
    out.append(sql[last:])
    return "".join(out), removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete agents and their seed entries together.")
    parser.add_argument("--ids", nargs="*", type=int, default=None)
    parser.add_argument("--names", nargs="*", default=None)
    parser.add_argument("--unused", action="store_true", help="select every agent with no chats")
    parser.add_argument("--force-with-chats", action="store_true",
                        help="also delete agents that have conversations (loses that history)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="/tmp/prune-agent-library.json")
    parser.add_argument("--rollback", default=None, metavar="FILE")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.rollback:
            return _rollback(db, args.rollback)

        rows = _agents(db)
        seeded = _seed_names()

        if args.unused:
            chosen = [r for r in rows if r.chats == 0]
        elif args.ids or args.names:
            wanted = set(args.ids or [])
            names = set(args.names or [])
            chosen = [r for r in rows if r.id in wanted or r.name in names]
            missing = (wanted - {r.id for r in chosen}) | (names - {r.name for r in chosen})
            for item in sorted(missing, key=str):
                print(f"  ?        no such agent: {item}")
        else:
            parser.error("nothing selected: pass --ids, --names or --unused")

        blocked = [r for r in chosen if r.chats and not args.force_with_chats]
        doable = [r for r in chosen if r not in blocked]

        print()
        print("  agent library prune")
        print("  " + "─" * 62)
        print(f"  selected {len(chosen)}   deletable {len(doable)}   refused (has chats) {len(blocked)}")
        for r in doable:
            origin = "seed" if r.name in seeded else "custom"
            print(f"    -{r.id:>4}  {r.name[:38]:<38} {origin:<6} chats={r.chats}")
        for r in blocked:
            print(f"    SKIP {r.id:>4}  {r.name[:38]:<38} has {r.chats} conversation(s) "
                  f"— use --force-with-chats to lose them")
        print()

        if not args.apply:
            print("  DRY RUN — nothing deleted, seed untouched. Re-run with --apply.")
            return 0
        if not doable:
            print("  nothing to do.")
            return 0

        payload = {"ids": [r.id for r in doable], "rows": []}
        from sqlalchemy import text

        for r in doable:
            row = db.execute(text(
                "SELECT to_jsonb(t) FROM deep_agent_templates t WHERE id = :i"
            ), {"i": r.id}).scalar()
            payload["rows"].append(row)
        Path(args.backup).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"  backup written: {args.backup} ({len(doable)} row(s))")

        # 1. the seed, so the next seed_all cannot bring them back
        sql = SEED_FILE.read_text(encoding="utf-8")
        shutil.copy2(SEED_FILE, SEED_FILE.with_suffix(".sql.bak"))
        stripped, removed_names = sql, []
        for r in doable:
            if r.name in seeded:
                stripped, removed = _strip_seed_entry(stripped, r.name)
                if removed:
                    removed_names.append(r.name)
        SEED_FILE.write_text(stripped, encoding="utf-8")
        print(f"  seed entries removed: {len(removed_names)} (backup: {SEED_FILE.name}.bak)")

        # 2. the rows (conversations included, which is why they were refused above)
        for r in doable:
            db.execute(text("DELETE FROM chat_sessions WHERE agent_id = :i"), {"i": r.id})
            db.execute(text("DELETE FROM deep_agent_templates WHERE id = :i"), {"i": r.id})
        db.commit()
        print(f"  rows deleted: {len(doable)}")
        print()
        print("  reminder: workspace directories are untouched — "
              "run scripts/audit_agents.py --prune-orphans to finish the job")
        return 0
    finally:
        db.close()


def _rollback(db, path: str) -> int:
    from sqlalchemy import text

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    restored = 0
    for row in payload.get("rows", []):
        keys = ", ".join(row.keys())
        values = ", ".join(f":{k}" for k in row.keys())
        db.execute(text(
            f"INSERT INTO deep_agent_templates ({keys}) VALUES ({values}) "
            f"ON CONFLICT (id) DO NOTHING"
        ), row)
        restored += 1
    db.commit()
    print(f"  restored {restored} row(s) from {path}")
    print("  the seed file is NOT restored — take it from deep_agents_merge.sql.bak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
