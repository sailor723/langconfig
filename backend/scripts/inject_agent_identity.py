"""Batch-inject the agent identity block into all existing DeepAgent templates.

Background: agents historically did not know their own identity or workspace —
they guessed by querying pg_get_agent and wrote self-invented identity blocks
into AGENTS.md. This backfill appends the identity block (with
{{agent_id}}/{{agent_name}}/{{category}}/{{workspace_root}} placeholders) to
each agent's ``config.system_prompt`` in PostgreSQL.

The placeholders are substituted at chat time with the runtime-resolved values
(see api/chat/messages.py); the DB stores the literals so the same prompt works
for every session regardless of project binding.

Idempotent: agents whose system_prompt already contains the "## Identity"
marker are skipped.

Usage:
    cd backend
    uv run python scripts/inject_agent_identity.py --dry-run   # preview only
    uv run python scripts/inject_agent_identity.py             # apply
"""
import sys
import os

# Normalize to the real backend/ directory. A non-normalized "scripts/.."
# entry makes config.__file__ resolve to "backend/scripts/../config.py", so
# config.py's dirname(dirname(__file__))/.env misses the root .env and the
# script silently connects to the default 5432 instead of the configured
# POSTGRES_PORT (docker 5433).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm.attributes import flag_modified

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate
from core.agents.identity import refresh_identity_block


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        agents = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id).all()
        updated = 0
        skipped = 0
        for agent in agents:
            cfg = dict(agent.config or {})
            prompt = cfg.get("system_prompt", "") or ""
            new_prompt = refresh_identity_block(prompt)
            if new_prompt == prompt:
                skipped += 1
                continue
            cfg["system_prompt"] = new_prompt
            agent.config = cfg
            flag_modified(agent, "config")
            if not dry_run:
                db.commit()
            updated += 1
            print(
                f"{'[dry-run] ' if dry_run else ''}"
                f"id={agent.id} name={agent.name!r} category={agent.category!r}"
                f" -> identity block appended"
            )
        print(f"\n{'DRY-RUN: ' if dry_run else ''}{updated} agent(s) would be/"
              f" updated, {skipped} already had the block.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
