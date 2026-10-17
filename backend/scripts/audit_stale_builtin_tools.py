"""Find built-in tool rows whose embedded code is older than the code in the repo.

Built-in tools are Postgres rows carrying their own source, and
``seed_builtin_tools.py`` deliberately never rewrites an existing row — that is
what protects a user's edit to a built-in. The cost is that a code fix never
reaches a database that was seeded before it: the row keeps running the old code
forever, and re-running ``seed_all.py`` cannot help, because the row already
exists.

That is how a team member's agent came to report "no Tavily API key" while the
Settings UI showed one saved and its Test button passed. The tool row still read
the key the pre-2026-08-16 way (the ``search`` settings document), while the UI
writes it to ``models.api_keys`` — the row was not wrong about the world, it was
old.

    cd <tree>/backend
    .venv/bin/python scripts/audit_stale_builtin_tools.py          # report only
    .venv/bin/python scripts/seeds/in/seed_builtin_tools.py --refresh # fix

Read-only: it generates the expected code in memory and compares, writing nothing.
"""
import os
import sys
from pathlib import Path

# Run from anywhere: take backend/ from this file's own location and work from there. The
# app resolves settings paths against the process CWD ("./data/documents"), so the CWD must be
# backend/ no matter where the script was invoked from — running it from the repo root used to
# fail with "can't open file .../scripts/<name>.py".
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

import tools.native_impl as native_impl  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402
from scripts.seeds.seed_builtin_tools import (  # noqa: E402
    SEEDABLE_TOOL_META,
    _TOOL_WRAPPER_OVERRIDE,
    _build_row,
)

expected: dict[str, str] = {}
unbuildable: list[str] = []
for order, name in enumerate(SEEDABLE_TOOL_META):
    try:
        tool_obj = getattr(native_impl, _TOOL_WRAPPER_OVERRIDE.get(name, name))
        meta = SEEDABLE_TOOL_META.get(name, (name, "misc", None))
        expected[name] = _build_row(name, tool_obj, meta, order=order)["implementation_config"]["code"]
    except Exception as exc:  # noqa: BLE001 - a tool that will not build is news too
        unbuildable.append(f"{name} ({exc})")

with engine.connect() as conn:
    rows = {
        r[0]: (r[1] or "")
        for r in conn.execute(
            text("SELECT tool_id, implementation_config->>'code' FROM custom_tools")
        )
    }

stale, missing, current = [], [], []
for name in SEEDABLE_TOOL_META:
    if name not in expected:
        continue
    if name not in rows:
        missing.append(name)
    elif (rows[name] or "").strip() == expected[name].strip():
        current.append(name)
    else:
        stale.append(name)

print(f"  built-in tools in the repo : {len(expected)}")
print(f"  rows matching current code : {len(current)}")
print(f"  rows MISSING               : {len(missing)}")
print(f"  rows STALE (older code)    : {len(stale)}")
if missing:
    print("    " + ", ".join(missing))
if stale:
    for name in stale:
        db_code = rows.get(name, "")
        hint = ""
        if "os.environ" in db_code or "search.get(" in db_code:
            hint = "  ← reads a key the way the pre-2026-08-16 code did"
        elif "get_api_key_from_db" in db_code:
            hint = "  ← reads the DB, but the rest of the code is older"
        print(f"    {name}{hint}")
if unbuildable:
    print(f"  could not build            : {len(unbuildable)}")
    for item in unbuildable:
        print(f"    {item}")

print()
if stale or missing:
    print("  Fix with:  .venv/bin/python scripts/seeds/in/seed_builtin_tools.py --refresh")
    print("  (that rewrites every seeded built-in row, so any deliberate edit to one")
    print("   is overwritten along with the stale code)")
else:
    print("  Every built-in row matches the code in this tree.")
