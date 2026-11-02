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

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, func, text
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

    # A second login identifier: what a person actually types. `username` stays the
    # stable, machine-shaped key (ownership columns point at it, the Basic prompt
    # used to demand it), so an alias is additive — the account can still sign in
    # with either. NULL means "no alias".
    #
    # Case-insensitive uniqueness is enforced by a partial index in migration 040;
    # the "a nickname may not shadow somebody else's username" rule needs a scan and
    # therefore lives in services/user_service.py.
    nickname = Column(String(32), nullable=True)

    role = Column(
        SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.MEMBER,
    )

    # Disabled rather than deleted: the account cannot authenticate, but the rows
    # it owns keep their owner.
    is_active = Column(Boolean, nullable=False, default=True)

    # Optional per-account workspace root. NULL — the normal case — means "use the
    # convention": ``<install root>/users/<id>`` (services/user_roots.py). Set it to
    # put one person's files on another disk (a bigger volume, an encrypted mount, a
    # machine-local scratch dir) without moving anyone else's.
    #
    # Stored as an absolute path exactly as the admin typed it; resolution expands
    # ``~`` and refuses anything relative, so a typo cannot silently become a
    # directory next to the process's CWD.
    workspace_path = Column(String(1024), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Declared here, after the columns, because it names `nickname`: a table-level
    # constraint written above the column would reference a name that does not exist
    # yet. nickname is a login identifier, so two accounts may not share one — and
    # the comparison has to ignore case, because nobody types "Alice" the same way
    # twice. Partial (WHERE nickname IS NOT NULL) so the many alias-less accounts do
    # not collide with each other on NULL.
    __table_args__ = (
        Index(
            "ix_users_nickname_lower",
            func.lower(nickname),
            unique=True,
            postgresql_where=text("nickname IS NOT NULL"),
        ),
    )

    # ── serialisation ────────────────────────────────────────────────────────

    def to_public(self) -> dict:
        """Everything the UI may see. Deliberately excludes ``password_hash``, so
        the hash cannot leak by someone hand-rolling a dict at a new call site."""
        return {
            "id": self.id,
            "username": self.username,
            "nickname": self.nickname,
            "display_name": self.display_name,
            "role": self.role.value if isinstance(self.role, UserRole) else str(self.role),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            # NULL means "the default convention" — the UI shows the resolved path
            # separately rather than inventing one here.
            "workspace_path": self.workspace_path,
        }

    def is_admin(self) -> bool:
        return (
            self.role == UserRole.ADMIN
            or (isinstance(self.role, str) and self.role == UserRole.ADMIN.value)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User(id={self.id}, username={self.username!r}, role={self.role})>"
