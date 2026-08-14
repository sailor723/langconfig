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
    return WorkspaceManager(base_dir=str(tmp_path))


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


async def test_regular_agent_gets_workspace_save_document_tool(tmp_path, monkeypatch):
    """A regular agent built with workspace_root must expose save_document
    and writing through it lands a file in the workspace."""
    from core.agents.factory import AgentFactory

    m = _make_manager(tmp_path)
    ws = m.resolve_agent_workspace(_FakeAgent(159, None))

    cfg = {
        "system_prompt": "test",
        "model": "claude-haiku-4-5-20251015",
        "use_deepagents": False,
        "native_tools": [],
        "custom_tools": [],
    }

    async def _load_native(names, workspace_context=None, agent_context=None):
        return []

    # Isolate tool loading so no DB rows are needed.
    monkeypatch.setattr("core.agents.tool_loader.ToolLoader.load_native", _load_native)

    inst, tools, _ = await AgentFactory.create_agent(
        agent_config=cfg, project_id=0, task_id=0, context="",
        workspace_root=str(ws), agent_id=159,
    )
    names = [getattr(t, "name", "") for t in tools]
    assert "save_document" in names
    sd = next(t for t in tools if t.name == "save_document")
    result = await sd.ainvoke({"file_path": "report.md", "content": "# Report"})
    assert "Successfully wrote" in str(result)
    # Generated deliverables land in the workspace's generated/ subfolder.
    assert (ws / "generated" / "report.md").exists()
    assert "Report" in (ws / "generated" / "report.md").read_text(encoding="utf-8")


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
