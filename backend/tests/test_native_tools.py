# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the tools-audit additions (docs/tools-audit.md):
delete_file / rename_file / move_file / mkdir / bash / read_image,
plus glob/grep still working. All file ops run inside the workspace sandbox.
"""

import shutil
from pathlib import Path

import pytest

from tools.native_impl import (
    bash, delete_file, glob, grep, mkdir, move_file, read_file,
    read_image, rename_file,
)


@pytest.fixture
def sandbox_dir():
    """A unique dir under the workspace sandbox root, cleaned up after."""
    from tools.native_impl import _sandbox_roots
    root = Path(_sandbox_roots()[0])
    test_dir = root / f".tool_audit_test_{id(object())}"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    shutil.rmtree(test_dir, ignore_errors=True)


# ── filesystem management ────────────────────────────────────────────────────

def test_mkdir_rename_move_delete_roundtrip(sandbox_dir):
    sub = sandbox_dir / "sub"
    assert "Created directory" in mkdir.invoke({"directory_path": str(sub)})

    src = sandbox_dir / "a.txt"
    src.write_text("hello\nworld\n", encoding="utf-8")
    renamed = sandbox_dir / "b.txt"
    assert "Renamed" in rename_file.invoke({"old_path": str(src), "new_path": str(renamed)})
    assert renamed.exists() and not src.exists()

    moved = sub / "b.txt"
    assert "Moved" in move_file.invoke({"source": str(renamed), "destination": str(sub)})
    assert moved.exists()

    assert "Deleted" in delete_file.invoke({"file_path": str(moved)})
    assert not moved.exists()


def test_fs_tools_refuse_sandbox_escape(sandbox_dir):
    outside = str(Path("/tmp/langconfig-audit-escape-test"))
    assert "outside the allowed workspace" in delete_file.invoke({"file_path": outside})
    assert "outside the allowed workspace" in mkdir.invoke({"directory_path": outside})


def test_glob_grep_still_work(sandbox_dir):
    (sandbox_dir / "code.py").write_text("def main():\n    pass\n", encoding="utf-8")
    files = glob.invoke({"pattern": "**/*.py", "path": str(sandbox_dir)})
    assert "code.py" in files
    found = grep.invoke({"pattern": "def main", "path": str(sandbox_dir)})
    assert "def main" in found


# ── bash ─────────────────────────────────────────────────────────────────────

def test_bash_runs_command():
    result = bash.invoke({"command": "echo audit-ok"})
    assert "audit-ok" in result
    assert "exit 0" in result


def test_bash_timeout():
    result = bash.invoke({"command": "sleep 5", "timeout": 1})
    assert "timed out" in result.lower()


def test_bash_sandbox_cwd():
    result = bash.invoke({"command": "pwd"})
    assert "outputs" in result  # cwd is the workspace outputs root


# ── read_image (OCR) ─────────────────────────────────────────────────────────

def test_read_image_returns_metadata_or_text(sandbox_dir):
    from PIL import Image

    png = sandbox_dir / "img.png"
    Image.new("RGB", (60, 30), "white").save(png)
    result = read_image.invoke({"file_path": str(png)})
    assert "Image:" in result
    assert "PNG" in result  # format reported regardless of OCR availability


def test_read_image_rejects_non_image(sandbox_dir):
    bad = sandbox_dir / "not_img.txt"
    bad.write_text("not an image", encoding="utf-8")
    assert "not a readable image" in read_image.invoke({"file_path": str(bad)})


# ── pluggable search backend ─────────────────────────────────────────────────

async def test_search_provider_falls_back_without_keys():
    """With no configured provider keys, the helper returns None → DDG path."""
    from tools.native_impl import _try_configured_search_provider
    assert await _try_configured_search_provider("test query", 3) is None
