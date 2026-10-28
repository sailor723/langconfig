# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Per-account workspace root (migration 038, ``users.workspace_path``).

The rule before this slice was one line: a person's files live at
``<install root>/users/<id>``, derived from the id and never stored. This adds an
optional override so one account can put its tree on another disk.

What is pinned here:

1. **NULL keeps the convention.** An install that never sets a path behaves
   exactly as before — no directory moves, no migration of existing files.
2. **An override moves the whole tree.** Everything hangs off ``root_for``, so
   vaults and agent workspaces follow without knowing about the column.
3. **Bad values are refused, not repaired.** A relative path, or a path that
   would sit inside / contain another account's tree, is an error at the API edge
   — resolving those silently is how one person ends up writing into another's
   files.
4. **The cache cannot go stale.** The resolver caches one entry per account, so
   the write path must invalidate it in the same request.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from db.database import SessionLocal, get_db
from services import user_roots

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test",
)
SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

ALICE = 284
BOB = 1070


@pytest.fixture(scope="module")
def Session():
    engine = create_engine(SYNC_URL, pool_pre_ping=True)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield maker
    engine.dispose()


@pytest.fixture(autouse=True)
def seed_accounts(Session):
    """The test database has no accounts; these tests need three rows to exist.

    They are inserted (not upserted over a real fixture) exactly once per test and
    removed by the autouse cleanup below, so the module stays independent of
    whatever the rest of the suite left behind.
    """
    db = Session()
    try:
        for uid, name in ((1, "owner"), (ALICE, "alice"), (BOB, "bob")):
            db.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, role, is_active, "
                    "created_at, updated_at) VALUES (:i, :u, 'x', 'member', true, now(), now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"i": uid, "u": name},
            )
        db.commit()
    finally:
        db.close()
    yield
    db = Session()
    try:
        db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [1, ALICE, BOB]})
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def point_at_the_test_database(Session, monkeypatch):
    """Make the module's implicit sessions land on the test database.

    ``services.user_roots`` opens ``db.database.SessionLocal`` itself (a path
    resolver must not need a session handed to it), so the only seam is the
    factory. Without this the resolver would read — and the API would write —
    the real install's ``users`` table.
    """
    monkeypatch.setattr("db.database.SessionLocal", Session)
    user_roots.invalidate_root_override()


@pytest.fixture
def db(Session):
    s = Session()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture(autouse=True)
def clean_overrides(db):
    """Every test starts from "no account has an override" and an empty cache.

    The test database is create_all-only (migrations are not replayed there), so
    a column added by migration 038 has to be brought in line here — the same
    thing the settings tests do for the tables they touch.
    """
    db.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS workspace_path VARCHAR(1024)"
    ))
    db.execute(text("UPDATE users SET workspace_path = NULL"))
    db.commit()
    user_roots.invalidate_root_override()
    yield
    db.execute(text("UPDATE users SET workspace_path = NULL"))
    db.commit()
    user_roots.invalidate_root_override()


# ── the convention still wins when nothing is set ────────────────────────────

def test_unset_means_the_conventional_tree(db):
    assert db.execute(
        text("SELECT workspace_path FROM users WHERE id = :i"), {"i": ALICE}
    ).scalar() is None
    assert user_roots.root_for(ALICE) == user_roots.default_root_for(ALICE)


def test_there_is_no_root_without_an_account():
    assert user_roots.root_for(None) == user_roots.install_root()


# ── an override moves the tree, and the cache follows ────────────────────────

def test_override_becomes_the_root(db, tmp_path):
    target = tmp_path / "alice-tree"
    db.execute(
        text("UPDATE users SET workspace_path = :p WHERE id = :i"),
        {"p": str(target), "i": ALICE},
    )
    db.commit()
    user_roots.invalidate_root_override(ALICE)

    assert user_roots.root_for(ALICE) == target
    # …and it does not disturb anyone else.
    assert user_roots.root_for(BOB) == user_roots.default_root_for(BOB)


def test_invalidation_is_visible_immediately(db, tmp_path):
    """The resolver caches per account; a write must drop that entry."""
    assert user_roots.root_for(ALICE) == user_roots.default_root_for(ALICE)  # cache filled

    target = tmp_path / "moved"
    db.execute(
        text("UPDATE users SET workspace_path = :p WHERE id = :i"),
        {"p": str(target), "i": ALICE},
    )
    db.commit()

    # Without invalidation the old tree would still be served.
    assert user_roots.root_for(ALICE) == user_roots.default_root_for(ALICE)
    user_roots.invalidate_root_override(ALICE)
    assert user_roots.root_for(ALICE) == target


def test_a_relative_path_is_ignored_at_read_time(db):
    """Defence in depth: the API refuses relative paths, but a hand-edited row
    must not silently become a directory under the server's CWD."""
    db.execute(
        text("UPDATE users SET workspace_path = 'relative/dir' WHERE id = :i"), {"i": ALICE}
    )
    db.commit()
    user_roots.invalidate_root_override(ALICE)
    assert user_roots.root_for(ALICE) == user_roots.default_root_for(ALICE)


# ── validation ──────────────────────────────────────────────────────────────

def test_validator_accepts_an_absolute_path(db, tmp_path):
    got = user_roots.validate_workspace_path(db, ALICE, str(tmp_path / "ok"))
    assert got == str((tmp_path / "ok").resolve())


def test_validator_clears_on_empty(db):
    assert user_roots.validate_workspace_path(db, ALICE, "") is None
    assert user_roots.validate_workspace_path(db, ALICE, None) is None


def test_validator_rejects_a_relative_path(db):
    with pytest.raises(ValueError, match="absolute"):
        user_roots.validate_workspace_path(db, ALICE, "some/where")


def test_validator_rejects_another_accounts_tree(db, tmp_path):
    bob_tree = tmp_path / "bob-tree"
    db.execute(
        text("UPDATE users SET workspace_path = :p WHERE id = :i"),
        {"p": str(bob_tree), "i": BOB},
    )
    db.commit()
    user_roots.invalidate_root_override()

    with pytest.raises(ValueError, match="already user"):
        user_roots.validate_workspace_path(db, ALICE, str(bob_tree))
    with pytest.raises(ValueError, match="inside user"):
        user_roots.validate_workspace_path(db, ALICE, str(bob_tree / "nested"))
    with pytest.raises(ValueError, match="contain user"):
        user_roots.validate_workspace_path(db, ALICE, str(tmp_path))


def test_validator_rejects_the_filesystem_root(db):
    with pytest.raises(ValueError, match="filesystem root"):
        user_roots.validate_workspace_path(db, ALICE, "/")


def test_validator_rejects_the_install_root(db):
    with pytest.raises(ValueError, match="install workspace root"):
        user_roots.validate_workspace_path(db, ALICE, str(user_roots.install_root()))


def test_validator_rejects_a_default_tree_of_another_account(db):
    with pytest.raises(ValueError, match="already user"):
        user_roots.validate_workspace_path(
            db, ALICE, str(user_roots.default_root_for(BOB))
        )


# ── the API surface ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from api.users.routes import router as users_router
    from core.context.current_user import UserContext, reset_current_user, set_current_user
    from core.security.passwords import hash_password  # noqa: F401 — module stays importable

    app = FastAPI()

    @app.middleware("http")
    async def _identity(request, call_next):
        uid = int(request.headers.get("x-test-uid", "1"))
        role = request.headers.get("x-test-role", "admin")
        token = set_current_user(UserContext(id=uid, username=f"u{uid}", role=role))
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)

    from db.database import SessionLocal as _SessionLocal  # patched to the test DB

    def _db():
        sess = _SessionLocal()
        try:
            yield sess
        finally:
            sess.close()

    app.include_router(users_router)
    app.dependency_overrides[get_db] = _db

    import services.user_service as us

    # require_user/require_admin read the ContextVar; nothing else to override.
    assert us is not None
    return TestClient(app)


def test_the_api_sets_and_clears_the_override(client, db, tmp_path):
    target = tmp_path / "via-api"

    res = client.patch(
        f"/api/users/{ALICE}",
        json={"workspace_path": str(target)},
    )
    assert res.status_code == 200, res.text
    assert res.json()["workspace_path"] == str(target.resolve())
    assert user_roots.root_for(ALICE) == target.resolve()

    cleared = client.patch(f"/api/users/{ALICE}", json={"workspace_path": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["workspace_path"] is None
    assert user_roots.root_for(ALICE) == user_roots.default_root_for(ALICE)


def test_the_api_refuses_a_relative_path(client):
    res = client.patch(f"/api/users/{ALICE}", json={"workspace_path": "nope/relative"})
    assert res.status_code == 400
    assert "absolute" in res.json()["detail"]


def test_leaving_the_field_out_does_not_touch_it(client, db, tmp_path):
    client.patch(f"/api/users/{ALICE}", json={"workspace_path": str(tmp_path / "keep")})
    before = db.execute(
        text("SELECT workspace_path FROM users WHERE id = :i"), {"i": ALICE}
    ).scalar()
    res = client.patch(f"/api/users/{ALICE}", json={"display_name": "Alice"})
    assert res.status_code == 200, res.text
    after = db.execute(
        text("SELECT workspace_path FROM users WHERE id = :i"), {"i": ALICE}
    ).scalar()
    assert after == before


def test_me_reports_the_override(client, db, tmp_path):
    target = tmp_path / "mine"
    client.patch("/api/users/me", json={"workspace_path": str(target)},
                 headers={"x-test-uid": str(ALICE), "x-test-role": "member"})
    body = client.get("/api/users/me", headers={"x-test-uid": str(ALICE)}).json()
    assert body["workspace_path"] == str(target.resolve())
