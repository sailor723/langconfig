"""Deleting an agent must take its workspace with it.

Before this, the delete endpoint removed the row and nothing else: 93 orphan directories
accumulated on one install, invisible in the UI and attributable to nothing.
"""

import uuid

import pytest

from services import agent_cleanup, user_roots


@pytest.fixture
def fake_agent():
    from types import SimpleNamespace

    return SimpleNamespace(id=4242, name="cleanup-test", workspace_path=None)


def _make_tree(tmp_path, agent_id, *, vault=None, files=()):
    base = tmp_path / "users" / "1"
    where = base / vault / "agents" / f"agent_{agent_id}" if vault else base / "agents" / f"agent_{agent_id}"
    (where / "generated").mkdir(parents=True, exist_ok=True)
    for name in files:
        (where / "generated" / name).write_bytes(b"x")
    return where


def test_every_layout_of_agent_directory_is_found(tmp_path, fake_agent, monkeypatch):
    """Flat, per-user and vault-scoped layouts all exist in the wild."""
    monkeypatch.setattr(user_roots, "install_root", lambda: tmp_path)
    plain = _make_tree(tmp_path, fake_agent.id)
    vaulted = _make_tree(tmp_path, fake_agent.id, vault="langconfig-test")

    found = {p.resolve() for p in agent_cleanup.workspace_dirs_for(fake_agent)}
    assert plain.resolve() in found
    assert vaulted.resolve() in found
    assert len(found) == 2, "the same directory must not be listed twice"


def test_another_agents_directory_is_untouched(tmp_path, fake_agent, monkeypatch):
    monkeypatch.setattr(user_roots, "install_root", lambda: tmp_path)
    mine = _make_tree(tmp_path, fake_agent.id)
    theirs = _make_tree(tmp_path, 9999)

    found = agent_cleanup.workspace_dirs_for(fake_agent)
    assert mine.resolve() in {p.resolve() for p in found}
    assert theirs.resolve() not in {p.resolve() for p in found}
    assert theirs.is_dir()


def test_cleanup_moves_to_trash_and_counts_files(tmp_path, fake_agent, monkeypatch,
                                                db_session):
    monkeypatch.setattr(user_roots, "install_root", lambda: tmp_path)
    monkeypatch.setattr(user_roots, "root_for", lambda user_id=None, root=None: tmp_path / "users" / "1")
    dirs = _make_tree(tmp_path, fake_agent.id, files=("report.pdf", "notes.md"))

    summary = agent_cleanup.remove_agent_workspaces(fake_agent)

    assert summary["files"] == 2
    assert len(summary["dirs"]) == 1
    assert not dirs.exists(), "the workspace must be gone from where it was"
    trash = tmp_path / "users" / "1" / ".trash" / "agents"
    assert trash.is_dir()
    moved = list(trash.rglob("report.pdf"))
    assert moved, "the deliverable is recoverable, not destroyed"


def test_dry_run_touches_nothing(tmp_path, fake_agent, monkeypatch):
    monkeypatch.setattr(user_roots, "install_root", lambda: tmp_path)
    dirs = _make_tree(tmp_path, fake_agent.id, files=("keep.txt",))

    summary = agent_cleanup.remove_agent_workspaces(fake_agent, dry_run=True)

    assert summary["dirs"] and summary["moved_to"] is None
    assert dirs.is_dir() and (dirs / "generated" / "keep.txt").exists()


def test_a_workspace_outside_the_install_is_left_alone(tmp_path, monkeypatch):
    """A hand-set absolute path outside the workspace is the setter's own choice."""
    from types import SimpleNamespace

    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex[:6]}"
    outside.mkdir()
    agent = SimpleNamespace(id=4243, name="outside", workspace_path=str(outside))
    monkeypatch.setattr(user_roots, "install_root", lambda: tmp_path / "ws")

    found = agent_cleanup.workspace_dirs_for(agent)
    assert found == []
    assert outside.is_dir()
