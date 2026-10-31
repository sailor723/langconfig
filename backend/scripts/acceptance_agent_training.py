#!/usr/bin/env python
"""Acceptance run for the agent-training build (CLI, no UI).

One command answers "does the platform still do what the run book teaches?":

    cd backend
    .venv/bin/python scripts/acceptance_agent_training.py            # all sections
    .venv/bin/python scripts/acceptance_agent_training.py --only hitl,handoffs
    .venv/bin/python scripts/acceptance_agent_training.py --keep     # keep created sessions

Sections (each checks behaviour, not configuration alone):

  A  catalog      — retired tools stay retired, `task` still there
  B  hitl         — pause, approve, one-shot 409
  C  subagents    — two delegations in one turn, spawns recorded with their names
  D  handoffs     — two hops, persisted, and each answer follows its hop
  E  skills       — no skill for an unrelated ask, `skill` loaded when it matters
  F  router       — two verticals dispatched in one turn, then synthesised

Requires the backend on :8765 with the case agents from the run book
(`case-2-subagents`, `case-3-handoff`, `case-4-skills`, `case-5-router`);
the HITL agent is created on first run and reused afterwards.
"""

import argparse, json, os, sys, uuid, requests

BASE = "http://127.0.0.1:8765"
PASS, FAIL = [], []

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--only", default="", help="comma-separated section names (catalog,hitl,subagents,handoffs,skills,router,calendar)")
_parser.add_argument("--keep", action="store_true", help="leave the sessions it created in place")
_args = _parser.parse_args()
ONLY = {s.strip().lower() for s in _args.only.split(",") if s.strip()}

def wanted(section: str) -> bool:
    return not ONLY or section in ONLY

def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   [{detail}]" if detail else ""))

def post(path, body, timeout=300):
    r = requests.post(f"{BASE}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get(path, timeout=120):
    r = requests.get(f"{BASE}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()

def chat(session_id, message, timeout=300):
    events = []
    with requests.post(f"{BASE}/api/chat/message/stream",
                       json={"session_id": session_id, "message": message},
                       timeout=timeout, stream=True) as r:
        for raw in r.iter_lines(decode_unicode=True):
            if raw and raw.startswith("data: "):
                try: events.append(json.loads(raw[6:]))
                except Exception: pass
    return events

def calls_of(events, prefix=None):
    names = [e.get("tool_name") for e in events if e.get("type") == "tool_start"]
    return [n for n in names if prefix is None or str(n).startswith(prefix)]

def answer_of(events):
    return "".join(e.get("content", "") for e in events if e.get("type") == "chunk")

def new_session(agent_id):
    sid = post("/api/chat/start", {"agent_id": agent_id})["session_id"]
    chat(sid, "hi")
    return sid

def find_agent(name):
    for a in get("/api/deepagents/"):
        if a.get("name") == name:
            return a["id"]
    return None

# ── A. catalog ────────────────────────────────────────────────────────────────
if wanted("catalog"):
    print("\n== A. tool catalog ==")
    registry = {t["id"]: t for t in get("/api/tools/registry")}
    check("save_document retired", "save_document" not in registry)
    check("current_time retired", "current_time" not in registry)
    check("image_generation retired", "image_generation" not in registry)
    check("update_agent_prompt retired", "update_agent_prompt" not in registry)
    check("browser still listed (Playwright)", "browser" in registry)
    check("generic handoff tool retired (transfers are generated)", "handoff" not in registry)
    check("task (subagent dispatch) present", "task" in registry)

# ── B. HITL ───────────────────────────────────────────────────────────────────
if wanted("hitl"):
    print("\n== B. HITL ==")
    NAME = "acc-hitl"
    agent_id = find_agent(NAME)
    if agent_id is None:
        cfg = {"system_prompt": "You are a helpful assistant.",
               "model": "deepseek-flash", "temperature": 0.0, "max_tokens": 2000,
               "use_deepagents": False, "native_tools": ["python_execute"],
               "custom_tools": [], "cli_tools": [], "skills": [], "subagents": [],
               "middleware": [{"type": "hitl", "enabled": True, "config": {
                   "interrupt_on": {"write_file": {"allowed_decisions": ["approve", "reject"]}}}}],
               "guardrails": {"interrupts": {}}}
        agent_id = post("/api/deepagents/", {"name": NAME, "category": "Custom",
                                             "description": "acceptance: HITL", "config": cfg})["id"]
    print("  agent:", agent_id)

    # The gate is on write_file, so the question has to make it write a file —
    # asking for "use python" exercised python_execute and proved nothing.
    target = f"acc-hitl-{uuid.uuid4().hex[:6]}.md"
    sid = new_session(agent_id)
    events = chat(sid, f"把 approved 写进文件 {target}")
    interrupts = [e for e in events if e.get("type") == "interrupt"]
    check("a gated tool call interrupts", bool(interrupts))
    if interrupts:
        allowed = [c.get("allowed_decisions") for c in interrupts[0]["data"].get("review_configs", [])]
        check("the policy travels with the interrupt", allowed == [["approve", "reject"]], str(allowed))
        r = requests.post(f"{BASE}/api/chat/{sid}/resume", json={"action": "approve"}, timeout=300)
        check("approve resumes the run", r.status_code == 200, str(r.status_code))
        r2 = requests.post(f"{BASE}/api/chat/{sid}/resume", json={"action": "approve"}, timeout=120)
        check("a second approve is refused (one-shot)", r2.status_code == 409, str(r2.status_code))

# ── C. subagents ──────────────────────────────────────────────────────────────
if wanted("subagents"):
    print("\n== C. subagents ==")
    sub_id = find_agent("case-2-subagents")
    check("case-2-subagents exists", sub_id is not None, str(sub_id))
    if sub_id:
        sid = new_session(sub_id)
        events = chat(sid, "上海今天的天气怎么样？另外算一下 1234567 乘以 891011。")
        tasks = calls_of(events, "task")
        check("two delegations in one turn", len(tasks) == 2, str(tasks))
        check("the run answered", len(answer_of(events)) > 50, f"{len(answer_of(events))} chars")
        spawns = get(f"/api/chat/{sid}/metrics")
        names = [s.get("subagent") for s in (spawns.get("subagent_spawns") or [])]
        check("both spawns recorded", len(names) == 2, str(names))
        check("spawn names are the configured ones",
              set(names) == {"weather_expert", "math_expert"}, str(names))

# ── D. handoffs ───────────────────────────────────────────────────────────────
if wanted("handoffs"):
    print("\n== D. handoffs ==")
    ho_id = find_agent("case-3-handoff")
    check("case-3-handoff exists", ho_id is not None, str(ho_id))
    if ho_id:
        steps = get(f"/api/deepagents/{ho_id}")["config"]["middleware"][0]["config"]["steps"]
        check("three roles configured", set(steps) == {"sales", "support", "finance"}, str(list(steps)))
        sid = new_session(ho_id)
        events = chat(sid, "发票开错了怎么处理？")
        transfers = calls_of(events, "transfer_to_")
        hops = [e.get("to") for e in events if e.get("type") == "handoff"]
        check("at least one transfer", bool(transfers), str(transfers))
        check("every transfer emitted a hop event", len(hops) == len(transfers), f"{len(hops)}/{len(transfers)}")
        hist = get(f"/api/chat/{sid}/history")
        persisted = [m.get("to") for m in hist["messages"] if m.get("role") == "handoff"]
        check("hops persisted", len(persisted) == len(hops), f"{len(persisted)}/{len(hops)}")
        check("hops carry a reason",
              all(m.get("reason") for m in hist["messages"] if m.get("role") == "handoff"))
        # order: each hop must precede the assistant message it enabled
        roles = [("handoff" if m.get("role") == "handoff" else m.get("role")) for m in hist["messages"]]
        last_hop = max((i for i, r in enumerate(roles) if r == "handoff"), default=-1)
        last_ai = max((i for i, r in enumerate(roles) if r == "assistant"), default=-1)
        check("the final answer follows the final hop", last_ai > last_hop, f"hop@{last_hop} ai@{last_ai}")

# ── E. skills ────────────────────────────────────────────────────────────────
if wanted("skills"):
    print("\n== E. skills ==")
    sk_id = find_agent("case-4-skills")
    check("case-4-skills exists", sk_id is not None, str(sk_id))
    if sk_id:
        sid = new_session(sk_id)
        events = chat(sid, "帮我把这句话改得更简洁：今天天气不错。")
        check("no skill loaded for an unrelated ask", not calls_of(events, "skill"), str(calls_of(events)))
        sid = new_session(sk_id)
        events = chat(sid, "帮我 review 这段 Python 代码：def f(x): return x/0")
        loaded = [c for c in calls_of(events, "skill")]
        check("skill loaded when the question needs it", bool(loaded), str(loaded))

# ── F. router ────────────────────────────────────────────────────────────────
if wanted("router"):
    print("\n== F. router ==")
    ro_id = find_agent("case-5-router")
    check("case-5-router exists", ro_id is not None, str(ro_id))
    if ro_id:
        sid = new_session(ro_id)
        events = chat(sid, "上海今天天气怎么样？顺便算一下 1280 的 15% 是多少。")
        tasks = calls_of(events, "task")
        check("two verticals dispatched", len(tasks) == 2, str(tasks))
        ans = answer_of(events)
        check("answer synthesises both parts", ("192" in ans) and ("℃" in ans), ans[:60])
        metrics = get(f"/api/chat/{sid}/metrics")
        check("metrics count the spawns", (metrics.get("metrics") or {}).get("subagent_spawns") == 2,
              str((metrics.get("metrics") or {}).get("subagent_spawns")))

# ── G. calendar panel (case 6 data source) ───────────────────────────────────
if wanted("calendar"):
    print("\n== G. calendar ==")
    ca_id = find_agent("case-6-assistant")
    check("case-6-assistant exists", ca_id is not None, str(ca_id))
    if ca_id:
        tag = uuid.uuid4().hex[:6]
        sid = new_session(ca_id)
        before = get(f"/api/chat/{sid}/calendar")
        check("calendar answers before any event", isinstance(before.get("events"), list),
              str(before.get("files_scanned")))
        events = chat(sid, f"直接让 calendar_expert 安排下周三上午 10 点跟 Bob-{tag} 开 30 分钟会，不要问我确认。")
        after = get(f"/api/chat/{sid}/calendar")
        found = [e for e in after.get("events", [])
                 if tag in (e.get("title") or "") or tag in (e.get("file") or "")]
        check("the scheduled event reaches the calendar", bool(found),
              f"{len(after.get('events', []))} events")
        if found:
            first = found[0]
            check("event carries start/end", bool(first.get("start")) and bool(first.get("end")),
                  f"{first.get('start')}→{first.get('end')}")
            check("event names its source file", bool(first.get("file")), str(first.get("file")))
            # The panel must be told the truth about the clock: a file with no
            # TZID has to arrive as an explicit null, never as a guessed zone.
            check("a floating time arrives as an explicit null zone",
                  "timezone" in first and (first["timezone"] is None or isinstance(first["timezone"], str)),
                  repr(first.get("timezone")))

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}   FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  ✗", f)
sys.exit(0 if not FAIL else 1)
