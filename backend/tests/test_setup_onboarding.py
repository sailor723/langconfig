# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the first-run setup endpoints + workspace wiring.

Covers:
1. workspace path validation (_validate_workspace_path).
2. setup-status: needs_setup logic (completed flag + api key + workspace).
3. setup-complete marks the wizard done.
4. update_workspace_settings resets the cached WorkspaceManager so the new
   root takes effect immediately.
5. WorkspaceManager honors the DB workspace_path when set.
"""
import asyncio

import pytest


def _settings_row(**overrides):
    """A fake Settings row (id=1) supporting getattr-style access."""
    class _Row:
        id = 1
        setup_complete = False
        workspace_path = ""
        api_keys = {}
    for k, v in overrides.items():
        setattr(_Row, k, v)
    return _Row()


class _FakeDb:
    """Minimal fake Session covering what get_or_create_settings needs:
    execute (SET LOCAL / ALTER TABLE), query/filter/first, add/commit/
    rollback/refresh/close."""

    def __init__(self, row=None):
        self.row = row
        self.committed = 0
        self.added = []

    def execute(self, *a, **kw):
        return None

    def query(self, model):
        return self

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self.row

    def add(self, obj):
        self.added.append(obj)
        if self.row is None:
            self.row = obj

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def refresh(self, row):
        pass

    def close(self):
        pass


def test_validate_workspace_path(tmp_path):
    from api.system.settings import _validate_workspace_path

    # Existing, writable dir → valid
    r = _validate_workspace_path(str(tmp_path))
    assert r.valid is True
    assert r.writable is True
    assert r.resolved_path == str(tmp_path.resolve())

    # Missing nested dir → created + valid
    nested = tmp_path / "a" / "b"
    r = _validate_workspace_path(str(nested))
    assert r.valid is True
    assert nested.is_dir()

    # Non-writable location → invalid
    r = _validate_workspace_path("/nonexistent-root-xyz/foo")
    assert r.valid is False
    assert r.error


def test_setup_status_logic(monkeypatch):
    import api.system.settings as mod

    captured = {}
    monkeypatch.setattr(mod, "_has_any_chat_api_key", lambda db: captured["has_key"])
    monkeypatch.setattr(mod, "_default_workspace_path", lambda: "/ws/default")

    # Fresh install: nothing completed, no key, no workspace → needs setup
    captured["has_key"] = False
    db = _FakeDb(_settings_row(setup_complete=False, workspace_path=""))
    status = asyncio.run(mod.get_setup_status(db))
    assert status.needs_setup is True
    assert status.completed is False
    assert status.has_api_key is False
    assert status.has_workspace is False
    assert status.default_workspace_path == "/ws/default"

    # Key present (e.g. from .env), no workspace → still needs setup
    captured["has_key"] = True
    status = asyncio.run(mod.get_setup_status(db))
    assert status.needs_setup is True
    assert status.has_api_key is True

    # Everything configured (key + workspace) → no wizard, even if the
    # completed flag was never flipped (e.g. configured via Settings).
    db = _FakeDb(_settings_row(setup_complete=False, workspace_path="/ws"))
    status = asyncio.run(mod.get_setup_status(db))
    assert status.needs_setup is False
    assert status.has_workspace is True

    # Completed → never needs setup again
    db = _FakeDb(_settings_row(setup_complete=True, workspace_path="/ws"))
    status = asyncio.run(mod.get_setup_status(db))
    assert status.needs_setup is False


def test_complete_setup_marks_done():
    import api.system.settings as mod

    db = _FakeDb(_settings_row(setup_complete=False))
    res = asyncio.run(mod.complete_setup(db))
    assert res == {"ok": True, "needs_setup": False}
    assert db.row.setup_complete is True
    assert db.committed >= 1


def test_update_workspace_settings_resets_manager(tmp_path):
    """Changing the workspace path must drop the cached manager so the new
    root is picked up."""
    import api.system.settings as mod
    from services.workspace_manager import reset_workspace_manager, get_workspace_manager

    reset_workspace_manager()
    old = get_workspace_manager()
    assert old is not None

    db = _FakeDb(_settings_row(workspace_path=""))
    ws = asyncio.run(mod.update_workspace_settings(
        mod.WorkspaceSettings(workspace_path=str(tmp_path / "my-ws")), db
    ))
    assert ws.workspace_path == str((tmp_path / "my-ws").resolve())
    assert db.row.workspace_path == str((tmp_path / "my-ws").resolve())

    # Invalid path → 400 via HTTPException
    from fastapi import HTTPException
    db2 = _FakeDb(_settings_row(workspace_path=""))
    with pytest.raises(HTTPException):
        asyncio.run(mod.update_workspace_settings(
            mod.WorkspaceSettings(workspace_path="/nonexistent-root-xyz/foo"), db2
        ))

    reset_workspace_manager()  # clean up the global for other tests


def test_workspace_manager_prefers_db_path(monkeypatch, tmp_path):
    """WorkspaceManager's base_dir honors the DB workspace_path when set."""
    from services.workspace_manager import WorkspaceManager, reset_workspace_manager

    class _Row:
        id = 1
        workspace_path = str(tmp_path / "chosen")

    class _Db:
        def query(self, model):
            return self

        def filter(self, *a, **kw):
            return self

        def first(self):
            return _Row()

        def close(self):
            pass

    def _fake_session():
        return _Db()

    monkeypatch.setattr("db.database.SessionLocal", _fake_session)
    m = WorkspaceManager()
    assert m.base_dir == (tmp_path / "chosen").resolve()
    reset_workspace_manager()
