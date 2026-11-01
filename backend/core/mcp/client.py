# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""MCP → LangChain tool bridge.

The LangChain docs put this behind ``langchain.mcp.MCPAdapter``, which needs
``langchain[mcp]>=1.4.0``; that extra requires ``fastmcp>=4``, which requires
``starlette>=1``, which our ``fastapi==0.115`` cannot take. So the same server
config shape is adapted here on the MCP Python SDK that FastMCP itself wraps —
the wire protocol is identical, only the wrapper differs.

A server is one dict entry, spelled like ``.mcp.json`` / ``plugin.json``:

    stdio server   {"command": "npx", "args": ["-y", "some-mcp"], "env": {...}}
    remote server  {"url": "https://calendarmcp.googleapis.com/mcp/v1",
                    "headers": {"Authorization": "Bearer ..."}}

Tool names are prefixed with the config key (``calendar_list_events``), the way
FastMCP prefixes an ``MCPConfig`` fleet, so two servers exposing ``list-events``
stay distinguishable in the model's catalog.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool

from .shared import logger

# JSON Schema type → Python type, for the args model the model sees.
_JSON_TO_PY: Dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}

_TOOL_NAME_OK = re.compile(r"[^0-9A-Za-z_]")


def normalize_server_config(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Accept ``{name: {...}}`` or ``{"mcpServers": {name: {...}}}``.

    Both spellings turn up in the wild (``.mcp.json`` uses the wrapper) and the
    rest of the platform reads plugin manifests the short way.
    """
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("mcpServers"), dict):
        raw = raw["mcpServers"]
    servers: Dict[str, Dict[str, Any]] = {}
    for key, cfg in raw.items():
        if not isinstance(cfg, dict):
            logger.warning(f"MCP server {key!r} is not a dict — skipped")
            continue
        entry = dict(cfg)
        # `serverUrl` is the spelling Google's own MCP config uses.
        if "url" not in entry and entry.get("serverUrl"):
            entry["url"] = entry.pop("serverUrl")
        if not entry.get("url") and not entry.get("command"):
            logger.warning(f"MCP server {key!r} has neither 'url' nor 'command' — skipped")
            continue
        servers[key] = entry
    return servers


@asynccontextmanager
async def _transport(cfg: Dict[str, Any]):
    """Open the read/write streams for one server (http or stdio)."""
    if cfg.get("url"):
        from mcp.client.streamable_http import streamablehttp_client

        headers = cfg.get("headers") or None
        async with streamablehttp_client(cfg["url"], headers=headers) as (read, write, _):
            yield read, write
        return

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, **(cfg.get("env") or {})}
    params = StdioServerParameters(
        command=cfg["command"],
        args=list(cfg.get("args") or []),
        env=env,
        cwd=cfg.get("cwd") or None,
    )
    async with stdio_client(params) as (read, write):
        yield read, write


@asynccontextmanager
async def open_session(cfg: Dict[str, Any]):
    """An initialized MCP session. One connection, one handshake."""
    from mcp import ClientSession

    async with _transport(cfg) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _text_of(result: Any) -> str:
    """Flatten an MCP CallToolResult into what the model should read."""
    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        elif hasattr(block, "model_dump"):
            parts.append(json.dumps(block.model_dump(exclude_none=True), ensure_ascii=False))
        else:
            parts.append(str(block))
    if getattr(result, "isError", False):
        return "[MCP tool error] " + ("\n".join(parts) or "no message")
    return "\n".join(parts)


def _args_model(tool_name: str, schema: Dict[str, Any]):
    """Build the pydantic args model MCPAdapter would hand LangChain."""
    from pydantic import Field, create_model

    props: Dict[str, Any] = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    fields: Dict[str, Any] = {}
    for prop, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        py_type = _JSON_TO_PY.get(spec.get("type"), Any)
        default = ... if prop in required else spec.get("default", None)
        fields[prop] = (py_type, Field(default, description=spec.get("description")))
    model_name = _TOOL_NAME_OK.sub("_", tool_name) + "_args"
    return create_model(model_name, **fields) if fields else None


def _tool_name(server_key: str, remote_name: str) -> str:
    return f"{server_key}_{_TOOL_NAME_OK.sub('_', remote_name)}".strip("_")


def _approval_decision(tool_name: str, payload: Dict[str, Any], allowed: List[str]) -> Optional[str]:
    """Ask a human whether this call may run. Returns None (go) or a refusal.

    The gate lives inside the tool, not in the agent's middleware chain, because
    a subagent runs its own graph: `HumanInTheLoopMiddleware` on the parent never
    sees a tool the child calls. Measured, not assumed — a `task` subagent
    created a real Google Calendar event with the parent's `interrupt_on` set.
    Interrupting from the tool itself fires wherever the tool runs.

    Payload shape matches `HumanInTheLoopMiddleware`, so the existing approval
    card and the resume endpoint work unchanged:
    {"action_requests": [...], "review_configs": [...]}.
    """
    from langgraph.types import interrupt

    decision = interrupt(
        {
            "action_requests": [
                {
                    "name": tool_name,
                    "args": payload,
                    "description": f"Approve {tool_name}? It writes through MCP.",
                }
            ],
            "review_configs": [
                {"action_name": tool_name, "allowed_decisions": allowed}
            ],
        }
    )

    # The resume endpoint sends {"decisions": [{...}]}; accept a bare decision too.
    if isinstance(decision, dict) and "decisions" in decision:
        flat = decision.get("decisions") or []
        decision = flat[0] if flat else {}
    if isinstance(decision, list):
        decision = decision[0] if decision else {}
    kind = decision.get("type") if isinstance(decision, dict) else decision

    # Fail closed. An empty decision list — the shape a "carry on" resume without
    # an explicit choice produces — must not read as approval: it did, because an
    # empty list normalised to `{}` and `{}` to None. Only a literal "approve"
    # runs the tool (found by agent 1 reading this file, 2026-11-01).
    if kind == "approve":
        return None
    if kind == "reject":
        return f"[rejected by human] {decision.get('message') or 'no reason given'}"
    if kind in (None, ""):
        return "[rejected] no decision was recorded — the tool did not run"
    return f"[rejected by human] unsupported decision: {kind}"


def _build_tool(
    server_key: str,
    server_cfg: Dict[str, Any],
    remote_name: str,
    description: str,
    args_schema: Optional[Any],
    approval: Optional[Dict[str, Any]] = None,
) -> BaseTool:
    """One MCP tool as a LangChain tool: async path opens its own session."""

    # `interrupt_on` values are either True or {"allowed_decisions": [...]}.
    if approval is True:
        allowed = ["approve", "reject"]
    else:
        allowed = list((approval or {}).get("allowed_decisions") or ["approve", "reject"])

    # A tool call must fail fast. Without a cap, a server that is waiting on
    # something it cannot reach (Google OAuth refresh with the token expired and
    # the network down, measured 2026-11-01) hangs the whole agent turn: the
    # stream produced nothing for 230s and the acceptance calendar section timed
    # out twice. The server is not ours to fix, so bound the wait here.
    call_timeout = float(os.getenv("MCP_CALL_TIMEOUT", "90"))

    async def _acall(**kwargs: Any) -> str:
        # Drop unset optionals instead of sending `null`: MCP servers validate
        # with zod-style schemas that reject an explicit null for an optional
        # string ("expected string, received null at account" — seen on the
        # google-calendar server). LangChain hands us every field of the args
        # model, including the ones the model did not fill in.
        payload = {k: v for k, v in kwargs.items() if v is not None}
        if approval is not None:
            refusal = _approval_decision(_tool_name(server_key, remote_name), payload, allowed)
            if refusal:
                return refusal
        try:
            async with asyncio.timeout(call_timeout):
                async with open_session(server_cfg) as session:
                    result = await session.call_tool(remote_name, payload)
                    return _text_of(result)
        except TimeoutError:
            return (
                f"[MCP timeout] {server_key}/{remote_name} did not answer within "
                f"{call_timeout:.0f}s. The server is reachable but its tool call is not "
                f"returning — check its own upstream (network, credentials, token refresh) "
                f"before retrying. Raise MCP_CALL_TIMEOUT to wait longer."
            )

    def _call(**kwargs: Any) -> str:
        # Sync callers (tool previews, workflow nodes) have no running loop.
        return asyncio.run(_acall(**kwargs))

    return StructuredTool(
        name=_tool_name(server_key, remote_name),
        description=description or f"MCP tool {remote_name} from {server_key}",
        args_schema=args_schema,
        func=_call,
        coroutine=_acall,
        metadata={
            "mcp_server": server_key,
            "mcp_tool": remote_name,
            "needs_approval": approval is not None,
        },
    )


async def load_mcp_tools(
    servers: Any,
    timeout: float = 20.0,
    approvals: Optional[Dict[str, Any]] = None,
) -> List[BaseTool]:
    """Discover every configured server's tools and adapt them.

    A server that fails to start must not take the agent down with it: the
    failure is logged with the server key so it shows up in the chat log rather
    than as a silent empty tool list.

    `approvals` maps an exposed tool name (``calendar_create_event``) to its
    approval policy; those tools interrupt for a human before they run.
    """
    approvals = approvals or {}
    tools: List[BaseTool] = []
    for key, cfg in normalize_server_config(servers).items():
        try:
            async with asyncio.timeout(timeout):
                async with open_session(cfg) as session:
                    listed = await session.list_tools()
        except Exception as exc:  # noqa: BLE001 — one bad server is not fatal
            logger.warning(f"MCP server {key!r} unavailable: {type(exc).__name__}: {exc}")
            continue
        for remote in listed.tools:
            exposed = _tool_name(key, remote.name)
            tools.append(
                _build_tool(
                    key,
                    cfg,
                    remote.name,
                    remote.description or "",
                    _args_model(remote.name, getattr(remote, "inputSchema", None) or {}),
                    approval=approvals.get(exposed) or approvals.get(remote.name),
                )
            )
        gated = [t.name for t in tools if t.metadata.get("needs_approval")]
        logger.info(
            f"MCP server {key!r}: {len(listed.tools)} tools "
            f"({', '.join(t.name for t in listed.tools[:4])}{'…' if len(listed.tools) > 4 else ''})"
            + (f" · approval required: {sorted(gated)}" if gated else "")
        )
    return tools


async def mcp_server_health(servers: Any, timeout: float = 15.0) -> List[Dict[str, Any]]:
    """Per-server reachability + tool names — what a UI or a test wants to show."""
    report: List[Dict[str, Any]] = []
    for key, cfg in normalize_server_config(servers).items():
        entry: Dict[str, Any] = {
            "server": key,
            "transport": "http" if cfg.get("url") else "stdio",
            "target": cfg.get("url") or f"{cfg.get('command')} {' '.join(cfg.get('args') or [])}".strip(),
        }
        try:
            async with asyncio.timeout(timeout):
                async with open_session(cfg) as session:
                    listed = await session.list_tools()
            entry["ok"] = True
            entry["tools"] = [t.name for t in listed.tools]
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report.append(entry)
    return report
