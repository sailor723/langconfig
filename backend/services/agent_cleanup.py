# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Remove an agent's workspace when the agent itself is removed.

Before this, deleting an agent removed its row and left its directories behind — 93 of
them accumulated on one install, invisible in the UI and impossible to attribute. A tree
that belongs to nothing is worse than a tree that belongs to someone: nobody can find it,
nobody dares delete it, and it quietly counts toward "where did my disk go".

Two decisions worth knowing:

* **Trash, not `rm -rf`.** The directory may hold the only copy of a deliverable the
  agent produced (`agent_222` on this install had three finished reports). Deletion is
  what the user asked for, so it is gone from their workspace — but it goes to
  ``<owner tree>/.trash/agents/<agent>_<timestamp>/``, which is recoverable and out of
  the way, rather than being unrecoverable. A dot-directory, so the file listing skips it.
* **Every tree, not just the caller's.** An agent is a global object: it has no owner
  column, and a second account may have run it in their own vault. Its directories are
  garbage wherever they are, so the sweep covers every `users/<id>/` tree. Anything
  outside the workspace (a hand-set absolute `workspace_path`) is left alone and logged —
  deleting outside the workspace is exactly what this codebase refuses to do.
"""

from __future__ import annotations

import datetime
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def workspace_dirs_for(agent, install_root: Optional[Path] = None) -> list[Path]:
    """Every directory that belongs to this agent, wherever it is.

    Three shapes, all of which exist in the wild: `<install>/users/<id>/agents/agent_N`
    (no vault), `<install>/users/<id>/<vault>/agents/agent_N` (vault-scoped), and the
    pre-per-user `<install>/<vault>/agents/agent_N`.
    """
    from services import user_roots

    root = Path(install_root or user_roots.install_root())
    agent_id = getattr(agent, "id", None)
    if agent_id is None:
        return []

    found: list[Path] = []
    seen: set = set()

    def _add(path: Path) -> None:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key not in seen:      # `**/agent_N` also matches `**/agents/agent_N`
            seen.add(key)
            found.append(path)

    for base in (root, root / user_roots.USERS_DIRNAME):
        if not base.is_dir():
            continue
        # `**/agent_N` covers `<base>/agents/agent_N`, `<base>/users/<id>/agents/agent_N`
        # and `<base>/users/<id>/<vault>/agents/agent_N` in one pattern.
        for candidate in base.glob(f"**/agent_{agent_id}"):
            if candidate.is_dir():
                _add(candidate)

    # A hand-set absolute workspace_path inside the workspace is also this agent's.
    custom = getattr(agent, "workspace_path", None)
    if custom and str(custom).strip():
        path = Path(str(custom).strip()).expanduser()
        try:
            path.resolve().relative_to(root.resolve())
            if path.is_dir():
                _add(path)
        except ValueError:
            logger.info(
                "Agent %s has a workspace outside the workspace root (%s) — leaving it alone",
                agent_id, path,
            )
    return found


def remove_agent_workspaces(agent, dry_run: bool = False) -> dict:
    """Move the agent's directories to the trash. Returns what happened.

    Never raises: a failure to tidy up must not make deleting an agent look broken, so
    problems are logged and reported in the summary instead.
    """
    from services import user_roots

    dirs = workspace_dirs_for(agent)
    trash_root = user_roots.root_for(user_roots.subject_user_id()) / ".trash" / "agents"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    summary = {"agent_id": getattr(agent, "id", None), "dirs": [], "files": 0, "moved_to": None}
    for path in dirs:
        files = [f for f in path.rglob("*") if f.is_file()]
        summary["dirs"].append(str(path))
        summary["files"] += len(files)
        if dry_run:
            continue
        try:
            trash_root.mkdir(parents=True, exist_ok=True)
            target = trash_root / f"agent_{getattr(agent, 'id', 'x')}_{stamp}_{path.parent.parent.name}"
            suffix = 1
            while target.exists():
                target = trash_root / f"agent_{getattr(agent, 'id', 'x')}_{stamp}_{path.parent.parent.name}_{suffix}"
                suffix += 1
            shutil.move(str(path), str(target))
            summary["moved_to"] = str(trash_root)
        except Exception as exc:  # noqa: BLE001 - tidy-up must not break deletion
            logger.warning("Could not remove workspace %s: %s", path, exc)

    if summary["dirs"]:
        action = "would move" if dry_run else "moved"
        logger.info(
            "Agent %s: %s %d workspace dir(s) (%d files) to the trash",
            summary["agent_id"], action, len(summary["dirs"]), summary["files"],
        )
    return summary
