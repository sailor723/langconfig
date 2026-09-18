# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Execution pipeline around compiled tools (DSH pre/guard/around/post, Phase B
of docs/tools-refactor.md).

``apply_tool_pipeline(tools)`` wraps every compiled tool whose declarative
definition asks for enforcement:

- ``guard.approval``  → the tool refuses to run unless the call has been
  explicitly approved (HITL). ``ApprovalGate`` is the Phase-B seam: code that
  grants approval (e.g. an approval UI/API in a later phase) calls
  ``ApprovalGate.grant(name)``; tools without a grant return a blocking
  message instead of executing.
- ``timeout_ms``     → cooperative timeout via ``asyncio.wait_for``.
- ``output_schema``  → declared-now / enforced-gradually: when the schema is
  present and the result is JSON-shaped, a light check runs (``jsonschema``
  when available, else a required-key check); strings and non-JSON results
  pass through unchanged.

Tools without enforcement needs pass through untouched — the pipeline is
additive and never breaks the direct-call flow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool

from core.tools.definition import ToolDefinition

logger = logging.getLogger(__name__)

_APPROVAL_TIMEOUT = 3600  # grants expire after an hour (safety)


class ApprovalGate:
    """Phase-B approval seam: granted tool names (with expiry)."""

    def __init__(self) -> None:
        self._granted: Dict[str, float] = {}

    def grant(self, tool_name: str, ttl_seconds: float = _APPROVAL_TIMEOUT) -> None:
        self._granted[tool_name] = time.monotonic() + ttl_seconds

    def is_granted(self, tool_name: str) -> bool:
        now = time.monotonic()
        expiry = self._granted.get(tool_name)
        if expiry is None:
            return False
        if expiry < now:
            self._granted.pop(tool_name, None)
            return False
        return True

    def revoke(self, tool_name: str) -> None:
        self._granted.pop(tool_name, None)

    def reset(self) -> None:
        self._granted.clear()


approval_gate = ApprovalGate()


def _normalize_output(definition: ToolDefinition, result: Any) -> Any:
    """Light output-schema check (declared now, enforced gradually)."""
    schema = definition.output_schema
    if not schema or not isinstance(result, dict):
        return result
    try:
        import jsonschema  # noqa: F401

        jsonschema.validate(result, schema)
        return result
    except Exception:
        pass
    # Fallback / jsonschema unavailable: check required keys only.
    required = schema.get("required") or []
    if required and any(k not in result for k in required):
        missing = [k for k in required if k not in result]
        logger.warning(
            f"tool output missing required keys {missing} (schema declared)"
        )
    return result


def _wrap_tool(tool: BaseTool, definition: ToolDefinition) -> BaseTool:
    """Wrap one tool with its definition's enforcement (guard/timeout/normalize)."""
    original_invoke = tool.ainvoke

    async def _pipeline_invoke(**kwargs: Any) -> Any:
        # guard: approval required → block unless granted
        if definition.guard.approval and not approval_gate.is_granted(tool.name):
            return (
                f"⚠️ Tool '{tool.name}' requires human approval and was not "
                "approved — describe the action to the user and ask for "
                "permission before retrying."
            )
        # timeout
        coro = original_invoke(kwargs)
        if definition.timeout_ms:
            coro = asyncio.wait_for(coro, definition.timeout_ms / 1000.0)
        result = await coro
        # normalize
        return _normalize_output(definition, result)

    return StructuredTool.from_function(
        coroutine=_pipeline_invoke,
        name=tool.name,
        description=getattr(tool, "description", tool.name),
        args_schema=getattr(tool, "args_schema", None),
        metadata=dict(getattr(tool, "metadata", None) or {}),
    )


def apply_tool_pipeline(tools: List[BaseTool]) -> List[BaseTool]:
    """Wrap every tool whose definition requires enforcement. Additive —
    tools without timeout/approval/output-schema pass through unchanged."""
    wrapped: List[BaseTool] = []
    for tool in tools:
        raw = (getattr(tool, "metadata", None) or {}).get("definition")
        definition = ToolDefinition.from_row(raw)
        needs_enforcement = (
            definition.guard.approval
            or definition.timeout_ms is not None
            or definition.output_schema is not None
        )
        if needs_enforcement:
            wrapped.append(_wrap_tool(tool, definition))
        else:
            wrapped.append(tool)
    return wrapped
