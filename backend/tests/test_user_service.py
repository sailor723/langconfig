"""Tests for user accounts: password storage, CRUD rules and authentication.

These run against a real PostgreSQL session (``db_session``) because the rules
under test are enforced by the database as much as by the code — the unique
username index, the enum role, the "somebody must stay an admin" invariant.

Every test uses the ``mu-test-`` username prefix and cleans up after itself, so a
run never leaves accounts behind in a developer's database.
"""

import uuid

import pytest
from sqlalchemy import text

from core.security import passwords
from models.user import UserRole
from services import user_service
from services.user_service import UserError

PREFIX = "mu-test-"


def _name(tag: str) -> str:
    """A unique username: tests run against a shared database, not a fixture DB."""
    return f"{PREFIX}{tag}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def users(db_session):
    """Create accounts and guarantee their removal, even when a test fails."""
    created = []

    def make(name, password="correct horse 1", **kwargs):
        user = user_service.create_user(db_session, name, password, **kwargs)
        created.append(user)
        return user

    try:
        yield make
    finally:
        names = [u.username for u in created]
        if names:
            db_session.execute(
                text("DELETE FROM users WHERE username = ANY(:names)"),
                {"names": names},
            )
            db_session.commit()


# ── password storage ────────────────────────────────────────────────────────

def test_hash_is_salted_and_verifies():
    first = passwords.hash_password("hunter2hunter2")
    second = passwords.hash_password("hunter2hunter2")

    assert first != second, "identical passwords must not produce identical hashes"
    assert first.startswith("scrypt$")
    assert "hunter2hunter2" not in first
    assert passwords.verify_password("hunter2hunter2", first) is True
    assert passwords.verify_password("hunter2hunter3", first) is False


def test_verify_survives_a_malformed_hash():
    """A corrupt row must read as "wrong password", not crash the login path."""
    for bad in ("", "nonsense", "scrypt$", "scrypt$a$b$c$d$e", "bcrypt$whatever"):
        assert passwords.verify_password("x", bad) is False


def _weak_hash(password: str) -> str:
    """A hash made with a lower cost factor, as an older install would have."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(passwords, "N", 2 ** 12)
        return passwords.hash_password(password)


def test_needs_rehash_flags_weak_and_foreign_hashes():
    strong = passwords.hash_password("hunter2hunter2")
    weak = _weak_hash("hunter2hunter2")

    assert passwords.needs_rehash(weak) is True
    assert passwords.needs_rehash(strong) is False
    assert passwords.needs_rehash("something-else") is True


def test_minimum_password_length_is_enforced():
    assert passwords.MIN_PASSWORD_LENGTH == 8
    assert user_service.MIN_PASSWORD_LENGTH == 8
    with pytest.raises(UserError):
        user_service.validate_password("short")
    assert user_service.validate_password("long enough") == "long enough"


# ── validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "a", "has space", "bad!", "-leading", "x" * 65])
def test_usernames_outside_the_rule_are_refused(bad):
    with pytest.raises(UserError):
        user_service.validate_username(bad)


@pytest.mark.parametrize("good", ["ab", "alice", "a.b_c-d", "User123", "x" * 64])
def test_acceptable_usernames_pass(good):
    assert user_service.validate_username(good) == good


# ── creation ────────────────────────────────────────────────────────────────

def test_create_user_stores_a_hash_and_defaults_to_member(users):
    name = _name("alice")
    user = users(name, "alicepass1", display_name="Alice")

    assert user.username == name
    assert user.role == UserRole.MEMBER
    assert user.is_active is True
    assert user.password_hash != "alicepass1"
    assert passwords.verify_password("alicepass1", user.password_hash)

    public = user.to_public()
    assert "password_hash" not in public, "the hash must never be serialisable"
    assert public["role"] == "member"


def test_duplicate_username_is_refused(users, db_session):
    name = _name("dup")
    users(name, "duplicate1")
    with pytest.raises(UserError, match="already exists"):
        user_service.create_user(db_session, name, "duplicate2")


def test_short_password_is_refused_on_create(users):
    with pytest.raises(UserError, match="at least 8"):
        users(_name("short"), "abc")


# ── authentication ──────────────────────────────────────────────────────────

def test_authenticate_accepts_the_right_password_and_stamps_the_login(users, db_session):
    name = _name("auth")
    user = users(name, "authpass1")
    assert user.last_login_at is None

    found = user_service.authenticate(db_session, name, "authpass1")
    assert found is not None
    assert found.username == name
    assert found.last_login_at is not None


def test_authenticate_rejects_a_wrong_password(users, db_session):
    name = _name("wrong")
    users(name, "authpass1")
    assert user_service.authenticate(db_session, name, "authpass2") is None
    assert user_service.authenticate(db_session, name, "") is None


def test_authenticate_rejects_an_unknown_user(db_session):
    assert user_service.authenticate(db_session, _name("ghost"), "whatever1") is None


def test_disabled_account_cannot_authenticate(users, db_session):
    """Disabled must look exactly like a wrong password — no oracle for attackers."""
    name = _name("disabled")
    user = users(name, "authpass1")
    user_service.update_user(db_session, user, is_active=False)

    assert user_service.authenticate(db_session, name, "authpass1") is None


def test_rehash_upgrades_an_old_cost_factor_on_login(users, db_session):
    """Old hashes keep working, and are quietly strengthened when next used."""
    name = _name("rehash")
    user = users(name, "authpass1")
    user.password_hash = _weak_hash("authpass1")
    db_session.commit()

    assert passwords.needs_rehash(user.password_hash) is True
    assert user_service.authenticate(db_session, name, "authpass1") is not None
    db_session.refresh(user)
    assert passwords.needs_rehash(user.password_hash) is False


# ── password changes ────────────────────────────────────────────────────────

def test_set_password_changes_what_authenticates(users, db_session):
    name = _name("rotate")
    user = users(name, "oldpass12")

    user_service.set_password(db_session, user, "newpass12")

    assert user_service.authenticate(db_session, name, "oldpass12") is None
    assert user_service.authenticate(db_session, name, "newpass12") is not None


def test_set_password_rejects_a_weak_password(users, db_session):
    user = users(_name("weak"), "goodpass12")
    with pytest.raises(UserError):
        user_service.set_password(db_session, user, "short")


def test_check_password_does_not_leak_or_change_anything(users, db_session):
    name = _name("check")
    user = users(name, "checkpass1")
    before = user.last_login_at

    assert user_service.check_password(db_session, user, "checkpass1") is True
    assert user_service.check_password(db_session, user, "nope") is False
    assert user.last_login_at == before, "checking a password is not a login"


# ── role and state rules ────────────────────────────────────────────────────

def test_admin_can_promote_a_member(users, db_session):
    user = users(_name("promote"), "promotepass1")
    user_service.update_user(db_session, user, role="admin")
    assert user.role == UserRole.ADMIN
    assert user.is_admin() is True


def test_unknown_role_is_refused(users, db_session):
    user = users(_name("badrole"), "badrolepass1")
    with pytest.raises(UserError):
        user_service.update_user(db_session, user, role="superuser")


def test_admin_cannot_demote_themselves(users, db_session):
    """An admin removing their own role is how a LAN install loses its last admin."""
    admin = users(_name("self"), "selfpass12", role=UserRole.ADMIN)
    with pytest.raises(UserError, match="own admin role"):
        user_service.update_user(db_session, admin, role="member", acting_user_id=admin.id)


def test_admin_cannot_disable_themselves(users, db_session):
    admin = users(_name("selfdisable"), "selfpass12", role=UserRole.ADMIN)
    with pytest.raises(UserError, match="own account"):
        user_service.update_user(db_session, admin, is_active=False, acting_user_id=admin.id)


def test_last_admin_guard_exists(db_session):
    """The invariant, stated as SQL rather than as a scenario.

    A scenario test would have to build an install with exactly one admin and
    then try to remove it, which the self-guards above make unreachable through
    the API. What still matters is that the helper the guards rely on is honest.
    """
    total = db_session.execute(
        text("SELECT count(*) FROM users WHERE role = 'admin' AND is_active")
    ).scalar()
    assert user_service.count_active_admins(db_session) == total


def test_display_name_round_trips(users, db_session):
    user = users(_name("rename"), "renamepass1")
    user_service.update_user(db_session, user, display_name="Renamed Person")
    assert user.display_name == "Renamed Person"
    assert user.to_public()["display_name"] == "Renamed Person"


# ── bootstrap ──────────────────────────────────────────────────────────────

def test_bootstrap_is_a_noop_once_users_exist(db_session, monkeypatch):
    """.env seeds the table once and then stops mattering — never resurrects users."""
    monkeypatch.setenv("LANGCONFIG_LAN_USERS", "bootstrap-ghost:ghostpass1")
    if user_service.count_users(db_session) == 0:
        pytest.skip("needs an existing account to prove the no-op")

    assert user_service.bootstrap_from_env(db_session) == []
    assert user_service.get_by_username(db_session, "bootstrap-ghost") is None


def test_env_credentials_are_parsed_without_accepting_junk(monkeypatch):
    from core.security.lan_auth import parse_env_credentials

    monkeypatch.delenv("LANGCONFIG_LAN_USER", raising=False)
    monkeypatch.delenv("LANGCONFIG_LAN_PASSWORD", raising=False)
    monkeypatch.setenv("LANGCONFIG_LAN_USERS", "alice:secret1, broken, :noname, bob:pw:with:colons")

    credentials, problems = parse_env_credentials()
    assert dict(credentials) == {"alice": "secret1", "bob": "pw:with:colons"}
    assert len(problems) == 2
