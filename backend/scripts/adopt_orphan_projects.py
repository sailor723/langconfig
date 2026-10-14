"""Adopt document folders that exist on disk but have no `projects` row.

    cd <tree>/backend
    .venv/bin/python scripts/adopt_orphan_projects.py                 # report only
    .venv/bin/python scripts/adopt_orphan_projects.py --apply
    .venv/bin/python scripts/adopt_orphan_projects.py --apply --names names.json

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

Read-only unless `--apply` is given.
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())  # run from <tree>/backend, as a file or via stdin

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402

DOCS_ROOT = os.path.join(os.getcwd(), "data", "documents")
KV_DIR = os.path.join(DOCS_ROOT, ".kvmeta")


def documents_root() -> str:
    """Ask the app where documents live rather than assuming data/documents."""
    try:
        from services.file_storage import file_storage
        return str(file_storage.base_dir)
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


def adopt(pid: int, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO projects (id, name, description, status, configuration,
                                  indexing_status, created_at, updated_at)
            VALUES (:id, :name, :desc, 'active', '{}'::json, 'not_indexed', now(), now())
            ON CONFLICT (id) DO NOTHING
        """), {"id": pid, "name": name,
               "desc": "Adopted from data/documents — rename me in the UI"})


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
    ap.add_argument("--names", help='JSON file mapping id -> name, e.g. {"77": "My Project"}')
    ap.add_argument("--name-pattern", default="project {id}",
                    help="name for adopted projects when --names has no entry (default: %(default)r)")
    args = ap.parse_args()

    names = {}
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

    if not args.apply:
        print("\n  report only. Re-run with --apply to insert these rows.")
        print("  Pass --names file.json to give them their real names; they can also be renamed")
        print("  in the UI afterwards.")
        return 0

    for pid, _, _ in orphans:
        adopt(pid, names.get(pid) or args.name_pattern.format(id=pid))
    before, after = fix_sequence()
    print(f"\n  adopted {len(orphans)} project(s); projects_id_seq {before} -> {after}")

    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM projects")).scalar()
    print(f"  projects now: {total}")
    print("\n  Verify: GET /api/projects/ lists them, and the Knowledge panel can open them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
