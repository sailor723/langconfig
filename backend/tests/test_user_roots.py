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


# ── the manager is scoped, and two people get different trees ───────────────

def test_the_app_manager_is_user_scoped(tmp_path, monkeypatch):
    """`user_scoping` defaults to True: forgetting it would silently un-isolate."""
    from services.workspace_manager import WorkspaceManager

    manager = WorkspaceManager(base_dir=str(tmp_path))
    assert manager.user_scoping is True
    assert manager.install_base_dir() == tmp_path.resolve()
    # No request context in a test → the install owner's tree (see subject_user_id).
    assert manager.user_base() == tmp_path.resolve() / "users" / str(user_roots.subject_user_id())


def test_two_users_resolve_different_agent_workspaces(tmp_path):
    """The same agent, opened by two people, must not share a directory."""
    from services.workspace_manager import WorkspaceManager

    class _Agent:
        id = 42
        workspace_path = None

    manager = WorkspaceManager(base_dir=str(tmp_path))
    seen = {}
    for user_id in (1, 2):
        token = set_current_user(
            UserContext(id=user_id, username=f"u{user_id}", role="member", via="session")
        )
        try:
            seen[user_id] = manager.get_agent_workspace(42)
        finally:
            reset_current_user(token)

    assert seen[1] != seen[2]
    assert seen[1] == tmp_path.resolve() / "users" / "1" / "agents" / "agent_42"
    assert seen[2] == tmp_path.resolve() / "users" / "2" / "agents" / "agent_42"
    # Both were created, and neither is inside the other.
    assert seen[1].is_dir() and seen[2].is_dir()
    assert not str(seen[1]).startswith(str(seen[2]))


# ── the database side of the boundary ──────────────────────────────────────

def test_owned_filters_rows_to_the_caller(db_session):
    """`workspace_scope.owned` is what keeps A's metadata out of B's queries."""
    from models.workspace_file import WorkspaceFile
    from services import workspace_scope

    token = set_current_user(UserContext(id=1, username="a", role="member", via="session"))
    try:
        sql = str(
            workspace_scope.owned(db_session.query(WorkspaceFile), WorkspaceFile, db_session)
            .statement.compile(compile_kwargs={"literal_binds": True})
        )
        assert "workspace_files.owner_id = 1" in sql
    finally:
        reset_current_user(token)


def test_owned_falls_back_to_unowned_rows_when_there_is_no_identity(db_session, monkeypatch):
    """No accounts at all: the install's own rows, exactly as before Slice 2."""
    from models.workspace_file import WorkspaceFile
    from services import workspace_scope

    monkeypatch.setattr(workspace_scope, "owner_id", lambda _db=None: None)
    sql = str(
        workspace_scope.owned(db_session.query(WorkspaceFile), WorkspaceFile, db_session)
        .statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "owner_id IS NULL" in sql


def test_same_owner_is_false_for_someone_elses_row():
    from services import workspace_scope

    class _Row:
        def __init__(self, owner):
            self.owner_id = owner

    token = set_current_user(UserContext(id=2, username="b", role="member", via="session"))
    try:
        assert workspace_scope.same_owner(_Row(2)) is True
        assert workspace_scope.same_owner(_Row(1)) is False
        assert workspace_scope.same_owner(_Row(None)) is False
    finally:
        reset_current_user(token)


# ── path validation lands in the caller's tree ─────────────────────────────

def test_path_validation_refuses_another_users_file(tmp_path):
    """A path copied out of someone else's file list must be useless here."""
    import pytest as _pytest
    from fastapi import HTTPException
    from api.workspace.files_routes import _validate_path_in_workspace
    from services.workspace_manager import WorkspaceManager

    manager = WorkspaceManager(base_dir=str(tmp_path))
    # alice's file exists; bob's tree exists too but holds nothing.
    alice_file = tmp_path / "users" / "1" / "report.md"
    alice_file.parent.mkdir(parents=True)
    alice_file.write_text("secret", encoding="utf-8")
    (tmp_path / "users" / "2").mkdir(parents=True)

    token = set_current_user(UserContext(id=2, username="bob", role="member", via="session"))
    try:
        with _pytest.raises(HTTPException) as denied:
            _validate_path_in_workspace("report.md", manager)
        assert denied.value.status_code == 404, "bob has no such file"

        with _pytest.raises(HTTPException) as traversal:
            _validate_path_in_workspace("../1/report.md", manager)
        assert traversal.value.status_code == 403, "walking into alice's tree is a traversal"
    finally:
        reset_current_user(token)

    # …and alice can read her own file, proving the block is about ownership.
    token = set_current_user(UserContext(id=1, username="alice", role="member", via="session"))
    try:
        assert _validate_path_in_workspace("report.md", manager) == alice_file.resolve()
    finally:
        reset_current_user(token)


def test_an_absolute_workspace_path_is_re_anchored_to_the_caller(tmp_path):
    """An agent configured with an absolute path must not hand its directory to
    everyone: inside the workspace it is re-anchored, outside it is left alone."""
    from services.workspace_manager import WorkspaceManager

    manager = WorkspaceManager(base_dir=str(tmp_path))

    class _Agent:
        id = 11
        workspace_path = str(tmp_path / "vault" / "agents" / "x")

    token = set_current_user(UserContext(id=5, username="e", role="member", via="session"))
    try:
        resolved = manager.resolve_agent_workspace(_Agent())
        assert resolved == (tmp_path / "users" / "5" / "vault" / "agents" / "x").resolve()

        # A path that already names someone else's tree is re-rooted, not nested.
        _Agent.workspace_path = str(tmp_path / "users" / "1" / "vault" / "y")
        assert manager.resolve_agent_workspace(_Agent()) == (
            tmp_path / "users" / "5" / "vault" / "y"
        ).resolve()

        # A path outside the workspace is the setter's own choice.
        _Agent.workspace_path = "/tmp/somewhere-else-entirely"
        assert str(manager.resolve_agent_workspace(_Agent())) == "/tmp/somewhere-else-entirely"
    finally:
        reset_current_user(token)


# ── conversations are private too (Slice 3 step 1) ─────────────────────────

def test_conversation_queries_filter_on_user_id(db_session):
    """`owned(..., column="user_id")` — the conversation tables carry `user_id`,
    not `owner_id`, and a filter that silently targeted the wrong column would
    either error or match nothing."""
    from models.deep_agent import ChatSession
    from services import workspace_scope

    token = set_current_user(UserContext(id=7, username="g", role="member", via="session"))
    try:
        sql = str(
            workspace_scope.owned(
                db_session.query(ChatSession), ChatSession, db_session, column="user_id"
            ).statement.compile(compile_kwargs={"literal_binds": True})
        )
        assert "chat_sessions.user_id = 7" in sql
    finally:
        reset_current_user(token)


def test_someone_elses_session_is_not_mine(db_session):
    from services import workspace_scope

    class _Session:
        user_id = 1

    token = set_current_user(UserContext(id=284, username="h", role="member", via="session"))
    try:
        assert workspace_scope.same_owner(_Session(), db_session, column="user_id") is False
    finally:
        reset_current_user(token)

    token = set_current_user(UserContext(id=1, username="i", role="member", via="session"))
    try:
        assert workspace_scope.same_owner(_Session(), db_session, column="user_id") is True
    finally:
        reset_current_user(token)


def test_every_conversation_has_an_author(db_session):
    """Migration 035 backfilled the history to the first admin; nothing is ownerless."""
    from sqlalchemy import text as _text

    admin = db_session.execute(
        _text("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    ).scalar()
    if admin is None:
        pytest.skip("no admin account")

    for table in ("chat_sessions", "conversation_archives"):
        total = db_session.execute(_text(f"SELECT count(*) FROM {table}")).scalar()
        if not total:
            continue
        unowned = db_session.execute(
            _text(f"SELECT count(*) FROM {table} WHERE user_id IS NULL")
        ).scalar()
        assert unowned == 0, f"{unowned} of {total} rows in {table} have no author"
