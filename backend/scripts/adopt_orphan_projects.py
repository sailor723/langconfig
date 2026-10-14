"""Adopt document folders that exist on disk but have no `projects` row.

    cd <tree>/backend
    .venv/bin/python scripts/adopt_orphan_projects.py                 # report only
    .venv/bin/python scripts/adopt_orphan_projects.py --apply
    .venv/bin/python scripts/adopt_orphan_projects.py --apply --names names.json
    .venv/bin/python scripts/adopt_orphan_projects.py --undo

Why this exists: the Knowledge panel lists projects from `GET /api/projects/`, so a
`data/documents/project_<id>/` folder is only reachable if a matching row exists. Copy a legacy
documents folder into a fresh install — the case that stalled a team migration — and every file
and every `.kvmeta` record is present and readable (`/api/kv/documents?project_id=<id>` returns
them, `/api/kv/documents/<id>/file` serves them), while the sidebar has no project to click. The
data is not lost; it is unreachable.

Two things this script has to get right, both learned the hard way:

1. **A row needs more than `id` and `name`.** `ProjectResponse` requires `status`,
   `configuration` and `indexing_status`; inserting only the first two makes
   `GET /api/projects/` return 500 for *every* project, turning "one project is invisible" into
   "the project list is broken". This inserts the full row.
2. **Explicit ids do not advance the sequence.** Inserting `id = 77` leaves
   `projects_id_seq` where it was, so the next project created in the UI collides. The sequence
   is reset past the highest adopted id.

Only numeric `project_<id>` folders that also have a `.kvmeta/project_<id>.json` are adopted.
That pairing is deliberate: it excludes `project_chat_sessions`, which is not a project but the
chat attachment container (its documents live under a session id).

`--apply` records the ids it actually created in `adopt-journal.json`, next to the documents it
made reachable, and `--undo` deletes exactly those rows. Nothing deletes a folder, ever.

Read-only unless `--apply` or `--undo` is given.
"""
import argparse
import json
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

from sqlalchemy import text  # noqa: E402

from db.database import SessionLocal, engine  # noqa: E402

# Discovery, the insert and the sequence fix now live in one place, shared with the projects
# endpoint that registers on read. Two copies of that logic would drift; the 500-on-partial-row
# trap in particular is only avoided because one function knows about it.
from services.kb_discovery import AUTO_DESC, discover, fix_sequence as _fix_sequence  # noqa: E402
from services.kb_discovery import kb_root, register_missing, uncatalogued  # noqa: E402


def documents_root() -> str:
    """Where this install keeps documents — from environment configuration, not the database."""
    return str(Path(kb_root()).resolve())


def find_orphans() -> list[tuple[int, int, str]]:
    """(project_id, document count, .kvmeta path) for on-disk projects with no projects row."""
    on_disk = discover()
    if not on_disk:
        return []
    with engine.connect() as conn:
        known = {r[0] for r in conn.execute(text("SELECT id FROM projects"))}
    return [(p.project_id, p.document_count, str(p.kv_file))
            for p in on_disk if p.project_id not in known]


def find_uncatalogued() -> list[tuple[str, int]]:
    """Folders that exist but cannot be registered — no catalog, or not a project at all."""
    return uncatalogued()


ADOPT_DESC = AUTO_DESC
JOURNAL_NAME = "adopt-journal.json"


def journal_path() -> Path:
    """Sibling of relocate-journal.json: both undo files live in the documents root."""
    return Path(documents_root()) / JOURNAL_NAME


def adopt(pid: int, name: str) -> bool:
    """Insert the row via the shared registrar, reporting whether this call created it."""
    db = SessionLocal()
    try:
        return bool(register_missing(db, names={pid: name}, only=[pid]))
    finally:
        db.close()


def fix_sequence() -> tuple[int, int]:
    """Advance projects_id_seq past the highest id, or the next UI insert collides."""
    db = SessionLocal()
    try:
        return _fix_sequence(db)
    finally:
        db.close()


def undo() -> int:
    """Delete exactly the rows a previous --apply created, and nothing else.

    A row is removed only while it still carries the adopt marker, so a project the user has
    since taken over (renamed, re-described) is left alone and reported instead. The documents
    stay on disk untouched — this reverses the *reachability* change, not the migration.

    The id sequence is deliberately not rolled back: shrinking it could hand a future project an
    id that some copied folder still uses.
    """
    path = journal_path()
    if not path.exists():
        print(f"  no journal at {path} — nothing to undo")
        print("  (the journal is written by --apply)")
        return 1

    created = json.loads(path.read_text()).get("created", [])
    if not created:
        print("  journal records no created rows — nothing to undo")
        return 0

    removed, kept = [], []
    with engine.begin() as conn:
        for pid in created:
            row = conn.execute(
                text("SELECT description FROM projects WHERE id = :i"), {"i": pid}
            ).first()
            if row is None:
                continue                      # already gone; nothing to reverse
            if row[0] != ADOPT_DESC:
                kept.append(pid)              # taken over by a human — leave it
                continue
            conn.execute(text("DELETE FROM projects WHERE id = :i"), {"i": pid})
            removed.append(pid)

    print(f"  removed {len(removed)} adopted row(s): {removed or 'none'}")
    if kept:
        print(f"  kept {len(kept)} row(s) that are no longer the adopted placeholder: {kept}")

    root = Path(documents_root())
    still = [p for p in removed if (root / f"project_{p}").is_dir()]
    if still:
        print(f"\n  their folders are untouched and still on disk: {still}")
        print("  without a projects row they are unreachable again — re-run --apply to undo this undo.")
    path.rename(path.with_suffix(".json.undone"))
    print(f"  journal closed: {path.name} -> {path.name}.undone")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="insert the missing project rows")
    ap.add_argument("--undo", action="store_true",
                    help="delete the rows a previous --apply created (uses its journal)")
    ap.add_argument("--names", help='JSON file mapping id -> name, e.g. {"77": "My Project"}')
    ap.add_argument("--name-pattern", default="project {id}",
                    help="name for adopted projects when --names has no entry (default: %(default)r)")
    args = ap.parse_args()

    if args.undo:
        return undo()

    names = {}
    created: list[int] = []
    if args.names:
        names = {int(k): v for k, v in json.load(open(args.names)).items()}

    root = documents_root()
    print(f"  documents root : {root}")
    orphans = find_orphans()

    if not orphans:
        print("  no orphan folders — every numeric project_<id> folder has a projects row")
        return 0

    print(f"  {len(orphans)} orphan folder(s): documents on disk, no project to reach them\n")
    for pid, count, _ in orphans:
        label = names.get(pid) or args.name_pattern.format(id=pid)
        print(f"    project_{pid:<6} {count:>5} document(s)   would be named {label!r}")

    uncatalogued = find_uncatalogued()
    if uncatalogued:
        print("\n  not adoptable (no .kvmeta record, so nothing could list them anyway):")
        for name, files in uncatalogued:
            print(f"    {name:<20} {files:>5} file(s)")

    if not args.apply:
        print("\n  report only. Re-run with --apply to insert these rows.")
        print("  Pass --names file.json to give them their real names; they can also be renamed")
        print("  in the UI afterwards.")
        return 0

    for pid, _, _ in orphans:
        if adopt(pid, names.get(pid) or args.name_pattern.format(id=pid)):
            created.append(pid)
    before, after = fix_sequence()
    print(f"\n  adopted {len(created)} project(s); projects_id_seq {before} -> {after}")

    journal_path().write_text(json.dumps({"created": created}, indent=2))
    print(f"  journal: {journal_path()}  (revert with --undo)")

    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM projects")).scalar()
    print(f"  projects now: {total}")
    print("\n  Verify: GET /api/projects/ lists them, and the Knowledge panel can open them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
