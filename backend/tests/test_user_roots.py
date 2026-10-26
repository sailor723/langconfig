"""Per-user file roots and ownership (Slice 2, step 1).

The resolver decides *where* files go and the schema decides *whose* they are. Both
are tested here before any service starts using them, because getting either wrong
means files land in a tree nobody looks in — silently, and only noticed when someone
asks where their report went.
"""

import uuid

import pytest
from sqlalchemy import text

from core.context.current_user import reset_current_user, set_current_user
from core.security.lan_auth import UserContext
from services import user_roots


# ── layout ──────────────────────────────────────────────────────────────────

def test_root_for_is_user_first():
    """`users/<id>/<vault>/…`: the person above the project, so a tree is movable."""
    root = user_roots.root_for(7, root="/tmp/ws")
    assert root.as_posix() == "/tmp/ws/users/7"


def test_no_user_means_the_flat_legacy_layout():
    """An install with no accounts must not gain a pointless directory level."""
    assert user_roots.root_for(None, root="/tmp/ws").as_posix() == "/tmp/ws"


def test_users_dir_is_the_parent_of_every_private_tree():
    assert user_roots.users_dir("/tmp/ws").as_posix() == "/tmp/ws/users"


def test_resolving_a_path_never_creates_it(tmp_path):
    """A read path must not conjure an empty tree (or hide a typo)."""
    root = user_roots.root_for(42, root=str(tmp_path))
    assert not root.exists()


def test_two_users_do_not_share_a_tree():
    alice = user_roots.root_for(1, root="/tmp/ws")
    bob = user_roots.root_for(2, root="/tmp/ws")
    assert alice != bob
    assert not str(alice).startswith(str(bob) + "/")


# ── identity resolution ─────────────────────────────────────────────────────

def test_request_identity_wins(db_session):
    token = set_current_user(UserContext(id=999, username="req", role="member", via="session"))
    try:
        assert user_roots.subject_user_id(db_session) == 999
    finally:
        reset_current_user(token)


def test_without_a_request_the_owner_is_used(db_session):
    """Background work has no identity; it must land where the owner can find it."""
    owner = db_session.execute(
        text("SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1")
    ).scalar()
    if owner is None:
        pytest.skip("needs an admin account")

    assert user_roots.subject_user_id(db_session) == owner


def test_describe_reports_scope_without_touching_disk(tmp_path):
    summary = user_roots.describe(5, root=str(tmp_path))
    assert summary["user_id"] == 5
    assert summary["scoped"] is True
    assert summary["exists"] is False


# ── ownership in the schema ─────────────────────────────────────────────────

@pytest.fixture
def owner(db_session):
    """Two throwaway accounts, so ownership can be told apart."""
    from models.user import UserRole
    from services import user_service

    created = []
    for tag in ("a", "b"):
        user = user_service.create_user(
            db_session, f"mu-test-own-{tag}-{uuid.uuid4().hex[:8]}", "ownerpass12",
            role=UserRole.MEMBER,
        )
        created.append(user)
    try:
        yield created
    finally:
        ids = [u.id for u in created]
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM workspace_files WHERE owner_id = ANY(:ids)"), {"ids": ids}
        )
        db_session.execute(
            text("DELETE FROM storage_objects WHERE owner_id = ANY(:ids)"), {"ids": ids}
        )
        db_session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
        db_session.commit()


def test_two_users_may_hold_the_same_relative_path(db_session, owner):
    """The old global UNIQUE made "notes.md" impossible for the second person."""
    a, b = owner
    for user in (a, b):
        db_session.execute(
            text("INSERT INTO workspace_files (filename, file_path, owner_id) "
                 "VALUES ('notes.md', 'vault/notes.md', :o)"),
            {"o": user.id},
        )
    db_session.commit()

    paths = db_session.execute(
        text("SELECT owner_id, file_path FROM workspace_files "
             "WHERE file_path = 'vault/notes.md' AND owner_id = ANY(:ids) ORDER BY owner_id"),
        {"ids": [a.id, b.id]},
    ).all()
    assert [row[0] for row in paths] == [a.id, b.id]


def test_storage_keys_are_scoped_the_same_way(db_session, owner):
    a, b = owner
    for user in (a, b):
        db_session.execute(
            text("INSERT INTO storage_objects (key, content, size_bytes, owner_id) "
                 "VALUES ('reports/q1.md', ''::bytea, 0, :o)"),
            {"o": user.id},
        )
    db_session.commit()

    count = db_session.execute(
        text("SELECT count(*) FROM storage_objects "
             "WHERE key = 'reports/q1.md' AND owner_id = ANY(:ids)"),
        {"ids": [a.id, b.id]},
    ).scalar()
    assert count == 2


def test_existing_rows_were_adopted_by_the_first_admin(db_session):
    """Migration 034 backfilled every pre-existing row so nothing became ownerless.

    This is the state after the migration on a real install; a row with `owner_id`
    NULL now would be one written with no accounts at all.
    """
    unowned = db_session.execute(
        text("SELECT count(*) FROM workspace_files WHERE owner_id IS NULL")
    ).scalar()
    total = db_session.execute(text("SELECT count(*) FROM workspace_files")).scalar()
    admin = db_session.execute(
        text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    ).scalar()

    if admin is None or total == 0:
        pytest.skip("no accounts or no files on this install")
    assert unowned == 0, f"{unowned} of {total} file rows have no owner"
