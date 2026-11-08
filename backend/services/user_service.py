# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
User accounts: CRUD, authentication, and first-boot bootstrap.

The bootstrapping rule is the important part of this module.

Before this slice, people signed in with credentials listed in ``.env``
(``LANGCONFIG_LAN_USERS``). Those credentials cannot just be deleted, or everyone
is locked out on upgrade. So on first boot, if the ``users`` table is empty, the
``.env`` credentials are **imported once** as real users — the first one as
``admin``, the rest as ``member`` — and then ``.env`` stops being read.

That mirrors how provider API keys already work here: ``.env`` is a bootstrap
input, PostgreSQL is the source of truth, and a stale file can never shadow the
database. It also means editing ``LANGCONFIG_LAN_USERS`` after the first boot has
**no effect**, which must be said out loud in the docs, because the opposite
assumption is what a reader will bring.

Every mutating call invokes :func:`invalidate_auth_cache`, so a password change or
a disabled account takes effect on the *next* request rather than after the LAN
gate's short auth-cache TTL.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.security.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    verify_password,
)
from models.user import User, UserRole

logger = logging.getLogger(__name__)

# Deliberately conservative: Basic auth splits on ':' and the username appears in
# URLs/logs, so keep it to characters that never need escaping.
USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$")

# A nickname is typed at the same prompt as a username, so it keeps the same
# character set — Basic auth has no encoding negotiation worth relying on, and a
# name with a space or a colon is a support ticket waiting to happen. Shorter cap:
# it exists to be *easy* to type.
NICKNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,31}$")


class UserError(ValueError):
    """A user operation was refused (validation, conflict, or last-admin guard)."""


# ── auth cache invalidation ──────────────────────────────────────────────────

def _revoke_sessions(db: Session, user_id: int, reason: str) -> None:
    """Kill an account's signed-in browsers.

    A password change and a disable both have to end live sessions, or "I changed
    my password" would not stop the browser that already had one. Imported lazily:
    session_service pulls in the identity types and the session model, and this
    module is imported from the gate's hottest path.
    """
    try:
        from services.session_service import revoke_all_for_user

        revoke_all_for_user(db, user_id, reason=reason)
    except Exception:  # pragma: no cover - the sweep must never break account writes
        logger.warning("Could not revoke sessions for user_id=%s", user_id, exc_info=True)


def invalidate_auth_cache() -> None:
    """Drop cached authentications. Called after any credential/state change."""
    try:
        from core.security.lan_auth import invalidate_auth_cache as _drop

        _drop()
    except Exception:  # pragma: no cover - cache is an optimisation, never a gate
        logger.debug("auth cache invalidation skipped", exc_info=True)


# ── validation ───────────────────────────────────────────────────────────────

def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise UserError(
            "Username must be 2-64 characters: letters, digits, dot, dash or "
            "underscore, starting with a letter or digit."
        )
    return username


def validate_nickname(nickname) -> Optional[str]:
    """Normalise a nickname. ``""``/None means "no alias" and returns None."""
    text = (nickname or "").strip()
    if not text:
        return None
    if not NICKNAME_RE.match(text):
        raise UserError(
            "Nickname must be 2-32 characters: letters, digits, dot, dash or "
            "underscore, starting with a letter or digit."
        )
    return text


def _ensure_nickname_free(db: Session, nickname: str, *, exclude_user_id: Optional[int] = None) -> None:
    """Two identifiers for one person are fine; one identifier for two is not.

    The partial unique index covers nickname-vs-nickname. It cannot cover
    nickname-vs-*username*, which is the ambiguity that actually bites at a login
    prompt, so that half is a scan here. Both comparisons ignore case: the browser's
    Basic prompt does not preserve the case the owner typed.
    """
    lowered = nickname.lower()

    clash = db.query(User).filter(func.lower(User.nickname) == lowered)
    if exclude_user_id is not None:
        clash = clash.filter(User.id != exclude_user_id)
    other = clash.first()
    if other is not None:
        raise UserError(f"Nickname {nickname!r} is already used by {other.username!r}.")

    shadow = db.query(User).filter(func.lower(User.username) == lowered)
    if exclude_user_id is not None:
        shadow = shadow.filter(User.id != exclude_user_id)
    taken = shadow.first()
    if taken is not None:
        raise UserError(
            f"Nickname {nickname!r} is somebody's username - pick another one."
        )


def get_by_nickname(db: Session, nickname: str) -> Optional[User]:
    """Case-insensitive lookup by alias. None for blank input, never a wildcard."""
    text = (nickname or "").strip()
    if not text:
        return None
    return db.query(User).filter(func.lower(User.nickname) == text.lower()).first()


def get_by_login(db: Session, identifier: str) -> Optional[User]:
    """Resolve whatever the person typed: their username first, then their nickname.

    Username wins on an exact match. That ordering is what keeps an alias from ever
    shadowing a real account, and it is why :func:`_ensure_nickname_free` refuses a
    nickname that equals an existing username.
    """
    text = (identifier or "").strip()
    if not text:
        return None
    return get_by_username(db, text) or get_by_nickname(db, text)


def coerce_role(role) -> UserRole:
    """Parse a role, as a clean client error rather than an enum traceback.

    ``UserRole('superuser')`` raises ValueError, which in FastAPI means a 500 —
    a typo in a role name is the caller's mistake and must read as one.
    """
    if isinstance(role, UserRole):
        return role
    try:
        return UserRole(str(role).strip().lower())
    except ValueError:
        valid = ", ".join(r.value for r in UserRole)
        raise UserError(f"Unknown role {role!r} - expected one of: {valid}.") from None


def validate_password(password: str) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


# ── reads ────────────────────────────────────────────────────────────────────

def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.id).all()


def count_users(db: Session) -> int:
    return db.query(User).count()


def count_active_admins(db: Session) -> int:
    return (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .count()
    )


def get_user(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def owner_user(db: Session) -> Optional[User]:
    """The identity that loopback (local development) resolves to.

    First *active* admin wins, else first active user. None means the install has
    no users at all, which callers must treat as "no identity" rather than
    inventing one.
    """
    admin = (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .order_by(User.id)
        .first()
    )
    if admin is not None:
        return admin
    return db.query(User).filter(User.is_active.is_(True)).order_by(User.id).first()


# ── writes ───────────────────────────────────────────────────────────────────

def ensure_userrole_enum() -> list[str]:
    """Make sure every role the CODE declares exists in the DB's `userrole` enum.

    Measured on the ECS deploy: the users table had been created when the enum had two values
    (admin, member), so `ontology_editor` — a role this code declares and the publish route checks —
    could not be granted at all: `ALTER TYPE` was missing, and every attempt failed with
    `invalid input value for enum userrole: "ontology_editor"`. `create_all` does not alter an enum,
    so an existing install needs this once. Returns the values that had to be added.
    """
    import logging

    from sqlalchemy import text

    from db.database import SessionLocal
    from models.user import UserRole

    log = logging.getLogger(__name__)
    added: list[str] = []
    db = SessionLocal()
    try:
        for role in UserRole:
            value = role.value
            exists = db.execute(
                text("select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid "
                     "where t.typname = 'userrole' and e.enumlabel = :v"), {"v": value}
            ).first()
            if exists:
                continue
            try:
                db.execute(text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'"))
                db.commit()
                added.append(value)
            except Exception as exc:                             # noqa: BLE001
                db.rollback()
                log.warning("could not add userrole value %r: %s", value, exc)
    except Exception as exc:                                     # noqa: BLE001
        log.warning("userrole enum ensure skipped: %s", exc)
    finally:
        db.close()
    return added


def create_user(
    db: Session,
    username: str,
    password: str,
    *,
    display_name: Optional[str] = None,
    nickname: Optional[str] = None,
    role: UserRole | str = UserRole.MEMBER,
    _commit: bool = True,
) -> User:
    username = validate_username(username)
    validate_password(password)
    nickname = validate_nickname(nickname)

    if get_by_username(db, username) is not None:
        raise UserError(f"User {username!r} already exists.")
    # Same ambiguity as _ensure_nickname_free, from the other side: a new username
    # must not steal an alias somebody already signs in with.
    if get_by_nickname(db, username) is not None:
        raise UserError(f"{username!r} is already somebody's nickname - pick another username.")
    if nickname is not None:
        _ensure_nickname_free(db, nickname)

    role_value = coerce_role(role)
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or None,
        nickname=nickname,
        role=role_value,
        is_active=True,
    )
    db.add(user)
    if _commit:
        db.commit()
        db.refresh(user)
        invalidate_auth_cache()
    return user


def set_password(db: Session, user: User, new_password: str) -> None:
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    invalidate_auth_cache()
    # Signing in with a new password ends the sessions made with the old one.
    _revoke_sessions(db, user.id, "password changed")


def update_user(
    db: Session,
    user: User,
    *,
    display_name: Optional[str] = None,
    nickname: Optional[str] = None,
    role: Optional[UserRole | str] = None,
    is_active: Optional[bool] = None,
    acting_user_id: Optional[int] = None,
) -> User:
    """Update a user, refusing changes that would lock everyone out.

    Two guards, both about not bricking the install: an admin cannot demote or
    disable themselves, and the last active admin cannot be demoted or disabled by
    anyone.
    """
    if role is not None:
        new_role = coerce_role(role)
        if new_role != user.role:
            demoting = user.role == UserRole.ADMIN and new_role != UserRole.ADMIN
            if demoting and acting_user_id == user.id:
                raise UserError("You cannot remove your own admin role.")
            if demoting and user.is_active and count_active_admins(db) <= 1:
                raise UserError("This is the last active admin - promote someone else first.")
            user.role = new_role

    if is_active is not None and bool(is_active) != bool(user.is_active):
        if not is_active:
            if acting_user_id == user.id:
                raise UserError("You cannot disable your own account.")
            if user.role == UserRole.ADMIN and count_active_admins(db) <= 1:
                raise UserError("This is the last active admin - promote someone else first.")
        user.is_active = bool(is_active)

    if display_name is not None:
        user.display_name = display_name.strip() or None

    # Convention matches display_name: None = "leave it alone", "" = "clear it".
    # Clearing matters — an alias that has been leaked to a group chat is worth
    # being able to take away without deleting the account.
    if nickname is not None:
        clean = validate_nickname(nickname)
        if clean is not None and clean.lower() != (user.nickname or "").lower():
            _ensure_nickname_free(db, clean, exclude_user_id=user.id)
        user.nickname = clean

    disabling = is_active is not None and not is_active
    user.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(user)
    invalidate_auth_cache()
    if disabling:
        # Disabling has to be immediate for browsers, not just for new sign-ins.
        _revoke_sessions(db, user.id, "account disabled")
    return user


# ── authentication ───────────────────────────────────────────────────────────

def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """Verify credentials for the LAN gate. Returns None on any failure.

    A disabled account fails exactly like a wrong password: the gate cannot
    distinguish them, so an attacker learns nothing about which usernames exist or
    which are merely switched off.
    """
    # The prompt says "username or nickname": username wins on an exact match, and
    # an alias may never shadow a real username (see _ensure_nickname_free).
    user = get_by_login(db, username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None

    # Opportunistic upgrade: raise hash parameters without a forced reset.
    if needs_rehash(user.password_hash):
        try:
            user.password_hash = hash_password(password)
        except ValueError:
            pass

    user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return user


def check_password(db: Session, user: User, password: str) -> bool:
    """Verify a password without recording a login (self-service change)."""
    return verify_password(password or "", user.password_hash)


# ── bootstrap ────────────────────────────────────────────────────────────────

def bootstrap_from_env(db: Session) -> list[str]:
    """Import ``.env`` LAN credentials as users when the table is empty.

    Returns the usernames created (empty when nothing was needed). Safe to call on
    every boot: it is a no-op once any user exists, so it can never resurrect a
    user an admin deleted.
    """
    if count_users(db) > 0:
        return []

    credentials, problems = _env_credentials()
    for problem in problems:
        logger.warning("Ignoring LANGCONFIG_LAN_USERS entry: %s", problem)

    if not credentials:
        logger.warning(
            "No users exist and no LANGCONFIG_LAN_USERS in .env - nobody can sign in "
            "yet. Create the first account with: cd backend && "
            ".venv/bin/python scripts/create_user.py <username> <password> --admin"
        )
        return []

    created: list[str] = []
    for index, (username, password) in enumerate(credentials):
        try:
            create_user(
                db,
                username,
                password,
                role=UserRole.ADMIN if index == 0 else UserRole.MEMBER,
                _commit=False,
            )
            created.append(username)
        except UserError as exc:
            logger.warning(
                "Bootstrap skipped %r: %s. Fix the password policy (min %d chars) or "
                "create the account with scripts/create_user.py.",
                username,
                exc,
                MIN_PASSWORD_LENGTH,
            )

    if created:
        db.commit()
        invalidate_auth_cache()
        logger.warning(
            "Bootstrapped %d user(s) from .env: %s. The first is an admin. "
            ".env is NOT read again - manage users in the app from now on.",
            len(created),
            ", ".join(created),
        )
    return created


def _env_credentials() -> tuple[list[tuple[str, str]], list[str]]:
    from core.security.lan_auth import parse_env_credentials

    return parse_env_credentials()


def iter_public(db: Session) -> Iterable[dict]:
    """Every user as a wire-safe dict (never includes password hashes)."""
    return (user.to_public() for user in list_users(db))
