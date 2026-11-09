# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Debug API endpoints for development
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Any
import json

from db.database import get_db
from models.workflow import WorkflowProfile
from models.custom_tool import CustomTool

router = APIRouter(prefix="/api/debug", tags=["debug"])

# Named here so the terminal WebSocket's failure path has somewhere to report. That handler used
# to swallow its exception entirely, which is why a dying terminal left only `[accepted]` in the
# syslog and a closed socket on the client.
logger = logging.getLogger(__name__)


@router.get("/workflow/{workflow_id}")
async def get_workflow_debug(workflow_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get detailed debug information about a workflow's configuration.
    Shows tool assignments, node configs, and validates setup.
    """
    workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    nodes = workflow.configuration.get('nodes', [])

    # Analyze each node
    node_analysis = []
    for node in nodes:
        node_id = node.get('id')
        node_type = node.get('type', 'unknown')
        node_config = node.get('config', {})

        # Remove emojis for display
        safe_type = ''.join(c for c in node_type if ord(c) < 128) if node_type else 'unknown'

        custom_tools = node_config.get('custom_tools', [])
        # Prefer native_tools; fall back to legacy mcp_tools for older configs
        native_tools = node_config.get('native_tools', node_config.get('mcp_tools', []))

        node_analysis.append({
            "node_id": node_id,
            "type": safe_type,
            "native_tools": native_tools,
            "custom_tools": custom_tools,
            "has_image_generation": "image_generation" in custom_tools,
            "model": node_config.get('model'),
            "config_keys": list(node_config.keys())
        })

    # Get all available custom tools
    all_custom_tools = db.query(CustomTool).all()
    custom_tools_list = [
        {
            "tool_id": tool.tool_id,
            "name": tool.name,
            "tool_type": tool.tool_type.value
        }
        for tool in all_custom_tools
    ]

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.name,
        "nodes": node_analysis,
        "available_custom_tools": custom_tools_list,
        "raw_configuration": workflow.configuration
    }



@router.post("/client-log")
async def client_log(payload: dict):
    """A BROWSER-side event, written into the same log the server writes.

    The folder-upload failure is invisible from here: the handler's own guards return before any
    request is made, so the server log shows nothing and every remedy is a guess. A client that can
    say "I was clicked, I saw 0 files, here is the exception" turns that into a fact. Bodies are
    capped and flattened; this is a diagnostic channel, not a general-purpose log sink.
    """
    from services.log_stream import hub, attach_log_stream
    import logging as _logging

    attach_log_stream()
    event = str(payload.get("event") or "?")[:80]
    detail = {k: (str(v)[:200] if not isinstance(v, (int, float, bool, type(None))) else v)
              for k, v in (payload.get("detail") or {}).items() if k}
    line = f"[client] {event} {json.dumps(detail, ensure_ascii=False)}"
    _logging.getLogger("client").warning(line)
    try:
        hub.publish(line)                      # show it in the Terminal tab the user already has open
    except Exception:                                            # noqa: BLE001
        pass
    return {"ok": True}


@router.get("/logs/stream")
async def stream_logs(request: Request):
    """SSE stream of backend system logs for the bottom-panel Terminal tab.

    Sends buffered history first so a freshly-opened terminal isn't empty,
    then live log lines. Comment frames keep the connection alive so proxies
    don't time it out during quiet periods.
    """
    from services.log_stream import hub, attach_log_stream

    attach_log_stream()

    async def event_gen():
        for line in hub.snapshot():
            yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"

        queue = hub.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.websocket("/terminal/ws")
async def terminal_ws(websocket: WebSocket, terminal_id: str = "default"):
    """Interactive shell terminal over WebSocket (VS Code-style).

    One shell subprocess per connection. The client sends `input`/`resize`
    frames and receives `ready`/`output`/`exit` frames — see
    `services.terminal_service` for the wire protocol.
    """
    from services.terminal_service import TerminalSession, active_sessions

    await websocket.accept()
    session = TerminalSession(terminal_id, websocket)
    active_sessions[terminal_id] = session
    try:
        try:
            await session.start()
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": f"Failed to start shell: {exc}"})
            return

        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                await session.write(str(msg.get("data", "")))
            elif mtype == "resize":
                try:
                    cols = int(msg.get("cols", 80))
                    rows = int(msg.get("rows", 24))
                except (TypeError, ValueError):
                    cols, rows = 80, 24
                await session.resize(cols, rows)
    except WebSocketDisconnect:
        pass
    except Exception:
        # Logged rather than swallowed. This used to be a bare `pass`, which meant a terminal that
        # died mid-session left a `[accepted]` and nothing else in the syslog — the client sees a
        # closed socket and the proxy reports EPIPE, and there is no record of why. An interactive
        # shell failing silently is the hardest kind to chase.
        logger.exception("terminal session %r failed", terminal_id)
    finally:
        await session.close()
        active_sessions.pop(terminal_id, None)
