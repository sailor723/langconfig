# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for path-containment fixes.

1. WorkspaceManager used ``str(path).startswith(str(workspace))`` — a prefix
   check without a trailing separator, so a sibling task (``task_1`` vs
   ``task_10``) could read/write/rename files across task boundaries.
2. FileStorage hierarchy segments were only checked for a leading dot, so a
   segment like ``a/../../etc`` or an absolute ``/etc`` escaped project_dir.
"""
import pytest

from services.workspace_manager import WorkspaceManager, _is_within
from services.file_storage import FileStorage


# ── _is_within (workspace containment) ───────────────────────────────

def test_is_within_accepts_child():
    root = pytest.importorskip("pathlib").Path("/tmp/ws/task_1")
    assert _is_within(root / "report.txt", root)


def test_is_within_rejects_sibling_prefix():
    """task_10 must NOT be considered inside task_1."""
    root = pytest.importorskip("pathlib").Path("/tmp/ws/task_1")
    assert not _is_within(root.parent / "task_10" / "x.txt", root)


def test_is_within_rejects_traversal():
    root = pytest.importorskip("pathlib").Path("/tmp/ws/task_1")
    assert not _is_within(root / ".." / "task_10" / "x.txt", root)


def test_is_within_rejects_outside():
    root = pytest.importorskip("pathlib").Path("/tmp/ws/task_1")
    assert not _is_within(root.parent, root)


async def test_get_file_content_blocks_sibling_task(tmp_path):
    """Regression: task_1 must not read task_10's file via ../task_10."""
    ws = WorkspaceManager(base_dir=str(tmp_path))
    # task_1 workspace exists
    w1 = ws.get_task_workspace(1, 1, 1)
    w1.mkdir(parents=True, exist_ok=True)
    (w1 / "own.txt").write_text("mine", encoding="utf-8")
    # sibling task_10 workspace with a secret
    w10 = ws.get_task_workspace(1, 1, 10)
    w10.mkdir(parents=True, exist_ok=True)
    (w10 / "secret.txt").write_text("top-secret", encoding="utf-8")

    result = ws.get_file_content(1, 1, 1, "../task_10/secret.txt")
    assert result is None


# ── FileStorage hierarchy sanitization ───────────────────────────────

def _make_storage(tmp_path):
    return FileStorage(base_dir=str(tmp_path))


def test_save_file_accepts_safe_hierarchy(tmp_path):
    from pathlib import Path
    fs = _make_storage(tmp_path)
    path = fs.save_file(
        project_id=1,
        filename="report.csv",
        content=b"a,b\n1,2\n",
        hierarchy={"industry": "retail", "player": "acme"},
    )
    assert "retail" in str(path) and "acme" in str(path)
    assert Path(path).exists()


@pytest.mark.parametrize("bad_segment", [
    "a/../../etc",
    "/etc",
    "a\\b",
    " x ",
])
def test_save_file_rejects_unsafe_hierarchy(tmp_path, bad_segment):
    fs = _make_storage(tmp_path)
    with pytest.raises(ValueError, match="Unsafe hierarchy segment"):
        fs.save_file(
            project_id=1,
            filename="report.csv",
            content=b"a,b\n1,2\n",
            hierarchy={"industry": bad_segment},
        )


@pytest.mark.parametrize("dot_segment", [".", "..", ".hidden"])
def test_save_file_dot_segments_skipped_safely(tmp_path, dot_segment):
    """Legacy behavior: dot-prefixed segments are ignored (no escape)."""
    fs = _make_storage(tmp_path)
    path = fs.save_file(
        project_id=1,
        filename="report.csv",
        content=b"x",
        hierarchy={"industry": dot_segment, "player": "acme"},
    )
    assert "acme" in str(path)
    assert ".hidden" not in str(path) and ".." not in str(path).split("/")[-3:]
