# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for Code Mode (Phase C, docs/tools-refactor.md): the run_code tool
dispatches to compiled tools through the generated Python SDK; the sandbox
blocks imports/forbidden calls; output is curated (print/return only).
"""

import pytest
from langchain_core.tools import StructuredTool

import core.tools.code_mode as cm
from core.tools.code_mode import create_run_code_tool, generate_python_sdk


def _double_tool() -> StructuredTool:
    def _double(x: int) -> str:
        return str(x * 2)

    return StructuredTool.from_function(func=_double, name="double", description="Doubles an integer")


def _add_tool() -> StructuredTool:
    def _add(a: int, b: int) -> str:
        return str(a + b)

    return StructuredTool.from_function(func=_add, name="add", description="Adds two integers")


# ── SDK generation ───────────────────────────────────────────────────────────

def test_sdk_generation_has_async_stubs():
    source = generate_python_sdk([_double_tool(), _add_tool()])
    assert "async def double(**kwargs):" in source
    assert "async def add(**kwargs):" in source
    assert "return await _dispatch('double', **kwargs)" in source
    assert "Doubles an integer" in source


def test_sdk_skips_run_code_itself():
    run_tool = create_run_code_tool([_double_tool()])
    source = generate_python_sdk([run_tool, _double_tool()])
    assert "async def run_code" not in source


# ── run_code execution ───────────────────────────────────────────────────────

async def test_run_code_calls_sdk_tool():
    tool = create_run_code_tool([_double_tool(), _add_tool()])
    result = await tool.ainvoke({
        "code": "r = await tools.double(x=21)\nprint('doubled:', r)",
        "description": "double 21",
    })
    assert "doubled: 42" in result


async def test_run_code_return_value_curated():
    tool = create_run_code_tool([_add_tool()])
    result = await tool.ainvoke({
        "code": "return await tools.add(a=19, b=23)",
        "description": "add",
    })
    assert "<return> 42" in result


async def test_run_code_multiple_tool_calls():
    tool = create_run_code_tool([_double_tool(), _add_tool()])
    result = await tool.ainvoke({
        "code": (
            "a = await tools.add(a=10, b=5)\n"
            "b = await tools.double(x=int(a))\n"
            "print(a, b)"
        ),
        "description": "chain",
    })
    assert "15 30" in result


# ── sandbox ──────────────────────────────────────────────────────────────────

async def test_run_code_rejects_imports():
    tool = create_run_code_tool([_double_tool()])
    result = await tool.ainvoke({"code": "import os\nprint(os.getcwd())", "description": "bad"})
    assert "cannot import" in result.lower()


async def test_run_code_rejects_forbidden_calls():
    tool = create_run_code_tool([_double_tool()])
    result = await tool.ainvoke({"code": "open('/etc/passwd')", "description": "bad"})
    assert "cannot call 'open'" in result


async def test_run_code_rejects_forbidden_attrs():
    tool = create_run_code_tool([_double_tool()])
    result = await tool.ainvoke({"code": "print(os.getcwd())", "description": "bad"})
    assert "cannot touch 'os'" in result


async def test_run_code_program_error_reported():
    tool = create_run_code_tool([_double_tool()])
    result = await tool.ainvoke({"code": "x = 1 / 0", "description": "boom"})
    assert "run_code failed" in result


async def test_run_code_timeout(monkeypatch):
    import asyncio

    async def _slow(x: int) -> str:
        await asyncio.sleep(5)
        return str(x)

    slow_tool = StructuredTool.from_function(coroutine=_slow, name="slow", description="slow tool")
    monkeypatch.setattr(cm, "DEFAULT_RUN_CODE_TIMEOUT", 1)
    tool = create_run_code_tool([slow_tool])
    result = await tool.ainvoke({"code": "return await tools.slow(x=1)", "description": "slow"})
    assert "timed out" in result.lower()


# ── agent wiring helper ──────────────────────────────────────────────────────

def test_code_mode_tool_is_single_run_code():
    tool = create_run_code_tool([_double_tool(), _add_tool()])
    assert tool.name == "run_code"
    meta = (tool.metadata or {}).get("definition", {})
    assert meta["category"] == "code"
