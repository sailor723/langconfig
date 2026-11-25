"""Gates for tool usage counting — the number that decides housekeeping.

Measured 2026-11-25: `custom_tools.usage_count` was 0 for all 88 rows, including tools we had just invoked
through a chat turn, and `last_used_at` was empty. The only writer was `load_custom` — the path for
user-defined tools — so every builtin/native tool counted nothing.

Counting at load was also the wrong question. "Was this agent built with the tool" is not "does the tool
earn its place"; the second one is what a housekeeping pass needs, so the counter now sits around the tool's
CALLABLE (`ToolFactory.create_tool` wraps every tool it builds, both load paths).

Pinned here:

* a call increments `usage_count` and stamps `last_used_at`;
* a call that RAISES increments `error_count` (and the exception still reaches the caller — telemetry may
  not swallow a failure);
* `record_use` never raises, even for a tool id that does not exist (a counter must not break a tool call);
* wrapping twice does not double count (an agent rebuilt must not look like two calls);
* both sync and async tools are counted (the `db_*` family is async; the filesystem tools are sync).

Run: cd backend && .venv/bin/python -m pytest tests/test_tool_usage_counting.py -v
"""
from __future__ import annotations

import asyncio
import types

import pytest

from core.tools import usage as U


def _row(tool_id: str = "db_describe") -> tuple:
    from sqlalchemy import text

    from db.database import SessionLocal

    db = SessionLocal()
    try:
        return db.execute(text("select usage_count, error_count, last_used_at from custom_tools "
                               "where tool_id = :t"), {"t": tool_id}).fetchone()
    finally:
        db.close()


def test_a_call_is_counted_and_stamped():
    from sqlalchemy import text

    from db.database import SessionLocal

    db = SessionLocal()
    # Reset BOTH counters: these tests share one row, and a test that only resets the column it
    # asserts would read a neighbour's error_count and fail for a reason that is not about counting.
    db.execute(text("update custom_tools set usage_count = 0, error_count = 0, last_used_at = null, "
                    "last_error_at = null where tool_id = 'db_describe'"))
    db.commit()
    db.close()

    U.record_use("db_describe")
    used, errors, stamp = _row()
    assert used == 1 and errors == 0 and stamp is not None


def test_a_failure_is_counted_as_an_error_but_still_raises():
    from sqlalchemy import text

    from db.database import SessionLocal

    db = SessionLocal()
    db.execute(text("update custom_tools set error_count = 0 where tool_id = 'db_describe'"))
    db.commit()
    db.close()

    def explode():
        raise RuntimeError("tool blew up")

    tool = types.SimpleNamespace(func=explode)
    wrapped = U.wrap(tool, "db_describe")
    with pytest.raises(RuntimeError):
        wrapped.func()
    _used, errors, _stamp = _row()
    assert errors == 1, "a raising call must be visible as an error, not silently swallowed"


def test_an_async_tool_is_counted():
    from sqlalchemy import text

    from db.database import SessionLocal

    db = SessionLocal()
    db.execute(text("update custom_tools set usage_count = 0 where tool_id = 'db_describe'"))
    db.commit()
    db.close()

    async def work(x: int) -> int:
        return x * 2

    tool = types.SimpleNamespace(coroutine=work)
    wrapped = U.wrap(tool, "db_describe")
    assert asyncio.run(wrapped.coroutine(3)) == 6
    used, _errors, _stamp = _row()
    assert used == 1


def test_wrapping_twice_does_not_double_count():
    from sqlalchemy import text

    from db.database import SessionLocal

    db = SessionLocal()
    db.execute(text("update custom_tools set usage_count = 0 where tool_id = 'db_describe'"))
    db.commit()
    db.close()

    calls = []
    tool = types.SimpleNamespace(func=lambda: calls.append(1) or "ok")
    U.wrap(tool, "db_describe")
    U.wrap(tool, "db_describe")          # a rebuild must not add a second wrapper
    tool.func()
    used, _errors, _stamp = _row()
    assert len(calls) == 1 and used == 1, f"calls={len(calls)} used={used}"


def test_recording_never_raises_for_an_unknown_tool():
    U.record_use("definitely_not_a_tool_id")   # no exception, and nothing else changes
    U.record_use("")
