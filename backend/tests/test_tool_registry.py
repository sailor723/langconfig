# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for Phase B of docs/tools-refactor.md:

- ToolRegistry: legacy definitions merged + ordered; resolve_for_agent
  (canonical names, aliases, ordering); run_code reserved.
- Tool pipeline: approval guard, timeout, output-schema normalization,
  pass-through for tools without enforcement.
"""

import asyncio

import pytest
from langchain_core.tools import StructuredTool

from core.tools.definition import ToolDefinition
from core.tools.pipeline import apply_tool_pipeline, approval_gate
from core.tools.registry import RUN_CODE_NAME, ToolRegistry, get_tool_registry_service


def _make_tool(name: str, fn, definition: dict | None = None) -> StructuredTool:
    kwargs = (
        {"coroutine": fn} if asyncio.iscoroutinefunction(fn) else {"func": fn}
    )
    tool = StructuredTool.from_function(**kwargs, name=name, description=f"{name} tool")
    if definition:
        tool.metadata = {"definition": ToolDefinition.from_row(definition).to_metadata()}
    return tool


# ── ToolRegistry ─────────────────────────────────────────────────────────────

def test_registry_lists_legacy_definitions_ordered():
    reg = ToolRegistry()
    entries = reg.list_definitions(project_id=0)  # no DB rows expected in tests
    ids = [e["tool_id"] for e in entries]
    # the 9 legacy-only tools are always present
    for legacy in ("browser", "think_tool", "memory_store", "memory_recall",
                   "write_todos", "read_todos", "vfs_ls", "vfs_read_file", "vfs_write_file"):
        assert legacy in ids
    # ordered by definition.order
    orders = [e["order"] for e in entries]
    assert orders == sorted(orders)
    browser = next(e for e in entries if e["tool_id"] == "browser")
    assert browser["category"] == "web"
    assert browser["order"] == 10


def test_registry_definition_for_unknown_returns_none():
    reg = ToolRegistry()
    assert reg.definition_for("no_such_tool", project_id=0) is None


def test_registry_resolve_for_agent_orders_and_deduplicates():
    reg = ToolRegistry()
    agent_config = {
        "native_tools": ["web_search", "write_file", "browser", "tavily"],
        "cli_tools": ["read_file"],
        "custom_tools": ["my_custom"],
        "enable_memory": True,
    }
    resolved = reg.resolve_for_agent(agent_config, project_id=0)
    # canonical names, deduplicated, memory tools added
    assert resolved.count("read_file") == 1
    assert "memory_store" in resolved and "memory_recall" in resolved
    # alias maps to canonical
    assert "tavily" not in resolved
    assert "tavily_search" in resolved
    # ordered by definition order: legacy browser (order 10) precedes the
    # unknown custom tool (default 500); DB seeded built-ins may sort earlier.
    assert resolved.index("browser") < resolved.index("my_custom")
    assert resolved.index("browser") < resolved.index("memory_store")


def test_run_code_reserved():
    assert RUN_CODE_NAME == "run_code"


# ── pipeline: approval guard ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_approval_gate():
    approval_gate.reset()
    yield
    approval_gate.reset()


async def test_pipeline_blocks_ungranted_approval_tool():
    calls = []

    def _dangerous(x: int) -> str:
        calls.append(x)
        return f"ran {x}"

    tool = _make_tool("danger_tool", _dangerous, {
        "category": "web", "guard": {"approval": True},
    })
    (wrapped,) = apply_tool_pipeline([tool])
    result = await wrapped.ainvoke({"x": 1})
    assert "requires human approval" in str(result)
    assert calls == []  # never executed

    # grant → runs
    approval_gate.grant("danger_tool")
    result = await wrapped.ainvoke({"x": 2})
    assert str(result) == "ran 2"
    assert calls == [2]


# ── pipeline: timeout ────────────────────────────────────────────────────────

async def test_pipeline_timeout_enforced():
    async def _slow(x: int) -> str:
        await asyncio.sleep(0.2)
        return f"slow {x}"

    tool = _make_tool("slow_tool", _slow, {"timeout_ms": 50})
    (wrapped,) = apply_tool_pipeline([tool])
    with pytest.raises(asyncio.TimeoutError):
        await wrapped.ainvoke({"x": 1})

    # a fast tool under the same timeout runs fine
    async def _fast(x: int) -> str:
        return f"fast {x}"

    tool2 = _make_tool("fast_tool", _fast, {"timeout_ms": 5000})
    (wrapped2,) = apply_tool_pipeline([tool2])
    assert str(await wrapped2.ainvoke({"x": 9})) == "fast 9"


# ── pipeline: output schema (declare now, enforce gradually) ─────────────────

async def test_pipeline_output_schema_normalizes():
    def _json_tool() -> dict:
        return {"ok": True, "data": 1}

    tool = _make_tool("json_tool", _json_tool, {"output_schema": {"type": "object", "required": ["ok"]}})
    (wrapped,) = apply_tool_pipeline([tool])
    result = await wrapped.ainvoke({})
    assert result == {"ok": True, "data": 1}  # valid → unchanged

    # missing required key → still returned (gradual), no crash
    def _bad_json() -> dict:
        return {"data": 1}

    tool2 = _make_tool("bad_json_tool", _bad_json, {"output_schema": {"type": "object", "required": ["ok"]}})
    (wrapped2,) = apply_tool_pipeline([tool2])
    assert await wrapped2.ainvoke({}) == {"data": 1}


# ── pipeline: pass-through ───────────────────────────────────────────────────

async def test_pipeline_passthrough_without_enforcement():
    def _plain(x: int) -> str:
        return str(x)

    tool = _make_tool("plain_tool", _plain, {"category": "web"})  # no enforcement keys
    (wrapped,) = apply_tool_pipeline([tool])
    assert wrapped is tool  # unchanged instance
    assert str(await wrapped.ainvoke({"x": 7})) == "7"


def test_service_singleton():
    assert get_tool_registry_service() is get_tool_registry_service()
