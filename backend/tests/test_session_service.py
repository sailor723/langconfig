"""Session service: tokens, expiry, sliding renewal, revocation.

These are the rules that keep a cookie from being a permanent password, so they are
tested directly rather than inferred from a login endpoint returning 200.
"""

import datetime
import uuid

import pytest
from sqlalchemy import text

from core.security import passwords
from models.auth_session import AuthSession
from models.user import UserRole
from services import session_service, user_service

PREFIX = "mu-test-"


def _name(tag: str) -> str:
    return f"{PREFIX}sess-{tag}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def account(db_session):
    user = user_service.create_user(db_session, _name("owner"), "sessionpass1", role=UserRole.MEMBER)
    try:
        yield user
    finally:
        db_session.rollback()
        db_session.execute(text("DELETE FROM auth_sessions WHERE user_id = :u"), {"u": user.id})
        db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
        db_session.commit()


# ── tokens ──────────────────────────────────────────────────────────────────

def test_token_is_not_stored(db_session, account):
    token, session = session_service.create_session(db_session, account)

    stored = db_session.execute(
        text("SELECT token_hash FROM auth_sessions WHERE id = :i"), {"i": session.id}
    ).scalar()
    assert stored != token, "the raw token must never be persisted"
    assert len(stored) == 64, "sha256 hex"
    assert token not in stored


def test_two_sessions_get_different_tokens(db_session, account):
    first, first_row = session_service.create_session(db_session, account)
    second, second_row = session_service.create_session(db_session, account)

    assert first != second
    assert first_row.token_hash != second_row.token_hash


def test_resolve_returns_identity_from_a_valid_cookie(db_session, account):
    token, _ = session_service.create_session(db_session, account)

    identity = session_service.resolve_context(db_session, token)
    assert identity is not None
    assert identity.id == account.id
    assert identity.username == account.username
    assert identity.via == "session"


@pytest.mark.parametrize("token", [None, "", "not-a-real-token", "x" * 43])
def test_unknown_or_absent_tokens_resolve_to_nothing(db_session, account, token):
    assert session_service.resolve_context(db_session, token) is None


def test_a_token_for_another_user_does_not_work(db_session, account):
    """The password is not in the cookie, so a token is all an attacker would need."""
    other = user_service.create_user(db_session, _name("other"), "otherpass12")
    try:
        token, _ = session_service.create_session(db_session, other)
        identity = session_service.resolve_context(db_session, token)
        assert identity.username == other.username
        assert identity.username != account.username
    finally:
        session_service.revoke_all_for_user(db_session, other.id)
        db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other.id})
        db_session.commit()


# ── expiry ──────────────────────────────────────────────────────────────────

def test_expired_session_is_refused_and_deleted(db_session, account):
    token, session = session_service.create_session(db_session, account)

    # Age it past its expiry by hand: waiting seven days is not a test strategy.
    db_session.execute(
        text("UPDATE auth_sessions SET expires_at = now() - interval '1 minute' WHERE id = :i"),
        {"i": session.id},
    )
    db_session.commit()

    assert session_service.resolve(db_session, token) is None
    remaining = db_session.execute(
        text("SELECT count(*) FROM auth_sessions WHERE id = :i"), {"i": session.id}
    ).scalar()
    assert remaining == 0, "an expired row must not survive to be trusted later"


def test_sliding_renewal_only_writes_when_the_window_is_running_out(db_session, account):
    token, session = session_service.create_session(db_session, account)

    # Fresh session: no renewal yet (nothing has aged past the grace window).
    before = db_session.execute(
        text("SELECT expires_at FROM auth_sessions WHERE id = :i"), {"i": session.id}
    ).scalar()
    assert session_service.resolve(db_session, token) is not None
    after = db_session.execute(
        text("SELECT expires_at FROM auth_sessions WHERE id = :i"), {"i": session.id}
    ).scalar()
    assert after == before

    # Age it beyond the grace window: the next use extends it again.
    db_session.execute(
        text("UPDATE auth_sessions SET expires_at = now() + interval '2 days' WHERE id = :i"),
        {"i": session.id},
    )
    db_session.commit()
    assert session_service.resolve(db_session, token) is not None
    extended = db_session.execute(
        text("SELECT expires_at FROM auth_sessions WHERE id = :i"), {"i": session.id}
    ).scalar()
    assert extended > after


# ── revocation ──────────────────────────────────────────────────────────────

def test_revoke_kills_exactly_one_session(db_session, account):
    keep, _ = session_service.create_session(db_session, account)
    drop, _ = session_service.create_session(db_session, account)

    assert session_service.revoke(db_session, drop) is True
    assert session_service.resolve(db_session, drop) is None
    assert session_service.resolve(db_session, keep) is not None


def test_revoke_is_idempotent(db_session, account):
    token, _ = session_service.create_session(db_session, account)
    assert session_service.revoke(db_session, token) is True
    assert session_service.revoke(db_session, token) is False
    assert session_service.revoke(db_session, None) is False


def test_disabling_an_account_kills_its_sessions(db_session, account):
    """Admin "Disable" has to be immediate for browsers, not just for new sign-ins."""
    token, _ = session_service.create_session(db_session, account)
    user_service.update_user(db_session, account, is_active=False)

    assert session_service.resolve(db_session, token) is None


def test_changing_a_password_kills_its_sessions(db_session, account):
    """"I changed my password" must log out the browser that already had one."""
    token, _ = session_service.create_session(db_session, account)
    user_service.set_password(db_session, account, "brandnewpass1")

    assert session_service.resolve(db_session, token) is None


def test_purge_removes_only_expired_rows(db_session, account):
    live, _live_row = session_service.create_session(db_session, account)
    dead, dead_row = session_service.create_session(db_session, account)
    # Capture the id first: deleting the row detaches the ORM object, and reading
    # `dead_row.id` afterwards would raise instead of asserting.
    dead_id = dead_row.id
    db_session.execute(
        text("UPDATE auth_sessions SET expires_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": dead_id},
    )
    db_session.commit()

    session_service.purge_expired(db_session)

    assert session_service.resolve(db_session, live) is not None
    assert (
        db_session.execute(
            text("SELECT count(*) FROM auth_sessions WHERE id = :i"), {"i": dead_id}
        ).scalar()
        == 0
    )


def test_sessions_are_listed_newest_first(db_session, account):
    _, first = session_service.create_session(db_session, account)
    db_session.execute(
        text("UPDATE auth_sessions SET last_seen_at = now() - interval '2 hours' WHERE id = :i"),
        {"i": first.id},
    )
    db_session.commit()
    _, second = session_service.create_session(db_session, account)

    listed = [row.id for row in session_service.list_for_user(db_session, account.id)]
    assert listed[0] == second.id
    assert first.id in listed


def test_session_metadata_is_recorded_but_never_a_secret(db_session, account):
    token, session = session_service.create_session(db_session, account)
    public = session.to_public()

    assert public["expires_at"] is not None
    assert "token_hash" not in public
    assert token not in str(public)
    assert "password" not in str(public).lower()
