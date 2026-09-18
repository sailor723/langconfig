# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Per-agent tool parameters (``tool_params``).

Lets an agent configuration pin values onto its tools — e.g.
``{"neo4j_agent_tool": {"database": "neo4j"}}`` — so the agent *knows* which
database to query at runtime. Pinned params are **hard-pinned**: they are
removed from the model's tool schema and injected on every invocation, so the
configured value is authoritative (the model cannot override or forget it).

Config shape (stored in ``deep_agent_templates.config.tool_params``):
    tool_params = {
        "<tool_id>": { "<param>": <value>, ... },
        ...
    }

Wiring: both factories apply this to their loaded tool set —
``AgentFactory.create_agent`` (core/agents/factory/assembly.py) and
``DeepAgentFactory._load_base_tools`` (services/deepagent_factory/support.py)
— so it works identically for normal agents and DeepAgents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool
from pydantic import create_model

logger = logging.getLogger(__name__)


def apply_tool_params(
    tools: List[BaseTool],
    tool_params: Optional[Dict[str, Dict[str, Any]]],
) -> List[BaseTool]:
    """Bind per-agent default params onto the loaded tools (no-op when unset).

    For every tool whose id/name appears in ``tool_params``, return a copy of
    the tool whose args schema carries the configured defaults. Params the
    model omits fall back to the configured value; params it supplies win.
    Tools not mentioned pass through untouched.
    """
    if not tool_params:
        return tools

    out: List[BaseTool] = []
    for tool in tools:
        tool_id = getattr(tool, "tool_id", None) or tool.name
        params = tool_params.get(tool_id) or tool_params.get(tool.name)
        if not params:
            out.append(tool)
            continue
        try:
            out.append(_with_defaults(tool, params))
        except Exception as exc:  # noqa: BLE001 — never break agent build
            logger.warning(
                f"tool_params: failed to bind {params!r} onto '{tool.name}': {exc} "
                "(tool used unmodified)"
            )
            out.append(tool)
    return out


def _with_defaults(tool: BaseTool, defaults: Dict[str, Any]) -> BaseTool:
    """Return a StructuredTool copy of ``tool`` with params hard-pinned.

    Pinned params (e.g. ``database``) are REMOVED from the LLM-facing args
    schema — the model neither sees nor can override them — and the configured
    value is injected on every invocation. This makes the agent's configured
    target (e.g. the Neo4j database) authoritative at runtime.
    """
    from langchain_core.tools import StructuredTool

    schema = tool.args_schema
    fields: Dict[str, Any] = {}
    if schema is not None:
        for name, field in schema.model_fields.items():
            if name in defaults:
                # Hard-pinned: hidden from the model, injected at call time.
                continue
            fields[name] = (
                field.annotation,
                _pydantic_field(field),
            )
    new_schema = create_model(f"{tool.name}Schema", **fields) if fields else None

    async def _afunc(**kwargs: Any) -> Any:
        merged = {**defaults, **kwargs}
        return await tool.ainvoke(merged)

    def _func(**kwargs: Any) -> Any:
        merged = {**defaults, **kwargs}
        return tool.invoke(merged)

    # Mirror the original tool's sync/async surface: DB-backed tools
    # (ToolFactory python_function) are async-only — wrapping them with a sync
    # func would break sync invocation with NotImplementedError. Only expose
    # a sync func when the original has one.
    build_kwargs: Dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "args_schema": new_schema,
    }
    if tool.coroutine is not None:
        build_kwargs["coroutine"] = _afunc
    if tool.func is not None or tool.coroutine is None:
        build_kwargs["func"] = _func

    return StructuredTool.from_function(**build_kwargs)


def _pydantic_field(field: Any, default: Any = None):
    """Rebuild a pydantic Field, preserving description/annotation semantics.

    ``field.default`` is ``PydanticUndefined`` for required fields — in that
    case, without an explicit pinned ``default``, the field stays required
    (passing ``...`` as the default marks it required).
    """
    from pydantic import Field

    kw: Dict[str, Any] = {}
    if field.description is not None:
        kw["description"] = field.description
    if default is not None:
        kw["default"] = default
        return Field(**kw)

    is_required = field.default is None or _is_undefined(field.default)
    if is_required:
        kw["default"] = ...
    else:
        kw["default"] = field.default
    return Field(**kw)


def _is_undefined(value: Any) -> bool:
    try:
        from pydantic_core import PydanticUndefined
        return value is PydanticUndefined
    except Exception:  # pragma: no cover
        return False
