"""
LAN access guard — a Basic-auth door for non-loopback requests.

Why this exists
---------------
The backend binds 0.0.0.0, so without a gate every route on port 8765 is
reachable from the network. The app is also a code-execution surface (agents hold
filesystem and shell tools) and keeps every provider key in `settings.api_keys`.

This middleware answers one question: "is this request coming from the machine
itself, or from the network?"

* Loopback requests (127.0.0.1 / ::1) are always allowed, so local development,
  the Vite dev-server proxy and the test suite are untouched.
* Every other request must carry HTTP Basic credentials that match a row in the
  ``users`` table.
* Credentials cannot be resolved at all (no users configured, database down)
  → **503**, never 200. A misconfiguration must never silently reopen the hole
  this module exists to close.

Where identity goes
-------------------
On success the resolved identity is parked on the ASGI scope under
``langconfig.user`` and ``middleware/identity.UserContextMiddleware`` promotes it
into the request context. This middleware deliberately does not touch the
ContextVar itself — verification and identity stay separate concerns.

Credentials are **bootstrap-only** now: ``LANGCONFIG_LAN_USERS`` is imported once
into the ``users`` table on first boot (``services/user_service``) and never read
again. Manage users in the app after that.

Implementation notes
--------------------
* Pure ASGI, deliberately NOT BaseHTTPMiddleware: the app streams SSE and upgrades
  WebSockets (terminal sessions), and a buffering middleware would break both.
* The loopback exemption keys off the *source address*, not the Host header, which
  any client can forge.
* Credential verification runs in a worker thread — scrypt costs ~25 ms and the
  verifier caches successes, but it must never block the event loop.
"""

import logging
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from core.security.lan_auth import (
    CredentialVerifier,
    VerifierUnavailable,
    get_default_verifier,
    parse_env_credentials,
)
from middleware.identity import PRINCIPAL_KEY, is_loopback_scope

logger = logging.getLogger(__name__)

# Kept for the pre-Slice-1 name used by tests and docs.
_is_loopback = is_loopback_scope


def lan_access_enabled() -> bool:
    """True when LAN access (and therefore the gate) is switched on."""
    import os

    return os.getenv("LANGCONFIG_LAN_ACCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bypass_paths() -> tuple[str, ...]:
    import os

    raw = os.getenv("LANGCONFIG_LAN_BYPASS_PATHS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_lan_users() -> tuple[dict[str, str], list[str]]:
    """``.env`` credentials as ``{username: password}``, plus rejected entries.

    Retained because the bootstrap path and the boot-time report both read the
    same rules. These are **not** the credentials used to authenticate anymore.
    """
    credentials, problems = parse_env_credentials()
    return dict(credentials), problems


def _path_of(scope: Scope) -> str:
    path = scope.get("path") or "/"
    return path.split("?", 1)[0]


def _basic_credentials(scope: Scope) -> tuple[Optional[str], Optional[str]]:
    """Decode an ``Authorization: Basic`` header into ``(user, password)``."""
    import base64

    for key, value in scope.get("headers") or []:
        if key.lower() != b"authorization":
            continue
        try:
            raw = value.decode("latin-1").strip()
        except Exception:
            return None, None
        if not raw.lower().startswith("basic "):
            return None, None
        try:
            decoded = base64.b64decode(raw[6:].strip(), validate=True).decode("utf-8")
        except Exception:
            return None, None
        user, sep, password = decoded.partition(":")
        if not sep:
            return None, None
        return user, password
    return None, None


def _attempted_username(scope: Scope) -> str:
    """Who a refused request claimed to be, made safe for a log line."""
    user, _ = _basic_credentials(scope)
    if not user:
        return "anonymous"
    cleaned = "".join(ch for ch in user if ch.isprintable()).strip()
    return cleaned[:64] or "anonymous"


class LanGuardMiddleware:
    """Reject non-loopback requests that do not carry valid Basic credentials."""

    def __init__(self, app: ASGIApp, verifier: Optional[CredentialVerifier] = None):
        self.app = app
        self.enabled = lan_access_enabled()
        self.bypass_paths = _bypass_paths()
        self._verifier = verifier
        self._resolved_verifier: Optional[CredentialVerifier] = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _get_verifier(self) -> CredentialVerifier:
        if self._verifier is not None:
            return self._verifier
        if self._resolved_verifier is None:
            self._resolved_verifier = get_default_verifier()
        return self._resolved_verifier

    # ── ASGI ─────────────────────────────────────────────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.enabled:
            await self.app(scope, receive, send)
            return

        # The local machine always gets in — that is the owner.
        if is_loopback_scope(scope):
            await self.app(scope, receive, send)
            return

        path = _path_of(scope)
        if self.bypass_paths and any(path.startswith(p) for p in self.bypass_paths):
            await self.app(scope, receive, send)
            return

        username, password = _basic_credentials(scope)

        if username is None:
            # No credentials at all: is there even an install to sign in to?
            try:
                owner = await run_in_threadpool(self._get_verifier().owner)
            except VerifierUnavailable as exc:
                logger.error("LAN guard could not read the user store: %s", exc)
                await self._deny_unavailable(scope, send)
                return
            if owner is None:
                await self._deny_unconfigured(scope, send)
                return
            self._log_denied(scope, path)
            await self._deny_unauthorized(scope, send)
            return

        try:
            user = await run_in_threadpool(
                self._get_verifier().verify, username, password or ""
            )
        except VerifierUnavailable as exc:
            logger.error("LAN guard could not read the user store: %s", exc)
            await self._deny_unavailable(scope, send)
            return

        if user is not None:
            scope[PRINCIPAL_KEY] = user
            await self.app(scope, receive, send)
            return

        self._log_denied(scope, path)
        await self._deny_unauthorized(scope, send)

    # ── denials ──────────────────────────────────────────────────────────────

    @staticmethod
    def _log_denied(scope: Scope, path: str) -> None:
        client = scope.get("client")
        logger.warning(
            "LAN guard refused %s %s from %s (claimed user %r)",
            scope.get("method", scope["type"]).upper(),
            path,
            client[0] if client else "unknown",
            _attempted_username(scope),
        )

    @staticmethod
    async def _deny_unauthorized(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send(
                {"type": "websocket.close", "code": 1008, "reason": "authentication required"}
            )
            return

        body = (
            b"LangConfig: authentication required.\n\n"
            b"Sign in with your own account. Accounts are managed by an\n"
            b"administrator in the app (Admin -> Users).\n"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": _plain_headers(
                    body,
                    extra=[(b"www-authenticate", b'Basic realm="LangConfig", charset="UTF-8"')],
                ),
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _deny_unconfigured(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send(
                {"type": "websocket.close", "code": 1011, "reason": "LAN access misconfigured"}
            )
            return

        body = (
            b"LangConfig: LAN access is enabled but no account exists.\n"
            b"Refusing the request. Create the first administrator on the server:\n"
            b"  cd backend && .venv/bin/python scripts/create_user.py <name> <pw> --admin\n"
        )
        await send(
            {"type": "http.response.start", "status": 503, "headers": _plain_headers(body)}
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _deny_unavailable(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send(
                {"type": "websocket.close", "code": 1011, "reason": "user store unavailable"}
            )
            return

        body = (
            b"LangConfig: the user store is unavailable, so credentials cannot be\n"
            b"checked. Refusing the request rather than guessing.\n"
        )
        await send(
            {"type": "http.response.start", "status": 503, "headers": _plain_headers(body)}
        )
        await send({"type": "http.response.body", "body": body})


def _plain_headers(body: bytes, extra: list | None = None) -> list:
    headers = [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if extra:
        headers.extend(extra)
    return headers
