"""Tests for the LAN access guard (backend/middleware/lan_guard.py).

The guard is the only thing standing between a 0.0.0.0-bound, unauthenticated
code-execution surface and the rest of the network, so its defaults are tested
as carefully as its happy path: "off" must stay off, and "on but misconfigured"
must fail closed rather than open.

Pure ASGI, no app fixtures — these tests exercise the gate in isolation by
hand-building scopes.

Credentials themselves now live in the ``users`` table, so the gate delegates to
a ``CredentialVerifier``. The autouse fixture below swaps in a verifier that reads
the same ``LANGCONFIG_LAN_*`` environment the tests set, which keeps every
assertion here about the *gate* (challenge, fail closed, loopback, bypass,
websocket close) rather than about where a password is stored. Database-backed
verification is covered by ``test_user_service.py``.
"""

import asyncio
import base64

import pytest

import middleware.lan_guard as lan_guard
from core.security.lan_auth import InMemoryCredentialVerifier
from middleware.lan_guard import (
    LanGuardMiddleware,
    _is_loopback,
    lan_access_enabled,
    parse_lan_users,
)


class _EnvVerifier:
    """A verifier over the ``LANGCONFIG_LAN_*`` fixtures, re-read on every call.

    Re-read rather than snapshotted because several tests change the environment
    mid-test (e.g. removing one person's credential and asserting the rest still
    work). The gate caches the verifier *object*, never the credentials, so this
    stays correct without the gate knowing anything about tests.
    """

    @staticmethod
    def _current() -> InMemoryCredentialVerifier:
        from core.security.lan_auth import parse_env_credentials

        credentials, _problems = parse_env_credentials()
        return InMemoryCredentialVerifier(dict(credentials))

    def verify(self, username, password):
        return self._current().verify(username, password)

    def owner(self):
        return self._current().owner()


@pytest.fixture(autouse=True)
def _env_backed_verifier(monkeypatch):
    """Verify against the fixtures instead of the ``users`` table."""
    monkeypatch.setattr(lan_guard, "get_default_verifier", _EnvVerifier, raising=True)


PASSWORD = "correct horse battery staple"
USER = "langconfig"


def _run(coro):
    return asyncio.run(coro)


class _Downstream:
    """Stand-in for the real app: records whether it was reached."""

    def __init__(self, status: int = 200):
        self.called = False
        self.status = status

    async def __call__(self, scope, receive, send):
        self.called = True
        if scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
            return
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _call(middleware, *, client=("192.168.1.50", 51000), kind="http", path="/api/agents",
                headers=()):
    scope = {
        "type": kind,
        "path": path,
        "method": "GET",
        "headers": list(headers),
        "client": client,
        "query_string": b"",
    }
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    await middleware(scope, receive, send)
    return sent


def _basic(user: str, password: str) -> tuple:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return (b"authorization", f"Basic {token}".encode())


@pytest.fixture(autouse=True)
def _isolate_lan_env(monkeypatch):
    """Start every test from "no LAN config", never from the developer's .env.

    The backend loads the repo's .env on import, so a real
    LANGCONFIG_LAN_USERS sitting in it would leak into this process and quietly
    change what these assertions mean — a fail-closed test would find a
    configured gate and stop testing the fail-closed path at all. Autouse so no
    individual test has to remember.
    """
    for var in (
        "LANGCONFIG_LAN_ACCESS",
        "LANGCONFIG_LAN_USERS",
        "LANGCONFIG_LAN_USER",
        "LANGCONFIG_LAN_PASSWORD",
        "LANGCONFIG_LAN_BYPASS_PATHS",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def lan_off(monkeypatch):
    monkeypatch.delenv("LANGCONFIG_LAN_ACCESS", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_PASSWORD", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_USERS", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_BYPASS_PATHS", raising=False)


@pytest.fixture
def lan_on(monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    monkeypatch.setenv("LANGCONFIG_LAN_USER", USER)
    monkeypatch.setenv("LANGCONFIG_LAN_PASSWORD", PASSWORD)
    monkeypatch.delenv("LANGCONFIG_LAN_USERS", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_BYPASS_PATHS", raising=False)


@pytest.fixture
def lan_multi(monkeypatch):
    """Three people, three credentials — the arrangement this was extended for."""
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    monkeypatch.setenv(
        "LANGCONFIG_LAN_USERS",
        f"alice:{PASSWORD}, bob:bob-secret, carol:carol-secret",
    )
    monkeypatch.delenv("LANGCONFIG_LAN_USER", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_PASSWORD", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_BYPASS_PATHS", raising=False)


# ── defaults ────────────────────────────────────────────────────────────────

def test_disabled_by_default(lan_off):
    """No flag in .env means no behaviour change — this must never gate silently."""
    assert lan_access_enabled() is False
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream)))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_unknown_flag_values_stay_off(monkeypatch):
    for value in ("", "0", "false", "off", "no", "maybe"):
        monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", value)
        assert lan_access_enabled() is False


# ── fail closed ─────────────────────────────────────────────────────────────

def test_enabled_without_password_fails_closed(monkeypatch):
    """A gate with no key must refuse, not open. This is the important one."""
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    monkeypatch.delenv("LANGCONFIG_LAN_PASSWORD", raising=False)
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream)))
    assert downstream.called is False
    assert sent[0]["status"] == 503


def test_enabled_with_empty_password_fails_closed(monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    monkeypatch.setenv("LANGCONFIG_LAN_PASSWORD", "   ")
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream)))
    # Whitespace-only is a password technically, but the far more likely intent
    # is an unfinished .env — treat as configured and require it exactly.
    assert downstream.called is False
    assert sent[0]["status"] in (401, 503)


# ── authentication ──────────────────────────────────────────────────────────

def test_network_request_without_credentials_is_challenged(lan_on):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream)))
    assert downstream.called is False
    assert sent[0]["status"] == 401
    headers = dict(sent[0]["headers"])
    assert b"www-authenticate" in headers
    assert b"Basic" in headers[b"www-authenticate"]


def test_network_request_with_correct_credentials_passes(lan_on):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic(USER, PASSWORD)]))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_wrong_password_is_rejected(lan_on):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic(USER, "wrong")]))
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_wrong_username_is_rejected(lan_on):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic("someone", PASSWORD)]))
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_malformed_authorization_header_is_rejected(lan_on):
    for value in (b"", b"Bearer abc", b"Basic", b"Basic !!!not-base64!!!", b"Basic bm9jb2xvbg=="):
        downstream = _Downstream()
        sent = _run(_call(LanGuardMiddleware(downstream), headers=[(b"authorization", value)]))
        assert downstream.called is False, value
        assert sent[0]["status"] == 401, value


# ── loopback exemption ──────────────────────────────────────────────────────

@pytest.mark.parametrize("client", [("127.0.0.1", 41000), ("::1", 41000), ("127.0.0.2", 41000), None])
def test_loopback_is_exempt(lan_on, client):
    """Local dev, the Vite proxy and the test suite must keep working unauthenticated."""
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), client=client))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_forwarded_ip_header_does_not_grant_loopback(lan_on):
    """Only the real source address counts — a spoofed header must not open the gate."""
    downstream = _Downstream()
    sent = _run(
        _call(
            LanGuardMiddleware(downstream),
            client=("192.168.1.50", 51000),
            headers=[(b"x-forwarded-for", b"127.0.0.1"), (b"host", b"localhost:8765")],
        )
    )
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_is_loopback_helper():
    assert _is_loopback({"client": ("127.0.0.1", 1)}) is True
    assert _is_loopback({"client": ("::1", 1)}) is True
    assert _is_loopback({"client": ("127.0.0.9", 1)}) is True
    assert _is_loopback({"client": ("192.168.1.50", 1)}) is False
    assert _is_loopback({"client": ("10.0.0.5", 1)}) is False


# ── websockets ──────────────────────────────────────────────────────────────

def test_websocket_without_credentials_is_closed(lan_on):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), kind="websocket"))
    assert downstream.called is False
    assert sent[0]["type"] == "websocket.close"
    assert sent[0]["code"] == 1008


def test_websocket_with_credentials_is_accepted(lan_on):
    downstream = _Downstream()
    sent = _run(
        _call(LanGuardMiddleware(downstream), kind="websocket", headers=[_basic(USER, PASSWORD)])
    )
    assert downstream.called is True
    assert sent[0]["type"] == "websocket.accept"


# ── bypass prefixes ─────────────────────────────────────────────────────────

def test_bypass_prefix_skips_auth(monkeypatch, lan_on):
    monkeypatch.setenv("LANGCONFIG_LAN_BYPASS_PATHS", "/api/webhooks/")
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), path="/api/webhooks/google"))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_bypass_prefix_does_not_match_other_paths(monkeypatch, lan_on):
    monkeypatch.setenv("LANGCONFIG_LAN_BYPASS_PATHS", "/api/webhooks/")
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), path="/api/workflows/1/execute"))
    assert downstream.called is False
    assert sent[0]["status"] == 401


# ── multiple people, one credential each ────────────────────────────────────

@pytest.mark.parametrize("user,password", [
    ("alice", PASSWORD),
    ("bob", "bob-secret"),
    ("carol", "carol-secret"),
])
def test_each_person_can_sign_in(lan_multi, user, password):
    """Every configured credential works — one password per person, not one shared."""
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic(user, password)]))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_password_from_another_person_is_rejected(lan_multi):
    """alice's name with bob's password must fail — this is what makes revocation real."""
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic("alice", "bob-secret")]))
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_unknown_user_is_rejected(lan_multi):
    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic("mallory", PASSWORD)]))
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_removing_one_person_leaves_the_others_working(monkeypatch, lan_multi):
    """The point of per-person credentials: drop bob, tell nobody else."""
    monkeypatch.setenv("LANGCONFIG_LAN_USERS", f"alice:{PASSWORD},carol:carol-secret")

    bob = _Downstream()
    _run(_call(LanGuardMiddleware(bob), headers=[_basic("bob", "bob-secret")]))
    assert bob.called is False

    for user, password in (("alice", PASSWORD), ("carol", "carol-secret")):
        downstream = _Downstream()
        sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic(user, password)]))
        assert downstream.called is True, user
        assert sent[0]["status"] == 200


def test_passwords_may_contain_a_colon(monkeypatch, lan_multi):
    """Only the first colon separates, so generated passwords with ':' still work."""
    assert parse_lan_users()[0]["alice"] == PASSWORD

    monkeypatch.setenv("LANGCONFIG_LAN_USERS", "dave:a:b:c")
    accounts, problems = parse_lan_users()
    assert accounts == {"dave": "a:b:c"}
    assert problems == []


def test_malformed_entries_are_dropped_and_reported(monkeypatch, lan_multi):
    """A bad entry must not become a blank-password account, and must be reported."""
    monkeypatch.setenv(
        "LANGCONFIG_LAN_USERS",
        "alice:good, broken-no-colon, :missing-name, empty-password:",
    )
    accounts, problems = parse_lan_users()
    assert accounts == {"alice": "good"}
    assert len(problems) == 3

    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic("broken-no-colon", "")]))
    assert downstream.called is False
    assert sent[0]["status"] == 401


def test_wholly_invalid_entries_leave_no_account_and_fail_closed(monkeypatch, lan_multi):
    """Nothing usable is configured, so nothing gets in — via either door.

    Two different refusals, deliberately: no credential at all means "this install
    has no accounts" (503, with the fix in the body), while a presented credential
    on an empty user list is an ordinary failed login (401). Both routes must
    refuse; neither may fall open.
    """
    monkeypatch.setenv("LANGCONFIG_LAN_USERS", "nonsense, also-nonsense")

    silent = _Downstream()
    sent = _run(_call(LanGuardMiddleware(silent)))
    assert silent.called is False
    assert sent[0]["status"] == 503

    claiming = _Downstream()
    sent = _run(_call(LanGuardMiddleware(claiming), headers=[_basic("nonsense", "")]))
    assert claiming.called is False
    assert sent[0]["status"] == 401


def test_legacy_single_credential_still_works(lan_on):
    """An existing .env with USER/PASSWORD keeps working — no forced migration."""
    accounts, problems = parse_lan_users()
    assert accounts == {USER: PASSWORD}
    assert problems == []

    downstream = _Downstream()
    sent = _run(_call(LanGuardMiddleware(downstream), headers=[_basic(USER, PASSWORD)]))
    assert downstream.called is True
    assert sent[0]["status"] == 200


def test_users_takes_precedence_over_legacy_pair(monkeypatch, lan_on):
    monkeypatch.setenv("LANGCONFIG_LAN_USERS", "alice:alice-secret")
    accounts, _ = parse_lan_users()
    assert accounts == {"alice": "alice-secret"}

    legacy = _Downstream()
    _run(_call(LanGuardMiddleware(legacy), headers=[_basic(USER, PASSWORD)]))
    assert legacy.called is False


def test_denial_log_names_the_claimed_user(lan_multi, caplog):
    """With several people, "someone was refused" is not enough — say who tried."""
    import logging
    with caplog.at_level(logging.WARNING, logger="middleware.lan_guard"):
        _run(_call(LanGuardMiddleware(_Downstream()), headers=[_basic("mallory", "nope")]))
    assert any("mallory" in record.getMessage() for record in caplog.records)


def test_claimed_username_is_sanitized(lan_multi):
    """The username comes from the request, so it must not reach the log raw."""
    from middleware.lan_guard import _attempted_username

    payload = "evil\nFAKE LOG LINE\x00" + "A" * 200
    token = base64.b64encode(f"{payload}:pw".encode()).decode().encode()
    scope = {"type": "http", "path": "/", "headers": [(b"authorization", b"Basic " + token)]}

    result = _attempted_username(scope)
    assert "\n" not in result
    assert "\x00" not in result
    assert len(result) <= 64
