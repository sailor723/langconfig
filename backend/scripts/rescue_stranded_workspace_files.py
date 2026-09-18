"""One-shot rescue: move files stranded in nested ``Users/`` trees into the
correct agent workspace subfolders.

Background
==========
Before ``WorkspaceFilesystemBackend`` (services/workspace_filesystem_backend.py)
fixed absolute-path handling, an agent whose baked identity pointed at an
ABSOLUTE legacy workspace (e.g. ``outputs/agents/agent_115``) wrote
deliverables through the SDK's virtual filesystem. The SDK re-based the
absolute path UNDER the session's resolved workspace root, producing nested
trees like::

    <workspace>/Users/weiping/dev/…/backend/outputs/agents/agent_115/generated/report.md

while the workspace's own ``generated/`` stayed empty — the Files panel showed
a stray "Users" folder instead of the deliverable.

What this script does
=====================
1. Walks the workspace base dir for files whose workspace-relative path
   contains a ``Users`` segment (the re-based absolute-path marker).
2. Parses the legacy target from the tail: ``outputs/agents/agent_<id>/<sub>/``
   (or ``outputs/projects/<proj>/agents/<name>/``).
3. Resolves the agent's CURRENT workspace — vault-scoped, using the project of
   the agent's most-recent chat session — and moves the file into its
   ``generated/`` (or ``upload/`` / ``other/``) subfolder there.
   Agents that can't be resolved (deleted / legacy rows) fall back to the
   workspace root the file already lives in, moved to ``other/``.
4. Prunes the emptied nested ``Users/`` trees (never touches anything above
   the workspace root).

Idempotent: files already in place are skipped. ``--dry-run`` prints the plan
without writing anything.

Usage
=====
    cd backend
    uv run python scripts/rescue_stranded_workspace_files.py --dry-run   # preview
    uv run python scripts/rescue_stranded_workspace_files.py             # apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Normalize to the real backend/ directory so config.py finds the root .env
# (a non-normalized "scripts/.." entry makes it miss the .env and silently
# connect to the default 5432 instead of the configured POSTGRES_PORT).
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
_REPO = _BACKEND.parent

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")

from db.database import SessionLocal  # noqa: E402
from models.deep_agent import ChatSession, DeepAgentTemplate  # noqa: E402
from services.workspace_manager import get_workspace_manager  # noqa: E402

# Subfolders a stranded file may be moved into; anything else (or unknown)
# lands in "other" — never "skills".
SAFE_SUBFOLDERS = ("generated", "upload", "other")


def _find_marker(parts: tuple[str, ...], marker: tuple[str, ...]) -> int:
    """Index of the first occurrence of `marker` as a contiguous subsequence
    of `parts`, or -1."""
    n = len(marker)
    for i in range(len(parts) - n + 1):
        if parts[i : i + n] == marker:
            return i
    return -1


def _parse_stranded(rel_parts: tuple[str, ...]) -> dict | None:
    """Parse a workspace-relative path that contains a nested ``Users`` tree.

    Returns ``{"agent_id": str|None, "subfolder": str|None, "filename": str}``
    or None when the path is not a stranded file.
    """
    try:
        i_users = rel_parts.index("Users")
    except ValueError:
        return None
    tail = rel_parts[i_users + 1 :]
    if not tail:
        return None

    # Pattern A: …/outputs/agents/agent_<id>/[<subfolder>/]<filename>
    i = _find_marker(tail, ("outputs", "agents"))
    if i != -1 and i + 2 < len(tail) and tail[i + 2].startswith("agent_"):
        rest = tail[i + 3 :]
        if not rest:
            return None
        subfolder, filename = (rest[0], rest[-1]) if len(rest) > 1 else (None, rest[0])
        return {"agent_id": tail[i + 2][len("agent_") :], "subfolder": subfolder, "filename": filename}

    # Pattern B: …/outputs/projects/<proj>/agents/<name>/[<subfolder>/]<filename>
    # (rest[0] is the AGENT name, not a subfolder)
    i = _find_marker(tail, ("outputs", "projects"))
    if i != -1 and i + 3 < len(tail) and tail[i + 3] == "agents":
        rest = tail[i + 4 :]
        if not rest:
            return None
        filename = rest[-1]
        subfolder = rest[1] if len(rest) >= 3 else None
        return {"agent_id": None, "subfolder": subfolder, "filename": filename}

    return None


def _resolve_current_workspace(db, mgr, agent_id: str | None) -> Path | None:
    """The agent's current vault-scoped workspace root.

    Project = the agent's most-recent chat session (the vault the user is
    actively using); falls back to the legacy per-agent root when the agent
    row is gone or has no sessions.
    """
    if not agent_id or not agent_id.isdigit():
        return None
    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == int(agent_id)).first()
    if agent is None:
        return None
    sess = (
        db.query(ChatSession)
        .filter(ChatSession.agent_id == agent.id)
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    pid = getattr(sess, "project_id", None) if sess else None
    vault_key = None
    if pid is not None:
        vault_key = mgr.project_vault_key(db, pid) or None
    return mgr.resolve_agent_workspace(
        agent,
        pid,
        vault_key=vault_key,
        agent_key=mgr.agent_vault_key(db, agent),
    )


def _workspace_root_of(base: Path, rel_parts: tuple[str, ...]) -> Path:
    """The workspace root that contains the file: everything up to (but not
    including) the ``Users`` directory — the re-based tree starts right at the
    workspace root."""
    try:
        i = rel_parts.index("Users")
    except ValueError:
        return base
    return base.joinpath(*rel_parts[:i])


def _unique_target(target_dir: Path, filename: str) -> Path:
    """A target path that does not collide with an existing file."""
    target = target_dir / filename
    if not target.exists():
        return target
    stem, suffix = filename.rsplit(".", 1) if "." in filename else (filename, "")
    suffix = "." + suffix if suffix else ""
    for n in range(1, 1000):
        candidate = target_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
    return target_dir / f"{stem}_{os.getpid()}{suffix}"


def _plan_moves(db, mgr) -> list[dict]:
    """Compute the move plan. Each entry:
    {src, dst, agent_id, subfolder, reason}"""
    base = mgr.base_dir
    plans = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(base)
        except ValueError:
            continue
        parsed = _parse_stranded(rel.parts)
        if parsed is None:
            continue
        filename = parsed["filename"]
        subfolder = parsed["subfolder"]
        if subfolder not in SAFE_SUBFOLDERS:
            subfolder = "other"

        target_ws = _resolve_current_workspace(db, mgr, parsed["agent_id"])
        if target_ws is None:
            # Agent row gone / unparsable: keep the file in the workspace root
            # it already lives in, moved to other/.
            target_ws = _workspace_root_of(base, rel.parts)
            reason = "fallback: agent unresolved, kept in current workspace"
        else:
            reason = f"agent {parsed['agent_id']} current workspace (vault-scoped)"

        dst_dir = target_ws / subfolder
        dst = _unique_target(dst_dir, filename)
        plans.append(
            {
                "src": p,
                "dst": dst,
                "agent_id": parsed["agent_id"],
                "subfolder": subfolder,
                "reason": reason,
            }
        )
    return plans


def _prune_empty_users_trees(base: Path, moved_srcs: list[Path]) -> int:
    """Remove directories that became empty after the moves, walking up from
    each old parent to (but not including) the workspace root. Returns the
    number of directories removed."""
    removed = 0
    for src in moved_srcs:
        d = src.parent
        while True:
            if not d.exists():
                break
            try:
                rel = d.relative_to(base)
            except ValueError:
                break
            if "Users" not in rel.parts:
                break  # reached the workspace root (or above it) — stop
            if any(d.iterdir()):
                break  # non-empty — keep ancestors
            d.rmdir()
            removed += 1
            d = d.parent
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan without moving anything")
    args = ap.parse_args()

    mgr = get_workspace_manager()
    base = mgr.base_dir
    print(f"Workspace base: {base}")

    db = SessionLocal()
    try:
        plans = _plan_moves(db, mgr)
    finally:
        db.close()

    if not plans:
        print("No stranded files found — nothing to do.")
        return

    print(f"Found {len(plans)} stranded file(s):\n")
    for i, plan in enumerate(plans, 1):
        print(f"  {i}. {plan['src'].relative_to(base)}")
        print(f"     -> {plan['dst'].relative_to(base)}")
        print(f"        ({plan['reason']})")

    if args.dry_run:
        print("\n[dry-run] no files were moved.")
        return

    moved = []
    for plan in plans:
        plan["dst"].parent.mkdir(parents=True, exist_ok=True)
        plan["src"].rename(plan["dst"])
        moved.append(plan["src"])
        print(f"Moved: {plan['src'].relative_to(base)} -> {plan['dst'].relative_to(base)}")

    pruned = _prune_empty_users_trees(base, moved)
    print(f"\nDone. Moved {len(moved)} file(s), pruned {pruned} empty nested dir(s).")


if __name__ == "__main__":
    main()
