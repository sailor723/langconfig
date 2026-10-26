from core.context.current_user import reset_current_user, set_current_user
from core.security.lan_auth import UserContext
from services.chat_session_manager import ChatSessionManager, _cache_key


def _as(user_id, username="someone"):
    return set_current_user(UserContext(id=user_id, username=username, role="member"))


def test_remove_session_clears_plain_and_composite_keys():
    manager = ChatSessionManager()
    manager.active_sessions["s1"] = object()
    manager.active_sessions["s1:5:123"] = object()
    manager.active_sessions["u3:s1:5:123"] = object()
    manager.active_sessions["other"] = object()

    assert manager.remove_session("s1") is True
    assert "s1" not in manager.active_sessions
    assert "s1:5:123" not in manager.active_sessions
    assert "u3:s1:5:123" not in manager.active_sessions
    assert "other" in manager.active_sessions


def test_remove_session_returns_false_when_absent():
    manager = ChatSessionManager()
    assert manager.remove_session("missing") is False


# ── the cache key carries the caller ────────────────────────────────────────

def test_cache_key_is_scoped_per_user():
    """Two people on the same session must not share one cached agent instance.

    The instance holds resolved credentials and a resolved workspace, so a shared
    entry is a credential leak the day keys become per-user.
    """
    first = _as(1, "alice")
    try:
        alice_key = _cache_key("s1", 5, "123")
    finally:
        reset_current_user(first)

    second = _as(2, "bob")
    try:
        bob_key = _cache_key("s1", 5, "123")
    finally:
        reset_current_user(second)

    assert alice_key != bob_key
    assert alice_key.startswith("u1:")
    assert bob_key.startswith("u2:")


def test_cache_key_outside_a_request_is_anonymous():
    """No identity (startup, scripts) must still be a usable, isolated namespace."""
    assert _cache_key("s1", 5, None) == "u~:s1:5"


def test_manager_does_not_serve_one_users_instance_to_another():
    manager = ChatSessionManager()
    instance = object()

    as_alice = _as(1, "alice")
    try:
        manager.cache_agent("s1", instance, agent_id=5, agent_version="123")
        assert manager.get_agent("s1", 5, "123") is instance
    finally:
        reset_current_user(as_alice)

    assert manager.get_agent("s1", 5, "123") is None, "bob must not receive alice's instance"

    as_bob = _as(2, "bob")
    try:
        manager.cache_agent("s1", object())
        assert manager.get_agent("s1", 5, "123") is None
    finally:
        reset_current_user(as_bob)
