#!/usr/bin/env python3
"""Drive one DeepAgent turn from the shell, non-interactively.

Why this exists: the agents are the deliverable, not the chat window. An operator who wants to say "run the
Mock Data Agent on this brief and give me the artifacts" should not have to click five times, and a run that
takes four minutes should not be retyped by a human. This is the same two calls the UI makes:

    POST /api/chat/start     → a session bound to the agent
    POST /api/chat/message   → one turn, waited on to completion

The transcript is printed as it arrives (the backend has already finished by then) and the session id is
written to the log so a follow-up turn can continue the SAME conversation.

    .venv/bin/python scripts/run_agent_turn.py --agent 352 --message-file /tmp/task.md --timeout 1800

Exit: 0 the agent answered, 1 the call failed, 2 nothing to send.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _post(base: str, path: str, payload: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:                                    # noqa: BLE001
            return exc.code, {"error": body[:2000]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--agent", type=int, required=True)
    ap.add_argument("--message", default="")
    ap.add_argument("--message-file", default="")
    ap.add_argument("--project", type=int, default=1)
    ap.add_argument("--session", default="", help="continue an existing session instead of starting one")
    ap.add_argument("--timeout", type=float, default=1800)
    args = ap.parse_args()

    message = args.message
    if args.message_file:
        message = Path(args.message_file).read_text(encoding="utf-8")
    if not message.strip():
        print("ERROR: empty message", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    session = args.session
    if not session:
        status, body = _post(base, "/api/chat/start",
                             {"agent_id": args.agent, "project_id": args.project}, timeout=120)
        session = body.get("session_id") or body.get("id") or ""
        print(f"[start] HTTP {status} session={session or body}", flush=True)
        if status != 200 or not session:
            return 1

    started = time.time()
    print(f"[send] agent={args.agent} session={session} chars={len(message)} "
          f"timeout={args.timeout:.0f}s", flush=True)
    status, body = _post(base, "/api/chat/message",
                         {"session_id": session, "message": message,
                          "project_id": args.project}, timeout=args.timeout)
    took = time.time() - started
    print(f"[done] HTTP {status} in {took:.0f}s", flush=True)
    if status != 200:
        print(json.dumps(body, ensure_ascii=False, indent=1)[:4000], flush=True)
        return 1

    content = (body.get("response") or body.get("message") or body.get("content") or "")
    if isinstance(content, dict):
        content = content.get("content") or json.dumps(content, ensure_ascii=False)
    print("\n" + "=" * 70 + "\nAGENT REPLY\n" + "=" * 70, flush=True)
    print(content, flush=True)
    out = {"session_id": session, "agent_id": args.agent, "seconds": round(took),
           "reply_chars": len(content or "")}
    Path("/tmp/last_agent_turn.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
