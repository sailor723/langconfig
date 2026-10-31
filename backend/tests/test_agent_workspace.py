# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the per-agent workspace feature.

1. Workspace path is user-defined and persisted in PostgreSQL
   (deep_agent_templates.workspace_path); the resolver honours it with a
   fallback to the default outputs/agents/agent_{id}/ convention.
2. Regular agents (no deepagents filesystem) get a workspace-scoped
   save_document tool so "persist this as a file" actually writes a file
   (the reported bug: agent claimed it saved, Files panel showed nothing).
3. save_document (DB mode) binds agent_id and writes a workspace copy.
"""
import pytest

from services.workspace_manager import WorkspaceManager


class _FakeAgent:
    def __init__(self, agent_id, workspace_path):
        self.id = agent_id
        self.workspace_path = workspace_path


def _make_manager(tmp_path):
    # Raw layout arithmetic — see WorkspaceManager(user_scoping=...).
    return WorkspaceManager(base_dir=str(tmp_path), user_scoping=False)


def test_resolver_uses_user_defined_path(tmp_path):
    custom = tmp_path / "my-custom-workspace"
    custom.mkdir()
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159, str(custom)))
    assert resolved == custom.resolve()
    assert resolved.is_dir()


def test_resolver_creates_missing_custom_path(tmp_path):
    custom = tmp_path / "brand-new-workspace"
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159, str(custom)))
    assert resolved.is_dir()


def test_resolver_relative_path_resolves_against_base(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159, "custom/relative"))
    assert resolved == (tmp_path / "custom" / "relative").resolve()
    assert resolved.is_dir()


def test_resolver_falls_back_to_default_when_unset(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159, None))
    assert resolved == (tmp_path / "agents" / "agent_159").resolve()


def test_resolver_falls_back_when_empty_string(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159, "   "))
    assert resolved == (tmp_path / "agents" / "agent_159").resolve()


async def test_regular_agent_has_no_injected_save_document(tmp_path, monkeypatch):
    """The workspace-scoped save_document injection is gone.

    It existed because "regular agents have no FilesystemMiddleware" — untrue
    since the factory installs the middleware for every agent — and it shadowed
    the catalogued save_document with a second tool of the same name but a
    different schema (file_path/content instead of title/content/doc_type).
    write_file from the middleware is the single writer now.
    """
    from core.agents.factory import AgentFactory

    m = _make_manager(tmp_path)
    ws = m.resolve_agent_workspace(_FakeAgent(159, None))

    cfg = {
        "system_prompt": "test",
        "model": "deepseek-flash",
        "use_deepagents": False,
        "native_tools": [],
        "custom_tools": [],
    }

    async def _load_native(names, workspace_context=None, agent_context=None):
        return []

    monkeypatch.setattr("core.agents.tool_loader.ToolLoader.load_native", _load_native)

    _inst, tools, _ = await AgentFactory.create_agent(
        agent_config=cfg, project_id=0, task_id=0, context="",
        workspace_root=str(ws), agent_id=159,
    )
    assert "save_document" not in [getattr(t, "name", "") for t in tools]


async def test_save_document_binds_agent_id_and_writes_copy(tmp_path, monkeypatch):
    """DB-mode save_document (native tool) must record agent_id and write a
    workspace copy when workspace_root is in the workspace context."""
    from tools.native_impl import _save_document_impl

    m = _make_manager(tmp_path)
    ws = m.resolve_agent_workspace(_FakeAgent(159, None))

    # Patch the DB session factory so no real DB is touched.
    captured = {}

    class _FakeRow:
        pass

    class _FakeQuery:
        def __init__(self, rows): self.rows = rows
        def filter(self, *a, **kw): return self
        def order_by(self, *a, **kw): return self
        def with_for_update(self): return self
        def first(self): return None

    class _FakeDb:
        def query(self, model):
            captured["model"] = model
            return _FakeQuery([])
        def add(self, obj):
            captured["obj"] = obj
            obj.id = 1
            obj.version = 1
        def commit(self):
            captured["committed"] = True
        def rollback(self): pass
        def close(self): pass

    def _fake_session():
        return _FakeDb()

    monkeypatch.setattr("db.database.SessionLocal", _fake_session)
    monkeypatch.setattr("sqlalchemy.exc.IntegrityError", type("IntegrityError", (Exception,), {}))

    result = _save_document_impl(
        title="测试报告",
        content="# 内容",
        doc_type="report",
        _workspace_context={"workspace_root": str(ws)},
        _agent_context={"agent_id": 159},
    )
    assert "saved to the document library" in str(result)
    # agent_id bound on the DB row
    assert captured["obj"].agent_id == 159
    # workspace copy written into the generated/ subfolder
    assert (ws / "generated" / "测试报告.md").exists()


async def test_save_document_treats_zero_project_as_unscoped(tmp_path, monkeypatch):
    """A project-less chat passes project_id=0 (`_session_project_id or 0`).

    0 is not a row in `projects`, so storing it trips
    agent_documents_project_id_fkey and the retry loop reported the failure as
    "concurrent version conflict". The sentinel must be stored as NULL.
    """
    from tools.native_impl import _save_document_impl

    m = _make_manager(tmp_path)
    ws = m.resolve_agent_workspace(_FakeAgent(159, None))
    captured = {}

    class _FakeQuery:
        def filter(self, *a, **kw): return self
        def order_by(self, *a, **kw): return self
        def with_for_update(self): return self
        def first(self): return None

    class _FakeDb:
        def query(self, model): return _FakeQuery()
        def add(self, obj):
            captured["obj"] = obj
            obj.id = 1
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    monkeypatch.setattr("db.database.SessionLocal", lambda: _FakeDb())
    monkeypatch.setenv("GRAPHINDEX_PROJECT_ID", "")
    monkeypatch.setattr("sqlalchemy.exc.IntegrityError", type("IntegrityError", (Exception,), {}))

    result = _save_document_impl(
        title="无项目文档",
        content="# 内容",
        _workspace_context={"workspace_root": str(ws), "project_id": 0},
        _agent_context={"agent_id": 159},
    )
    assert "saved to the document library" in str(result)
    assert captured["obj"].project_id is None
