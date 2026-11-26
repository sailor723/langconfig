#!/usr/bin/env python
"""Replace an agent's authored prompt body, re-baking the machine tail.

A deep-agent ``system_prompt`` in the DB is two things glued together:

  * the **body** — what a human wrote (this file's input), and
  * the **machine tail** — ``## Identity`` + the embedded ``AGENTS.md`` —
    which ``core/agents/identity.py`` builds from the agent's id, its resolved
    workspace, and ``agent.agent_docs``.

The chat path strips and rebuilds the tail on every turn (``api/chat/messages.py``
calls ``_strip_identity_block`` + ``build_identity_system_prompt``), so a body
written here is never at risk of duplicating the tail. This script rebuilds the
stored copy the same way, so the agent-detail view of the prompt stays truthful
instead of showing a body with no identity.

Usage:
    cd backend && .venv/bin/python scripts/set_agent_prompt.py 372 --body-file body.md
    cd backend && .venv/bin/python scripts/set_agent_prompt.py 372 --show
    cd backend && .venv/bin/python scripts/set_agent_prompt.py 372 --body-file body.md --dry-run

Exit codes: 0 changed (or --show/--dry-run), 1 agent not found, 2 nothing changed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _resolve_workspace(db, agent, project_override: int | None = None) -> str:
    """解析这个 agent 的工作区,写进 prompt 的机器尾巴。

    为什么要能指定项目:`deep_agent_templates` **没有** project_id 列,所以不指定时永远
    落到「无项目兜底」目录(`outputs/users/<id>/agents/agent_N`),而运行时的会话是按
    当前项目解析的(`outputs/users/<id>/<vault>/agents/agent_N`)。两者不是同一个目录 ——
    存下来的 prompt 会写一个**运行时不会用**的路径,而这正是 agent"在错的地方找文件"那类问题。
    """
    from services.workspace_manager import get_workspace_manager

    mgr = get_workspace_manager()
    project_id = project_override if project_override is not None else getattr(agent, "project_id", None)
    return str(
        mgr.resolve_agent_workspace(
            agent,
            project_id,
            vault_key=mgr.project_vault_key(db, project_id) or None,
            agent_key=mgr.agent_vault_key(db, agent),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("agent_id", type=int)
    parser.add_argument("--body-file", type=Path, help="file holding the new authored body")
    parser.add_argument("--show", action="store_true", help="print the stored prompt and exit")
    parser.add_argument("--dry-run", action="store_true", help="report the change without writing")
    # 存下来的机器尾巴里会写工作区绝对路径。不指定项目就会写成无项目兜底目录,
    # 和运行时按当前项目解析出来的目录不是同一个 —— 用这个参数对齐。
    parser.add_argument("--project", type=int, default=None,
                        help="用哪个项目的 vault 解析工作区(缺省=无项目兜底目录)")
    args = parser.parse_args()

    if not args.show and args.body_file is None:
        parser.error("pass --body-file or --show")

    from core.agents.identity import _strip_identity_block, build_identity_system_prompt
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate

    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == args.agent_id).first()
        if agent is None:
            print(f"agent {args.agent_id} not found", file=sys.stderr)
            return 1

        cfg = dict(agent.config or {})
        stored = cfg.get("system_prompt", "") or ""
        if args.show:
            print(stored)
            return 0

        body = args.body_file.read_text(encoding="utf-8").strip()
        workspace_root = _resolve_workspace(db, agent, args.project)
        rebuilt = build_identity_system_prompt(
            body, agent.id, workspace_root, agent.agent_docs or {}
        )

        tail_before = len(stored) - len(_strip_identity_block(stored))
        tail_after = len(rebuilt) - len(body)
        print(f"agent {agent.id}: body {len(stored) - tail_before:,} → {len(body):,} chars; "
              f"tail {tail_before:,} → {tail_after:,} chars; workspace {workspace_root}")
        if rebuilt == stored:
            print("nothing changed")
            return 2
        if args.dry_run:
            print("dry run: not written")
            return 0

        cfg["system_prompt"] = rebuilt
        agent.config = cfg
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(agent, "config")
        db.commit()
        print("written")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
