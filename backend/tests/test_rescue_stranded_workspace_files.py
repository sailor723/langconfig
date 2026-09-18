# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the stranded-workspace-file rescue script.

Covers the pure helpers only (path parsing, collision-free targets, empty-tree
pruning) — no DB, no filesystem writes beyond tmp_path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rescue_stranded_workspace_files import (  # noqa: E402
    _parse_stranded,
    _prune_empty_users_trees,
    _unique_target,
)


def _parts(path: str) -> tuple:
    return tuple(Path(path).parts)


def test_parse_nested_agent_generated():
    parsed = _parse_stranded(_parts(
        "my-project/agents/hello/Users/weiping/dev/backend/outputs/agents/"
        "agent_159/generated/report.md"
    ))
    assert parsed == {"agent_id": "159", "subfolder": "generated", "filename": "report.md"}


def test_parse_nested_agent_no_subfolder():
    parsed = _parse_stranded(_parts(
        "ws/Users/weiping/dev/backend/outputs/agents/agent_115/notes.txt"
    ))
    assert parsed == {"agent_id": "115", "subfolder": None, "filename": "notes.txt"}


def test_parse_nested_projects_agent():
    parsed = _parse_stranded(_parts(
        "my-second-project/agents/x/Users/weiping/dev/backend/outputs/projects/"
        "default-project/agents/ai-in-healthcare-research/presentation_outline.json"
    ))
    assert parsed == {
        "agent_id": None,
        "subfolder": None,
        "filename": "presentation_outline.json",
    }


def test_parse_non_stranded_returns_none():
    # Legit workspace files must never be parsed as stranded.
    assert _parse_stranded(_parts("my-project/agents/hello/generated/report.md")) is None
    assert _parse_stranded(_parts("agents/agent_159/AGENTS.md")) is None
    assert _parse_stranded(_parts("default/file.txt")) is None


def test_unique_target_avoids_collision(tmp_path):
    (tmp_path / "a.md").write_text("1")
    (tmp_path / "a_1.md").write_text("2")
    t = _unique_target(tmp_path, "a.md")
    assert t.name == "a_2.md"


def test_prune_empty_users_tree(tmp_path):
    nested = tmp_path / "agents" / "hello" / "Users" / "weiping" / "dev"
    f = nested / "x.md"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    f.unlink()  # the move already happened — prune runs afterwards
    # Removes dev, weiping, Users — stops at the workspace root (agents/hello).
    assert _prune_empty_users_trees(tmp_path, [f]) == 3
    assert not (tmp_path / "agents" / "hello" / "Users").exists()
    # Workspace root itself is preserved.
    assert (tmp_path / "agents" / "hello").exists()
