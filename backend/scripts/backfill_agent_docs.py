"""Backfill agent instruction docs (AGENTS.md / CLAUDE.md) into PostgreSQL.

Background: agent docs are now stored in ``deep_agent_templates.agent_docs``
with identity placeholders ({{agent_id}} / {{workspace_root}}), exactly like
the system prompt, and substituted at chat time when materialized to disk.

This backfill:
- seeds placeholder-based defaults for agents with no docs, and
- upgrades old-format defaults (literal baked workspace paths, no
  placeholders) to the placeholder-based version, so the same docs work for
  every session regardless of project binding.

Idempotent: docs that already carry {{agent_id}} placeholders are left alone.

Usage:
    cd backend
    uv run python scripts/backfill_agent_docs.py --dry-run   # preview only
    uv run python scripts/backfill_agent_docs.py             # apply
"""
import sys
import os

# Normalize to the real backend/ directory so config.py finds the root .env
# (a non-normalized "scripts/.." entry makes it miss the .env and silently
# connect to the default 5432 instead of the configured POSTGRES_PORT).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm.attributes import flag_modified

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate
from core.agents.identity import default_agent_docs

# Marker for old-format defaults (literal baked paths, no placeholders).
_PLACEHOLDER_TOKEN = "{{agent_id}}"
_LEGACY_LITERAL_PATH = ("outputs/agents/", "outputs/projects/")


def _needs_refresh(docs: dict) -> bool:
    """True if the stored docs are missing/old-format and should be replaced.

    Old-format defaults have no {{agent_id}} placeholder and contain a literal
    baked workspace path. User-authored docs (with placeholders or without the
    legacy literal-path signature) are left untouched.
    """
    if not docs:
        return True
    ag = docs.get("AGENTS.md") or ""
    if _PLACEHOLDER_TOKEN in ag:
        return False  # already placeholder-based
    return any(marker in ag for marker in _LEGACY_LITERAL_PATH)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        agents = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id).all()
        updated = 0
        skipped = 0
        for agent in agents:
            docs = agent.agent_docs or {}
            if not _needs_refresh(docs):
                skipped += 1
                continue
            new_docs = default_agent_docs(agent)
            agent.agent_docs = new_docs
            flag_modified(agent, "agent_docs")
            if not dry_run:
                db.commit()
            updated += 1
            print(
                f"{'[dry-run] ' if dry_run else ''}"
                f"id={agent.id} name={agent.name!r} -> docs "
                f"{'seeded' if not docs else 'refreshed (placeholder-based)'}"
            )
        print(f"\n{'DRY-RUN: ' if dry_run else ''}{updated} agent(s) would be/"
              f" updated, {skipped} already current.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
