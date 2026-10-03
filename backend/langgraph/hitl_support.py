"""Shared helpers for the HITL LangGraph agents (sql_agent_hitl, neo4j_agent_hitl).

Two problems this module solves, both discovered by running the agents from the
Graph activity:

1. **Dangling tool calls after an interrupt.**
   The review node pauses with ``interrupt()`` *between* the model asking for a
   tool call and that tool running. The checkpoint therefore holds an assistant
   message with ``tool_calls`` that no ``ToolMessage`` answers. If a human then
   sends a *new message* instead of a decision (which the UI allowed), the very
   next model call carries that invalid history and the provider rejects it:

       Error code: 400 - "An assistant message with 'tool_calls' must be
       followed by tool messages responding to each tool_call_id"

   ``repair_node()`` answers any unmatched tool call with a placeholder
   ``ToolMessage``, so every route out of START has a valid history. This is the
   hand-built-graph equivalent of deepagents' ``PatchToolCallsMiddleware``.

2. **The preamble re-running on every turn.**
   Both HITL graphs wired ``START -> list_tables`` unconditionally, so every new
   message re-fetched the tables and schema (2 extra model calls). The conditional
   router mirrors ``sql_agent.py``: the preamble runs once per thread, then is
   skipped because the schema is already in the checkpointed history.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.messages import RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

logger = logging.getLogger(__name__)

# Placeholder text recorded for a tool call that was interrupted and superseded.
SUPERSEDED_NOTE = (
    "Not executed: the run was interrupted for human review and a new message "
    "arrived before a decision was made. If the query is still needed, call the "
    "tool again."
)


def repair_dangling_tool_calls(messages: list) -> tuple[list, int]:
    """Return ``(messages, inserted)`` with every unanswered tool call answered.

    A tool call is "answered" when some message carries its ``tool_call_id``.
    Inserted placeholders keep the history valid for the provider without
    pretending the tool ran.
    """
    answered = {
        getattr(m, "tool_call_id", None)
        for m in messages
        if getattr(m, "tool_call_id", None)
    }

    patched: list = []
    inserted = 0
    for message in messages:
        patched.append(message)
        for call in getattr(message, "tool_calls", None) or []:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if not call_id or call_id in answered:
                continue
            kwargs: dict[str, Any] = {
                "content": SUPERSEDED_NOTE,
                "tool_call_id": call_id,
            }
            if name:
                kwargs["name"] = name
            patched.append(ToolMessage(**kwargs))
            answered.add(call_id)
            inserted += 1

    return patched, inserted


def make_repair_node():
    """Build the ``repair_history`` node: fix history, then continue."""

    def repair_history(state) -> dict:
        messages = state.get("messages") or []
        patched, inserted = repair_dangling_tool_calls(messages)
        if not inserted:
            return {}
        logger.info(
            "repair_history: answered %d interrupted tool call(s) so the "
            "history stays valid for the provider",
            inserted,
        )
        # The messages reducer (add_messages) merges by id and appends anything
        # new at the END of the list — which is the wrong position for a tool
        # response: it must directly follow the assistant message that made the
        # call. Clearing the channel first lets us write the corrected order.
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *patched]}

    repair_history.__name__ = "repair_history"
    return repair_history


def make_preamble_router(marker: str, preamble_node: str):
    """Build the router that runs the schema preamble once per thread.

    ``marker`` is the text the preamble node stamps into an AIMessage
    (e.g. "Available tables"); its presence means the schema is already in the
    checkpointed history.
    """

    def should_preamble(state) -> str:
        for message in state.get("messages") or []:
            if marker in str(getattr(message, "content", "") or ""):
                return "generate_query"
        return preamble_node

    should_preamble.__name__ = "should_preamble"
    return should_preamble
