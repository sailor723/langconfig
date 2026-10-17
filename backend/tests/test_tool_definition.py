# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the DSH-style tool definition (Phase A, docs/tools-refactor.md):

- ToolDefinition parsing (defaults, invalid shapes fall back safely)
- ToolFactory attaches the definition as tool metadata
- a compiled python_function tool carries its definition and still works
"""

import pytest

from core.tools.definition import ToolDefinition, TOOL_CATEGORIES


# ── ToolDefinition parsing ───────────────────────────────────────────────────

def test_definition_defaults():
    d = ToolDefinition.from_row(None)
    assert d.category == "custom"
    assert d.order == 500
    assert d.is_concurrency_safe is True
    assert d.timeout_ms is None
    assert d.output_schema is None
    assert d.guard.approval is False
    assert d.presentation.requires_api_key is None


def test_definition_from_row():
    d = ToolDefinition.from_row({
        "category": "analysis",
        "order": 10,
        "timeout_ms": 5000,
        "is_concurrency_safe": False,
        "output_schema": {"type": "integer"},
        "guard": {"approval": True},
        "presentation": {"requires_api_key": "DEEPSEEK_API_KEY", "icon": "🧮"},
    })
    assert d.category == "analysis"
    assert d.order == 10
    assert d.timeout_ms == 5000
    assert d.is_concurrency_safe is False
    assert d.output_schema == {"type": "integer"}
    assert d.guard.approval is True
    assert d.presentation.requires_api_key == "DEEPSEEK_API_KEY"
    assert "analysis" in TOOL_CATEGORIES


def test_definition_invalid_falls_back():
    # Unknown fields are rejected (extra=forbid) -> safe defaults
    d = ToolDefinition.from_row({"category": "web", "nonsense": 1})
    assert d.category == "custom"
    # Garbage input -> defaults
    d2 = ToolDefinition.from_row("garbage")
    assert d2.category == "custom"


# ── ToolFactory wiring ───────────────────────────────────────────────────────

def _python_tool_config(definition=None):
    return {
        "tool_id": "t_definition_test",
        "name": "Definition Test",
        "description": "Doubles an integer",
        "tool_type": "python_function",
        "template_type": "custom",
        "implementation_config": {
            "function_name": "run",
            "code": "def run(x: int) -> int:\n    return x * 2",
            "args_schema": {"x": {"type": "integer", "description": "the number"}},
        },
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
        "output_format": "string",
        "is_builtin": True,
        "definition": definition,
    }


async def test_create_tool_attaches_definition():
    from core.tools.factory import ToolFactory

    tool = await ToolFactory.create_tool(_python_tool_config({
        "category": "analysis",
        "order": 10,
        "timeout_ms": 5000,
        "is_concurrency_safe": False,
    }))
    meta = (tool.metadata or {}).get("definition", {})
    assert meta["category"] == "analysis"
    assert meta["order"] == 10
    assert meta["timeout_ms"] == 5000
    assert meta["is_concurrency_safe"] is False
    assert meta["section"] == "analysis"
    # the tool still compiles and runs
    result = await tool.ainvoke({"x": 3})
    assert str(result) == "6"


async def test_create_tool_without_definition_defaults():
    from core.tools.factory import ToolFactory

    tool = await ToolFactory.create_tool(_python_tool_config())
    meta = (tool.metadata or {}).get("definition", {})
    assert meta["category"] == "custom"
    assert meta["order"] == 500
    result = await tool.ainvoke({"x": 21})
    assert str(result) == "42"


# ── Seeder produces definitions ──────────────────────────────────────────────

def test_seed_build_row_emits_definition():
    """The built-in seeder's row payload carries a definition with a
    definition-category derived from the display category."""
    # The seeder lives under scripts/seeds/in/ and is not an importable
    # package, so load it by path.
    import importlib.util
    from pathlib import Path as _Path

    _seeder_path = (_Path(__file__).resolve().parents[1]
                    / "scripts" / "seeds" / "in" / "seed_builtin_tools.py")
    _spec = importlib.util.spec_from_file_location("seed_builtin_tools", _seeder_path)
    seeder = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(seeder)

    payload = seeder._build_row(
        "web_search",  # tool name
        lambda *a, **k: None,  # placeholder obj (only metadata used below)
        ("Web Search", "web", None),
        order=1,
    )
    # definition is present and parseable
    definition = ToolDefinition.from_row(payload["definition"])
    assert definition.category == "web"
    assert definition.order == 1
