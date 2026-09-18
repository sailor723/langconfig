# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the first-run setup endpoints + workspace wiring (Phase 5).

Covers:
1. workspace path validation (_validate_workspace_path).
2. setup-status: needs_setup logic (onboarding doc + api key + workspace doc).
3. setup-complete marks the wizard done (onboarding namespace).
4. workspace mutate resets the cached WorkspaceManager so the new root takes
   effect immediately.
5. WorkspaceManager honors the workspace document path when set.
"""
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import settings as cs

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test",
)
SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

Session = sessionmaker(
    bind=create_engine(SYNC_URL, pool_pre_ping=True),
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
def clean_documents():
    cs._reset_table_ensure()  # noqa: SLF001 — test hook
    db = Session()
    try:
        cs.ensure_table(db)
        cs.reset_documents(db)
    finally:
        db.close()
    yield
    db = Session()
    try:
        cs.reset_documents(db)
    finally:
        db.close()


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


def test_setup_status_logic(monkeypatch):
    import api.system.settings as mod

    captured = {}
    monkeypatch.setattr(mod, "_onboarding_state", lambda db: captured["state"])
    monkeypatch.setattr(mod, "_default_workspace_path", lambda: "/ws/default")

    # Fresh install: nothing completed, no key, no workspace → needs setup
    captured["state"] = {"completed": False, "has_api_key": False, "has_workspace": False}
    status = asyncio.run(mod.get_setup_status(None))
    assert status.needs_setup is True
    assert status.completed is False
    assert status.has_api_key is False
    assert status.has_workspace is False
    assert status.default_workspace_path == "/ws/default"

    # Key present (e.g. from .env), no workspace → still needs setup
    captured["state"] = {"completed": False, "has_api_key": True, "has_workspace": False}
    status = asyncio.run(mod.get_setup_status(None))
    assert status.needs_setup is True
    assert status.has_api_key is True

    # Everything configured (key + workspace) → no wizard, even if the
    # completed flag was never flipped (e.g. configured via Settings).
    captured["state"] = {"completed": False, "has_api_key": True, "has_workspace": True}
    status = asyncio.run(mod.get_setup_status(None))
    assert status.needs_setup is False
    assert status.has_workspace is True

    # Completed → never needs setup again
    captured["state"] = {"completed": True, "has_api_key": False, "has_workspace": False}
    status = asyncio.run(mod.get_setup_status(None))
    assert status.needs_setup is False


def test_setup_status_from_engine_documents():
    """Integration: setup-status derives from the onboarding/workspace docs."""
    import api.system.settings as mod

    db = Session()
    try:
        status = asyncio.run(mod.get_setup_status(db))
        assert status.completed is False
        assert status.needs_setup is True  # no key + no workspace

        cs.mutate(db, "onboarding", [{"op": "set", "path": ["setup_complete"], "value": True}])
        status = asyncio.run(mod.get_setup_status(db))
        assert status.completed is True
        assert status.needs_setup is False
    finally:
        db.close()


def test_complete_setup_marks_done():
    import api.system.settings as mod

    db = Session()
    try:
        res = asyncio.run(mod.complete_setup(db))
        assert res == {"ok": True, "needs_setup": False}
        assert cs.resolve_value(db, "onboarding")["setup_complete"] is True
    finally:
        db.close()


def test_workspace_mutate_resets_manager(tmp_path, monkeypatch):
    """Changing the workspace path (mutate) must drop the cached manager so the
    new root is picked up."""
    from api.system.settings_documents import _apply_runtime_side_effects
    from services.workspace_manager import reset_workspace_manager, get_workspace_manager

    # WorkspaceManager resolves the path through the global SessionLocal —
    # point it at the test DB for this test.
    monkeypatch.setattr("db.database.SessionLocal", lambda: Session())

    reset_workspace_manager()
    db = Session()
    try:
        cs.mutate(db, "workspace", [{"op": "set", "path": ["workspace_path"], "value": str(tmp_path / "a")}])
        _apply_runtime_side_effects(db, "workspace")
        first = get_workspace_manager()
        assert first.base_dir == (tmp_path / "a").resolve()

        cs.mutate(db, "workspace", [{"op": "set", "path": ["workspace_path"], "value": str(tmp_path / "b")}])
        _apply_runtime_side_effects(db, "workspace")
        second = get_workspace_manager()
        assert second.base_dir == (tmp_path / "b").resolve()
        assert second is not first  # cached manager was dropped
    finally:
        db.close()
    reset_workspace_manager()  # clean up the global for other tests


def test_workspace_manager_prefers_doc_path(monkeypatch, tmp_path):
    """WorkspaceManager's base_dir honors the workspace document path."""
    from services.workspace_manager import WorkspaceManager, reset_workspace_manager

    monkeypatch.setattr(
        "core.settings.resolve_value",
        lambda db, ns: {"workspace_path": str(tmp_path / "chosen")} if ns == "workspace" else {},
    )
    m = WorkspaceManager()
    assert m.base_dir == (tmp_path / "chosen").resolve()
    reset_workspace_manager()
