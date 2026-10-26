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


# ── sign out ────────────────────────────────────────────────────────────────
#
# The marker cookie is the one piece of state an otherwise stateless gate keeps:
# it is what makes "Sign out" mean anything under HTTP Basic.

def test_sign_out_sets_a_session_cookie_and_explains_itself(db_session, monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    app = FastAPI()
    from api.auth.signout import router as signout_router

    app.include_router(signout_router)
    client = TestClient(app)

    response = client.get("/api/auth/sign-out")
    assert response.status_code == 200
    assert "Signed out" in response.text
    assert "/api/auth/sign-in" in response.text

    cookie = response.headers.get("set-cookie", "")
    assert "langconfig_signed_out=1" in cookie
    assert "httponly" in cookie.lower()
    # A session cookie: it must expire with the browser, like the credential it hides.
    assert "max-age" not in cookie.lower()


def test_sign_out_says_so_when_the_gate_is_off(monkeypatch):
    monkeypatch.delenv("LANGCONFIG_LAN_ACCESS", raising=False)
    app = FastAPI()
    from api.auth.signout import router as signout_router

    app.include_router(signout_router)
    response = TestClient(app).get("/api/auth/sign-out")
    assert response.status_code == 200
    assert "LAN access is off" in response.text
    assert "set-cookie" not in response.headers


def test_sign_in_clears_the_marker_and_redirects_home(monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    app = FastAPI()
    from api.auth.signout import router as signout_router

    app.include_router(signout_router)
    response = TestClient(app).get("/api/auth/sign-in", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers.get("set-cookie", "")
    assert "langconfig_signed_out=" in cookie
    assert 'Max-Age=0' in cookie or 'max-age=0' in cookie.lower()


@pytest.mark.parametrize(
    "target",
    ["https://evil.example/steal", "//evil.example", "/\\evil.example", "javascript:alert(1)"],
)
def test_sign_in_refuses_to_render_someone_elses_page(monkeypatch, target):
    """An unvalidated `next` is an open redirect on a freshly authenticated browser."""
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    app = FastAPI()
    from api.auth.signout import router as signout_router

    app.include_router(signout_router)
    response = TestClient(app).get("/api/auth/sign-in", params={"next": target}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_sign_in_keeps_a_same_origin_path(monkeypatch):
    monkeypatch.setenv("LANGCONFIG_LAN_ACCESS", "on")
    app = FastAPI()
    from api.auth.signout import router as signout_router

    app.include_router(signout_router)
    response = TestClient(app).get(
        "/api/auth/sign-in", params={"next": "/#/agents"}, follow_redirects=False
    )
    assert response.headers["location"] == "/#/agents"
