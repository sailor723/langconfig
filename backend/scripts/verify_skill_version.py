#!/usr/bin/env python3
"""Which version of a skill does each agent ACTUALLY read? And make them all read the current one.

A skill lives in three places that can disagree, and only the third is what an agent reads:

  1. the repo       backend/skills/builtin/<id>/SKILL.md          (git-tracked, the source of truth)
  2. the database   skills.instructions                            (synced FS→DB at app startup, by mtime)
  3. the workspace  <agent workspace>/skills/builtin/<id>/SKILL.md  (staged when a SESSION STARTS)

Measured on the ECS box: the file and the database were 2.3 while two agents' workspaces still held 2.2,
because a workspace copy is only refreshed by a session start — so an agent that had not been talked to
since the skill changed kept reading the old ladder, and "did the agent see the fix?" had no answer.

    .venv/bin/python scripts/verify_skill_version.py                      # audit every copy
    .venv/bin/python scripts/verify_skill_version.py --restage            # copy the current file into every workspace
    .venv/bin/python scripts/verify_skill_version.py --restage --agent 364
    exit 0 when every copy matches the repo file, 1 when one does not (after --restage: 0 unless a copy is unwritable)
"""
from __future__ import annotations

import argparse
import glob
import pathlib
import re
import shutil
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
BUILTIN = BACKEND / "skills" / "builtin"
WORKSPACES = BACKEND / "outputs" / "users"

#: A phrase that only exists in the version we are checking for. A version number can be pinned wrong in
#: two files at once; a sentence from the newest section cannot.
MARKERS = {
    "build-ontology-from-db": "The ladder ends at S8",
}


def version_of(blob: str) -> str:
    m = re.search(r"^version:\s*'?([0-9.]+)'?", blob or "", re.M)
    return m.group(1) if m else "?"


def db_version(skill_id: str) -> tuple[str, bool]:
    try:
        from sqlalchemy import text
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            row = db.execute(text("select version, instructions from skills where skill_id=:s"),
                             {"s": skill_id}).first()
        finally:
            db.close()
    except Exception as exc:                                     # noqa: BLE001
        return (f"unreadable ({type(exc).__name__})", False)
    if row is None:
        return ("MISSING", False)
    marker = MARKERS.get(skill_id)
    return (str(row[0]), bool(marker and marker in (row[1] or "")))


def workspace_copies(skill_id: str, agent: str | None) -> list[pathlib.Path]:
    pattern = str(WORKSPACES / "*" / "*" / "agents" / "agent_*" / "skills" / "builtin" / skill_id / "SKILL.md")
    paths = [pathlib.Path(p) for p in sorted(glob.glob(pattern))]
    if agent:
        paths = [p for p in paths if f"agent_{agent}" in str(p.parent)]
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skill", default="build-ontology-from-db")
    ap.add_argument("--agent", default="", help="only this agent id (e.g. 364)")
    ap.add_argument("--restage", action="store_true",
                    help="copy the repo file into every workspace copy found (what a session start would do)")
    args = ap.parse_args()

    src = BUILTIN / args.skill / "SKILL.md"
    if not src.is_file():
        print(f"no skill at {src}")
        return 2
    blob = src.read_text(encoding="utf-8")
    fs_version = version_of(blob)
    marker = MARKERS.get(args.skill)
    print(f"repo file     {fs_version:>6}  {len(blob):>7,} chars  marker={bool(marker and marker in blob)}  {src}")

    dbv, db_marker = db_version(args.skill)
    print(f"database row  {dbv:>6}            marker={db_marker}   (a restart syncs FS→DB by mtime)")

    copies = workspace_copies(args.skill, args.agent or None)
    print(f"workspace copies: {len(copies)}")
    stale = []
    for path in copies:
        old = path.read_text(encoding="utf-8", errors="replace")
        ok = version_of(old) == fs_version and (not marker or marker in old)
        who = path.parts[-6] if len(path.parts) >= 6 else "?"
        agent = next((p for p in path.parts if p.startswith("agent_")), "?")
        user = next((p for p in path.parts[path.parts.index("users") + 1:]), "?" ) if "users" in path.parts else "?"
        print(f"  {'OK   ' if ok else 'STALE'} user={user:>3} {agent:12} v{version_of(old):<5} {len(old):>7,} chars")
        if not ok:
            stale.append(path)

    if args.restage and stale:
        for path in stale:
            try:
                shutil.copy2(src, path)
                print(f"  restaged → {path}")
            except Exception as exc:                             # noqa: BLE001
                print(f"  could not restage {path}: {exc}")
        stale = [p for p in stale if version_of(p.read_text(encoding="utf-8", errors="replace")) != fs_version]

    if stale:
        print(f"\n{len(stale)} workspace cop{'y' if len(stale) == 1 else 'ies'} do NOT match the repo file."
              " A session start restages it; --restage does it now.")
        return 1
    print("\nevery copy the agents read matches the repo file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
