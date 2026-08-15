# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for the default native-tool set (docs/tools-audit.md)."""

from core.tools.defaults import DEFAULT_NATIVE_TOOLS, resolve_native_tools


def test_default_set_is_curated():
    d = DEFAULT_NATIVE_TOOLS
    # universal base present
    for tool in ("think_tool", "reasoning_chain", "write_todos", "read_todos",
                 "web_search", "web_fetch", "read_file", "write_file", "edit_file",
                 "ls", "glob", "grep", "delete_file", "rename_file", "move_file",
                 "mkdir", "bash", "skill", "save_document"):
        assert tool in d, tool
    # specialized/opt-in tools excluded
    for tool in ("pg_query", "pg_execute", "python_execute", "sqlite_execute",
                 "neo4j_query", "graphindex_search", "create_deepagent",
                 "create_skill", "tavily_search", "browser", "memory_store",
                 "memory_recall", "task", "gen_pptx"):
        assert tool not in d, f"{tool} should not be default"


def test_resolve_configured_wins():
    configured = ["web_search", "bash"]
    assert resolve_native_tools(configured) == configured


def test_resolve_empty_uses_defaults():
    assert resolve_native_tools(None) == DEFAULT_NATIVE_TOOLS
    assert resolve_native_tools([]) == DEFAULT_NATIVE_TOOLS


def test_resolve_disabled_forces_empty():
    assert resolve_native_tools(None, enable_default_tools=False) == []
    assert resolve_native_tools(["web_search"], enable_default_tools=False) == ["web_search"]


def test_default_set_has_no_duplicates():
    assert len(DEFAULT_NATIVE_TOOLS) == len(set(DEFAULT_NATIVE_TOOLS))
