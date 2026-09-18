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
                 "memory_store", "memory_recall", "web_search", "web_fetch",
                 "tavily_search", "rename_file", "move_file", "mkdir", "bash",
                 "skill", "save_document"):
        assert tool in d, tool
    # db/analysis/retrieval categories present (read-only db; no pg_execute)
    for tool in ("pg_list_tables", "pg_describe_table", "pg_query",
                 "sqlite_execute", "sqlite_load_csv", "python_execute",
                 "save_analysis_result", "graphindex_search", "graphindex_load",
                 "doc_index_list"):
        assert tool in d, f"{tool} should be default"
    # excluded: db writes, heavy, meta, graph ops, custom (tavily_search is now
    # a default web tool — AI-optimized search, key-gated, graceful without key)
    for tool in ("pg_execute", "browser", "neo4j_query", "neo4j_upsert_doc",
                 "graphindex_ingest", "create_deepagent", "create_skill",
                 "update_skill", "delete_skill", "task", "gen_pptx"):
        assert tool not in d, f"{tool} should not be default"
    # filesystem tools are provided by the deepagents SDK FilesystemMiddleware
    # (default for all agents, format-aware via FormatAwareBackend); only tools
    # the SDK lacks (rename/move/mkdir) stay native.
    for tool in ("ls", "read_file", "write_file", "edit_file", "glob", "grep",
                 "delete_file", "read_image"):
        assert tool not in d, f"{tool} should not be default (SDK provides it)"


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
