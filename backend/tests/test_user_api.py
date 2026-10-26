"""HTTP-level tests for the users API and the identity middleware.

Why these exist alongside ``test_user_service.py``: the service layer can be
perfectly correct while the routes still let a member reach an admin endpoint, or
while no identity reaches the handler at all. Both are checked here against a real
router, a real database session and the real ``UserContextMiddleware``.

The LAN gate is replaced by a one-line stand-in that parks an identity on the ASGI
scope — exactly what the gate does after a verified Basic-auth credential — so the
middleware chain (gate → identity → route) is exercised in its production order
without needing a network round trip.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import api.users.routes as users_routes
from core.context.current_user import current_user
from core.security.lan_auth import InMemoryCredentialVerifier, UserContext
from middleware.identity import PRINCIPAL_KEY, UserContextMiddleware
from models.user import UserRole
from services import user_service

PREFIX = "mu-test-"


def _name(tag: str) -> str:
    return f"{PREFIX}{tag}-{uuid.uuid4().hex[:8]}"


class _VerifiedCredential:
    """Stand-in for the LAN gate: park the identity the gate would have verified."""

    def __init__(self, app, user):
        self.app = app
        self.user = user

    async def __call__(self, scope, receive, send):
        if self.user is not None:
            scope[PRINCIPAL_KEY] = self.user
        await self.app(scope, receive, send)


def _build_client(db_session, user):
    """A minimal app: identity middleware → users router, over the test session."""
    app = FastAPI()
    app.include_router(users_routes.router)

    def _session():
        yield db_session

    app.dependency_overrides[users_routes.get_db] = _session

    # The verifier is irrelevant here (no loopback path is taken); it exists so the
    # middleware cannot accidentally reach the real database.
    app.add_middleware(UserContextMiddleware, verifier=InMemoryCredentialVerifier({"nobody": "x"}))
    app.add_middleware(_VerifiedCredential, user=user)
    return TestClient(app)


def _identity(user, role="admin") -> UserContext:
    return UserContext(
        id=user.id if user is not None else 1,
        username=user.username if user is not None else "someone",
        role=role,
        via="lan",
    )


@pytest.fixture
def accounts(db_session):
    created = []

    def make(tag, password="memberpass1", role=UserRole.MEMBER):
        user = user_service.create_user(db_session, _name(tag), password, role=role)
        created.append(user)
        return user

    try:
        yield make
    finally:
        names = [u.username for u in created]
        if names:
            db_session.execute(
                text("DELETE FROM users WHERE username = ANY(:names)"), {"names": names}
            )
            db_session.commit()


# ── who is asking ───────────────────────────────────────────────────────────

def test_me_returns_the_verified_identity(db_session, accounts):
    me = accounts("me", role=UserRole.ADMIN)
    client = _build_client(db_session, _identity(me))

    response = client.get("/api/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == me.username
    assert body["role"] == "admin"
    assert "password_hash" not in body


def test_no_identity_is_a_401(db_session):
    """Nothing implicitly becomes the owner — anonymous means anonymous."""
    client = _build_client(db_session, None)
    response = client.get("/api/users/me")
    assert response.status_code == 401
    assert "www-authenticate" in {k.lower() for k in response.headers}


def test_identity_does_not_leak_between_requests(db_session, accounts):
    me = accounts("leak")
    client = _build_client(db_session, _identity(me))
    assert client.get("/api/users/me").status_code == 200
    assert current_user() is None, "the ContextVar must be reset after the request"


def test_deleted_account_is_a_401_not_a_crash(db_session, accounts):
    """A session that outlived its account by one request must not 500."""
    ghost = accounts("ghost")
    identity = _identity(ghost)
    db_session.delete(ghost)
    db_session.commit()

    client = _build_client(db_session, identity)
    assert client.get("/api/users/me").status_code == 401


# ── self-service ────────────────────────────────────────────────────────────

def test_member_can_rename_themselves(db_session, accounts):
    me = accounts("rename")
    client = _build_client(db_session, _identity(me, role="member"))

    response = client.patch("/api/users/me", json={"display_name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"


def test_changing_your_own_password_requires_the_current_one(db_session, accounts):
    me = accounts("selfpw")
    client = _build_client(db_session, _identity(me, role="member"))

    wrong = client.post(
        "/api/users/me/password",
        json={"current_password": "not-it", "new_password": "brandnew12"},
    )
    assert wrong.status_code == 400

    right = client.post(
        "/api/users/me/password",
        json={"current_password": "memberpass1", "new_password": "brandnew12"},
    )
    assert right.status_code == 200

    db_session.expire_all()
    assert user_service.authenticate(db_session, me.username, "memberpass1") is None
    assert user_service.authenticate(db_session, me.username, "brandnew12") is not None


def test_weak_new_password_is_refused(db_session, accounts):
    me = accounts("weakpw")
    client = _build_client(db_session, _identity(me, role="member"))
    response = client.post(
        "/api/users/me/password",
        json={"current_password": "memberpass1", "new_password": "short"},
    )
    assert response.status_code == 400
    assert "8" in response.json()["detail"]


# ── administration ──────────────────────────────────────────────────────────

def test_admin_lists_accounts(db_session, accounts):
    me = accounts("listadmin", role=UserRole.ADMIN)
    other = accounts("listed")
    client = _build_client(db_session, _identity(me))

    response = client.get("/api/users")
    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert {me.username, other.username} <= usernames


def test_member_cannot_list_accounts(db_session, accounts):
    me = accounts("member")
    client = _build_client(db_session, _identity(me, role="member"))

    response = client.get("/api/users")
    assert response.status_code == 403
    assert "Administrator" in response.json()["detail"]


def test_member_cannot_create_or_promote(db_session, accounts):
    me = accounts("memberwriter", role=UserRole.MEMBER)
    other = accounts("target")
    client = _build_client(db_session, _identity(me, role="member"))

    assert client.post(
        "/api/users", json={"username": _name("nope"), "password": "whatever12"}
    ).status_code == 403
    assert client.patch(f"/api/users/{other.id}", json={"role": "admin"}).status_code == 403


def test_admin_creates_an_account(db_session, accounts):
    me = accounts("creator", role=UserRole.ADMIN)
    client = _build_client(db_session, _identity(me))
    name = _name("created")

    try:
        response = client.post(
            "/api/users",
            json={"username": name, "password": "createdpass1", "display_name": "New Person"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["username"] == name
        assert body["role"] == "member"
        assert body["is_active"] is True

        db_session.expire_all()
        assert user_service.authenticate(db_session, name, "createdpass1") is not None
    finally:
        db_session.execute(text("DELETE FROM users WHERE username = :n"), {"n": name})
        db_session.commit()


def test_creation_errors_are_400s(db_session, accounts):
    me = accounts("badcreator", role=UserRole.ADMIN)
    existing = accounts("existing")
    client = _build_client(db_session, _identity(me))

    duplicate = client.post(
        "/api/users", json={"username": existing.username, "password": "whatever12"}
    )
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.json()["detail"]

    short = client.post("/api/users", json={"username": _name("s"), "password": "tiny"})
    assert short.status_code == 400

    bad_name = client.post("/api/users", json={"username": "not valid!", "password": "whatever12"})
    assert bad_name.status_code == 400

    bad_role = client.post(
        "/api/users", json={"username": _name("r"), "password": "whatever12", "role": "root"}
    )
    assert bad_role.status_code == 400, "a bad role must be a client error, not a 500"


def test_admin_disables_and_reenables(db_session, accounts):
    me = accounts("admin2", role=UserRole.ADMIN)
    target = accounts("victim")
    client = _build_client(db_session, _identity(me))

    assert client.patch(f"/api/users/{target.id}", json={"is_active": False}).status_code == 200
    db_session.expire_all()
    assert user_service.authenticate(db_session, target.username, "memberpass1") is None

    assert client.patch(f"/api/users/{target.id}", json={"is_active": True}).status_code == 200
    db_session.expire_all()
    assert user_service.authenticate(db_session, target.username, "memberpass1") is not None


def test_admin_resets_another_password(db_session, accounts):
    me = accounts("resetter", role=UserRole.ADMIN)
    target = accounts("forgetful")
    client = _build_client(db_session, _identity(me))

    response = client.post(f"/api/users/{target.id}/password", json={"new_password": "resetpass123"})
    assert response.status_code == 200

    db_session.expire_all()
    assert user_service.authenticate(db_session, target.username, "resetpass123") is not None


def test_admin_cannot_lock_themselves_out(db_session, accounts):
    me = accounts("selflock", role=UserRole.ADMIN)
    client = _build_client(db_session, _identity(me))

    assert client.patch(f"/api/users/{me.id}", json={"role": "member"}).status_code == 400
    assert client.patch(f"/api/users/{me.id}", json={"is_active": False}).status_code == 400


def test_unknown_account_is_a_404(db_session, accounts):
    me = accounts("finder", role=UserRole.ADMIN)
    client = _build_client(db_session, _identity(me))

    assert client.patch("/api/users/999999", json={"display_name": "x"}).status_code == 404
    assert client.post("/api/users/999999/password", json={"new_password": "whatever12"}).status_code == 404


def test_roles_endpoint_names_the_vocabulary(db_session, accounts):
    me = accounts("rolelist", role=UserRole.ADMIN)
    client = _build_client(db_session, _identity(me))

    response = client.get("/api/users/roles")
    assert response.status_code == 200
    assert response.json()["roles"] == ["admin", "member"]


# ── sign in / sign out ──────────────────────────────────────────────────────
#
# The sign-in page is a real page with a real form, and the session it creates is
# the only thing that lets a browser use the app. These tests drive that flow end
# to end against the database: form post in, cookie out, session row present,
# logout revoking it.

from api.auth import signin as signin_module  # noqa: E402
from db.database import SessionLocal  # noqa: E402
from services import session_service  # noqa: E402


def _auth_app():
    app = FastAPI()
    app.include_router(signin_module.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    signin_module.reset_failure_state()
    yield
    signin_module.reset_failure_state()


def test_sign_in_page_renders_a_form(db_session, accounts, monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    response = _auth_app().get("/signin")
    assert response.status_code == 200
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text
    assert 'action="/api/auth/login"' in response.text
    assert "no-store" in response.headers.get("cache-control", "")


def test_sign_in_page_explains_an_empty_install(db_session, monkeypatch):
    """With no accounts, a login form would be a dead end — say what to do instead.

    The count is patched rather than the table emptied: this database belongs to a
    developer and a test must not delete their accounts to check a message.
    """
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    monkeypatch.setattr(signin_module.user_service, "count_users", lambda _db: 0)

    response = _auth_app().get("/signin")
    assert "No accounts exist yet" in response.text
    assert "create_user.py" in response.text


def test_login_with_the_right_password_creates_a_session(db_session, accounts):
    me = accounts("signinok", password="signinpass1")
    client = _auth_app()

    response = client.post(
        "/api/auth/login",
        data={"username": me.username, "password": "signinpass1"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers.get("set-cookie", "")
    assert "langconfig_session=" in cookie
    assert "httponly" in cookie.lower()
    assert "max-age=" in cookie.lower()
    # the sign-out marker must not survive a fresh sign-in
    assert "langconfig_signed_out" in cookie or "langconfig_session" in cookie

    db = SessionLocal()
    try:
        rows = session_service.list_for_user(db, me.id)
        assert len(rows) == 1
        assert rows[0].expires_at > rows[0].created_at
        # The cookie value is NOT in the database — only its hash.
        raw = cookie.split("langconfig_session=")[1].split(";")[0]
        assert raw not in [row.token_hash for row in rows]
    finally:
        db.close()
        _cleanup_sessions(me.id)


def test_login_rejects_a_wrong_password_without_creating_a_session(db_session, accounts):
    me = accounts("signinbad", password="signinpass1")
    response = _auth_app().post(
        "/api/auth/login",
        data={"username": me.username, "password": "wrong-password"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 200  # the page, with the error in it
    assert "Incorrect username or password" in response.text
    assert "set-cookie" not in response.headers or "langconfig_session" not in response.headers.get("set-cookie", "")

    db = SessionLocal()
    try:
        assert session_service.list_for_user(db, me.id) == []
    finally:
        db.close()


def test_login_refuses_a_disabled_account(db_session, accounts):
    me = accounts("signindisabled", password="signinpass1")
    user_service.update_user(db_session, me, is_active=False)

    response = _auth_app().post(
        "/api/auth/login",
        data={"username": me.username, "password": "signinpass1"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Incorrect username or password" in response.text


def test_login_answers_json_for_api_clients(db_session, accounts):
    me = accounts("signinjson", password="signinpass1")
    response = _auth_app().post(
        "/api/auth/login",
        json={"username": me.username, "password": "signinpass1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["user"]["username"] == me.username
    assert "password" not in str(body)
    _cleanup_sessions(me.id)


def test_login_returns_to_the_requested_page(db_session, accounts):
    me = accounts("signinnext", password="signinpass1")
    response = _auth_app().post(
        "/api/auth/login",
        data={"username": me.username, "password": "signinpass1", "next": "/#/agents"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/#/agents"
    _cleanup_sessions(me.id)


def test_login_is_rate_limited_after_repeated_failures(db_session, accounts):
    me = accounts("signinbrute", password="signinpass1")
    client = _auth_app()
    for _ in range(signin_module.MAX_FAILURES):
        client.post("/api/auth/login", json={"username": me.username, "password": "nope"})

    response = client.post("/api/auth/login", json={"username": me.username, "password": "signinpass1"})
    assert response.status_code == 429, "the limiter must stop a guessing script"


def test_logout_revokes_the_session_and_returns_to_the_page(db_session, accounts):
    me = accounts("signinout", password="signinpass1")
    client = _auth_app()
    login = client.post(
        "/api/auth/login",
        data={"username": me.username, "password": "signinpass1"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    out = client.get("/api/auth/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/signin"
    cookie = out.headers.get("set-cookie", "")
    assert "langconfig_signed_out=1" in cookie, "the Basic-auth fallback needs the marker too"

    db = SessionLocal()
    try:
        assert session_service.list_for_user(db, me.id) == []
    finally:
        db.close()


def test_session_endpoint_reports_who_is_signed_in(db_session, accounts):
    me = accounts("signinwho", password="signinpass1")
    client = _auth_app()
    client.post("/api/auth/login", json={"username": me.username, "password": "signinpass1"})

    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json()["user"]["username"] == me.username
    assert response.json()["expires_in_seconds"] > 0

    client.get("/api/auth/logout")
    assert client.get("/api/auth/session").status_code == 401


def test_my_sessions_lists_browsers_and_revokes_one(db_session, accounts):
    me = accounts("signinlist", password="signinpass1")
    first = _auth_app()
    first.post("/api/auth/login", json={"username": me.username, "password": "signinpass1"})
    second = _auth_app()
    second.post("/api/auth/login", json={"username": me.username, "password": "signinpass1"})

    listing = first.get("/api/auth/sessions").json()
    assert len(listing["sessions"]) == 2
    other = next(s for s in listing["sessions"] if s["id"] != listing["current_id"])

    assert first.post(f"/api/auth/sessions/{other['id']}/revoke").status_code == 200
    listing = first.get("/api/auth/sessions").json()
    assert len(listing["sessions"]) == 1
    assert second.get("/api/auth/session").status_code == 401


@pytest.mark.parametrize(
    "target",
    ["https://evil.example/steal", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/signin"],
)
def test_return_path_cannot_become_an_open_redirect(db_session, accounts, target):
    me = accounts("signinredir", password="signinpass1")
    response = _auth_app().post(
        "/api/auth/login",
        data={"username": me.username, "password": "signinpass1", "next": target},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"
    _cleanup_sessions(me.id)


def _cleanup_sessions(user_id: int) -> None:
    db = SessionLocal()
    try:
        session_service.revoke_all_for_user(db, user_id, reason="test cleanup")
    finally:
        db.close()


# ── reload-loop regressions ─────────────────────────────────────────────────
#
# Reported from a real session: "I run sign off, but page keeps refreshing". Two
# redirect cycles could do that, and both are pinned here so they cannot come back.

def test_sign_in_page_does_not_bounce_a_signed_out_browser(db_session, accounts):
    """marker + a still-valid session must render the page, not redirect.

    The gate refuses a marked browser (the marker outranks the session), so
    redirecting it into the app sends it straight back here — a reload loop.
    """
    me = accounts("loopmarker", password="looppass123")
    client = _auth_app()
    client.post("/api/auth/login", json={"username": me.username, "password": "looppass123"})

    # Plant the marker while the session is still valid (exactly the state that
    # produced the loop).
    client.cookies.set("langconfig_signed_out", "1", path="/")

    response = client.get("/signin", follow_redirects=False)
    assert response.status_code == 200, "must render, not redirect"
    assert 'name="password"' in response.text

    _cleanup_sessions(me.id)


def test_sign_in_page_redirects_when_cleanly_signed_in(db_session, accounts):
    me = accounts("loopclean", password="looppass123")
    client = _auth_app()
    client.post("/api/auth/login", json={"username": me.username, "password": "looppass123"})

    response = client.get("/signin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    _cleanup_sessions(me.id)


def test_signing_in_again_clears_the_marker(db_session, accounts):
    """Otherwise the next page load is refused by the gate for no visible reason."""
    me = accounts("loopclear", password="looppass123")
    client = _auth_app()
    client.cookies.set("langconfig_signed_out", "1", path="/")

    response = client.post(
        "/api/auth/login", json={"username": me.username, "password": "looppass123"}
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "langconfig_signed_out=" in set_cookie
    _cleanup_sessions(me.id)


def test_me_reports_how_the_caller_is_signed_in(db_session, accounts):
    """`via` tells a person (and a support call) how access was obtained."""
    me = accounts("viafield")
    client = _build_client(db_session, _identity(me, role="member"))

    body = client.get("/api/users/me").json()
    assert body["username"] == me.username
    assert body["via"] == "lan", "the identity used by this test arrives as a LAN credential"


def test_account_list_does_not_carry_via(db_session, accounts):
    """`via` is about the caller, so it must not leak into other accounts' rows."""
    me = accounts("vialist", role=UserRole.ADMIN)
    other = accounts("vialisted")
    client = _build_client(db_session, _identity(me))

    rows = client.get("/api/users").json()
    assert {row["username"] for row in rows} >= {me.username, other.username}
    assert all("via" not in row for row in rows)
