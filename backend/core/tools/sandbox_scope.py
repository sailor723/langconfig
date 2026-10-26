# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Bind each tool call to the workspace root of the person it runs for.

The problem this solves, precisely: an agent's native tools resolve their filesystem
sandbox from ``services.user_roots.current_root()``, which reads the request identity.
But the agent harness executes tool calls in its own task, where that identity is not
visible — so the lookup fell through to the install's owner, and a second account's
agent ran in the first account's tree (and could read every other account's files).

The fix is to stop asking "who is this?" inside the tool and instead carry the answer
in: whoever builds the agent already knows the workspace root (``create_agent(...,
workspace_root=...)``), so it is bound here for the duration of each tool call.

Why per call rather than around the whole invocation: the harness may run tool calls in
a different task than the one that started the agent — the earlier attempt to bind once,
around ``ainvoke``, silently did nothing for exactly that reason. Inside the call, the
binding is always in the context that reads it, and two people's agents running
concurrently cannot see each other's root.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def scope_tools_to_root(tools: Iterable, root: Optional[str]) -> list:
    """Return the tools, each wrapped to run with ``root`` bound.

    Returns the input untouched when there is no root (an install with no accounts keeps
    its old behaviour) or when a tool cannot be re-wrapped, so this can never break an
    agent that was working before.
    """
    tools = list(tools or [])
    if not root:
        return tools

    from langchain_core.tools import StructuredTool

    from services import user_roots

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
                        token = user_roots.bind_run_root(root)
                        try:
                            return await fn(*args, **kwargs)
                        finally:
                            user_roots.clear_run_root(token)
                    return _async

                def _sync(*args, **kwargs):
                    token = user_roots.bind_run_root(root)
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        user_roots.clear_run_root(token)
                return _sync

            scoped = StructuredTool.from_function(
                func=_bind(sync_fn, False),
                coroutine=_bind(async_fn, True),
                name=tool.name,
                description=tool.description,
                args_schema=getattr(tool, "args_schema", None),
            )
            # Preserve the flags an agent may depend on.
            for flag in ("return_direct", "tags", "metadata"):
                if hasattr(tool, flag):
                    try:
                        setattr(scoped, flag, getattr(tool, flag))
                    except Exception:
                        pass
            wrapped.append(scoped)
        except Exception:  # never lose a tool because wrapping failed
            logger.warning(
                "Could not scope tool %r to the workspace root; using it unscoped",
                getattr(tool, "name", "?"), exc_info=True,
            )
            wrapped.append(tool)
    return wrapped
