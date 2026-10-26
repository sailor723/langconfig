# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Resolve *who* is calling, and publish it for the rest of the request.

Separate from the LAN gate on purpose. The gate answers a transport question
("did this arrive from the network, and did it carry a valid credential?") and
this answers an identity question ("so which person is that?"). Keeping them apart
means the auth mechanism can change without touching the gate, and vice versa.

Behaviour:

* The LAN gate has already verified a credential and parked the identity on the
  ASGI scope; this promotes it into the request context.
* **Loopback** (127.0.0.1 / ::1) has no credential by design, so it resolves to
  the install's *owner* — the first active admin. Local development therefore has
  a real identity instead of an anonymous one, which is what stops half the code
  base from growing single-user special cases.
* Anything else with no identity simply has no user. Endpoints that need one call
  ``require_user`` and get 401. Nothing implicitly becomes the owner.

Why not ``BaseHTTPMiddleware``: the app streams SSE and upgrades WebSockets. This
wraps neither; it sets a ContextVar, calls downstream, and resets in a ``finally``
so a raised exception cannot leak one user's identity into the next task.
"""

from __future__ import annotations

import logging
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from core.context.current_user import reset_current_user, set_current_user
from core.security.lan_auth import (
    CredentialVerifier,
    VerifierUnavailable,
    get_default_verifier,
)

logger = logging.getLogger(__name__)

# Where the LAN gate parks a verified identity for this middleware to pick up.
PRINCIPAL_KEY = "langconfig.user"

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_LOOPBACK_PREFIXES = ("127.",)


def is_loopback_scope(scope: Scope) -> bool:
    """True when the request came from this machine.

    Keyed on the source address, never on ``Host``/``X-Forwarded-For``: both are
    client-controlled, and trusting them would hand the loopback exemption to
    anyone who can reach the port.
    """
    client = scope.get("client")
    if not client:
        # No client address at all (in-process ASGI calls, test clients).
        return True
    host = client[0] or ""
    if host in _LOOPBACK_HOSTS:
        return True
    return any(host.startswith(prefix) for prefix in _LOOPBACK_PREFIXES)


class UserContextMiddleware:
    """Bind the caller's identity for the duration of one request."""

    def __init__(self, app: ASGIApp, verifier: Optional[CredentialVerifier] = None):
        self.app = app
        self._verifier = verifier
        self._resolved_verifier: Optional[CredentialVerifier] = None

    def _get_verifier(self) -> CredentialVerifier:
        if self._verifier is not None:
            return self._verifier
        if self._resolved_verifier is None:
            self._resolved_verifier = get_default_verifier()
        return self._resolved_verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        user = scope.get(PRINCIPAL_KEY)

        if user is None and is_loopback_scope(scope):
            # Local owner. A DB problem here must not break local work: treat it as
            # "no identity" and let user-scoped endpoints say 401.
            try:
                user = await run_in_threadpool(self._get_verifier().owner)
            except VerifierUnavailable:
                logger.warning("Could not resolve the local owner identity", exc_info=True)
                user = None

        token = set_current_user(user)
        if user is not None:
            scope[PRINCIPAL_KEY] = user
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_user(token)
