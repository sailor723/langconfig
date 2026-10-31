"""Transfer tools generated from a handoff configuration.

LangChain's handoff pattern (docs: multi-agent/handoffs) is *one tool per
target* — `transfer_to_sales`, `transfer_to_support` — not a single dispatch tool
with a `to` argument. The difference matters: with the target in the tool's
identity the model cannot invent a step name, the description carries the routing
decision (exactly like `task` does for subagents), and a step simply lacks the
tool that would transfer to itself.

The tools are generated at agent-build time from:

    "steps": {
      "sales":   {"tools": [...], "transfers": [{"to": "support", "description": "技术故障交给售后"}]},
      "support": {"tools": [...], "transfers": [{"to": "sales",   "description": "问价格转回售前"}]}
    }

They only acknowledge: the state change belongs to the middleware, which owns the
real `tool_call_id` (building the ToolMessage inside the tool gave an id LangGraph
refused).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TRANSFER_PREFIX = "transfer_to_"


def transfer_tool_name(step: str) -> str:
    return f"{TRANSFER_PREFIX}{step}"


def transfer_target(tool_name: str) -> str | None:
    """Inverse of :func:`transfer_tool_name` — None when this is not a transfer."""
    if not tool_name.startswith(TRANSFER_PREFIX):
        return None
    target = tool_name[len(TRANSFER_PREFIX):]
    return target or None


def build_transfer_tools(steps: Dict[str, Dict[str, Any]]) -> List[Any]:
    """One tool per (step → target) edge declared in the configuration."""
    try:
        from pydantic import BaseModel, Field
        from langchain_core.tools import StructuredTool
    except ImportError:  # pragma: no cover
        logger.warning("langchain not available — transfer tools not generated")
        return []

    class TransferArgs(BaseModel):
        reason: str = Field(
            default="",
            description="为什么要转交（会被记录，也会展示给用户）",
        )

    tools: List[Any] = []
    seen: Dict[str, str] = {}
    for step_name, step in (steps or {}).items():
        for edge in (step or {}).get("transfers") or []:
            target = str((edge or {}).get("to") or "").strip()
            if not target:
                logger.warning("step '%s' has a transfer without a target — ignored", step_name)
                continue
            name = transfer_tool_name(target)
            if name in seen:
                # Two steps may both transfer to the same target; one tool is enough
                # because the state field records where the conversation goes next.
                continue
            seen[name] = target
            description = (
                (edge or {}).get("description")
                or f"把对话转交给「{target}」"
            )
            message = (edge or {}).get("message") or f"已转交给 {target}"

            def _ack(reason: str = "", _message: str = message) -> str:
                return f"{_message}（原因：{reason}）" if reason else _message

            tools.append(
                StructuredTool.from_function(
                    func=_ack,
                    name=name,
                    description=description,
                    args_schema=TransferArgs,
                )
            )
    if tools:
        logger.info("handoff: generated %d transfer tool(s): %s", len(tools), [t.name for t in tools])
    return tools


def tools_for_step(step: Dict[str, Any] | None) -> List[str]:
    """Tool names a step may use: its own tools plus the transfers it declares."""
    if not step:
        return []
    names = list(step.get("tools") or [])
    for edge in step.get("transfers") or []:
        target = str((edge or {}).get("to") or "").strip()
        if target:
            names.append(transfer_tool_name(target))
    return names


__all__ = ["TRANSFER_PREFIX", "build_transfer_tools", "tools_for_step",
           "transfer_target", "transfer_tool_name"]
