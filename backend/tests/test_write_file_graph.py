"""The writer graph (core/graphs/write_file.py) — md/text branch first.

The graph gives each output format its own node so a format can be changed (and
reviewed) on its own. Only the md/text branch is this module's own rendering; the
docx/pdf/html nodes still call the renderers that existed before, and this file
pins that boundary: the tests here must keep passing when those three are
upgraded one at a time.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.graphs import write_file as wf


def _write(tmp_path: Path, name: str, content: str = "# Hi\n\nbody\n"):
    path = tmp_path / name
    return path, wf.write_document(str(path), content)


# ── classification ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,kind", [
    ("a.md", "text"), ("a.markdown", "text"), ("a.txt", "text"), ("a.csv", "text"),
    ("a.json", "text"), ("a.py", "text"), ("a.rst", "text"), ("a", "text"),
    ("a.docx", "docx"), ("a.pdf", "pdf"), ("a.html", "html"), ("a.htm", "html"),
    ("a.pptx", "unsupported"), ("a.xlsx", "unsupported"), ("a.doc", "unsupported"),
])
def test_classify_picks_the_branch_by_extension(name, kind):
    assert wf.classify_output_node({"target_path": name})["kind"] == kind


def test_router_maps_every_kind_to_a_node():
    for kind in ("text", "docx", "pdf", "html", "unsupported"):
        assert wf.route_by_kind({"kind": kind}) == kind


def test_unwritable_formats_point_at_what_can_do_it(tmp_path):
    deck, deck_state = _write(tmp_path, "deck.pptx")
    sheet, sheet_state = _write(tmp_path, "data.xlsx")

    assert deck_state["error"] and "gen_pptx" in deck_state["result"]
    assert sheet_state["error"] and ".csv" in sheet_state["result"]
    assert not deck.exists() and not sheet.exists()


# ── the md/text branch (this module's own work) ──────────────────────────────
def test_text_is_stored_verbatim_byte_for_byte(tmp_path):
    source = "# 报告\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**bold** and `code`\r\n"
    path, state = _write(tmp_path, "notes.md", source)

    assert not state.get("error")
    assert path.read_bytes() == source.encode("utf-8")


def test_text_gets_no_bom_and_keeps_crlf(tmp_path):
    path, _ = _write(tmp_path, "crlf.txt", "line1\r\nline2\r\n")

    raw = path.read_bytes()
    assert raw == b"line1\r\nline2\r\n"
    assert not raw.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("name", ["notes.md", "data.csv", "payload.json", "script.py",
                                  "no-extension", "UPPER.MD"])
def test_every_text_extension_takes_the_same_branch(tmp_path, name):
    path, state = _write(tmp_path, name, "content\n")

    assert state["kind"] == "text"
    assert "written verbatim" in state["format_label"]
    assert path.read_text(encoding="utf-8") == "content\n"


def test_empty_content_is_allowed(tmp_path):
    path, state = _write(tmp_path, "empty.md", "")

    assert not state.get("error")
    assert path.exists() and path.stat().st_size == 0


def test_overwriting_replaces_the_content(tmp_path):
    _write(tmp_path, "report.md", "first\n")
    path, _ = _write(tmp_path, "report.md", "second\n")

    assert path.read_text() == "second\n"


# ── the rendered branches (unchanged renderers for now) ──────────────────────
@pytest.mark.parametrize("name,label_word", [
    ("report.docx", "Word"), ("report.pdf", "PDF"), ("report.html", "HTML"),
])
def test_rendered_formats_still_produce_a_file_with_the_content(tmp_path, name, label_word):
    path, state = _write(tmp_path, name, "# Report\n\nSome body text.\n")

    assert not state.get("error")
    assert path.exists() and path.stat().st_size > 200
    assert state["written_bytes"] == path.stat().st_size
    assert label_word in state["format_label"]


def test_render_failure_is_reported_not_raised(tmp_path, monkeypatch):
    from tools import native_impl

    def boom(*_a, **_k):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(native_impl, "_write_docx_file", boom)
    _path, state = _write(tmp_path, "broken.docx")

    assert state["error"] and "renderer exploded" in state["result"]


# ── verify, caps, failures ───────────────────────────────────────────────────
def test_verify_reports_the_size(tmp_path):
    path, state = _write(tmp_path, "notes.md", "hello\n")

    assert state["written_bytes"] == path.stat().st_size
    assert str(path.stat().st_size) in state["result"]


def test_verify_catches_a_file_that_was_never_written(tmp_path):
    state = wf.verify_node({"target_path": str(tmp_path / "missing.md"), "content": "x"})

    assert state["error"] and "not written" in state["result"]


def test_verify_catches_an_empty_render(tmp_path):
    empty = tmp_path / "empty.docx"
    empty.write_bytes(b"")

    state = wf.verify_node({"target_path": str(empty), "content": "# not empty"})

    assert state["error"] and "came out empty" in state["result"]


def test_content_over_the_cap_is_refused(tmp_path):
    path, state = _write(tmp_path, "big.md", "x" * (wf.MAX_CONTENT_CHARS + 1))

    assert state["error"] and "write limit" in state["result"]
    assert not path.exists()


def test_writing_to_a_directory_is_an_error(tmp_path):
    directory = tmp_path / "adir"
    directory.mkdir()

    state = wf.write_document(str(directory), "content")

    assert state["error"]


def test_cli_writes_a_file_and_reports_it(tmp_path, capsys):
    out = tmp_path / "cli.md"

    assert wf._cli([str(out), "--text", "# Hi\n"]) == 0
    assert out.read_text() == "# Hi\n"
    assert "written verbatim" in capsys.readouterr().out


def test_cli_reports_a_refusal_with_a_nonzero_exit(tmp_path, capsys):
    assert wf._cli([str(tmp_path / "deck.pptx"), "--text", "x"]) == 1
    assert "cannot write" in capsys.readouterr().out


# ── two names, one writer ────────────────────────────────────────────────────
def test_write_file_and_write_any_file_are_the_same_writer():
    """Both names are offered on purpose; they must stay one implementation.

    Two names for one tool is only safe while nothing drifts: if a future change
    edits one description or one code path, this fails and says so.
    """
    import asyncio

    from core.agents.tool_loader import ToolLoader
    from tools import native_impl

    assert native_impl.write_file.name == "write_file"
    assert native_impl.write_any_file.name == "write_any_file"
    assert native_impl.write_file.func is native_impl.write_any_file.func
    assert native_impl.write_file.args_schema is native_impl.write_any_file.args_schema

    # Both resolve to a callable tool through the loader agents use.
    for configured in ("write_file", "write_any_file"):
        loaded = asyncio.run(ToolLoader.load_native([configured]))
        assert [tool.name for tool in loaded] == [configured], configured


def test_the_two_descriptions_each_state_the_two_parameter_contract():
    from tools import native_impl

    for tool in (native_impl.write_file, native_impl.write_any_file):
        text = tool.description
        assert "file_path" in text and "content" in text
        assert "verbatim" in text                     # md/text contract
        assert ".docx" in text and ".pdf" in text and ".html" in text
        assert "generated/" in text and "upload/" in text
