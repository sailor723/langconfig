from services.chat_session_manager import ChatSessionManager


def test_remove_session_clears_plain_and_composite_keys():
    manager = ChatSessionManager()
    manager.active_sessions["s1"] = object()
    manager.active_sessions["s1:5:123"] = object()
    manager.active_sessions["other"] = object()

    assert manager.remove_session("s1") is True
    assert "s1" not in manager.active_sessions
    assert "s1:5:123" not in manager.active_sessions
    assert "other" in manager.active_sessions


def test_remove_session_returns_false_when_absent():
    manager = ChatSessionManager()
    assert manager.remove_session("missing") is False
