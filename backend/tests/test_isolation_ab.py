"""Two accounts, one install: the boundaries from both sides.

These are the checks a reviewer would actually ask for — A writes something, B cannot
see it, find it, download it, resume it, or reach it from a shell — plus the deliberate
exception: both still share the knowledge base.

Written against the services rather than HTTP so it runs in a second and needs no server;
`scripts/verify_isolation.sh` is the HTTP twin used after a deploy.
"""

import uuid

import pytest
from sqlalchemy import text

from core.context.current_user import reset_current_user, set_current_user
from core.security.lan_auth import UserContext
from models.user import UserRole
from services import user_roots, user_service, workspace_scope
from services.workspace_manager import WorkspaceManager

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.fixture
def pair(db_session, tmp_path):
    """Two accounts and a private install root, so nothing touches the real workspace."""
    created = []
    for tag in ("a", "b"):
        created.append(user_service.create_user(
            db_session, f"mu-test-ab-{tag}-{uuid.uuid4().hex[:8]}", "abpass12345",
            role=UserRole.MEMBER,
        ))
    try:
        yield created[0], created[1], tmp_path
    finally:
        ids = [u.id for u in created]
        db_session.rollback()
        db_session.execute(text("DELETE FROM chat_sessions WHERE user_id = ANY(:i)"), {"i": ids})
        db_session.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids})
        db_session.commit()


def _as(user_id):
    return set_current_user(UserContext(id=user_id, username=f"u{user_id}", role="member", via="session"))


def test_files_written_by_one_account_are_invisible_to_the_other(db_session, pair):
    a, b, root = pair
    manager = WorkspaceManager(base_dir=str(root))

    token = _as(a.id)
    try:
        theirs = manager.get_agent_workspace(7)
        # `list_all_files` walks the tree's top level and only descends into the shapes
        # it knows (`default/`, `standalone/`, `project_*`), so the probe file goes in a
        # directory it actually enumerates.
        probe_dir = manager.user_base() / "default"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "report.md").write_text("A's data", encoding="utf-8")
        a_files = manager.list_all_files()
    finally:
        reset_current_user(token)

    token = _as(b.id)
    try:
        b_files = manager.list_all_files()
        b_workspace = manager.get_agent_workspace(7)
    finally:
        reset_current_user(token)

    assert any(f["filename"] == "report.md" for f in a_files)
    assert not any(f["filename"] == "report.md" for f in b_files)
    # …and B's own agent workspace is a different directory, not a view of A's.
    assert str(theirs) != str(b_workspace)
    assert not str(b_workspace).startswith(str(theirs))


def test_the_conversation_list_is_filtered_by_author(db_session, pair):
    from models.deep_agent import ChatSession

    a, b, _ = pair
    for user, tag in ((a, "a"), (b, "b")):
        db_session.add(ChatSession(
            session_id=str(uuid.uuid4()), agent_id=1, user_id=user.id,
            messages=[], metrics={}, tool_calls=[], subagent_spawns=[],
            context_operations=[], is_active=True,
        ))
    db_session.commit()

    token = _as(a.id)
    try:
        visible = workspace_scope.owned(
            db_session.query(ChatSession), ChatSession, db_session, column="user_id"
        ).all()
    finally:
        reset_current_user(token)

    assert visible, "A should see her own session"
    assert all(s.user_id == a.id for s in visible)
    assert b.id not in {s.user_id for s in visible}


def test_knowledge_stays_shared(db_session, pair):
    """The half of the boundary that must not drift: `context_documents` has no owner."""
    a, b, _ = pair
    count = db_session.execute(text("SELECT count(*) FROM context_documents")).scalar()
    if not count:
        pytest.skip("no knowledge documents on this install")

    columns = db_session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'context_documents'"
    )).scalars().all()
    assert "owner_id" not in columns and "user_id" not in columns, (
        "knowledge became per-user by accident — that is a product decision, not a detail"
    )


def test_a_path_from_someone_elses_list_is_useless(db_session, pair):
    from api.workspace.files_routes import _validate_path_in_workspace
    from fastapi import HTTPException

    a, b, root = pair
    manager = WorkspaceManager(base_dir=str(root))

    token = _as(a.id)
    try:
        space = manager.get_agent_workspace(9)
        (space / "secret.md").write_text("secret", encoding="utf-8")
    finally:
        reset_current_user(token)

    relative = f"agents/agent_9/secret.md"
    token = _as(b.id)
    try:
        with pytest.raises(HTTPException) as denied:
            _validate_path_in_workspace(relative, manager)
        assert denied.value.status_code == 404
        with pytest.raises(HTTPException) as traversal:
            _validate_path_in_workspace(f"../{a.id}/{relative}", manager)
        assert traversal.value.status_code in (403, 404)
    finally:
        reset_current_user(token)
