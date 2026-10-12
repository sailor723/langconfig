#!/usr/bin/env python
"""Verify the per-agent recursion limit actually caps a chat run.

Sets ``config.recursion_limit`` on real agents, drives a real chat over the
HTTP API (SSE), and counts how far the agent got:

  limit 10   -> the run must stop after ~5 model+tool turns with a recursion error
  limit 1000 -> the same prompt completes

That difference is the proof: same agent, same prompt, only the limit changes.

Usage (from ``backend/``, with the backend running on --port):
    .venv/bin/python scripts/test_recursion_limit.py --agents 221,222 --port 8766
    .venv/bin/python scripts/test_recursion_limit.py --agents 222 --limits 10 --keep-config

Restores every agent's original config unless --keep-config is given, and
deletes the chat sessions + checkpoint rows it created.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from db.database import SessionLocal  # noqa: E402
from models.deep_agent import DeepAgentTemplate  # noqa: E402

# A prompt that needs many turns: one tool call per turn, N times.
LOOP_PROMPT_TEMPLATE = (
    "You must make exactly {calls} separate tool calls, ONE per turn, before answering. "
    "Use `ls` (or `glob`) on a different path each time, starting with the workspace root. "
    "After each tool result, immediately make the next tool call. "
    "Do not answer until all {calls} calls are done, then reply exactly: DONE-{calls}"
)


def set_limit(agent_id: int, limit: int | None) -> None:
    db = SessionLocal()
    try:
        if limit is None:
            db.execute(text("""
                update deep_agent_templates
                set config = (config::jsonb - 'recursion_limit')::json, updated_at = now()
                where id = :id"""), {"id": agent_id})
        else:
            db.execute(text("""
                update deep_agent_templates
                set config = (config::jsonb || jsonb_build_object('recursion_limit', :lim))::json,
                    updated_at = now()
                where id = :id"""), {"id": agent_id, "lim": limit})
        db.commit()
    finally:
        db.close()


def agent_meta(agent_id: int) -> dict:
    db = SessionLocal()
    try:
        row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if row is None:
            raise SystemExit(f"agent {agent_id} not found")
        cfg = row.config or {}
        return {
            "name": row.name,
            "kind": "deepagent" if cfg.get("use_deepagents", True) else "regular agent",
            "original": cfg.get("recursion_limit"),
        }
    finally:
        db.close()


def post(url: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def drive(port: int, agent_id: int, prompt: str, timeout: int = 240) -> dict:
    """Start a session and stream one message; count turns and capture the ending."""
    base = f"http://127.0.0.1:{port}/api"
    session_id = post(f"{base}/chat/start", {"agent_id": agent_id})["session_id"]
    req = urllib.request.Request(
        f"{base}/chat/message/stream",
        data=json.dumps({"session_id": session_id, "message": prompt}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")

    tool_calls, terminal, error, chunks, events = 0, None, None, [], 0
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as stream:
        for raw in stream:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            events += 1
            kind = ev.get("type")
            if kind == "tool_start":
                tool_calls += 1
            elif kind == "chunk":
                chunks.append(ev.get("content") or "")
            elif kind == "error":
                terminal, error = "error", ev.get("message") or ""
            elif kind in ("complete", "done", "end"):
                terminal = kind
    elapsed = time.time() - started

    db = SessionLocal()
    try:
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            db.execute(text(f"delete from {table} where thread_id = :t"), {"t": session_id})
        db.execute(text("delete from chat_sessions where session_id = :t"), {"t": session_id})
        db.commit()
    finally:
        db.close()

    return {"tool_calls": tool_calls, "terminal": terminal, "error": error,
            "elapsed": elapsed, "events": events, "reply": "".join(chunks)[-200:]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agents", default="221,222")
    ap.add_argument("--limits", default="10,1000", help="comma-separated limits to try")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--keep-config", action="store_true", help="do not restore original config")
    ap.add_argument("--calls", type=int, default=12,
                    help="how many tool calls the prompt demands")
    ap.add_argument("--keep-sessions", action="store_true")
    args = ap.parse_args()

    agent_ids = [int(a) for a in args.agents.split(",") if a.strip()]
    limits = [int(x) for x in args.limits.split(",") if x.strip()]
    originals = {aid: agent_meta(aid) for aid in agent_ids}

    try:
        for aid, meta in originals.items():
            print(f"\nagent {aid} \"{meta['name']}\" ({meta['kind']}), "
                  f"original recursion_limit={meta['original']}")
            print(f"{'limit':>6} {'tool calls':>11} {'events':>7} {'secs':>6}  ending")
            for limit in limits:
                set_limit(aid, limit)
                res = drive(args.port, aid, LOOP_PROMPT_TEMPLATE.format(calls=args.calls))
                ending = res["terminal"] or "stream closed"
                if res["error"]:
                    ending += f": {res['error'][:90]}"
                print(f"{limit:>6} {res['tool_calls']:>11} {res['events']:>7} "
                      f"{res['elapsed']:>6.1f}  {ending}")
                if res["error"]:
                    print(f"       reply so far: {res['reply'][-90:]!r}")
    finally:
        if not args.keep_config:
            for aid, meta in originals.items():
                set_limit(aid, meta["original"])
            print("\nrestored original recursion_limit for:",
                  ", ".join(f"{a}={originals[a]['original']}" for a in agent_ids))
        else:
            print("\nconfig left as-is (--keep-config)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
