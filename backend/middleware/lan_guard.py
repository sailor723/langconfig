"""
LAN access guard — a Basic-auth door for non-loopback requests.

Why this exists
---------------
This app is single-user and has no authentication at all: every route trusts
whoever called it. It is also a code-execution surface (agents hold filesystem
and shell tools) and it keeps every provider key in `settings.api_keys`.
`start.sh` binds the backend to 0.0.0.0, so *anyone* who can reach port 8765
already has full control of the machine and of your API spend.

This middleware is the smallest thing that closes that hole without inventing
user accounts. It answers exactly one question: "is this request coming from
the machine itself, or from the network?"

* Loopback requests (127.0.0.1 / ::1) are always allowed, so local
  development, the Vite dev-server proxy and the test suite are untouched.
* Every other request must present HTTP Basic credentials from `.env`.
* Enabled with no password configured FAILS CLOSED (503). A misconfiguration
  must never silently reopen the hole this module exists to close.

Scope, stated plainly
---------------------
There is still exactly one identity per credential, and the data behind the door
is shared. This is not authentication of a *person* in the application's sense —
it is a door with a key each. Everyone behind it shares the same settings,
API keys, projects, files and chat history. Per-person data is a separate,
larger piece of work: docs/reference/plans/2026-10-17-multiuser-design.md.

Why one credential per person, and not a second shared password: it makes
revocation individual (drop a name, tell nobody else) and makes the refusal log
name the credential that was tried.

Implementation notes
--------------------
* Pure ASGI, deliberately NOT BaseHTTPMiddleware. The app streams SSE (chat and
  workflow execution) and upgrades WebSockets (terminal sessions); a middleware
  that buffers or wraps the response would break both.
* The loopback exemption keys off the *source address* (scope["client"]), not
  the Host header. A Host header can be forged by any client, so trusting it
  would be a one-line bypass for exactly the attacker this guards against.

Configuration (.env)
--------------------
    LANGCONFIG_LAN_ACCESS=on            # off (default) | on
    LANGCONFIG_LAN_USERS=alice:pw,bob:pw # one credential per person, comma-separated
    # Legacy single-credential form, still honoured when USERS is unset:
    LANGCONFIG_LAN_USER=langconfig      # Basic-auth username
    LANGCONFIG_LAN_PASSWORD=...         # Basic-auth password (required)
    LANGCONFIG_LAN_BYPASS_PATHS=        # optional, comma-separated path prefixes
                                        # that skip auth (e.g. /api/webhooks/ —
                                        # only for endpoints that verify their
                                        # own signatures)
"""

import base64
import hmac
import logging
import os

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Source addresses that mean "the machine itself". Anything else is the network.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_LOOPBACK_PREFIXES = ("127.",)


def lan_access_enabled() -> bool:
    """True when LAN access (and therefore the gate) is switched on."""
    return os.getenv("LANGCONFIG_LAN_ACCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_loopback(scope: Scope) -> bool:
    client = scope.get("client")
    if not client:
        # No client address at all (in-process ASGI calls, some test clients).
        # Treat as local: it cannot have come off the network.
        return True
    host = client[0] or ""
    if host in _LOOPBACK_HOSTS:
        return True
    return any(host.startswith(prefix) for prefix in _LOOPBACK_PREFIXES)


def _bypass_paths() -> tuple[str, ...]:
    raw = os.getenv("LANGCONFIG_LAN_BYPASS_PATHS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _path_of(scope: Scope) -> str:
    path = scope.get("path") or "/"
    # WebSocket scopes carry the query string in the path in some servers.
    return path.split("?", 1)[0]


def parse_lan_users() -> tuple[dict[str, str], list[str]]:
    """Credentials allowed through the gate: ``{username: password}``, plus problems.

    `LANGCONFIG_LAN_USERS` is the multi-person form — comma-separated
    ``name:password``. Only the FIRST colon separates, so a password may itself
    contain one (``alice:a:b`` is user ``alice`` with password ``a:b``).

    Unset, it falls back to the single `LANGCONFIG_LAN_USER` /
    `LANGCONFIG_LAN_PASSWORD` pair, so an existing .env keeps working.

    This is *not* multi-user in the app's sense: the accounts only decide who may
    come through the door. Once inside, everyone still shares one workspace, one
    settings row and one set of API keys.

    Malformed entries are dropped, never guessed at. An entry with no colon would
    otherwise become a user with a blank password, and "blank means anything"
    is precisely the failure this module exists to prevent.
    """
    raw = os.getenv("LANGCONFIG_LAN_USERS", "").strip()
    accounts: dict[str, str] = {}
    problems: list[str] = []

    if raw:
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, sep, password = entry.partition(":")
            name, password = name.strip(), password.strip()
            if not sep:
                problems.append(f"{name!r} has no ':' — expected name:password")
                continue
            if not name or not password:
                problems.append(f"{name!r} has an empty name or password")
                continue
            accounts[name] = password
        return accounts, problems

    single_user = os.getenv("LANGCONFIG_LAN_USER", "langconfig").strip() or "langconfig"
    single_password = os.getenv("LANGCONFIG_LAN_PASSWORD", "")
    if single_password:
        accounts[single_user] = single_password
    return accounts, problems


def _basic_credentials(scope: Scope) -> tuple[str | None, str | None]:
    """Decode an ``Authorization: Basic`` header into ``(user, password)``."""
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


def _match_credentials(scope: Scope, accounts: dict[str, str]) -> str | None:
    """Return the matching username, or None if the request carries no valid one.

    Every account is compared even after a match, and both fields go through
    `compare_digest`, so how long the check takes cannot reveal which usernames
    exist — or which of the several credentials was the near miss.
    """
    user, password = _basic_credentials(scope)
    if user is None:
        return None
    matched: str | None = None
    for name, expected in accounts.items():
        user_ok = hmac.compare_digest(user, name)
        password_ok = hmac.compare_digest(password or "", expected)
        if user_ok and password_ok:
            matched = name
    return matched


def _attempted_username(scope: Scope) -> str:
    """Who a refused request claimed to be, made safe for a log line.

    The value comes from the request, so it is attacker-controlled: strip
    non-printable characters and cap the length before it reaches the log.
    """
    user, _ = _basic_credentials(scope)
    if not user:
        return "anonymous"
    cleaned = "".join(ch for ch in user if ch.isprintable()).strip()
    return cleaned[:64] or "anonymous"


class LanGuardMiddleware:
    """Reject non-loopback requests that do not carry valid Basic credentials."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.enabled = lan_access_enabled()
        self.accounts, self.account_problems = parse_lan_users()
        self.bypass_paths = _bypass_paths()

        if self.enabled:
            # Reporting lives in main.py, which can do it at boot; this is only
            # for someone constructing the middleware directly.
            if not self.accounts:
                logger.debug(
                    "LAN guard enabled with no credentials — refusing non-loopback requests"
                )
            else:
                logger.debug(
                    "LAN guard enabled (%d credential(s), %d bypass prefix(es))",
                    len(self.accounts),
                    len(self.bypass_paths),
                )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.enabled:
            await self.app(scope, receive, send)
            return

        # The local machine always gets in — that is the owner.
        if _is_loopback(scope):
            await self.app(scope, receive, send)
            return

        # An enabled gate with no usable credential is a configuration bug, not
        # permission.
        if not self.accounts:
            await self._deny_unconfigured(scope, send)
            return

        path = _path_of(scope)
        if self.bypass_paths and any(path.startswith(p) for p in self.bypass_paths):
            await self.app(scope, receive, send)
            return

        if _match_credentials(scope, self.accounts):
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
            # Reject before accept: closes the handshake, no frames exchanged.
            await send(
                {
                    "type": "websocket.close",
                    "code": 1008,
                    "reason": "authentication required",
                }
            )
            return

        body = (
            b"LangConfig: authentication required.\n\n"
            b"This instance is shared over the network. Sign in with your own "
            b"credentials from the server's .env (LANGCONFIG_LAN_USERS).\n"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": _html_headers(
                    body,
                    extra=[
                        (b"www-authenticate", b'Basic realm="LangConfig", charset="UTF-8"'),
                    ],
                ),
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _deny_unconfigured(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1011,
                    "reason": "LAN access misconfigured",
                }
            )
            return

        body = (
            b"LangConfig: LAN access is enabled but no credential is configured.\n"
            b"Refusing the request. Set LANGCONFIG_LAN_USERS (name:password,...) in the\n"
            b"server's .env and restart.\n"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": _html_headers(body),
            }
        )
        await send({"type": "http.response.body", "body": body})


def _html_headers(body: bytes, extra: list | None = None) -> list:
    headers = [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if extra:
        headers.extend(extra)
    return headers
