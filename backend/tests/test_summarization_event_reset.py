"""Dropping messages must also reset deepagents' summarization event.

Measured on ECS (2026-11-14, agent 380 / ebl_ops_v1): our compaction dropped the older messages, but
`SummarizationState._summarization_event` kept an ABSOLUTE `cutoff_index` of 373 while the list held
74-200 messages. `_apply_event_to_messages` then returned "summary message only" on every model call
— the agent lost all recent context, re-issued the same `ls` until the loop guard fired, and the
warning printed every two seconds (`Request options` 20 in 40 s, 0 tool calls, 0 files written).

The event's index is meaningful only against the list it was computed on, so an event that points
past the end is stale and must be cleared in the SAME state update that removes the messages.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUDGET = REPO / "backend" / "services" / "thread_budget.py"


def _module():
    spec = importlib.util.spec_from_file_location("thread_budget2", BUDGET)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["thread_budget2"] = module
    spec.loader.exec_module(module)
    return module


def test_an_event_pointing_past_the_end_is_stale():
    module = _module()
    values = {"messages": [object()] * 74,
              "_summarization_event": {"cutoff_index": 373, "summary_message": "…"}}
    assert module.summarization_event_is_stale(values) is True


def test_an_event_inside_the_list_is_not_stale():
    module = _module()
    values = {"messages": [object()] * 200,
              "_summarization_event": {"cutoff_index": 120, "summary_message": "…"}}
    assert module.summarization_event_is_stale(values) is False


def test_no_event_is_not_stale():
    module = _module()
    assert module.summarization_event_is_stale({"messages": [object()]}) is False
    assert module.summarization_event_is_stale({}) is False


def test_the_compaction_writes_the_reset_in_the_same_update():
    """The reset must ride along with the removals — a second call could be lost to a crash."""
    text = BUDGET.read_text(encoding="utf-8")
    start = text.index("async def shrink_thread")
    body = text[start:]
    assert "SUMMARIZATION_EVENT_KEY] = None" in body, \
        "a compaction still leaves a stale summarization index behind"
    assert "if plan.dropped_ids or event_stale:" in body, \
        "the reset is not tied to the drop it invalidates"
    assert "payload" in body and "aupdate_state(config, payload)" in body, \
        "messages and the event reset must travel in one update"
