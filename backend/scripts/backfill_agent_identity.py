"""Backfill ALL existing agents/deepagents with their real identity.

For every ``deep_agent_templates`` row this:
  1. resolves the agent's real workspace root (same rule as creation:
     ``WorkspaceManager.resolve_agent_workspace`` — custom ``workspace_path``
     first, then vault-scoped, then legacy ``outputs/agents/agent_{id}/``);
  2. calls the shared ``rebake_agent_identity`` helper which:
     - strips the stale ``## Identity`` block (and any legacy
       ``{{agent_id}}`` / ``{{workspace_root}}`` placeholders) from
       ``config.system_prompt``;
     - regenerates ``agent_docs`` when they look like the default template
       (or are empty); preserves user-authored docs verbatim, refreshing
       only the workspace-root lines via ``refresh_doc_identity``;
     - rebuilds the system prompt = original base + identity + AGENTS.md +
       CLAUDE.md embedded inline;
  3. persists BOTH ``config.system_prompt`` and ``agent_docs`` to PostgreSQL.

This script is a thin wrapper around ``core.agents.identity.rebake_agent_identity``,
which is also called by ``services/agent_bundle.import_agent_bundle`` so
imported agents never carry the source agent's id baked into their prompt.

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
from core.agents.identity import rebake_agent_identity


def _resolve_workspace(agent, override_root: str = "") -> str:
    from services.workspace_manager import get_workspace_manager
    ws_mgr = get_workspace_manager()
    if override_root:
        # Team install: the workspace root is defined by the user (seed step),
        # so resolve each agent's folder under that root.
        from pathlib import Path as _Path
        root = _Path(override_root).resolve()
        agent_folder = f"agent_{getattr(agent, 'id', 'unknown')}"
        custom = getattr(agent, "workspace_path", None)
        if custom and str(custom).strip():
            p = _Path(str(custom).strip()).expanduser()
            if not p.is_absolute():
                p = root / p
        else:
            p = root / "agents" / agent_folder
        p.mkdir(parents=True, exist_ok=True)
        return str(p)
    return str(ws_mgr.resolve_agent_workspace(
        agent, None, vault_key=None, agent_key=None,
    ))


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    override_root = ""
    if "--workspace-root" in sys.argv:
        idx = sys.argv.index("--workspace-root")
        if idx + 1 < len(sys.argv):
            override_root = sys.argv[idx + 1]
    db = SessionLocal()
    try:
        agents = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.id).all()
        updated = 0
        skipped = 0
        for agent in agents:
            ws_root = _resolve_workspace(agent, override_root)
            docs_were_empty = not (agent.agent_docs or {})
            if rebake_agent_identity(agent, ws_root):
                flag_modified(agent, "config")
                flag_modified(agent, "agent_docs")
                if not dry_run:
                    db.commit()
                updated += 1
                print(
                    f"{'[dry-run] ' if dry_run else ''}"
                    f"id={agent.id} name={agent.name!r} workspace={ws_root}"
                    f" -> prompt+docs {'regenerated' if docs_were_empty else 'identity refreshed'}"
                )
            else:
                skipped += 1
        print(f"\n{'DRY-RUN: ' if dry_run else ''}{updated} agent(s) would be/"
              f" updated, {skipped} already current.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
