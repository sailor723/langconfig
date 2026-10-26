# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Credential verification for the LAN gate, and the identity it produces.

Two jobs, deliberately kept apart from the gate itself
(``middleware/lan_guard.py``) so the transport concern — "is this request from
the network" — stays separate from the policy concern — "who is this person".

**The cache is load-bearing.** A successful scrypt verification costs ~25 ms. A
browser loading the app issues dozens of requests, and SSE endpoints issue more;
verifying each one would add seconds to every page load. So a successful
authentication is cached for a short TTL. The trade-off is explicit:

* revoking a user, changing a password, or disabling an account is effective
  within :data:`DEFAULT_TTL_SECONDS` (60 s) — not instantly;
* :func:`invalidate_auth_cache` makes it instant, and every mutating call in
  ``services/user_service.py`` invokes it, so in practice revocation is immediate
  on the machine that performed it;
* failed attempts are cached for :data:`NEGATIVE_TTL_SECONDS` only, to blunt
  password guessing without letting a lockout linger.

``.env`` is *not* consulted here. Credentials are imported once at first boot
(``services/user_service.bootstrap_from_env``) and PostgreSQL is authoritative
afterwards — the same rule provider API keys already follow.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60.0
NEGATIVE_TTL_SECONDS = 5.0


# ── the identity object ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserContext:
    """A resolved person. Immutable, DB-free, safe to hand across threads.

    Deliberately not an ORM object: this travels from middleware into request
    handlers and possibly into worker threads, where a live Session would be a
    liability.
    """

    id: int
    username: str
    role: str  # 'admin' | 'member'
    display_name: Optional[str] = None
    via: str = "lan"  # how they were identified: 'lan' | 'loopback' | 'test'

    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "via": self.via,
        }


class VerifierUnavailable(RuntimeError):
    """The user store could not be reached. Mapped to 503, never to 401.

    The distinction matters: "wrong password" and "the database is down" must not
    look alike, or an outage reads as an attack.
    """


class CredentialVerifier(Protocol):
    def verify(self, username: str, password: str) -> Optional[UserContext]:
        """Return the matching identity, or None."""

    def owner(self) -> Optional[UserContext]:
        """The identity loopback resolves to (local development)."""


# ── helpers ──────────────────────────────────────────────────────────────────

def _digest(username: str, password: str) -> str:
    """Cache key. Hashed so a password is never held as a dict key verbatim."""
    return hashlib.sha256(f"{username}\x00{password}".encode("utf-8")).hexdigest()


def _to_context(user, via: str) -> Optional[UserContext]:
    """Snapshot a User ORM row into the DB-free identity object.

    Called *inside* the open session on purpose: ``authenticate`` commits (it
    stamps ``last_login_at``), which expires the row, so reading attributes after
    ``db.close()`` raises DetachedInstanceError. One read here, then the session
    may die.
    """
    if user is None:
        return None
    return UserContext(
        id=user.id,
        username=user.username,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        display_name=user.display_name,
        via=via,
    )


def parse_env_credentials() -> tuple[list[tuple[str, str]], list[str]]:
    """Credentials from ``.env``, in declaration order — plus rejected entries.

    Only used to **bootstrap** the first users, never to authenticate. Comma
    separated ``name:password``; only the first colon splits, so a password may
    contain one. Malformed entries are returned rather than silently dropped, so
    the caller can report them at boot — an ignored entry means a person who
    cannot sign in.
    """
    raw = os.getenv("LANGCONFIG_LAN_USERS", "").strip()
    credentials: list[tuple[str, str]] = []
    problems: list[str] = []

    if raw:
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, sep, password = entry.partition(":")
            name, password = name.strip(), password.strip()
            if not sep:
                problems.append(f"{name!r} has no ':' — expected name:password")
                continue
            if not name or not password:
                problems.append(f"{name!r} has an empty name or password")
                continue
            credentials.append((name, password))
        return credentials, problems

    # Legacy single-credential form.
    single_user = (os.getenv("LANGCONFIG_LAN_USER", "") or "").strip()
    single_password = os.getenv("LANGCONFIG_LAN_PASSWORD", "") or ""
    if single_user and single_password:
        credentials.append((single_user, single_password))
    return credentials, problems


# ── the DB-backed verifier ───────────────────────────────────────────────────

class DatabaseCredentialVerifier:
    """Verify against the ``users`` table, with a short-lived success cache."""

    def __init__(
        self,
        *,
        session_factory: Optional[Callable] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        negative_ttl_seconds: float = NEGATIVE_TTL_SECONDS,
    ):
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._negative_ttl = negative_ttl_seconds
        self._lock = threading.Lock()
        # key -> (expires_at, UserContext | None)
        self._cache: dict[str, tuple[float, Optional[UserContext]]] = {}
        self._owner_cache: Optional[tuple[float, Optional[UserContext]]] = None

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from db.database import SessionLocal  # local import: keeps boot cheap

        return SessionLocal()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._owner_cache = None

    def _cached(self, key: str) -> tuple[bool, Optional[UserContext]]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                self._cache.pop(key, None)
                return False, None
            return True, value

    def _store(self, key: str, value: Optional[UserContext]) -> None:
        ttl = self._ttl if value is not None else self._negative_ttl
        with self._lock:
            # Cheap bound: this dict is per-process and small, but an unbounded map
            # fed by hostile usernames is still a leak.
            if len(self._cache) > 4096:
                self._cache.clear()
            self._cache[key] = (time.monotonic() + ttl, value)

    def verify(self, username: str, password: str) -> Optional[UserContext]:
        key = _digest(username, password)
        hit, value = self._cached(key)
        if hit:
            return value

        from services.user_service import authenticate

        db = self._session()
        try:
            context = _to_context(authenticate(db, username, password), "lan")
        except Exception as exc:
            # A broken/absent DB must read as "cannot decide", not "no".
            raise VerifierUnavailable(str(exc)) from exc
        finally:
            try:
                db.close()
            except Exception:
                pass

        self._store(key, context)
        return context

    def owner(self) -> Optional[UserContext]:
        with self._lock:
            if self._owner_cache is not None:
                expires_at, value = self._owner_cache
                if expires_at > time.monotonic():
                    return value

        from services.user_service import owner_user

        db = self._session()
        try:
            context = _to_context(owner_user(db), "loopback")
        except Exception as exc:
            raise VerifierUnavailable(str(exc)) from exc
        finally:
            try:
                db.close()
            except Exception:
                pass

        with self._lock:
            self._owner_cache = (time.monotonic() + self._ttl, context)
        return context


# ── test / bootstrap verifier ────────────────────────────────────────────────

class InMemoryCredentialVerifier:
    """Static credentials for tests and for driving the gate without a database."""

    def __init__(self, credentials: dict[str, str], owner_username: Optional[str] = None):
        self._credentials = dict(credentials)
        self._owner_username = owner_username or next(iter(credentials), None)

    def verify(self, username: str, password: str) -> Optional[UserContext]:
        if self._credentials.get(username) != password:
            return None
        return self._context(username)

    def owner(self) -> Optional[UserContext]:
        if self._owner_username is None:
            return None
        return self._context(self._owner_username, via="loopback")

    def _context(self, username: str, via: str = "lan") -> UserContext:
        order = list(self._credentials)
        index = order.index(username)
        return UserContext(
            id=index + 1,
            username=username,
            role="admin" if index == 0 else "member",
            via=via,
        )


# ── the process-wide instance ────────────────────────────────────────────────

_default_verifier: Optional[DatabaseCredentialVerifier] = None


def get_default_verifier() -> DatabaseCredentialVerifier:
    """The verifier used by the app (one per process, so its cache is shared)."""
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = DatabaseCredentialVerifier()
    return _default_verifier


def invalidate_auth_cache() -> None:
    """Drop cached authentications process-wide."""
    if _default_verifier is not None:
        _default_verifier.invalidate()
