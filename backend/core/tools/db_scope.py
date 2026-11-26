"""Bind each tool call to the agent's OWN database — the one configured in Agent → Database.

Why this file exists: `config.database` used to reach the sandbox only. The shell's `execute` received
PGHOST/PGPASSWORD from it, while the in-process tools (`db_query_agent`, `db_describe`, `db_review`, `db_admin.*`)
read `os.environ` and therefore always connected as the DEPLOYMENT's role. Measured 2026-11-25: the `test_db`
agent carried a Database block that nothing read — it appeared to work only because the backend's process env
holds `POSTGRES_*`. An agent whose Database section does nothing is worse than one without the section.

The binding is per CALL, in a contextvar (`services.agent_database.bind_run_db_env`), for the same reason the
workspace root is bound per call (`core/tools/sandbox_scope.py`): the harness may run tool calls in its own
task, so a binding made once around `ainvoke` is invisible inside the call — and two agents running at the
same time must not see each other's credentials.

A tool that cannot be wrapped is returned unchanged: this may never lose a working tool.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def scope_tools_to_database(tools: Iterable, env: Optional[dict]) -> list:
    """Return the tools, each wrapped to run with the agent's own connection bound."""
    tools = list(tools or [])
    if not env:
        return tools

    from langchain_core.tools import StructuredTool

    from services import agent_database

    wrapped = []
    for tool in tools:
        try:
            sync_fn = getattr(tool, "func", None)
            async_fn = getattr(tool, "coroutine", None)

            def _bind(fn, is_async):
                if fn is None:
                    return None
                if is_async:
                    async def _async(*args, **kwargs):
                        token = agent_database.bind_run_db_env(env)
                        try:
                            return await fn(*args, **kwargs)
                        finally:
                            agent_database.clear_run_db_env(token)
                    return _async

                def _sync(*args, **kwargs):
                    token = agent_database.bind_run_db_env(env)
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        agent_database.clear_run_db_env(token)
                return _sync

            wrapped_tool = StructuredTool.from_function(
                func=_bind(sync_fn, False),
                coroutine=_bind(async_fn, True),
                name=tool.name,
                description=tool.description,
                args_schema=getattr(tool, "args_schema", None),
            )
            for flag in ("return_direct", "tags", "metadata"):
                if hasattr(tool, flag):
                    try:
                        setattr(wrapped_tool, flag, getattr(tool, flag))
                    except Exception:                        # noqa: BLE001
                        pass
            wrapped.append(wrapped_tool)
        except Exception:                                    # never lose a tool because wrapping failed
            logger.warning("Could not scope tool %r to the agent's database; using it unscoped",
                           getattr(tool, "name", "?"), exc_info=True)
            wrapped.append(tool)
    return wrapped
