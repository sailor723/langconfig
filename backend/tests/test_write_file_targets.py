"""Where write_file puts a file, and what it tells the agent afterwards.

The md/text path is the only writer that stores content verbatim, so it is the
one that has to be boringly predictable: the folder the caller named is the
folder it gets, nothing leaves the workspace, and the result names the file's
real location (a bare "report.md" in the result is how a .md write ends up being
reported to a user as a .docx deliverable).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import native_impl

WRITE = native_impl._write_file_impl


@pytest.fixture
def workspace(tmp_path):
    """A stand-in agent workspace with the canonical subfolders."""
    root = tmp_path / "agent_999"
    for sub in ("upload", "generated", "skills", "other"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _write(workspace, file_path, content="content\n"):
    return WRITE(file_path, content, _workspace_context={"workspace_root": str(workspace),
                                                         "project_id": 1})


# ── where it goes ────────────────────────────────────────────────────────────
def test_bare_filename_lands_in_generated(workspace):
    result = _write(workspace, "report.md", "# Report\n")

    assert "Successfully wrote" in result
    assert "generated/report.md" in result          # the real location, not the basename
    assert (workspace / "generated" / "report.md").read_text() == "# Report\n"


def test_named_subfolders_are_honoured(workspace):
    _write(workspace, "generated/deliverable.md", "deliverable\n")
    _write(workspace, "other/scratch.md", "scratch\n")

    assert (workspace / "generated" / "deliverable.md").exists()
    assert (workspace / "other" / "scratch.md").exists()      # the skill promises this
    assert not (workspace / "generated" / "scratch.md").exists()


def test_deeper_paths_are_created(workspace):
    result = _write(workspace, "other/2026/q1/notes.md", "nested\n")

    assert (workspace / "other" / "2026" / "q1" / "notes.md").read_text() == "nested\n"
    assert "other/2026/q1/notes.md" in result


def test_upload_folder_is_refused_and_untouched(workspace):
    result = _write(workspace, "upload/mine.md")

    assert result.startswith("Error:")
    assert "read-only" in result
    assert list((workspace / "upload").iterdir()) == []


def test_parent_traversal_is_refused(workspace, tmp_path):
    result = _write(workspace, "../../escape.md")

    assert result.startswith("Error:")
    assert ".." in result
    assert not (tmp_path / "escape.md").exists()


def test_absolute_path_inside_the_workspace_is_accepted(workspace):
    result = _write(workspace, f"{workspace}/other/abs.md", "absolute\n")

    assert "other/abs.md" in result
    assert (workspace / "other" / "abs.md").read_text() == "absolute\n"


def test_absolute_path_outside_the_workspace_is_refused(workspace):
    result = _write(workspace, "/tmp/definitely-outside.md")

    assert result.startswith("Error:")
    assert "outside this agent's workspace" in result


@pytest.mark.parametrize("path", ["backend/x.md", "src/x.md", "core/x.md", "services/x.md"])
def test_source_tree_heads_are_refused(workspace, path):
    result = _write(workspace, path)

    assert result.startswith("Error:")
    assert "protected directory component" in result


def test_a_protected_word_deeper_in_the_path_is_fine(workspace):
    """The rule is about where a path starts, not about banning the word."""
    result = _write(workspace, "other/core/notes.md", "scratch mirror\n")

    assert result.startswith("Successfully")
    assert (workspace / "other" / "core" / "notes.md").exists()


def test_skills_folder_is_writable(workspace):
    assert "Successfully" in _write(workspace, "skills/agent-made.md", "note\n")


def test_filename_only_request_without_a_name_is_refused(workspace):
    assert _write(workspace, "").startswith("Error:")
    assert _write(workspace, "generated/").startswith("Error:")


# ── what it writes, verbatim ─────────────────────────────────────────────────
def test_markdown_is_stored_verbatim(workspace):
    source = "# 报告\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**bold** and `code`\n"
    _write(workspace, "zh.md", source)

    assert (workspace / "generated" / "zh.md").read_text(encoding="utf-8") == source


def test_crlf_and_encoding_are_not_rewritten(workspace):
    _write(workspace, "crlf.txt", "line1\r\nline2\r\n")

    raw = (workspace / "generated" / "crlf.txt").read_bytes()
    assert raw == b"line1\r\nline2\r\n"
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_empty_content_is_allowed(workspace):
    assert "Successfully wrote 0 characters" in _write(workspace, "empty.md", "")


def test_extension_case_does_not_change_the_format(workspace):
    result = _write(workspace, "DATA.CSV", "a,b\n1,2\n")

    assert "written verbatim" in result
    assert (workspace / "generated" / "DATA.CSV").read_text() == "a,b\n1,2\n"


def test_file_without_extension_is_plain_text(workspace):
    assert "written verbatim" in _write(workspace, "notes", "no extension\n")


def test_overwriting_replaces_the_content(workspace):
    _write(workspace, "report.md", "first\n")
    _write(workspace, "report.md", "second\n")

    assert (workspace / "generated" / "report.md").read_text() == "second\n"


# ── what the agent is told ───────────────────────────────────────────────────
def test_result_names_the_path_size_and_that_it_was_verbatim(workspace):
    result = _write(workspace, "other/notes.md", "abcde")

    assert "generated/" not in result.split("to ")[-1].split(" ")[0]
    assert "other/notes.md" in result
    assert "5 characters" in result
    assert "5 bytes" in result
    assert "written verbatim" in result


def test_result_says_when_a_format_was_rendered(workspace):
    result = _write(workspace, "other/report.docx", "# H\n\ntext\n")

    assert "other/report.docx" in result
    assert "Word document rendered from your markdown" in result
    assert (workspace / "other" / "report.docx").stat().st_size > 1000     # a real .docx


def test_default_workspace_without_context_uses_the_base_dir(tmp_path, monkeypatch):
    class _Manager:
        base_dir = tmp_path

        def persist_output(self, *_a, **_k):
            return None

    monkeypatch.setattr("services.workspace_manager.get_workspace_manager", lambda: _Manager())

    result = WRITE("standalone.md", "no context\n")

    assert "standalone.md" in result
    assert (tmp_path / "default" / "standalone.md").read_text() == "no context\n"
