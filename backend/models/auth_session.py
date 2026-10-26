# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Browser sessions — what a sign-in panel needs that HTTP Basic cannot give.

Basic auth has no session: the browser keeps the password and replays it on every
request, so "sign out", "remember me for a week", and "which browsers am I signed
in on?" are all unanswerable. A login form cannot set Basic credentials either, so
a sign-in page forces a real session mechanism.

Design, and why each choice:

* **Opaque random token, hashed at rest.** The cookie carries 32 random bytes; the
  table stores only their SHA-256. A database dump therefore cannot be replayed as
  a login, and lookup is an index hit on the hash.
* **Server-side rows, not signed tokens.** Revocation has to be immediate and
  per-session ("sign out this laptop"), and an admin disabling an account must kill
  its sessions at once. A self-contained token cannot be recalled without keeping
  state anyway, so it buys nothing here.
* **Sliding expiry with throttled writes.** Every request would otherwise rewrite
  the row; the service only extends when the session has aged past a grace window.
* **`expires_at` is authoritative.** An expired row is deleted, never trusted, and
  a missing row means "not signed in" — the same answer as a bad token, so nothing
  distinguishes "expired" from "forged".
"""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from db.database import Base


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class AuthSession(Base):
    """One signed-in browser."""

    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, index=True)

    # SHA-256 of the cookie value, hex. UNIQUE so two browsers can never share a
    # session; indexed because this is the lookup key on every request.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Context, so "sign out other devices" can be a readable list rather than a
    # row of opaque hashes. Never used for authentication.
    user_agent = Column(String(300), nullable=True)
    ip_address = Column(String(45), nullable=True)

    user = relationship("User", lazy="joined")

    __table_args__ = (
        # Disabling an account revokes its sessions; this index makes that sweep
        # (and the expired-session purge) cheap.
        Index("ix_auth_sessions_user_expiry", "user_id", "expires_at"),
    )

    def is_expired(self, now: datetime.datetime | None = None) -> bool:
        now = now or _utc_now()
        expires = self.expires_at
        if expires.tzinfo is None:  # a naive value from SQLite-style test setups
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        return expires <= now

    def to_public(self) -> dict:
        """Everything the UI may see. There is no secret in here by design."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuthSession(id={self.id}, user_id={self.user_id})>"
