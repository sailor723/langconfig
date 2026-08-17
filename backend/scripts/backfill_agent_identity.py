"""Backfill ALL existing agents/deepagents with their real identity.

For every ``deep_agent_templates`` row this:
  1. resolves the agent's real workspace root (same rule as creation:
     ``WorkspaceManager.resolve_agent_workspace`` — custom ``workspace_path``
     first, then vault-scoped, then legacy ``outputs/agents/agent_{id}/``);
  2. builds AGENTS.md / CLAUDE.md with the REAL agent id + workspace baked in
     (user-authored docs are preserved; old default-template docs and empty
     docs are regenerated with real values);
  3. rebuilds the system prompt = original base prompt + identity block
     (real id + workspace) + AGENTS.md/CLAUDE.md embedded inline;
  4. persists BOTH ``config.system_prompt`` and ``agent_docs`` to PostgreSQL.

Idempotent: an agent is skipped when its stored prompt and docs already match
what the backfill would produce (re-running reports 0 changes).

Usage:
    cd backend
    uv run python scripts/backfill_agent_identity.py --dry-run   # preview
    uv run python scripts/backfill_agent_identity.py             # apply
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
from core.agents.identity import (
    build_identity_system_prompt,
    default_agent_docs,
    _strip_identity_block,
)

# Signature of the OLD default-template docs (regenerable with real values).
# User-authored docs that do NOT match this shape are preserved.
_DEFAULT_TEMPLATE_SIGNATURE = "## Path map"


def _resolve_workspace(agent) -> str:
    from services.workspace_manager import get_workspace_manager
    ws_mgr = get_workspace_manager()
    return str(ws_mgr.resolve_agent_workspace(
        agent, None, vault_key=None, agent_key=None,
    ))


def _is_old_default_docs(docs: dict) -> bool:
    ag = (docs or {}).get("AGENTS.md") or ""
    return _DEFAULT_TEMPLATE_SIGNATURE in ag


def _build_docs(agent, workspace_root: str) -> dict:
    """Keep user-authored docs; regenerate old defaults/empty with real values."""
    existing = agent.agent_docs or {}
    if existing and not _is_old_default_docs(existing):
        return dict(existing)
    return default_agent_docs(agent, workspace_root)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        agents = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id).all()
        updated = 0
        skipped = 0
        for agent in agents:
            cfg = dict(agent.config or {})
            stored_prompt = cfg.get("system_prompt", "") or ""
            base_prompt = _strip_identity_block(stored_prompt)
            ws_root = _resolve_workspace(agent)
            docs = _build_docs(agent, ws_root)
            new_prompt = build_identity_system_prompt(
                base_prompt, agent.id, ws_root, docs
            )
            docs_changed = (agent.agent_docs or {}) != docs
            if new_prompt == stored_prompt and not docs_changed:
                skipped += 1
                continue
            cfg["system_prompt"] = new_prompt
            agent.config = cfg
            agent.agent_docs = docs
            flag_modified(agent, "config")
            flag_modified(agent, "agent_docs")
            if not dry_run:
                db.commit()
            updated += 1
            print(
                f"{'[dry-run] ' if dry_run else ''}"
                f"id={agent.id} name={agent.name!r} workspace={ws_root}"
                f" -> prompt+docs {'regenerated' if docs_changed else 'identity refreshed'}"
            )
        print(f"\n{'DRY-RUN: ' if dry_run else ''}{updated} agent(s) would be/"
              f" updated, {skipped} already current.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
