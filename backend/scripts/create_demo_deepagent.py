#!/usr/bin/env python3
"""
create_demo_deepagent.py — create a demo DeepAgent via the REST API and test chat.

Backend-first validation of the full flow the UI uses (form-based creation):
  1. POST /api/deepagents          create agent (prompt + tools + skills)
  2. GET  /api/deepagents/{id}     verify config round-trips
  3. POST /api/chat/start          open a chat session bound to the agent
  4. POST /api/chat/message        non-streaming turn
  5. POST /api/chat/message/stream SSE streaming turn (chunk/thinking/complete)

Usage:
    .venv/bin/python backend/scripts/create_demo_deepagent.py
    .venv/bin/python backend/scripts/create_demo_deepagent.py --agent-id 169   # reuse existing agent
    .venv/bin/python backend/scripts/create_demo_deepagent.py --tool-test      # also trigger web_search
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

API_BASE = "http://localhost:8765"
TIMEOUT = httpx.Timeout(180.0, connect=10.0)  # LLM turns can take a while


# =============================================================================
# Demo agent definition (mirrors the UI payload built in DeepAgentCreator.tsx)
# =============================================================================

def build_agent_payload(name: str, description: str) -> Dict[str, Any]:
    """Payload shaped exactly like DeepAgentCreator.buildConfig() submits."""
    native_tools = ["web_search", "web_fetch"]
    return {
        "name": name,
        "description": description,
        "category": "research",
        "config": {
            "system_prompt": (
                "You are Demo Research Assistant, a focused research agent. "
                "When asked to summarize, follow the text-summarizer skill. "
                "Use web_search/web_fetch for fresh information, then answer "
                "concisely with the source you used. Be accurate, admit uncertainty."
            ),
            "model": "deepseek-chat",       # key present in .env
            "temperature": 0.3,
            "max_tokens": 2048,
            "native_tools": native_tools,
            "cli_tools": [],
            "custom_tools": [],
            "tools": native_tools,          # UI sends native + custom merged
            "skills": ["web-search", "text-summarizer"],
            "subagents": [],
            "middleware": [
                {"type": "todo_list", "enabled": True, "config": {}},
                {"type": "filesystem", "enabled": True, "config": {}},
            ],
            "backend": {"type": "state"},
            "guardrails": {
                "enable_auto_eviction": False,
                "enable_summarization": False,
                "long_term_memory": False,
            },
            "use_deepagents": True,
        },
    }


# =============================================================================
# API helpers
# =============================================================================

def _check(resp: httpx.Response, label: str) -> Dict[str, Any]:
    """Raise with response body on HTTP error, else return parsed JSON."""
    if resp.status_code >= 400:
        body = resp.text[:800]
        raise RuntimeError(f"{label} failed ({resp.status_code}): {body}")
    return resp.json()


def create_agent(client: httpx.Client, payload: Dict[str, Any]) -> Dict[str, Any]:
    print(f"\n▶ POST /api/deepagents/  name={payload['name']!r}")
    # Trailing slash required: the router registers "/api/deepagents/" (POST "/"),
    # and a bare URL would 307-redirect (httpx does not follow redirects).
    resp = _check(client.post("/api/deepagents/", json=payload), "create agent")
    agent_id = resp["id"]
    print(f"  ✓ created agent id={agent_id}")
    return resp


def get_agent(client: httpx.Client, agent_id: int) -> Dict[str, Any]:
    print(f"▶ GET /api/deepagents/{agent_id}")
    resp = _check(client.get(f"/api/deepagents/{agent_id}"), "get agent")
    cfg = resp.get("config", {})
    print(f"  ✓ name={resp['name']!r} model={cfg.get('model')!r} "
          f"use_deepagents={resp.get('use_deepagents')}")
    print(f"  ✓ native_tools={cfg.get('native_tools')}")
    print(f"  ✓ skills={cfg.get('skills')}")
    print(f"  ✓ middleware={[m.get('type') for m in resp.get('middleware_config', [])]}")
    print(f"  ✓ system_prompt={str(cfg.get('system_prompt'))[:80]!r}...")
    return resp


def start_chat(client: httpx.Client, agent_id: int) -> str:
    print("\n▶ POST /api/chat/start")
    resp = _check(client.post("/api/chat/start", json={"agent_id": agent_id}), "start chat")
    session_id = resp["session_id"]
    print(f"  ✓ session_id={session_id} agent={resp['agent_name']!r}")
    return session_id


def send_message(client: httpx.Client, session_id: str, message: str) -> str:
    print(f"\n▶ POST /api/chat/message  (non-streaming)")
    resp = _check(client.post("/api/chat/message", json={
        "session_id": session_id,
        "message": message,
    }), "send message")
    content = resp.get("content") or resp.get("response") or resp.get("message") or ""
    print(f"  ✓ reply ({len(content)} chars):\n{_truncate(content, 500)}")
    return str(content)


def stream_message(client: httpx.Client, session_id: str, message: str) -> str:
    """POST /api/chat/message/stream (SSE). Accumulates chunk events until complete."""
    print(f"\n▶ POST /api/chat/message/stream  (SSE)")
    full = ""
    tool_calls: List[str] = []
    thinking = ""
    with client.stream("POST", "/api/chat/message/stream", json={
        "session_id": session_id,
        "message": message,
    }) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"stream failed ({resp.status_code}): {resp.text[:500]}")
        # SSE lines: "data: <json>\n\n"
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "chunk":
                full += evt.get("content", "")
            elif etype == "thinking":
                thinking += evt.get("content", "")
            elif etype == "tool_start":
                tool_calls.append(evt.get("tool_name", "?"))
            elif etype == "tool_end":
                pass
            elif etype == "complete":
                if evt.get("content"):
                    full = evt["content"]
            elif etype == "error":
                raise RuntimeError(f"stream error: {evt.get('message')}")
    print(f"  ✓ tools used: {tool_calls or 'none'}")
    if thinking:
        print(f"  ✓ thinking ({len(thinking)} chars, first 120): {thinking[:120]}...")
    print(f"  ✓ streamed reply ({len(full)} chars):\n{_truncate(full, 500)}")
    return full


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"... [{len(text)} chars total]"


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Create + test a demo DeepAgent")
    parser.add_argument("--agent-id", type=int, default=None,
                        help="Reuse an existing agent instead of creating one")
    parser.add_argument("--name", default="Demo Research Assistant")
    parser.add_argument("--skip-stream", action="store_true",
                        help="Skip the SSE streaming test")
    parser.add_argument("--tool-test", action="store_true",
                        help="Also ask a question that triggers web_search")
    args = parser.parse_args()

    start = time.time()
    with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
        if args.agent_id:
            agent_id = args.agent_id
            get_agent(client, agent_id)
        else:
            payload = build_agent_payload(args.name, "Demo deep agent created end-to-end via REST API to validate create → verify → chat.")
            created = create_agent(client, payload)
            agent_id = created["id"]
            get_agent(client, agent_id)

        session_id = start_chat(client, agent_id)

        # 1) Basic invocation (no tools needed)
        send_message(client, session_id,
                     "Hello! In two sentences: who are you, and which skills can you use?")

        # 2) Optional tool test — forces web_search path
        if args.tool_test:
            send_message(client, session_id,
                         "Search the web for 'LangGraph 2026' and summarize the top result in one line.")

        # 3) Streaming turn
        if not args.skip_stream:
            stream_message(client, session_id,
                           "Give me a 3-bullet summary of why skills help agents follow company best practices.")

    elapsed = time.time() - start
    print(f"\n✅ ALL TESTS PASSED in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
