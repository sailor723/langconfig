#!/usr/bin/env python3
"""Did the agent ask the DATABASE through a db tool, or through a shell?

Why this exists. On 2026-11-25 the ontology pipeline finished a build/register run using `execute`
**264 times** and `db_query_agent` **8 times**. The prompt said "don't query the database from the
shell"; nothing checked. A rule nobody can test is a wish, so this is the check:

  * every tool call in a session is read from `chat_sessions.tool_calls` (the transcript is the
    authority — a turn's prose is not);
  * the DB-touching calls are separated into "through a tool" and "through a shell";
  * the shell ones are matched on their actual command/args (`psql`, `psycopg`, `sqlalchemy`,
    `python -c … connect`, `copy … from stdin`), not on a keyword in prose.

Usage:

    cd backend && .venv/bin/python scripts/audit_db_tool_usage.py --agent-id 393
    cd backend && .venv/bin/python scripts/audit_db_tool_usage.py --session <session_id> --json
    cd backend && .venv/bin/python scripts/audit_db_tool_usage.py --agent-id 393 --last 5

Exit: 0 clean, 1 shell reached the database (warn), 2 shell reached the database and no db tool was
used at all (fail). Wire it into a turn's acceptance: a ticket that claims "查过库" must add
`--session <id>` to its verification and be exit-0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DB_TOOLS = {"db_query_agent", "db_query_langgraph", "db_describe", "db_list_databases",
            "db_review", "db_verify_against_file", "db_build_from_file", "db_plan_from_file",
            "db_rename_column", "db_execute"}
SHELL_TOOLS = {"execute", "bash", "python_execute", "shell"}

#: Patterns that mean "this shell command talked to a database".
SHELL_DB_PATTERNS = [
    r"\bpsql\b", r"\bpg_dump\b", r"\bpg_restore\b", r"\bcreatedb\b", r"\bdropdb\b",
    r"psycopg2?", r"\bsqlalchemy\b", r"\bcopy\s+\S+\s+from\s+stdin\b",
    r"connect\(.*dbname", r"PGPASSWORD", r"\bDATABASE_URL\b",
]
SHELL_DB_RE = re.compile("|".join(SHELL_DB_PATTERNS), re.I)


def _calls_of(call: dict) -> tuple[str, str]:
    """(tool_name, flattened argument text) for one recorded tool call."""
    name = str(call.get("tool_name") or call.get("name") or "")
    args = call.get("arguments") or {}
    if isinstance(args, dict):
        parts = []
        for key in ("command", "code", "sql", "sqls", "file", "db_name"):
            value = args.get(key)
            if value:
                parts.append(f"{key}={value}")
        text = " ".join(parts) if parts else json.dumps(args, ensure_ascii=False, default=str)
    else:
        text = str(args)
    return name, text


def classify(calls: list[dict], since: str = "") -> dict:
    """Split recorded calls into tool / shell-DB / blocked-by-guard.

    `since` (ISO) keeps only calls recorded after it: a session accumulates calls across turns, so a
    prefix from before the guard existed would otherwise be counted forever.
    """
    from datetime import datetime, timezone

    def _naive(stamp: str):
        """Timestamps in the transcript are naive local wall-clock; compare like-for-like (both naive)."""
        try:
            value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        return value.replace(tzinfo=None)

    cutoff = _naive(since) if since else None

    db_tool, shell_db, shell_total, other, blocked = [], [], 0, 0, []
    for call in calls:
        if not isinstance(call, dict):
            continue
        ts = str(call.get("timestamp") or "")
        if cutoff is not None and ts:
            stamp = _naive(ts)
            if stamp is not None and stamp < cutoff:
                continue
        if "拒绝执行" in str(call.get("result") or ""):
            blocked.append((str(call.get("tool_name") or ""), _calls_of(call)[1][:200]))
            continue
        name, text = _calls_of(call)
        if name in DB_TOOLS:
            db_tool.append((name, text[:160]))
        elif name in SHELL_TOOLS:
            shell_total += 1
            if SHELL_DB_RE.search(text):
                shell_db.append((name, text[:200]))
        else:
            other += 1
    verdict = "pass"
    if shell_db:
        verdict = "warn" if db_tool else "fail"
    return {"verdict": verdict, "db_tool_calls": len(db_tool), "shell_calls": shell_total,
            "shell_db_calls": len(shell_db), "other_calls": other,
            "db_tools_used": sorted({n for n, _ in db_tool}),
            "shell_db_examples": shell_db[:5], "db_examples": db_tool[:5],
            "blocked_attempts": len(blocked), "blocked_examples": blocked[:3]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent-id", type=int, default=None)
    ap.add_argument("--session", default="")
    ap.add_argument("--last", type=int, default=1, help="how many recent sessions to audit")
    ap.add_argument("--since", default="", help="only calls recorded after this ISO timestamp")
    ap.add_argument("--last-calls", type=int, default=0,
                    help="audit only the most recent N recorded calls (use after one turn)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    from db.database import SessionLocal
    from models.deep_agent import ChatSession

    db = SessionLocal()
    try:
        q = db.query(ChatSession)
        if args.session:
            q = q.filter(ChatSession.session_id == args.session)
        elif args.agent_id:
            q = q.filter(ChatSession.agent_id == args.agent_id)
        sessions = q.order_by(ChatSession.updated_at.desc()).limit(args.last if not args.session else 1).all()
        if not sessions:
            print("no session matched")
            return 0
        worst = 0
        reports = []
        for s in sessions:
            calls = s.tool_calls or []
            if args.last_calls and isinstance(calls, list):
                calls = calls[-args.last_calls:]
            rep = classify(calls if isinstance(calls, list) else [], since=args.since)
            rep.update({"session": s.session_id, "agent_id": s.agent_id,
                        "updated_at": str(s.updated_at), "messages": len(s.messages or [])})
            reports.append(rep)
            worst = max(worst, {"pass": 0, "warn": 1, "fail": 2}[rep["verdict"]])
        if args.as_json:
            print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
        else:
            for r in reports:
                print(f"{r['verdict'].upper():5} session={r['session'][:8]} agent={r['agent_id']} "
                      f"msgs={r['messages']}")
                print(f"      db tools {r['db_tool_calls']} ({', '.join(r['db_tools_used']) or '—'}) | "
                      f"shell {r['shell_calls']} (of which DB {r['shell_db_calls']}) | other {r['other_calls']}")
                if r.get("blocked_attempts"):
                    print(f"      blocked by guard: {r['blocked_attempts']} attempt(s), none reached the DB")
                    for name, text in r["blocked_examples"]:
                        print(f"         {name}: {text[:110]}")
                for name, text in r["shell_db_examples"]:
                    print(f"      ✗ shell→DB via {name}: {text[:120]}")
        return worst
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
