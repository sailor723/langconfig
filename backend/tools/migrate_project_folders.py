#!/usr/bin/env python3
"""One-time migration: rename vault + agent folders from id-keyed to name-keyed.

The vault/agent workspace folders were keyed by the DB ids
(``outputs/projects/{id}/agents/agent_{id}/``). They are now keyed by the
sanitized names (``outputs/projects/my-project/agents/hello/``). This tool
moves every existing folder so no generated files are orphaned.

Usage (from backend/):
    .venv/bin/python tools/migrate_project_folders.py [--dry-run]
"""
import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate_project_folders")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview moves only")
    args = parser.parse_args()

    from db.database import SessionLocal
    from models.core import Project
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import WorkspaceManager

    ws_mgr = WorkspaceManager()
    vault_root = ws_mgr.base_dir / "projects"
    if not vault_root.is_dir():
        logger.info("No vault root yet — nothing to migrate.")
        return 0

    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        moved = 0
        for p in projects:
            slug = WorkspaceManager.project_vault_key(db, p.id) or str(p.id)
            slug_dir = vault_root / slug
            id_dir = vault_root / str(p.id)

            # Resolve the CURRENT vault dir (already name-keyed or still id-keyed).
            if slug_dir.is_dir():
                vault_dir = slug_dir
            elif id_dir.is_dir():
                vault_dir = id_dir
                if slug != str(p.id) and not slug_dir.exists():
                    if args.dry_run:
                        logger.info(f"  would move {id_dir.name} → {slug}  (project {p.id} '{p.name}')")
                    else:
                        shutil.move(str(id_dir), str(slug_dir))
                        logger.info(f"  moved {id_dir.name} → {slug}  (project {p.id} '{p.name}')")
                        moved += 1
                    vault_dir = slug_dir if not args.dry_run else id_dir
            else:
                continue

            # Agent folders inside each vault: agents/agent_{id} → agents/{name}
            agents_root = vault_dir / "agents"
            if agents_root.is_dir():
                moved += _migrate_agent_folders(db, agents_root, args.dry_run)
    finally:
        db.close()

    logger.info(f"Done. {moved} folder(s) migrated." + ("  (dry-run)" if args.dry_run else ""))
    return 0


def _migrate_agent_folders(db, agents_root: Path, dry_run: bool) -> int:
    """Move agents/agent_{id} → agents/{sanitized-name} under a vault."""
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import WorkspaceManager

    moved = 0
    for old_dir in sorted(agents_root.iterdir()):
        if not old_dir.is_dir():
            continue
        name = old_dir.name
        if not name.startswith("agent_"):
            continue
        try:
            agent_id = int(name.split("_", 1)[1])
        except ValueError:
            continue
        agent = db.get(DeepAgentTemplate, agent_id)
        if agent is None:
            continue
        new_name = WorkspaceManager.agent_vault_key(db, agent)
        if new_name == name:
            continue
        new_dir = agents_root / new_name
        if new_dir.exists():
            logger.warning(f"  {name} → {new_name}: target exists, skipping")
            continue
        if dry_run:
            logger.info(f"  would move {name} → {new_name}  (agent {agent_id} '{agent.name}')")
            continue
        shutil.move(str(old_dir), str(new_dir))
        logger.info(f"  moved {name} → {new_name}  (agent {agent_id} '{agent.name}')")
        moved += 1
    return moved


if __name__ == "__main__":
    raise SystemExit(main())
