#!/usr/bin/env python3
"""用 UI 同一条链路驱动一个 agent 跑一轮 —— 没有浏览器时也能验收。

它做的事和 Talent 面板里点"发送"完全一样:

    POST /api/chat/start            → 新建会话
    POST /api/chat/message/stream   → 发消息,读 SSE

为什么要这个脚本:agent 的能力只能靠**真跑一轮**来验;而 Playwright 在这台机器上起不来。
所以走同一套 API,把 SSE 原样落盘 —— 工具调用、答案、报错全在里面,可以人肉复核。

用法:
    python -m scripts.talent.run_agent_turn --agent 386 --msg "起草 JD:品质经理" --log /tmp/t1.txt
    python -m scripts.talent.run_agent_turn --agent 385 --msg "..." --session <已存在的 sid>

退出码:0 = 跑完;2 = 接口失败;3 = 超时。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def post(path: str, payload: dict, stream: bool = False, timeout: int = 900):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=int, required=True)
    ap.add_argument("--msg", required=True)
    ap.add_argument("--log", default="/tmp/agent_turn.log")
    ap.add_argument("--session", default="")
    ap.add_argument("--project", type=int, default=18)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    log = pathlib.Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    sid = args.session
    if not sid:
        try:
            with post("/api/chat/start", {"agent_id": args.agent,
                                          "project_id": args.project}, timeout=120) as r:
                sid = json.loads(r.read().decode() or "{}").get("session_id", "")
        except urllib.error.HTTPError as exc:
            print(f"chat/start 失败 {exc.code}: {exc.read().decode()[:200]}")
            return 2
        if not sid:
            print("chat/start 没返回 session_id")
            return 2
    log.write_text(f"session={sid}\nagent={args.agent}\nmsg={args.msg}\n---\n", encoding="utf-8")

    t0 = time.time()
    n_tool = n_tok = 0
    try:
        resp = post("/api/chat/message/stream",
                    {"session_id": sid, "message": args.msg, "project_id": args.project},
                    timeout=900)
        with resp, log.open("a", encoding="utf-8") as fh:
            for raw in resp:
                line = raw.decode("utf-8", "replace")
                fh.write(line)
                if not args.quiet and line.startswith("data:"):
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    t = ev.get("type") or ev.get("event") or ""
                    if t == "tool_start":
                        n_tool += 1
                        print(f"  [tool {n_tool}] {ev.get('name') or ev.get('tool')}")
                    elif t in ("token", "delta"):
                        n_tok += 1
                    elif t == "error":
                        print(f"  [error] {str(ev.get('error'))[:200]}")
    except urllib.error.HTTPError as exc:
        print(f"stream 失败 {exc.code}: {exc.read().decode()[:300]}")
        return 2
    except TimeoutError:
        print("超时")
        return 3

    print(f"完成:session={sid} · 工具 {n_tool} 次 · 用时 {time.time()-t0:.0f}s · 日志 {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
