# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The current user, for the duration of one request.

Why a ContextVar and not a parameter: there are 349 routes and none of them take
a user. Threading an argument through all of them would be a rewrite with a long
tail of missed call sites, and the missed ones fail *open* (they keep serving
whoever). A ContextVar set once by middleware is available everywhere — routes,
services, tools, agent code — and the failure mode of a miss is "no user", which
callers can treat as an error rather than as permission.

Propagation, which is the part that bites:

* ASGI middleware → route handler: same task, works.
* sync endpoints / ``run_in_threadpool``: anyio copies the context into the worker
  thread, works.
* a bare ``threading.Thread`` or a process-pool job started by an agent: **does
  not** propagate. Anything that runs work later must capture the user explicitly.

So: read it with :func:`current_user` when absence is tolerable, and with
:func:`require_user` when it is not.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Optional

from fastapi import HTTPException, status

from core.security.lan_auth import UserContext

logger = logging.getLogger(__name__)

_current_user: ContextVar[Optional[UserContext]] = ContextVar(
    "langconfig_current_user", default=None
)


# ── set / reset (middleware) ─────────────────────────────────────────────────

def set_current_user(user: Optional[UserContext]) -> Token:
    """Bind the identity for the current context. Returns a reset token."""
    return _current_user.set(user)


def reset_current_user(token: Token) -> None:
    try:
        _current_user.reset(token)
    except ValueError:  # token from another context — harmless, ignore
        pass


# ── read ─────────────────────────────────────────────────────────────────────

def current_user() -> Optional[UserContext]:
    """The caller, or None (before the first user exists, or background work)."""
    return _current_user.get()


def current_user_id() -> Optional[int]:
    """Convenience for writing nullable ``user_id`` columns."""
    user = _current_user.get()
    return user.id if user is not None else None


def require_user() -> UserContext:
    """FastAPI dependency: the caller, or 401.

    Use on any endpoint that reads or writes user-owned data. Using it is the
    point at which an endpoint stops being anonymous.
    """
    user = _current_user.get()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No user identity on this request.",
            headers={"WWW-Authenticate": 'Basic realm="LangConfig", charset="UTF-8"'},
        )
    return user


def require_admin() -> UserContext:
    """FastAPI dependency: the caller, if they are an admin, else 403."""
    user = require_user()
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )
    return user
