#!/usr/bin/env python
"""Platform-level test: a LangConfig DeepAgent uses `build-ontology-from-db` for real.

The SDK test (test_ontology_skill_agent.py) proves the skill loads in deepagents. This one
proves it works inside **LangConfig**: the skill is a DB row, the agent is an agent row, the
chat is a real SSE run against the running backend — and the skill's script must actually
execute in the agent's sandbox and leave its output in the workspace.

Checks:
  P1 the agent is built with the skill pinned and the shell sandbox on
  P2 the chat run has `execute` in its tool set (a sandboxed agent that cannot run a script
     is a skill that only reads)
  P3 the skill's script runs and writes its brief into the agent workspace
  P4 the brief contains the target tables, with shape hints
  P5 the skill's supporting files are reachable at /skills/... (scripts/, references/)

Run against a live backend:
    cd backend && .venv/bin/python scripts/test_ontology_skill_platform_agent.py \
        --base-url http://localhost:8765 --agent-id 348 \
        --table appointments --table treatment_lines
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

OK = True


def check(name: str, ok: bool, detail: str = "") -> None:
    global OK
    OK = OK and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" — {detail}"))


def call(base: str, path: str, body: dict | None = None, timeout: int = 300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def stream_chat(base: str, session_id: str, message: str) -> tuple[list[str], str, list[str]]:
    """POST one message, collect (tool names, answer text, tool outputs)."""
    req = urllib.request.Request(
        base + "/api/chat/message/stream",
        data=json.dumps({"session_id": session_id, "message": message,
                         "project_id": None}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    tools, texts, outputs = [], [], []
    with urllib.request.urlopen(req, timeout=1200) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip()
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            kind = ev.get("type")
            if kind == "tool_start":
                tools.append(ev.get("tool_name") or "")
            elif kind == "tool_end":
                payload = ev.get("data") or {}
                out = payload.get("output")
                if isinstance(out, dict):
                    # deepagents' ExecuteResponse flattens to {output, exit_code, truncated}
                    out = out.get("output") or json.dumps(out, ensure_ascii=False)
                elif isinstance(out, list):
                    out = json.dumps(out, ensure_ascii=False)
                outputs.append("" if out is None else str(out))
            elif kind == "chunk":
                texts.append(ev.get("content") or "")
    return tools, "".join(texts), outputs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8765")
    ap.add_argument("--agent-id", type=int, required=True)
    ap.add_argument("--dsn", default="host=127.0.0.1 port=5432 dbname=clinic_db user=weiping")
    ap.add_argument("--python", required=True,
                    help="interpreter with psycopg2, reachable from the sandbox")
    ap.add_argument("--table", action="append", default=[],
                    help="a table the brief must contain (repeatable)")
    args = ap.parse_args()
    must = args.table or ["appointments"]

    agent = call(args.base_url, f"/api/deepagents/{args.agent_id}")
    cfg = agent.get("config") or {}
    print(f"agent {args.agent_id}: {agent.get('name')} · model={cfg.get('model')}")
    check("P1a the skill is pinned on the agent",
          "build-ontology-from-db" in (cfg.get("skills") or []), str(cfg.get("skills")))
    check("P1b the shell sandbox is enabled", bool(cfg.get("use_local_sandbox")),
          "config.use_local_sandbox is off — the skill's scripts cannot run")

    workspace = pathlib.Path(agent.get("workspace_path")
                             or cfg.get("workspace_path")
                             or f"outputs/users/1/agents/agent_{args.agent_id}")
    print(f"workspace: {workspace}")

    session = call(args.base_url, "/api/chat/start", {"agent_id": args.agent_id})
    sid = session["session_id"]
    print(f"session:   {sid}")

    script = ("skills/builtin/build-ontology-from-db/scripts/introspect_db.py")
    tools, answer, outputs = stream_chat(
        args.base_url, sid,
        "用 execute 运行技能阶段 1 的脚本。脚本已经在工作区里，路径是相对工作区根的 "
        f"`{script}`（注意：shell 里没有前导 `/`，不要把它复制到别处再跑）：\n"
        f"{args.python} {script} --dsn \"{args.dsn}\" --out ontology_brief.json\n"
        "然后读 ontology_brief.json，用中文列出每张表名和它的 shape。")

    check("P2 the run's tool set contains execute", "execute" in tools, f"tools: {tools}")
    joined = "\n".join(outputs) + "\n" + answer
    # Evidence, not narration. `execute` output is the platform's own relay of
    # stdout — if it is empty the chat UI shows an empty tool result and the agent
    # cannot see what its command did.
    non_empty = [o for o in outputs if o.strip()]
    check("P3a execute results reach the client (stdout is not null)",
          bool(non_empty), f"{len(outputs)} tool_end event(s), all empty")
    check("P3b the script reported writing the brief",
          any("wrote" in o.lower() and "brief" in o.lower() for o in outputs),
          (non_empty[0][:300] if non_empty else joined[:300]))

    briefs = []
    if workspace.exists():
        # The brief name is the agent's to choose; accept any *.json that parses
        # into the introspector's shape {"tables": [{"table": ...}, ...]}.
        for cand in sorted(workspace.rglob("*brief*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                parsed = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("tables"), list):
                briefs.append((cand, parsed))
    check("P3c the brief landed in the agent workspace", bool(briefs),
          f"no *brief*.json under {workspace}")
    if briefs:
        path, data = briefs[0]
        names = [t["table"] for t in data["tables"]]
        shapes = {t["table"]: t.get("shape_hint") or "" for t in data["tables"]}
        check("P4a the brief has every required table", all(t in names for t in must),
              f"{must} not in {names}")
        check("P4b every table carries a shape hint", all(shapes.values()), "a shape hint is empty")
        print(f"       tables: {names}")
        print(f"       shapes: { {k: v[:32] + '…' for k, v in shapes.items()} }")
        print(f"       brief:  {path}")

    # P3d: running the staged script must not require copying it somewhere else —
    # a copy means the skill's own files were treated as unreachable, which is the
    # failure this staging exists to prevent.
    mirror = workspace / "skills" / "builtin" / "build-ontology-from-db" / "scripts" / "introspect_db.py"
    copies = [p for p in workspace.rglob("introspect_db*.py")
              if p.resolve() != mirror.resolve()]
    check("P3d the script ran from the skill mirror, not a copy", mirror.exists() and not copies,
          f"mirror={'yes' if mirror.exists() else 'MISSING'}, copies={copies}")

    # P5: the supporting files a script-bearing skill needs must be reachable
    listing = call(args.base_url, "/api/skills/build-ontology-from-db/files")
    files = [f.get("path", "") for f in listing.get("files", [])]
    check("P5 scripts/ and references/ are part of the skill",
          any(p.startswith("scripts/") for p in files)
          and any(p.startswith("references/") for p in files),
          f"{len(files)} file(s) listed")

    print()
    print("ALL PASS" if OK else "SOME CHECKS FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
