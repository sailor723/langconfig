"""Record that a tool was actually CALLED — the one number the tool library could not answer.

Measured 2026-11-25: `custom_tools.usage_count` was 0 for all 88 rows, including tools we had just invoked
through a chat turn. The only writer was `core/agents/tool_loader.py::load_custom` — the path for
USER-DEFINED custom tools — so every builtin/native tool (the entire `db_*`, `pg_*`, skill and filesystem
family) never counted anything. `last_used_at` was equally empty.

Counting at LOAD would still be the wrong number: it says "this agent was built with this tool", not "anyone
ever called it". The housekeeping question is the second one ("does this tool earn its place?"), so the
counter lives where the call happens: `ToolFactory.create_tool` wraps the built callable, every path
(`load_custom` and `_load_builtin_from_db`) goes through it, and the wrap is the same for both.

Two rules this module keeps:

* **telemetry never breaks a tool call.** Any failure here (no database, missing row, a closed session) is
  swallowed and logged at debug level. A tool that worked must not fail because a counter did not.
* **a call that raises is counted too, as an error.** A tool that is always tried and always fails is a
  different housekeeping decision from one that is never tried, and `error_count` is where that shows.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def record_use(tool_id: str, *, ok: bool = True) -> None:
    """+1 to `usage_count` (or `error_count`), and stamp the matching timestamp. Never raises."""
    tid = (tool_id or "").strip()
    if not tid:
        return
    try:
        from sqlalchemy import text

        from db.database import SessionLocal

        col = "usage_count" if ok else "error_count"
        stamp = "last_used_at" if ok else "last_error_at"
        db = SessionLocal()
        try:
            db.execute(text(f"UPDATE custom_tools SET {col} = {col} + 1, {stamp} = now() "
                            f"WHERE tool_id = :t"), {"t": tid})
            db.commit()
        finally:
            db.close()
    except Exception as exc:                                     # noqa: BLE001
        logger.debug(f"tool usage not recorded for {tid!r}: {type(exc).__name__}: {exc}")


def wrap(tool, tool_id: str):
    """Return `tool` with its callable wrapped so every call is counted.

    Works for the `StructuredTool`s `ToolFactory` builds: `func` for sync tools, `coroutine` for async ones.
    A tool whose callable is already wrapped (a second build of the same row) is returned unchanged — the
    counter must not double-count because an agent was rebuilt.
    """
    if getattr(tool, "_usage_wrapped", False):
        return tool

    sync_fn = getattr(tool, "func", None)
    async_fn = getattr(tool, "coroutine", None)

    if sync_fn is not None:
        def counted_sync(*args, **kwargs):
            try:
                result = sync_fn(*args, **kwargs)
            except BaseException:
                record_use(tool_id, ok=False)
                raise
            record_use(tool_id, ok=True)
            return result

        try:
            tool.func = counted_sync
        except Exception:                                        # noqa: BLE001 — frozen tool: leave it alone
            return tool

    if async_fn is not None:
        async def counted_async(*args, **kwargs):
            try:
                result = await async_fn(*args, **kwargs)
            except BaseException:
                record_use(tool_id, ok=False)
                raise
            record_use(tool_id, ok=True)
            return result

        try:
            tool.coroutine = counted_async
        except Exception:                                        # noqa: BLE001
            return tool

    try:
        tool._usage_wrapped = True
    except Exception:                                            # noqa: BLE001
        pass
    return tool
