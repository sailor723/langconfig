# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Browser sessions: create, resolve, extend, revoke.

The rules that matter, and the reasons they are not negotiable:

* **The cookie carries the secret; the database carries its hash.** ``secrets``
  supplies 32 random bytes; only ``sha256(token)`` is stored. A leaked backup is
  then not a set of usable logins, and lookups stay an indexed equality test.
* **Expiry is checked on read, and an expired row is deleted.** A session that is
  merely "past its expiry" but still present is a bug waiting for a code path that
  forgets to look.
* **A disabled account loses its sessions immediately.** ``resolve`` re-reads the
  user and refuses an inactive one; an admin disabling someone does not have to wait
  for a cookie to expire, and does not need to know it exists.
* **Sliding renewal is throttled.** Extending on every request would rewrite a row
  per request on an app that streams SSE. The session is extended only once its
  remaining life has dropped below ``lifetime - GRACE``, so a busy browser touches
  the row at most once a day.
* **Revocation is by token, never by guess.** ``revoke`` deletes on the hash; an
  unknown token is a no-op, not an error, because "sign out" must be idempotent.

Nothing here logs a token, a hash, or a password.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from core.security.lan_auth import UserContext
from models.auth_session import AuthSession
from models.user import User

logger = logging.getLogger(__name__)

#: How long a sign-in lasts. Also the sliding window: activity pushes it out.
SESSION_LIFETIME = datetime.timedelta(days=7)

#: Renewal happens only once the remaining life has dropped by this much, so a
#: request does not become a write. One day of slack on a 7-day session.
RENEW_GRACE = datetime.timedelta(days=1)

TOKEN_BYTES = 32


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime.datetime) -> datetime.datetime:
    """Postgres gives tz-aware values, naive ones turn up in odd setups/tests."""
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def _documented_client(db: Session, request) -> tuple[Optional[str], Optional[str]]:
    """User agent and source address, for a "signed-in devices" list later."""
    if request is None:
        return None, None
    ua = request.headers.get("user-agent")
    client = getattr(request, "client", None)
    ip = client.host if client else None
    return (ua[:300] if ua else None), (ip[:45] if ip else None)


def create_session(
    db: Session,
    user: User,
    *,
    request=None,
    lifetime: datetime.timedelta = SESSION_LIFETIME,
) -> tuple[str, AuthSession]:
    """Start a session and return ``(raw_token, row)``.

    The raw token is returned exactly once, to be put in the cookie; it is not
    stored and cannot be recovered from the row.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = _utc_now()
    user_agent, ip_address = _documented_client(db, request)

    session = AuthSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + lifetime,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("Signed in %s from %s", user.username, ip_address or "unknown")
    return token, session


def resolve(db: Session, token: Optional[str]) -> Optional[AuthSession]:
    """The session for a cookie value, or None — never raises for a bad token.

    Returns None for: no cookie, unknown token, expired token, disabled account.
    Callers cannot tell those apart, which is deliberate: the browser's experience
    is the same ("sign in again") and probing learns nothing.
    """
    if not token:
        return None

    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == _hash_token(token))
        .first()
    )
    if session is None:
        return None

    now = _utc_now()
    if session.is_expired(now):
        # Delete rather than ignore: the row must not survive as a live-in-limbo
        # record that another code path could trust.
        db.delete(session)
        db.commit()
        logger.info("Expired session for user_id=%s removed", session.user_id)
        return None

    user = session.user
    if user is None or not user.is_active:
        # A disabled account's sessions die with its access. This is the path that
        # makes "Disable" in the admin panel immediate for browsers too.
        revoke_all_for_user(db, session.user_id, reason="account disabled or missing")
        return None

    if _aware(session.expires_at) - now < SESSION_LIFETIME - RENEW_GRACE:
        session.expires_at = now + SESSION_LIFETIME
        session.last_seen_at = now
        db.commit()

    return session


def to_context(session: AuthSession, user: User) -> UserContext:
    """The DB-free identity object the gate and request context use."""
    return UserContext(
        id=user.id,
        username=user.username,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        display_name=user.display_name,
        via="session",
    )


def resolve_context(db: Session, token: Optional[str]) -> Optional[UserContext]:
    """Cookie value → identity, in one call (what the gate needs)."""
    session = resolve(db, token)
    if session is None or session.user is None:
        return None
    return to_context(session, session.user)


def revoke(db: Session, token: Optional[str]) -> bool:
    """Delete one session. Idempotent: an unknown token is not an error."""
    if not token:
        return False
    deleted = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == _hash_token(token))
        .delete(synchronize_session="fetch")
    )
    db.commit()
    if deleted:
        logger.info("Signed out one session")
    return bool(deleted)


def revoke_all_for_user(db: Session, user_id: int, *, reason: str = "") -> int:
    """Kill every session belonging to an account (disable, password reset, reset)."""
    deleted = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id)
        .delete(synchronize_session="fetch")
    )
    db.commit()
    if deleted:
        logger.info(
            "Revoked %d session(s) for user_id=%s%s",
            deleted,
            user_id,
            f" ({reason})" if reason else "",
        )
    return int(deleted)


def list_for_user(db: Session, user_id: int) -> list[AuthSession]:
    return (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id)
        .order_by(AuthSession.last_seen_at.desc())
        .all()
    )


def purge_expired(db: Session) -> int:
    """Drop dead rows. Called at startup; cheap and safe to run repeatedly."""
    deleted = (
        db.query(AuthSession)
        .filter(AuthSession.expires_at <= _utc_now())
        .delete(synchronize_session="fetch")
    )
    db.commit()
    if deleted:
        logger.info("Purged %d expired session(s)", deleted)
    return int(deleted)
