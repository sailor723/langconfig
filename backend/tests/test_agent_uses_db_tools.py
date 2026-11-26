"""Gate: an agent that touched the database through the SHELL fails here.

The rule ("query the database with `db_query_agent` / `db_query_langgraph` / `db_execute`, never with
`psql` or `python -c`") was already written in prompts and skills — and measured on 2026-11-25, the
ontology builder still used `psql` from `execute` and **four** shell→DB calls in one session with only
four db-tool calls. A rule nobody can test is a wish; this is the test.

What it does: runs `scripts/audit_db_tool_usage.py`'s classifier over the most recent recorded
sessions of the agents named in `AUDITED_AGENTS` and fails when a session reached the database through
a shell. Sessions with no tool calls are skipped (nothing to judge).

Override the target for a specific session/turn:
    DSH_AUDIT_SESSION=<session_id> DSH_AUDIT_AGENT_ID=393 .venv/bin/python -m pytest tests/test_agent_uses_db_tools.py
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
AUDITED_AGENTS = (393, 375)          # ontology builder + the standalone table builder

#: The rule is enforced FROM here on. Sessions recorded before it are history, not regressions —
#: the 2026-11-25 13:2x run predates the boundary text and used `psql` from `execute` (see
#: docs/system-architecture/ontology-agent-boundaries.md §1). Override with DSH_AUDIT_SINCE.
ENFORCED_SINCE = os.environ.get("DSH_AUDIT_SINCE", "2026-11-25T14:20:00+00:00")


def _audit_module():
    path = BACKEND / "scripts" / "audit_db_tool_usage.py"
    spec = importlib.util.spec_from_file_location("audit_db_tool_usage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sessions(agent_id: int, limit: int):
    from db.database import SessionLocal
    from models.deep_agent import ChatSession

    db = SessionLocal()
    try:
        return (db.query(ChatSession)
                .filter(ChatSession.agent_id == agent_id)
                .order_by(ChatSession.updated_at.desc()).limit(limit).all())
    finally:
        db.close()


@pytest.mark.parametrize("agent_id", AUDITED_AGENTS)
def test_the_agent_reached_the_database_through_tools_not_a_shell(agent_id):
    wanted_session = os.environ.get("DSH_AUDIT_SESSION", "").strip()
    only_agent = os.environ.get("DSH_AUDIT_AGENT_ID", "").strip()
    if only_agent and str(agent_id) != only_agent:
        pytest.skip("auditing one agent only (DSH_AUDIT_AGENT_ID)")
    audit = _audit_module()

    sessions = _sessions(agent_id, 5)
    if wanted_session:
        sessions = [s for s in sessions if s.session_id == wanted_session]
    from datetime import datetime, timezone
    since = datetime.fromisoformat(ENFORCED_SINCE)
    judged = [s for s in sessions
              if s.tool_calls and s.updated_at and s.updated_at.astimezone(timezone.utc) >= since]
    if not judged:
        pytest.skip(f"agent {agent_id} has no recorded tool calls since {ENFORCED_SINCE}")

    problems = []
    for s in judged:
        rep = audit.classify(s.tool_calls if isinstance(s.tool_calls, list) else [])
        if rep["verdict"] != "pass":
            problems.append((s.session_id[:8], rep["verdict"], rep["db_tool_calls"],
                             rep["shell_db_calls"], rep["shell_db_examples"][:2]))
    assert not problems, (
        "an agent reached the database through a shell instead of db_query_agent / "
        "db_query_langgraph / db_execute:\n"
        + "\n".join(f"  session {sid} verdict={v} db_tools={n} shell→db={k} e.g. {ex}"
                    for sid, v, n, k, ex in problems)
    )
