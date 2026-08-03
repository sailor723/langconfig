"""
One-shot migration: copy existing filesystem artifacts into the storage backend.

Phase 4 of docs/system-architecture.md §15: run this once when flipping
``STORAGE_MODE=db`` so previously disk-only artifacts get a durable copy in
``storage_objects``. It covers exactly the namespaces Phase 2 writes through:

    data/documents/...            -> documents/<rel>              (FileStorage)
    backend/outputs/...           -> outputs/<rel>                (WorkspaceManager)
    skills table rows             -> skills/<type>/<id>/SKILL.md  (canonical render)

Skills are rendered from the DB rows (source of truth), not copied from the
git mirror, so migrated content matches what ``db_row_to_fs`` writes.

Idempotent by default: keys that already exist are skipped (use ``--force`` to
overwrite). Safe to re-run at any time.

Run (from backend/):
    uv run python -m tools.migrate_storage [--force] [--dry-run]
"""

import argparse
import logging
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env (DATABASE_URL etc.) before db.database is
# imported, mirroring how the FastAPI app boots (config.py -> load_dotenv).
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# Phase 4 targets storage_objects no matter what the ambient STORAGE_MODE is.
os.environ["STORAGE_MODE"] = "db"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_storage")


def _iter_files(root: Path):
    """Yield regular files under a root, sorted for deterministic output."""
    if not root.exists():
        logger.warning("Skipping missing directory: %s", root)
        return
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def _copy_tree(storage, root: Path, key_prefix: str, force: bool, dry_run: bool) -> tuple[int, int, int]:
    """Copy every file under `root` to `key_prefix/<rel>`. Returns
    (copied, skipped, errors)."""
    copied = skipped = errors = 0
    for p in _iter_files(root):
        key = f"{key_prefix}/{p.relative_to(root).as_posix()}"
        if storage.exists(key) and not force:
            skipped += 1
            continue
        mime, _ = mimetypes.guess_type(p.name)
        try:
            if not dry_run:
                storage.save(key, p.read_bytes(), mime)
            logger.info("  -> %s (%d bytes)", key, p.stat().st_size)
            copied += 1
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the run
            errors += 1
            logger.error("  !! %s: %s", key, e)
    return copied, skipped, errors


def migrate_documents(storage, force: bool, dry_run: bool) -> tuple[int, int, int]:
    """data/documents/... -> documents/<rel> (FileStorage base dir)."""
    from services.file_storage import FileStorage
    return _copy_tree(storage, FileStorage().base_dir.resolve(), "documents", force, dry_run)


def migrate_outputs(storage, force: bool, dry_run: bool) -> tuple[int, int, int]:
    """backend/outputs/... -> outputs/<rel> (WorkspaceManager base dir)."""
    from services.workspace_manager import WorkspaceManager
    return _copy_tree(storage, WorkspaceManager().base_dir.resolve(), "outputs", force, dry_run)


def migrate_skills(storage, force: bool, dry_run: bool) -> tuple[int, int, int]:
    """skills table rows -> skills/<type>/<id>/SKILL.md (canonical render)."""
    from core.skills.sync import skill_row_to_markdown, skill_storage_key
    from db.database import SessionLocal
    from models.skill import Skill

    copied = skipped = errors = 0
    db = SessionLocal()
    try:
        rows = db.query(Skill).all()
    finally:
        db.close()

    for row in rows:
        key = skill_storage_key(row)
        if storage.exists(key) and not force:
            skipped += 1
            continue
        try:
            if not dry_run:
                storage.save(key, skill_row_to_markdown(row).encode("utf-8"), "text/markdown")
            logger.info("  -> %s", key)
            copied += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.error("  !! %s: %s", key, e)
    return copied, skipped, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="Overwrite keys that already exist (default: skip)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be copied without writing anything")
    args = parser.parse_args()

    from services.storage import get_storage
    storage = get_storage()
    mode = "DRY-RUN" if args.dry_run else "MIGRATE"
    logger.info("%s into storage backend: %s", mode, type(storage).__name__)
    if args.force:
        logger.info("--force: existing keys will be overwritten")

    total = {"copied": 0, "skipped": 0, "errors": 0}
    for name, fn in (
        ("documents", migrate_documents),
        ("outputs", migrate_outputs),
        ("skills", migrate_skills),
    ):
        logger.info("[%s] %s/...", name, name)
        copied, skipped, errors = fn(storage, args.force, args.dry_run)
        total["copied"] += copied
        total["skipped"] += skipped
        total["errors"] += errors
        logger.info("[%s] copied=%d skipped=%d errors=%d", name, copied, skipped, errors)

    logger.info("done: copied=%d skipped=%d errors=%d%s",
                total["copied"], total["skipped"], total["errors"],
                " (dry run)" if args.dry_run else "")
    if total["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
