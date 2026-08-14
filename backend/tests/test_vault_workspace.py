# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the vault-scoped agent workspace + per-agent docs.

1. resolve_agent_workspace: user-defined path → vault-scoped default
   (outputs/projects/{id}/agents/agent_{id}) → legacy default.
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
    assert resolved == (tmp_path / "projects" / "7" / "agents" / "agent_159").resolve()
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
    assert resolved == (tmp_path / "projects" / "7" / "agents" / "my-agent").resolve()


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


def test_materialize_no_docs_is_noop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(_FakeAgent(159, agent_docs=None), str(ws))
    assert list(ws.iterdir()) == []


def test_materialize_rejects_unsafe_doc_name(tmp_path):
    agent = _FakeAgent(159, agent_docs={"../../etc/pwn.md": "x"})
    ws = tmp_path / "ws"
    ws.mkdir()
    _materialize_agent_docs(agent, str(ws))
    assert not (ws.parent / "etc" / "pwn.md").exists()
