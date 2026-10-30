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


def test_resolve_empty_means_no_tools():
    """Empty is a decision, not a missing value.

    This used to return the whole default set. That made the stored row disagree
    with the editor the user had just used: they unticked everything, the panel said
    `0/N`, and the agent ran with 28 tools while reporting, for example, web search
    and SQL it did not have. One meaning, one owner: `[]` = none.
    """
    assert resolve_native_tools([]) == []
    assert resolve_native_tools(None) == []


def test_resolve_returns_a_copy():
    """Callers mutate the result (memory tools are split out of it); they must not
    be able to edit the config they were handed."""
    configured = ["web_search"]
    out = resolve_native_tools(configured)
    out.append("bash")
    assert configured == ["web_search"]


def test_default_set_has_no_duplicates():
    assert len(DEFAULT_NATIVE_TOOLS) == len(set(DEFAULT_NATIVE_TOOLS))
