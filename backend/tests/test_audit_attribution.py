"""Audit attribution: a row written during a request names the person who made it.

Scope A does not isolate data, so this is the *only* thing multi-user buys today:
"who did that?" has an answer. It is therefore tested directly, not inferred from
the fact that some endpoint still returns 200.
"""

import uuid

import pytest
from sqlalchemy import text

from core.context.current_user import reset_current_user, set_current_user
from core.security.lan_auth import UserContext
from models.audit_log import AuditAction
from services.audit_service import audit_log_sync

PREFIX = "mu-test-"


@pytest.fixture
def identity(db_session):
    """An account plus its bound identity, both torn down afterwards."""
    from models.user import UserRole
    from services import user_service

    name = f"{PREFIX}audit-{uuid.uuid4().hex[:8]}"
    user = user_service.create_user(db_session, name, "auditpass1", role=UserRole.MEMBER)
    token = set_current_user(
        UserContext(id=user.id, username=user.username, role="member", via="lan")
    )
    try:
        yield user
    finally:
        reset_current_user(token)
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM audit_logs WHERE user_id = :uid"), {"uid": user.id}
        )
        db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
        db_session.commit()


def test_audit_row_carries_the_caller(db_session, identity):
    audit_log_sync(
        db=db_session,
        action=AuditAction.CREATE,
        resource_type="Workflow",
        message="created via test",
    )

    row = db_session.execute(
        text("SELECT user_id FROM audit_logs WHERE resource_type = 'Workflow' "
             "AND message = 'created via test' ORDER BY id DESC LIMIT 1")
    ).first()
    assert row is not None
    assert row[0] == identity.id


def test_explicit_user_id_still_wins(db_session, identity):
    """An explicit id overrides the ambient identity — background work keeps control."""
    marker = f"explicit-{uuid.uuid4().hex[:8]}"
    audit_log_sync(
        db=db_session,
        action=AuditAction.CREATE,
        resource_type="Workflow",
        user_id=identity.id + 1000,
        message=marker,
    )
    row = db_session.execute(
        text("SELECT user_id FROM audit_logs WHERE message = :m"), {"m": marker}
    ).first()
    assert row[0] == identity.id + 1000, "the explicit id must not be overwritten"


def test_anonymous_work_stays_null(db_session):
    """Scripts and startup have no identity; the column must stay honest, not guess."""
    marker = f"anonymous-{uuid.uuid4().hex[:8]}"
    try:
        audit_log_sync(
            db=db_session,
            action=AuditAction.CREATE,
            resource_type="Workflow",
            message=marker,
        )
        row = db_session.execute(
            text("SELECT user_id FROM audit_logs WHERE message = :m"), {"m": marker}
        ).first()
        assert row is not None
        assert row[0] is None
    finally:
        db_session.execute(text("DELETE FROM audit_logs WHERE message = :m"), {"m": marker})
        db_session.commit()
