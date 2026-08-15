# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Code Mode (Phase C of docs/tools-refactor.md) — the DSH ``run_code`` transport
on the compile model.

When an agent has ``code_mode`` enabled, it exposes a SINGLE tool, ``run_code``:
the model writes a Python program whose body calls the agent's other tools
through a generated SDK (``await tools.web_search(...)``). Sub-dispatches run
the compiled tools directly; only the curated program output (print/return)
enters model history.

Trust model: the program is model-generated (untrusted) — executed in-process
with a restricted namespace (no ``__import__``/``open``/``eval``/``exec``/``os``/
``sys``/``subprocess``…), guarded by AST validation. The only outside surface it
can reach is the agent's own compiled tools (already inside their trust
boundaries).
"""

from __future__ import annotations

import asyncio
import ast
import logging
import textwrap
from types import SimpleNamespace
from typing import Any, Dict, List

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from core.tools.registry import RUN_CODE_NAME

logger = logging.getLogger(__name__)

# Cooperative timeout for one program run.
DEFAULT_RUN_CODE_TIMEOUT = 120

# Names the program must not reach directly (the SDK + print are injected).
_FORBIDDEN_CALLS = {"__import__", "open", "eval", "exec", "compile", "input",
                    "breakpoint", "globals", "locals", "vars"}
_FORBIDDEN_ATTR_ROOTS = {"os", "sys", "pathlib", "io", "subprocess", "builtins"}


def _validate_code(code: str) -> str | None:
    """AST validation for a run_code program; returns an error string or None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error: {e}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "run_code programs cannot import modules — use the `tools` SDK instead"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _FORBIDDEN_CALLS:
            return f"run_code programs cannot call '{node.func.id}'"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in _FORBIDDEN_ATTR_ROOTS:
            return (f"run_code programs cannot touch '{node.value.id}' — "
                    f"use the `tools` SDK instead")
    return None


def generate_python_sdk(tools: List[BaseTool]) -> str:
    """Generate a Python SDK module: one ``async def name(**kwargs)`` per tool.

    Each stub carries a docstring with the tool's LLM description and its
    argument names, so the model knows how to call it. The ``_dispatch``
    function is injected at runtime.
    """
    parts = [
        '"""Generated tool SDK — call tools as `await tools.<name>(**kwargs)`."""',
        "",
    ]
    for tool in tools:
        name = getattr(tool, "name", "")
        if not name or name == RUN_CODE_NAME:
            continue
        desc = (getattr(tool, "description", "") or name).replace('"""', "'''")
        fields = getattr(getattr(tool, "args_schema", None), "model_fields", {}) or {}
        params = ", ".join(f"{n}" for n in fields) or "**kwargs"
        parts.append(f"async def {name}(**kwargs):")
        parts.append(f'    """{desc[:400]}\n\n    Params: {params}."""')
        parts.append(f"    return await _dispatch({name!r}, **kwargs)")
        parts.append("")
    return "\n".join(parts)


def _make_dispatch(tools_by_name: Dict[str, BaseTool]):
    async def _dispatch(name: str, **kwargs: Any) -> Any:
        tool = tools_by_name.get(name)
        if tool is None:
            return f"⚠️ tool '{name}' is not available to this agent"
        try:
            return await tool.ainvoke(kwargs)
        except Exception as exc:  # noqa: BLE001 — tool errors are model-facing
            return f"❌ tool '{name}' failed: {type(exc).__name__}: {exc}"
    return _dispatch


def create_run_code_tool(tools: List[BaseTool]) -> BaseTool:
    """Build the ``run_code`` tool bound to the agent's compiled tools."""
    tools_by_name: Dict[str, BaseTool] = {t.name: t for t in tools if t.name}
    sdk_ns: Dict[str, Any] = {"_dispatch": _make_dispatch(tools_by_name)}
    exec(generate_python_sdk(list(tools_by_name.values())), sdk_ns)
    sdk = {k: v for k, v in sdk_ns.items() if not k.startswith("_")}

    import builtins as _builtins_mod

    restricted_builtins = {
        name: getattr(_builtins_mod, name)
        for name in ("print", "len", "str", "int", "float", "bool", "list",
                     "dict", "set", "tuple", "range", "enumerate", "zip", "map",
                     "filter", "sum", "min", "max", "abs", "round", "sorted",
                     "reversed", "any", "all", "isinstance", "hasattr", "getattr",
                     "setattr", "type", "repr", "Exception", "ValueError",
                     "TypeError", "RuntimeError", "True", "False", "None",
                     "BaseException", "AttributeError", "KeyError", "IndexError",
                     "StopIteration", "MemoryError", "NotImplementedError",
                     "TimeoutError", "ArithmeticError", "NameError")
    }

    async def _run_code(code: str, description: str = "") -> str:
        error = _validate_code(code)
        if error:
            return f"❌ {error}"
        captured: List[str] = []

        def _print(*args: Any) -> None:
            captured.append(" ".join(str(a) for a in args))

        env: Dict[str, Any] = {
            "tools": SimpleNamespace(**sdk),
            "print": _print,
            "__builtins__": restricted_builtins,
        }
        wrapped = "async def _prog():\n" + textwrap.indent(code, "    ")
        try:
            exec(wrapped, env)
            result = await asyncio.wait_for(env["_prog"](), timeout=DEFAULT_RUN_CODE_TIMEOUT)
        except asyncio.TimeoutError:
            return f"⚠️ run_code program timed out after {DEFAULT_RUN_CODE_TIMEOUT}s"
        except Exception as exc:  # noqa: BLE001 — program errors are model-facing
            return f"❌ run_code failed: {type(exc).__name__}: {exc}"
        lines = list(captured)
        if result is not None:
            lines.append(f"<return> {result}")
        return "\n".join(lines) if lines else "(no output)"

    class _RunCodeArgs(BaseModel):
        code: str = Field(description="The body of an async Python function; "
                                       "top-level `await` and `return` work. "
                                       "Call tools as `await tools.<name>(**kwargs)`.")
        description: str = Field(default="", description="A short summary of what the program does.")

    return StructuredTool.from_function(
        coroutine=_run_code,
        name=RUN_CODE_NAME,
        description=(
            "Execute a Python program against the available tools. Takes two "
            "arguments: `code` (the body of an async function; top-level "
            "`await` and `return` work) and `description` (a short summary). "
            "Call tools as `await tools.name(args)` per the SDK in the system "
            "prompt. Only what you print or return comes back — curate it."
        ),
        args_schema=_RunCodeArgs,
        metadata={"definition": {
            "category": "code", "order": 5, "section": "code",
            "timeout_ms": DEFAULT_RUN_CODE_TIMEOUT * 1000,
            "is_concurrency_safe": False,
        }},
    )
