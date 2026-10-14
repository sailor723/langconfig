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
import glob
import json
import os
import re
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

from db.database import engine  # noqa: E402

DOCS_ROOT = os.path.join(os.getcwd(), "data", "documents")
KV_DIR = os.path.join(DOCS_ROOT, ".kvmeta")


def documents_root() -> str:
    """Ask the app where documents live rather than assuming data/documents."""
    try:
        from services.file_storage import file_storage
        return str(Path(file_storage.base_dir).resolve())
    except Exception:
        return DOCS_ROOT


def find_orphans() -> list[tuple[int, int, str]]:
    """(project_id, document count, .kvmeta path) for folders with no projects row."""
    root = documents_root()
    kv_dir = os.path.join(root, ".kvmeta")
    with engine.connect() as conn:
        known = {r[0] for r in conn.execute(text("SELECT id FROM projects"))}

    orphans = []
    for path in sorted(glob.glob(os.path.join(root, "project_*"))):
        if not os.path.isdir(path):
            continue
        match = re.fullmatch(r"project_(\d+)", os.path.basename(path))
        if not match:
            continue  # project_chat_sessions and friends are not projects
        pid = int(match.group(1))
        kv_file = os.path.join(kv_dir, f"project_{pid}.json")
        if not os.path.exists(kv_file):
            continue
        if pid in known:
            continue
        try:
            count = len(json.load(open(kv_file)))
        except Exception:
            count = 0
        orphans.append((pid, count, kv_file))
    return orphans


def find_uncatalogued() -> list[tuple[str, int]]:
    """Folders with files but no .kvmeta, plus non-numeric project_* dirs.

    Neither is adoptable, and for different reasons: without a `.kvmeta` there is no record for
    the panel to list (adopting the project would surface nothing), and `project_chat_sessions`
    is not a project at all — it is the chat attachment container, keyed by session id.
    """
    root = documents_root()
    kv_dir = os.path.join(root, ".kvmeta")
    found = []
    for path in sorted(glob.glob(os.path.join(root, "project_*"))):
        if not os.path.isdir(path):
            continue
        name = os.path.basename(path)
        files = sum(len(fs) for _, _, fs in os.walk(path))
        if not files:
            continue
        if not re.fullmatch(r"project_(\d+)", name):
            found.append((name, files))                       # not a project
        elif not os.path.exists(os.path.join(kv_dir, f"{name}.json")):
            found.append((name, files))                       # a project, but nothing lists it
    return found


ADOPT_DESC = "Adopted from data/documents — rename me in the UI"
JOURNAL_NAME = "adopt-journal.json"


def journal_path() -> Path:
    """Sibling of relocate-journal.json: both undo files live in the documents root."""
    return Path(documents_root()) / JOURNAL_NAME


def adopt(pid: int, name: str) -> bool:
    """Insert the row, reporting whether this call created it (ON CONFLICT may decline)."""
    with engine.begin() as conn:
        created = conn.execute(text("""
            INSERT INTO projects (id, name, description, status, configuration,
                                  indexing_status, created_at, updated_at)
            VALUES (:id, :name, :desc, 'active', '{}'::json, 'not_indexed', now(), now())
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """), {"id": pid, "name": name, "desc": ADOPT_DESC}).scalar()
    return created is not None


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


def fix_sequence() -> tuple[int, int]:
    """Advance projects_id_seq past the highest id, or the next insert collides."""
    with engine.begin() as conn:
        before = conn.execute(text("SELECT last_value FROM projects_id_seq")).scalar()
        highest = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM projects")).scalar()
        if highest > before:
            conn.execute(text("SELECT setval('projects_id_seq', :h)"), {"h": highest})
        after = conn.execute(text("SELECT last_value FROM projects_id_seq")).scalar()
        return before, after


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
