"""One-shot cleanup: remove demo/test 'hello' agents left over from debugging.

Targets agents whose name matches any of these (case-insensitive):
  - 'demo hello' (e.g. 'demo hello', 'demo hello1', 'demo hello 3')
  - 'new hello'  (e.g. 'new hello', 'new hello 2')
  - 'test hello' (e.g. 'test hello')

Always preserves id=159 'hello' (the original non-test agent).

Idempotent: re-running after the first successful run is a no-op (the agents
are gone, the query returns nothing).

Usage
=====
    cd backend
    uv run python scripts/cleanup_demo_hello.py --dry-run
        # List the agents that WOULD be deleted; no writes.

    uv run python scripts/cleanup_demo_hello.py
        # Delete the matching agents + their chat sessions + their agent_documents
        # + their filesystem workspace dirs (both the project-scoped path and
        # the legacy <base>/agents/agent_<id>/ path).

Skips agents with `is_active=False`? No — they're included. The script
only matches by name. Use --skip-ids to preserve additional agents.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Allow `from db...` etc. when run as a script.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# Hard-coded preserve list. Add more ids here if the team has other agents
# they want to keep.
DEFAULT_SKIP_IDS: set[int] = {159}  # the original 'hello' agent

# Name matchers (case-insensitive). Add more prefixes here for future cleanup.
DEFAULT_NAME_PATTERNS: tuple[str, ...] = ("demo hello", "new hello", "test hello")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be deleted; no writes.")
    ap.add_argument("--skip-ids", type=int, nargs="*", default=[],
                    help="Additional agent IDs to preserve (merged with the "
                         "default skip list).")
    args = ap.parse_args()

    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate, ChatSession
    from models.agent_document import AgentDocument
    from services.workspace_manager import WorkspaceManager

    skip_ids = DEFAULT_SKIP_IDS | set(args.skip_ids)
    db = SessionLocal()
    ws_mgr = WorkspaceManager()
    try:
        # Find matches
        matches = []
        for a in db.query(DeepAgentTemplate).all():
            if a.id in skip_ids:
                continue
            name = (a.name or "").lower()
            if any(pat in name for pat in DEFAULT_NAME_PATTERNS):
                matches.append(a)
        if not matches:
            print("No demo/test 'hello' agents found. Nothing to do.")
            return 0

        print(f"Found {len(matches)} agent(s) matching {[p for p in DEFAULT_NAME_PATTERNS]}:")
        for a in matches:
            print(f"  id={a.id} name={a.name!r}")
        print()

        if args.dry_run:
            print("DRY-RUN — no writes.")
            return 0

        deleted = 0
        sessions_deleted = 0
        docs_deleted = 0
        dirs_removed = 0
        for a in matches:
            aid = a.id
            name = a.name
            # 1) Delete agent_documents that FK-reference this agent
            for d in db.query(AgentDocument).filter_by(agent_id=aid).all():
                db.delete(d)
                docs_deleted += 1
            # 2) Delete chat sessions
            n = db.query(ChatSession).filter_by(agent_id=aid).delete()
            sessions_deleted += n
            # 3) Delete the agent row
            db.delete(a)
            db.commit()
            # 4) Remove filesystem workspace dirs (legacy + project-scoped)
            legacy = _BACKEND / "outputs" / "agents" / f"agent_{aid}"
            if legacy.is_dir():
                shutil.rmtree(legacy, ignore_errors=True)
                dirs_removed += 1
            project_path = ws_mgr.resolve_agent_workspace(
                a, None, vault_key=None, agent_key=None,
            )
            if project_path.is_dir():
                shutil.rmtree(project_path, ignore_errors=True)
                dirs_removed += 1
            deleted += 1
            print(f"  deleted {aid} ({name!r}) — {n} session(s)")

        print()
        print(f"=== SUMMARY ===")
        print(f"agents deleted:   {deleted}")
        print(f"sessions deleted: {sessions_deleted}")
        print(f"docs deleted:     {docs_deleted}")
        print(f"dirs removed:     {dirs_removed}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
