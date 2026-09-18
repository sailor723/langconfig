# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the vault-scoped agent workspace + per-agent docs.

1. resolve_agent_workspace: user-defined path → vault-scoped default
   (outputs/{id}/agents/agent_{id}) → vault-scoped default.
   (outputs/agents/agent_{id}) → legacy default.
2. Agent instruction docs (AGENTS.md / CLAUDE.md) live on the specific agent
   row in PostgreSQL and are materialized into the workspace at chat build.
"""
import sys
from pathlib import Path

# api.chat.messages imports think_filter at module level; it lives in
# learning/phase9 (added to sys.path by main.py at app boot).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "learning" / "phase9"))

import pytest

from services.workspace_manager import WorkspaceManager
from api.chat.messages import _materialize_agent_docs


class _FakeAgent:
    def __init__(self, agent_id, workspace_path=None, agent_docs=None):
        self.id = agent_id
        self.workspace_path = workspace_path
        self.agent_docs = agent_docs


def _make_manager(tmp_path):
    return WorkspaceManager(base_dir=str(tmp_path))


# ── vault-scoped resolution ─────────────────────────────────────────

def test_resolver_vault_scoped_default(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159), project_id=7)
    assert resolved == (tmp_path / "7" / "agents" / "agent_159").resolve()
    assert resolved.is_dir()


def test_resolver_legacy_default_without_vault(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(_FakeAgent(159), project_id=None)
    assert resolved == (tmp_path / "agents" / "agent_159").resolve()


def test_resolver_custom_path_beats_vault(tmp_path):
    m = _make_manager(tmp_path)
    custom = tmp_path / "my-custom"
    custom.mkdir()
    resolved = m.resolve_agent_workspace(_FakeAgent(159, str(custom)), project_id=7)
    assert resolved == custom.resolve()


def test_resolver_relative_custom_path_anchored_to_vault(tmp_path):
    m = _make_manager(tmp_path)
    resolved = m.resolve_agent_workspace(
        _FakeAgent(159, "agents/my-agent"), project_id=7
    )
    assert resolved == (tmp_path / "7" / "agents" / "my-agent").resolve()


# ── agent docs materialization ──────────────────────────────────────

def test_materialize_agent_docs_writes_into_workspace(tmp_path):
    agent = _FakeAgent(159, agent_docs={
        "AGENTS.md": "# Agent 159\nResearch US markets.",
        "CLAUDE.md": "# Agent 159 claude doc",
    })
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(agent, str(ws))
    assert (ws / "AGENTS.md").exists()
    assert (ws / "CLAUDE.md").exists()
    assert "Research US markets" in (ws / "AGENTS.md").read_text(encoding="utf-8")


def test_materialize_no_docs_writes_defaults(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(_FakeAgent(159, agent_docs=None), str(ws))
    assert (ws / "AGENTS.md").exists()
    assert (ws / "CLAUDE.md").exists()
    text = (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agent 159" in text  # default docs are agent-aware
    assert str(ws) in text      # and reference the workspace root


def test_materialize_no_docs_seeds_db_row(tmp_path):
    class _FakeDb:
        def __init__(self):
            self.committed = False

        def commit(self):
            self.committed = True

    ws = tmp_path / "ws"
    ws.mkdir()
    db = _FakeDb()
    agent = _FakeAgent(159, agent_docs=None)
    _materialize_agent_docs(agent, str(ws), db=db)
    assert agent.agent_docs and "AGENTS.md" in agent.agent_docs
    assert db.committed is True
    assert (ws / "AGENTS.md").exists()


def test_materialize_rejects_unsafe_doc_name(tmp_path):
    agent = _FakeAgent(159, agent_docs={"../../etc/pwn.md": "x"})
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(agent, str(ws))
    assert not (ws.parent / "etc" / "pwn.md").exists()


# ── name-based vault folder keys ────────────────────────────────────

class _FakeDb:
    def __init__(self, rows, name):
        self.rows = rows
        self._current_id = None

    def get(self, model, project_id):
        self._current_id = project_id
        return next((r for r in self.rows if r.id == project_id), None)

    def query(self, model):
        return self

    def filter(self, *a, **kw):
        return self

    def all(self):
        # Mirrors the real `Project.id != project_id` collision query.
        return [r for r in self.rows if r.id != self._current_id]


class _Row:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def test_vault_key_is_sanitized_project_name():
    from services.workspace_manager import WorkspaceManager
    db = _FakeDb([_Row(2, "my-project"), _Row(7, "my demo project 1")], None)
    assert WorkspaceManager.project_vault_key(db, 2) == "my-project"
    assert WorkspaceManager.project_vault_key(db, 7) == "my-demo-project-1"


def test_vault_key_cjk_names_kept():
    from services.workspace_manager import WorkspaceManager
    db = _FakeDb([_Row(9, "我的项目")], None)
    assert WorkspaceManager.project_vault_key(db, 9) == "我的项目"


def test_vault_key_falls_back_to_id():
    from services.workspace_manager import WorkspaceManager
    assert WorkspaceManager.project_vault_key(None, 42) == "42"


def test_vault_key_collision_appends_id():
    from services.workspace_manager import WorkspaceManager
    db = _FakeDb([_Row(2, "My Project"), _Row(3, "my-project")], None)
    assert WorkspaceManager.project_vault_key(db, 3) == "my-project-3"


def test_slugify_safe():
    from services.workspace_manager import WorkspaceManager
    assert WorkspaceManager._slugify("My Demo Project! / 1") == "my-demo-project-1"
    assert WorkspaceManager._slugify("") == "project"
    assert "/" not in WorkspaceManager._slugify("a/b/c")
    assert ".." not in WorkspaceManager._slugify("..")


# ── name-based agent folder keys ────────────────────────────────────

class _FakeAgentRow:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class _AgentDb:
    def __init__(self, rows):
        self.rows = rows
        self._current_id = None

    def query(self, model):
        return self

    def filter(self, *a, **kw):
        return self

    def all(self):
        return [r for r in self.rows if r.id != self._current_id]


def test_agent_vault_key_is_sanitized_name():
    from services.workspace_manager import WorkspaceManager
    db = _AgentDb([_FakeAgentRow(159, "hello"), _FakeAgentRow(160, "My Research Agent")])
    db._current_id = 159
    assert WorkspaceManager.agent_vault_key(db, _FakeAgentRow(159, "hello")) == "hello"
    db._current_id = 160
    assert WorkspaceManager.agent_vault_key(db, _FakeAgentRow(160, "My Research Agent")) == "my-research-agent"


def test_agent_vault_key_collision_appends_id():
    from services.workspace_manager import WorkspaceManager
    db = _AgentDb([_FakeAgentRow(159, "hello"), _FakeAgentRow(160, "Hello")])
    db._current_id = 160
    assert WorkspaceManager.agent_vault_key(db, _FakeAgentRow(160, "Hello")) == "hello-160"


def test_agent_vault_key_falls_back_to_id_without_name():
    from services.workspace_manager import WorkspaceManager
    class NoName:
        id = 7
    assert WorkspaceManager.agent_vault_key(None, NoName()) == "agent_7"


def test_resolve_uses_agent_key_folder():
    from services.workspace_manager import WorkspaceManager
    from pathlib import Path
    import tempfile
    tmp = Path(tempfile.mkdtemp()).resolve()
    m = WorkspaceManager(base_dir=str(tmp))
    ws = m.resolve_agent_workspace(_FakeAgent(159), project_id=2, vault_key="my-project", agent_key="hello")
    assert str(ws.relative_to(tmp)) == "my-project/agents/hello"
    # legacy fallback without keys stays agent_{id}
    ws2 = m.resolve_agent_workspace(_FakeAgent(159), project_id=2)
    assert str(ws2.relative_to(tmp)) == "2/agents/agent_159"


# ── identity / doc re-bake ──────────────────────────────────────────


def test_refresh_doc_identity_rebakes_all_forms():
    from core.agents.identity import refresh_doc_identity
    content = (
        "## Identity\n\n- **Agent ID**: 115\n"
        "- **Workspace**: /old/outputs/agents/agent_115\n\n"
        "## Workspace\n\nYour workspace directory is:\n\n"
        "    /old/outputs/agents/agent_115\n\n"
        "## Quick reference\n\n"
        "- Workspace: `/old/outputs/agents/agent_115`\n"
        "- Keep everything else intact.\n"
    )
    out = refresh_doc_identity(content, 115, "/new/my-project/agents/hello")
    assert "- **Workspace**: /new/my-project/agents/hello" in out
    assert "    /new/my-project/agents/hello" in out
    assert "- Workspace: `/new/my-project/agents/hello`" in out
    assert "/old/" not in out
    assert "- **Agent ID**: 115" in out
    assert "- Keep everything else intact." in out


def test_build_identity_system_prompt_embeds_rebaked_docs():
    from core.agents.identity import build_identity_system_prompt
    docs = {
        "AGENTS.md": "## Identity\n\n- **Workspace**: /old/outputs/agents/agent_115\n",
        "CLAUDE.md": "- Workspace: `/old/outputs/agents/agent_115`\n",
    }
    out = build_identity_system_prompt("Base.", 115, "/new/my-project/agents/hello", docs)
    assert "/old/" not in out
    assert "## Identity\n\n- **Agent ID**: 115" in out or "- **Agent ID**: 115" in out
    assert "/new/my-project/agents/hello" in out


def test_materialize_rebakes_baked_workspace_root(tmp_path):
    """Docs authored with a legacy baked workspace root are re-baked at
    materialization so the on-disk copy references the session's workspace."""
    agent = _FakeAgent(115, agent_docs={
        "AGENTS.md": (
            "## Identity\n\n- **Agent ID**: 115\n"
            "- **Workspace**: /legacy/outputs/agents/agent_115\n\n"
            "## Workspace\n\nYour workspace directory is:\n\n"
            "    /legacy/outputs/agents/agent_115\n"
        ),
        "CLAUDE.md": (
            "## Identity\n\n- **Agent ID**: 115\n"
            "- **Workspace**: /legacy/outputs/agents/agent_115\n"
            "- Workspace: `/legacy/outputs/agents/agent_115`\n"
        ),
    })
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(agent, str(ws))
    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (ws / name).read_text(encoding="utf-8")
        assert "/legacy/" not in text, f"{name} still carries the legacy path"
        assert str(ws) in text, f"{name} missing the resolved root"
        assert f"- **Workspace**: {ws}" in text
        if name == "CLAUDE.md":
            assert f"- Workspace: `{ws}`" in text
