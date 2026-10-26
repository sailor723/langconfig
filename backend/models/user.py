# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
User accounts — the real identity behind every request.

Why this table exists: the app was built single-user, so "who is asking" was
never answerable. `created_by` / `user_id` columns exist across the schema but
were never populated or filtered, and the LAN gate could only say "somebody knew
the shared password".

Scope, stated once: this slice gives **identities, not isolation**. Every user
still sees and edits every project, agent, workflow, chat and knowledge base in
the tenant — one shared workspace with separate front doors. Per-user files
(Slice 2) and per-user provider keys (Slice 3) build on this.

Two deliberate limits:

* **No hard delete.** ``is_active = False`` disables an account; deleting a row
  would orphan the ownership columns this slice starts to populate.
* **No email / reset link.** Credentials are set by an admin, or by the user
  knowing their current password. Adding mail means adding an outbound dependency
  to a LAN app; that is a later decision, not a missing piece.
"""

import datetime
import enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy import Enum as SQLEnum

from db.database import Base


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class UserRole(str, enum.Enum):
    """What a user may do beyond their own account.

    Two roles on purpose. More would need a per-endpoint permission matrix, and
    nothing in the current scope asks for one.
    """

    ADMIN = "admin"    # manages users; may publish shared assets later
    MEMBER = "member"  # their own account only


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # What the LAN gate's Basic-auth prompt sends. UNIQUE because two people
    # cannot share a login without making attribution a lie.
    username = Column(String(64), unique=True, nullable=False, index=True)

    # scrypt, format documented in core/security/passwords.py. Never returned by
    # any API surface — see to_public().
    password_hash = Column(String(255), nullable=False)

    display_name = Column(String(128), nullable=True)

    role = Column(
        SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.MEMBER,
    )

    # Disabled rather than deleted: the account cannot authenticate, but the rows
    # it owns keep their owner.
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ── serialisation ────────────────────────────────────────────────────────

    def to_public(self) -> dict:
        """Everything the UI may see. Deliberately excludes ``password_hash``, so
        the hash cannot leak by someone hand-rolling a dict at a new call site."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role.value if isinstance(self.role, UserRole) else str(self.role),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def is_admin(self) -> bool:
        return (
            self.role == UserRole.ADMIN
            or (isinstance(self.role, str) and self.role == UserRole.ADMIN.value)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User(id={self.id}, username={self.username!r}, role={self.role})>"
