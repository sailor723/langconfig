#!/usr/bin/env python
"""Verify the ontology pipeline agent's DELEGATION wiring — the claims, one command.

The architecture in `docs/system-architecture/ontology-pipeline.md` rests on five mechanical claims. Each is
checkable without believing a prompt, and each has been wrong in a sibling project at least once:

1. **The manager cannot bypass the experts.** If deepagents auto-adds its `general-purpose` subagent, the
   `task` tool lists a fifth agent with all the manager's tools — and a model under pressure will use it.
   So: the `task` description must name exactly our four experts and nothing else.
2. **Every expert reports in the receipt shape.** `response_format` is what lets the manager decide from
   `produced/unverified/needs_human` instead of re-reading the work.
3. **The manager does not do the work itself.** No `write_file`/`edit_file` and no `db_*` in its tools — the
   boundary is a tool subset (deepagents `permissions` do not cover sandbox `execute`, so they cannot be it).
4. **The four experts get different tools.** A `modeller` that can `db_build_from_file` is a `tables` expert
   with no rules.
5. **Delegation is actually wired** — `SubAgentMiddleware` present, and the SDK received four subagent specs.

What this script does NOT prove (state it plainly rather than imply it): that the experts cooperate in a real
run, that a step-capped expert fails loudly, or that the UI renders the dispatch. Those need real turns —
`--turn` runs one (`tables`, plan only) and prints the `task` frames it saw.

    cd backend && .venv/bin/python scripts/verify_ontology_pipeline.py 393
    cd backend && .venv/bin/python scripts/verify_ontology_pipeline.py 393 --turn
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXPECTED = ["tables", "modeller", "metrics", "board"]
RECEIPT_KEYS = {"produced", "facts", "unverified", "needs_human"}
# Structured output is NOT used: a JSON-schema dict needs `title` (else "Unsupported function"), and with one
# it becomes ToolStrategy → forced tool_choice → "Thinking mode does not support this tool_choice" on
# deepseek-v4-flash. The receipt is therefore prose the prompt demands, and that is what we assert.


def _ok(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""))
    return ok


def _load_config(agent_id: int):
    from sqlalchemy import text

    from db.database import SessionLocal
    from models.deep_agent import DeepAgentConfig

    db = SessionLocal()
    try:
        raw = db.execute(text("SELECT config FROM deep_agent_templates WHERE id=:i"),
                         {"i": agent_id}).scalar()
    finally:
        db.close()
    if raw is None:
        raise SystemExit(f"no deep_agent_templates row with id={agent_id}")
    return DeepAgentConfig(**(raw if isinstance(raw, dict) else json.loads(raw)))


def _tool_objects(node) -> dict:
    """name → tool, walked from the compiled tool node (same walk the inspect script uses)."""
    out: dict = {}
    seen: set[int] = set()

    def walk(obj, depth: int = 0) -> None:
        if obj is None or depth > 3 or id(obj) in seen:
            return
        seen.add(id(obj))
        by_name = getattr(obj, "tools_by_name", None)
        if isinstance(by_name, dict):
            out.update(by_name)
        for attr in ("bound", "func", "node", "runnable"):
            child = getattr(obj, attr, None)
            if child is not None:
                walk(child, depth + 1)

    walk(getattr(node, "bound", None) or node)
    return out


async def _build(agent_id: int, config):
    import deepagents
    import deepagents.graph as dg

    sdk: dict = {}
    stack: dict = {}
    real_da, real_ca = deepagents.create_deep_agent, dg.create_agent

    def spy_da(**kw):
        sdk.update(kw)
        return real_da(**kw)

    def spy_ca(*a, **kw):
        stack["middleware"] = kw.get("middleware") or []
        return real_ca(*a, **kw)

    deepagents.create_deep_agent = spy_da
    dg.create_agent = spy_ca
    try:
        from services.deepagent_factory import DeepAgentFactory

        agent, configured, _cbs = await DeepAgentFactory.create_deep_agent(
            config=config, project_id=1, task_id=1, context="verify",
            workspace_root=os.path.abspath(f"outputs/agents/agent_{agent_id}"),
            agent_id=agent_id)
    finally:
        deepagents.create_deep_agent = real_da
        dg.create_agent = real_ca
    return agent, configured, sdk, stack


def _turn(agent_id: int, message: str) -> None:
    """One real turn over the chat API — prints the `task` frames (dispatch + receipt)."""
    import urllib.request

    base = os.environ.get("LANGCONFIG_BASE", "http://127.0.0.1:8765").rstrip("/")

    def post(path: str, payload: dict):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        return urllib.request.urlopen(req, timeout=300)

    sid = json.load(post("/api/chat/start", {"agent_id": agent_id}))["session_id"]
    print(f"\n=== one real turn (session {sid}) ===")
    body = json.dumps({"session_id": sid, "message": message}).encode()
    req = urllib.request.Request(base + "/api/chat/message/stream", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    tasks, text = [], []
    for raw in urllib.request.urlopen(req, timeout=600):
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("tool_name") == "task" or (obj.get("data") or {}).get("task"):
            tasks.append(obj)
        for k in ("text", "delta", "content"):
            if isinstance(obj.get(k), str) and obj[k]:
                text.append(obj[k])
    print(f"  task frames: {len(tasks)}")
    for t in tasks[:6]:
        print(f"    {json.dumps(t, ensure_ascii=False)[:400]}")
    print("  answer tail:")
    print("    " + "".join(text)[-700:].replace("\n", "\n    "))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_id", type=int, nargs="?", default=393)
    ap.add_argument("--turn", action="store_true",
                    help="also run ONE real turn (dispatch tables for a plan, no build)")
    args = ap.parse_args()

    config = _load_config(args.agent_id)
    print(f"agent {args.agent_id} — {getattr(config, 'system_prompt', '')[:40]!r}…")
    print(f"  native_tools: {config.native_tools}")
    print(f"  subagents   : {[s.name for s in config.subagents]}")

    agent, configured, sdk, stack = await _build(args.agent_id, config)
    good = True

    print("\n1) the manager cannot bypass the experts")
    tools = _tool_objects(agent.nodes.get("tools"))
    task_tool = tools.get("task")
    desc = getattr(task_tool, "description", "") or ""
    listed = [n for n in EXPECTED if n in desc]
    good &= _ok(task_tool is not None, "`task` tool exists in the compiled graph")
    # deepagents auto-adds `general-purpose` unless a spec by that name exists; we supply one that REFUSES,
    # so the name is present but the all-tools route is not. Assert the placeholder, not its absence.
    gp = next((sa for sa in config.subagents if sa.name == "general-purpose"), None)
    gp_desc = (gp.description if gp else "") or ""
    good &= _ok(gp is not None and "禁用" in gp_desc,
                "the auto-added `general-purpose` is neutralised by our own refusing placeholder",
                f"spec: {gp_desc[:80]!r}" if gp else "no general-purpose spec — the SDK catch-all would be used")
    good &= _ok(sorted(listed) == sorted(EXPECTED),
                f"the four experts are listed ({', '.join(listed) or 'none'})")
    print("        task description (first 400 chars):")
    print("        " + " ".join(desc.split())[:400])

    print("\n2) every expert is told to end with the receipt block")
    for sa in config.subagents:
        if sa.name not in EXPECTED:
            continue
        prompt = sa.system_prompt or ""
        good &= _ok(all(k in prompt for k in RECEIPT_KEYS),
                    f"{sa.name}: prompt asks for {sorted(RECEIPT_KEYS)}")
        good &= _ok(sa.response_format is None,
                    f"{sa.name}: response_format not set (unavailable on a thinking-mode model)")

    print("\n3) the manager does not do the work itself")
    forbidden = {"write_file", "edit_file", "db_build_from_file", "db_plan_from_file", "db_query",
                 "ontology_open"}
    leaked = sorted(set(config.native_tools or []) & forbidden)
    good &= _ok(not leaked, "manager has no declaration/db/file-write tools", f"leaked: {leaked}")

    print("\n4) the experts get different tools")
    seen: dict[str, list[str]] = {}
    for sa in config.subagents:
        if sa.name in EXPECTED:
            seen[sa.name] = sorted(sa.tools or [])
    good &= _ok(len({tuple(v) for v in seen.values()}) >= 3,
                "at least three distinct tool subsets",
                "; ".join(f"{k}={len(v)}" for k, v in seen.items()))
    good &= _ok("db_build_from_file" not in (seen.get("modeller") or []),
                "`modeller` cannot build a database (that is `tables`)")

    print("\n5) delegation is wired")
    names = [m.__class__.__name__ for m in stack.get("middleware") or []]
    good &= _ok(any("SubAgent" in n for n in names), "SubAgentMiddleware is in the stack",
                ", ".join(names))
    passed = [s.get("name") if isinstance(s, dict) else getattr(s, "name", "?")
              for s in (sdk.get("subagents") or [])]
    good &= _ok(sorted(passed) == sorted(EXPECTED + ["general-purpose"]),
                f"SDK received four experts + our refusing placeholder ({passed})")

    print("\nNOT PROVEN HERE: a real multi-expert turn, a step-capped expert failing loudly, UI rendering.")
    if args.turn:
        _turn(args.agent_id,
              "先在 upload/ 里看有没有 .xlsx；如果有，派 tables 出一份建库方案（不要建库），"
              "把它回报的『需要确认的点』原样贴给我。没有文件就直接说没有。")

    print(f"\n=== {'PASS' if good else 'FAIL'} ===")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
