#!/usr/bin/env python3
"""Drive one agent turn over the SAME streaming endpoint the Web UI uses, and narrate it.

This is the CLI twin of the agent chat window, on purpose:

    POST /api/chat/start          {"agent_id": …, "project_id": …}      → a session
    POST /api/chat/message/stream {"session_id": …, "message": …}        → the SSE event stream

The UI only renders those events (`chunk` → text, `tool_start` → a tool chip, `progress` → the spinner's
caption). Printing them here means what you read below is what the browser would have shown — including the
events that explain a turn that looks "stuck": the 5-second `progress` heartbeat, a `tool_end` that never comes,
an `error` from a link failure, or the loop guard tripping.

    python scripts/sse_chat.py --agent 352 --project 18 --message-file /tmp/task.md [--timeout 1800]

Exit: 0 the turn completed and produced text, 3 the turn ended in an error event, 1 the request itself failed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE_DEFAULT = "http://127.0.0.1:8765"


def _post_json(base: str, path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--agent", type=int, required=True)
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--message", default="")
    ap.add_argument("--message-file", default="")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--quiet-chunks", action="store_true", help="do not print every chunk, only a summary")
    args = ap.parse_args()

    message = args.message
    if args.message_file:
        message = pathlib.Path(args.message_file).read_text(encoding="utf-8")
    if not message.strip():
        print("ERROR: empty message", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    started = _post_json(base, "/api/chat/start",
                         {k: v for k, v in (("agent_id", args.agent), ("project_id", args.project))
                          if v is not None}, timeout=120)
    session = started.get("session_id") or started.get("id") or ""
    print(f"[start] session={session}", flush=True)
    if not session:
        print(json.dumps(started, ensure_ascii=False)[:600], flush=True)
        return 1

    body = json.dumps({k: v for k, v in (("session_id", session), ("message", message),
                                         ("project_id", args.project)) if v is not None}).encode()
    req = urllib.request.Request(base + "/api/chat/message/stream", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "text/event-stream"})

    t0 = time.monotonic()
    text: list[str] = []
    counts: dict[str, int] = {}
    errors: list[str] = []
    chunk_run = 0
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as res:
            for raw in res:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:                             # noqa: BLE001
                    continue
                et = ev.get("type") or "?"
                counts[et] = counts.get(et, 0) + 1
                at = time.monotonic() - t0

                if et == "chunk":
                    piece = ev.get("content") or ""
                    text.append(piece)
                    chunk_run += len(piece)
                    if chunk_run >= 400 and not args.quiet_chunks:
                        print(f"[{at:7.1f}s] chunk        …{chunk_run} chars so far", flush=True)
                        chunk_run = 0
                elif et == "progress":
                    print(f"[{at:7.1f}s] progress     elapsed={ev.get('elapsed_s')}s "
                          f"tool={ev.get('tool') or '-'} calls={ev.get('tool_calls')} "
                          f"chars={ev.get('chars')} tokens={ev.get('tokens')}"
                          + (f" note={ev.get('note')}" if ev.get("note") else ""), flush=True)
                elif et == "tool_start":
                    print(f"[{at:7.1f}s] tool_start   {ev.get('tool_name')}", flush=True)
                elif et == "tool_end":
                    print(f"[{at:7.1f}s] tool_end     {ev.get('tool_name')}", flush=True)
                elif et == "error":
                    msg = str(ev.get("message") or "")
                    errors.append(msg)
                    print(f"[{at:7.1f}s] ERROR        {msg[:400]}", flush=True)
                elif et == "interrupt":
                    print(f"[{at:7.1f}s] interrupt    {json.dumps(ev.get('data'), ensure_ascii=False)[:300]}",
                          flush=True)
                elif et == "complete":
                    print(f"[{at:7.1f}s] complete", flush=True)
                else:
                    print(f"[{at:7.1f}s] {et}", flush=True)
    except Exception as exc:                                  # noqa: BLE001
        print(f"[fatal] {type(exc).__name__}: {exc}", flush=True)
        return 1

    answer = "".join(text).strip()
    out = pathlib.Path(f"/tmp/sse_chat_{session}.log")
    out.write_text(answer, encoding="utf-8")
    print("\n=== events ===")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:12s} {v}")
    print(f"\n=== answer ({len(answer)} chars, saved to {out}) ===")
    print(answer[:2500])
    if not answer and errors:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
