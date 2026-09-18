"""One-shot cleanup: remove orphan project rows + orphan vault dirs.

For team installs that have accumulated legacy / orphan projects over time.
Idempotent. Reads the `projects` table, asks the operator which to keep, and:

  - sets chat_sessions.project_id = NULL for sessions bound to to-delete
    projects (sessions stay, only their project binding is lost)
  - deletes the to-delete project rows
  - removes the legacy pre-K2 vault dirs at
    `<base>/projects/<slug>/` (orphans from before the drop-projects-segment
    migration; the new path is `<base>/<slug>/`)

Usage
=====
    cd backend
    uv run python scripts/clean_projects.py --dry-run
        # Plan: list projects + which are orphans (no DB row matches the
        # vault dir). No writes.

    uv run python scripts/clean_projects.py --keep my-project 'My Second Project'
        # Keep exactly these two project names (by name match); delete
        # all other project rows + their chat-session bindings.

    uv run python scripts/clean_projects.py --keep-all
        # Don't delete any DB project rows. Still clean the orphan
        # vault dirs.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Allow `from core.settings...` when run as a script.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
_REPO = _BACKEND.parent


def _resolve_base_dir() -> Path:
    try:
        from core.settings import runtime_get
        configured = runtime_get("workspace", "base_dir") or "backend/outputs"
    except Exception:
        configured = "backend/outputs"
    p = Path(configured).expanduser()
    if not p.is_absolute():
        p = _REPO / p
    return p.resolve()


def _resolve_workspace_root() -> Path:
    """Where agents_md_service reads/writes per-project AGENTS.md files."""
    try:
        from core.settings import runtime_get
        configured = runtime_get("runtime", "langconfig_workspace_root") or "backend/.workspace_data"
    except Exception:
        configured = "backend/.workspace_data"
    p = Path(configured).expanduser()
    if not p.is_absolute():
        p = _REPO / p
    return p.resolve()


def _read_db_projects() -> list[tuple[int, str]]:
    from db.database import SessionLocal
    from models.core import Project
    db = SessionLocal()
    try:
        return [(p.id, p.name) for p in db.query(Project).order_by(Project.id).all()]
    finally:
        db.close()


def _vault_orphan_dirs(root: Path, active_slugs: set[str]) -> list[Path]:
    """Return legacy `<root>/projects/<slug>/` dirs whose slug is NOT
    bound to any active project. Pre-K2 path."""
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return []
    out = []
    for child in projects_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name not in active_slugs:
            out.append(child)
    return out


def _output_orphan_dirs(base: Path, active_slugs: set[str]) -> list[Path]:
    """Return empty `<base>/<slug>/` dirs that have NO active project."""
    out = []
    if not base.is_dir():
        return out
    for child in base.iterdir():
        if not child.is_dir():
            continue
        # Skip known non-project dirs
        if child.name in {"agents", "default", "exports", "generated",
                          "presentations", "standalone", ".trash"}:
            continue
        if child.name.startswith("project_"):
            # Legacy project_<id> dirs (pre-K2 get_project_workspace format)
            out.append(child)
            continue
        if child.name not in active_slugs and not any(child.iterdir()):
            # Empty dir whose name isn't a current project slug
            out.append(child)
    return out


def _active_slugs(projects: list[tuple[int, str]]) -> set[str]:
    from services.workspace_manager import WorkspaceManager
    slugs = set()
    for pid, name in projects:
        s = WorkspaceManager._slugify(name)
        if s:
            slugs.add(s)
    return slugs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan: print what would change; no writes.")
    ap.add_argument("--keep-all", action="store_true",
                    help="Don't delete any project rows; only clean orphan "
                         "vault + empty output dirs.")
    ap.add_argument("--keep", nargs="*", default=[],
                    help="Project NAMES to keep (delete everything else). "
                         "Match by exact name, case-sensitive. If empty and "
                         "--keep-all is not set, the script will print the "
                         "current project list and exit (no writes).")
    ap.add_argument("--base-dir", default="",
                    help="Override the agent-workspace base directory "
                         "(defaults to the workspace settings doc `base_dir`).")
    args = ap.parse_args()

    projects = _read_db_projects()
    active_slugs = _active_slugs(projects)
    base = Path(args.base_dir).expanduser().resolve() if args.base_dir else _resolve_base_dir()
    ws_root = _resolve_workspace_root()

    print(f"base_dir (agents):     {base}")
    print(f"workspace_root (md):   {ws_root}")
    print()
    print("=== projects in DB ===")
    for pid, name in projects:
        print(f"  id={pid:>3d}  name={name!r}")
    print()

    # Decide what to keep
    if args.keep_all:
        keep_names: set[str] = {n for _, n in projects}
        print("--keep-all: keeping all DB project rows")
    elif args.keep:
        keep_names = set(args.keep)
        missing = keep_names - {n for _, n in projects}
        if missing:
            print(f"!! --keep names not in DB: {missing}")
            return 2
        print(f"--keep: keeping {sorted(keep_names)}; deleting the rest")
    else:
        print("(no --keep given and no --keep-all; nothing to delete)")
        print("Pass --keep <name> [...] or --keep-all to do the cleanup.")
        return 0

    delete_ids = [(pid, name) for pid, name in projects if name not in keep_names]
    kept = [(pid, name) for pid, name in projects if name in keep_names]
    print()
    print(f"  KEEP  ({len(kept)}): {[(pid, n) for pid, n in kept]}")
    print(f"  DEL   ({len(delete_ids)}): {[(pid, n) for pid, n in delete_ids]}")
    print()

    # 1) Unbind chat sessions from to-delete projects
    unbound_total = 0
    if delete_ids:
        from db.database import SessionLocal
        from models.deep_agent import ChatSession
        db = SessionLocal()
        try:
            for pid, _name in delete_ids:
                if args.dry_run:
                    n = db.query(ChatSession).filter_by(project_id=pid).count()
                    print(f"  [dry-run] would unbind {n} sessions from project_id={pid}")
                else:
                    n = db.query(ChatSession).filter_by(project_id=pid).update(
                        {"project_id": None}
                    )
                    db.commit()
                    print(f"  unbound {n} sessions from project_id={pid}")
                    unbound_total += n
        finally:
            db.close()
    print()

    # 2) Delete project rows
    if delete_ids and not args.dry_run:
        from db.database import SessionLocal
        from models.core import Project
        db = SessionLocal()
        try:
            for pid, _name in delete_ids:
                n = db.query(Project).filter_by(id=pid).delete()
                db.commit()
                print(f"  deleted project id={pid} ({n} row)")
        finally:
            db.close()
    elif delete_ids:
        for pid, name in delete_ids:
            print(f"  [dry-run] would delete project id={pid} ({name!r})")
    print()

    # 3) Clean legacy vault orphans (`<ws_root>/projects/<slug>/`)
    vault_orphans = _vault_orphan_dirs(ws_root, active_slugs)
    print(f"=== vault orphans at {ws_root}/projects/ ===")
    if vault_orphans:
        for d in vault_orphans:
            if args.dry_run:
                print(f"  [dry-run] would remove {d.relative_to(_REPO)}/")
            else:
                shutil.rmtree(d)
                print(f"  removed {d.relative_to(_REPO)}/")
        # If projects/ is now empty, remove it
        proj_dir = ws_root / "projects"
        if not args.dry_run and proj_dir.is_dir() and not any(proj_dir.iterdir()):
            proj_dir.rmdir()
            print(f"  removed empty source dir: {proj_dir.relative_to(_REPO)}/")
    else:
        print("  (none)")
    print()

    # 4) Clean empty legacy output dirs (`<base>/project_<id>/`, etc.)
    output_orphans = _output_orphan_dirs(base, active_slugs)
    print(f"=== empty legacy output dirs at {base}/ ===")
    if output_orphans:
        for d in output_orphans:
            if args.dry_run:
                print(f"  [dry-run] would remove {d.relative_to(_REPO)}/")
            else:
                shutil.rmtree(d)
                print(f"  removed {d.relative_to(_REPO)}/")
    else:
        print("  (none)")
    print()

    if args.dry_run:
        print("DRY-RUN — no writes performed.")
    else:
        print(f"Done. Unbound {unbound_total} sessions, "
              f"deleted {len(delete_ids)} projects, "
              f"cleaned {len(vault_orphans)} vault orphans, "
              f"cleaned {len(output_orphans)} legacy output dirs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
