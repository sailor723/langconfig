# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Where a person's files live.

The rule, in one line: ``<install root>/users/<user id>/<vault>/…``. Everything a
user produces — agent outputs, uploads, generated reports, the terminal's starting
directory, the root the agent's file tools are confined to — hangs off that one
directory, so "whose file is this?" is answered by the path as well as by the DB.

Why the user segment goes *above* the vault (project): a project is shared (it holds
shared agents and shared knowledge), but a person's files are not. Putting the user
first means one person's tree can be moved, backed up, permissioned or deleted as a
single unit, and a terminal started in that tree cannot wander into somebody else's
work by walking up one level.

Three deliberate properties:

* **No user, no nesting.** An install with no accounts (LAN access off, a fresh
  clone, the test suite) keeps the old flat layout ``<root>/<vault>/…``. Nesting
  under ``users/`` only starts once accounts exist, so single-user installs do not
  acquire a pointless directory level.
* **Unknown identity falls back to the owner.** Background work — scheduled runs,
  checkpoint cleanups, a script — has no request context. Attributing it to the
  install's owner keeps today's behaviour (the person who owns the machine sees what
  the machine produced) instead of inventing an invisible "system" tree.
* **This module resolves paths; it does not enforce them.** The terminal is a real
  shell: a root here sets its starting directory, it does not cage it. Isolation for
  the app's own read paths comes from the ``owner_id`` filters, and the honest
  boundary is documented in docs/reference/multiuser docs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

#: Directory under the install root that holds one subtree per account.
USERS_DIRNAME = "users"

#: The workspace root of the run currently executing, bound by whoever starts the run.
#:
#: Why this lives here and not in the tool module: the tools an agent actually runs are
#: **code snapshots in PostgreSQL** (`custom_tools`), generated from `tools/native_impl.py`
#: by inlining the helpers a tool references. A ContextVar declared in `native_impl`
#: would therefore be inlined into each snapshot as a *separate* variable, and a binding
#: set in the module would be invisible to the snapshot — which is exactly the kind of
#: silent no-op that looks like it works. Declared here, both sides import the same
#: object.
_RUN_ROOT: "ContextVar[Optional[str]]" = ContextVar("langconfig_run_root", default=None)


def personal_skills_dir() -> Path:
    """`backend/skills/personal` — the parent of every account's skill folder.

    Personal skills stay in the repository (unlike agent workspaces, which live under
    the workspace root) so they remain git-tracked and travel with the team seed. What
    changes is the structure: one folder per account, `personal/<user id>/<skill>/`.
    """
    from services.workspace_manager import get_workspace_manager

    backend_dir = Path(get_workspace_manager().install_base_dir()).parent
    return backend_dir / "skills" / "personal"


def personal_skills_dir_for(user_id: Optional[int]) -> Path:
    """One account's skill folder. No account → the parent, unscoped (legacy installs)."""
    base = personal_skills_dir()
    return base if user_id is None else base / str(user_id)


def install_root() -> Path:
    """The workspace base directory (``outputs/`` by default, or the Settings path).

    Delegates to :class:`services.workspace_manager.WorkspaceManager`'s own
    resolution so there is exactly one answer to "where is the workspace". Imported
    lazily: workspace_manager imports this module for its user roots.
    """
    from services.workspace_manager import get_workspace_manager

    return Path(get_workspace_manager().install_base_dir()).resolve()


def subject_user_id(db=None) -> Optional[int]:
    """The account a filesystem operation belongs to.

    ``current_user()`` when a request is in flight; otherwise the install's owner;
    otherwise None (no accounts at all). The owner fallback is what keeps scheduled
    runs and scripts writing to the same tree as before accounts existed.
    """
    from core.context.current_user import current_user_id

    user_id = current_user_id()
    if user_id is not None:
        return user_id

    close = False
    try:
        if db is None:
            from db.database import SessionLocal

            db = SessionLocal()
            close = True
        from services.user_service import owner_user

        owner = owner_user(db)
        return owner.id if owner is not None else None
    except Exception:  # a DB problem must not change where files go silently
        logger.warning("Could not resolve the install owner for a file path", exc_info=True)
        return None
    finally:
        if close and db is not None:
            try:
                db.close()
            except Exception:
                pass


def users_dir(root: Optional[Path] = None) -> Path:
    return Path(root or install_root()) / USERS_DIRNAME


def root_for(user_id: Optional[int], root: Optional[Path] = None) -> Path:
    """The private tree for one account, or the install root when there is none.

    Not created here: a path resolver that makes directories turns read paths into
    writes (and a typo into a new empty tree). Callers that write create their own.
    """
    base = Path(root or install_root())
    if user_id is None:
        return base
    return base / USERS_DIRNAME / str(user_id)


def bind_run_root(path) -> object:
    """Bind the workspace root for one run/tool call. Returns a reset token."""
    return _RUN_ROOT.set(str(path))


def clear_run_root(token) -> None:
    try:
        _RUN_ROOT.reset(token)
    except ValueError:  # token from another context — harmless
        pass


def current_run_root() -> Optional[str]:
    return _RUN_ROOT.get()


def current_root(db=None, root: Optional[Path] = None) -> Path:
    """The private tree of whoever is asking right now (see :func:`subject_user_id`).

    ``root`` overrides the install root — the workspace manager passes its own
    resolved base so both agree even when Settings points elsewhere.
    """
    bound = _RUN_ROOT.get()
    if bound:
        return Path(bound)
    return root_for(subject_user_id(db), root=root)


def describe(user_id: Optional[int], root: Optional[Path] = None) -> dict:
    """Small, loggable summary — used by boot logs and by ``/api/users/me`` callers."""
    path = root_for(user_id, root)
    return {
        "user_id": user_id,
        "root": str(path),
        "exists": path.is_dir(),
        "scoped": user_id is not None,
    }
