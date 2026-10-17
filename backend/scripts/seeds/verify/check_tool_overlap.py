"""Report tools that look like the same tool under different tool_ids.

The additive seed unions on ``tool_id`` — the only stable identity a migration
can trust. It cannot see "this is really the same tool": a teammate's
``my_current_time`` and the catalog's ``current_time`` are distinct rows with
distinct ids, so both survive and the team ends up with two tools that do one
thing. Names are user-editable labels, so treating a name match as identity
would be worse — it would silently DROP a genuinely different tool that happens
to share a label.

So this does not merge anything. It looks for the two signals a human can judge
from, and prints them:

  1. **same name** (case/space-insensitive) under different tool_ids;
  2. **same implementation** — an identical ``implementation_config`` body, which
     means the same code shipped twice under two ids.

Run it after a seed (or any time) and resolve what it lists: either delete the
redundant row, or rename one so the difference is visible in the UI.

    cd backend
    .venv/bin/python scripts/seeds/verify/check_tool_overlap.py
    .venv/bin/python scripts/seeds/verify/check_tool_overlap.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, IN_DIR, OUT_DIR, REPO, SEEDS  # noqa: E402


from sqlalchemy import text                      # noqa: E402
from db.database import SessionLocal             # noqa: E402


def norm_name(name: str) -> str:
    """Fold a display name for comparison: case, spaces, punctuation."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def body_hash(config) -> str:
    """Stable hash of a tool implementation, ignoring key order."""
    if config is None:
        return ""
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            return hashlib.sha1(config.encode()).hexdigest()
    return hashlib.sha1(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    db = SessionLocal()
    try:
        rows = [dict(r._mapping) for r in db.execute(text("""
            SELECT tool_id, name, tool_type, is_builtin, implementation_config
            FROM custom_tools ORDER BY tool_id
        """))]
    finally:
        db.close()

    by_name: dict[str, list[dict]] = defaultdict(list)
    by_body: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_name[norm_name(row["name"])].append(row)
        h = body_hash(row.get("implementation_config"))
        if h:                                   # '' means "no implementation"
            by_body[h].append(row)

    name_groups = [g for g in by_name.values() if len(g) > 1]
    body_groups = [g for g in by_body.values() if len(g) > 1]

    if args.json:
        print(json.dumps({
            "same_name": [[r["tool_id"] for r in g] for g in name_groups],
            "same_implementation": [[r["tool_id"] for r in g] for g in body_groups],
        }, indent=2))
        return 0

    def describe(group, reason):
        print(f"  [{reason}]")
        for r in group:
            kind = "builtin" if r["is_builtin"] else "custom"
            print(f"     {r['tool_id']:28} {r['name'][:34]:34} {r['tool_type']:16} {kind}")

    print(f"{len(rows)} tool(s) in the database")
    if not name_groups and not body_groups:
        print("\nNo overlapping tools found — every tool_id is distinct by name and by implementation.")
        return 0

    print(f"\n{len(name_groups)} name collision group(s) — different ids, same label:")
    for g in name_groups:
        describe(g, "same name")

    print(f"\n{len(body_groups)} implementation collision group(s) — same code, different ids:")
    for g in body_groups:
        describe(g, "same implementation")

    print("\nResolve by deleting the redundant row (UI or SQL) or renaming one tool.")
    print("Nothing was changed by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
