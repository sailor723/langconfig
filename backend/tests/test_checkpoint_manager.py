# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the CheckpointManager rewrite.

The old implementation queried LangGraph's checkpoints table with columns
that don't exist (checkpoint_namespace, created_at) on the SYNC engine
under ``async with`` — every method silently returned empty results. The
rewrite goes through the AsyncPostgresSaver API. These tests exercise the
manager logic with a fake checkpointer and guard the source against the
old broken patterns.
"""
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from core.workflows.checkpointing import utils as cp_utils
from core.workflows.checkpointing.utils import CheckpointManager
from core.workflows.state import WorkflowStatus


class _Tuple:
    def __init__(self, thread_id, checkpoint_id, channel_values, ts, metadata=None):
        self.config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }
        self.checkpoint = {
            "id": checkpoint_id,
            "ts": ts,
            "channel_values": channel_values,
        }
        self.metadata = metadata or {}


class _FakeSaver:
    """Minimal AsyncPostgresSaver stand-in."""

    def __init__(self, tuples):
        self.tuples = tuples
        self.deleted_threads = []

    async def aget_tuple(self, config):
        cfg = config["configurable"]
        tid, cid = cfg.get("thread_id"), cfg.get("checkpoint_id")
        matches = [
            t for t in self.tuples
            if (tid is None or t.config["configurable"]["thread_id"] == tid)
            and (cid is None or t.config["configurable"]["checkpoint_id"] == cid)
        ]
        if not matches:
            return None
        return matches[-1]  # latest

    async def alist(self, config=None, *, filter=None, before=None, limit=None):
        tid = (config or {}).get("configurable", {}).get("thread_id")
        for t in self.tuples:
            if tid and t.config["configurable"]["thread_id"] != tid:
                continue
            yield t
            if limit and ...:  # pragma: no cover
                pass

    async def adelete_thread(self, thread_id):
        self.deleted_threads.append(thread_id)


def _manager(saver):
    m = CheckpointManager()
    m.checkpointer = saver
    return m


@pytest.fixture
def manager():
    now = datetime.now(timezone.utc)
    saver = _FakeSaver([
        _Tuple("thread-A", "ckpt-a1", {"task_id": 1, "workflow_status": "AWAITING_HITL", "hitl_reason": "need approval"}, (now - timedelta(hours=2)).isoformat()),
        _Tuple("thread-A", "ckpt-a2", {"task_id": 1, "workflow_status": "RUNNING"}, now.isoformat()),
        _Tuple("thread-B", "ckpt-b1", {"task_id": 2, "workflow_status": "AWAITING_HITL"}, (now - timedelta(hours=3)).isoformat()),
        _Tuple("thread-C", "ckpt-c1", {"task_id": 3, "workflow_status": "FAILED_EXECUTION", "error_message": "boom"}, (now - timedelta(hours=2)).isoformat()),
    ])
    return _manager(saver)


async def test_get_workflow_state_returns_latest(manager):
    state = await manager.get_workflow_state("thread-A")
    assert state["workflow_status"] == "RUNNING"  # latest wins


async def test_get_workflow_state_specific_checkpoint(manager):
    state = await manager.get_workflow_state("thread-A", "ckpt-a1")
    assert state["workflow_status"] == "AWAITING_HITL"


async def test_get_workflow_state_missing_thread(manager):
    assert await manager.get_workflow_state("thread-NOPE") is None


async def test_list_checkpoints_thread_scoped(manager):
    rows = await manager.list_checkpoints("thread-A")
    assert {r["checkpoint_id"] for r in rows} == {"ckpt-a1", "ckpt-a2"}


async def test_list_checkpoints_status_filter(manager):
    rows = await manager.list_checkpoints(status=WorkflowStatus.AWAITING_HITL)
    assert {r["thread_id"] for r in rows} == {"thread-A", "thread-B"}


async def test_hitl_pending_latest_per_thread(manager):
    hitl = await manager.get_hitl_pending_workflows()
    threads = {h["thread_id"] for h in hitl}
    assert threads == {"thread-A", "thread-B"}
    # thread-A's latest HITL row is ckpt-a1 (ckpt-a2 is RUNNING, not HITL)
    a = next(h for h in hitl if h["thread_id"] == "thread-A")
    assert a["checkpoint_id"] == "ckpt-a1"


async def test_failed_workflows_time_window(manager):
    failed = await manager.get_failed_workflows(hours=24)
    assert {f["thread_id"] for f in failed} == {"thread-C"}
    assert failed[0]["error_message"] == "boom"
    # Outside the window → excluded
    assert await manager.get_failed_workflows(hours=1) == []


async def test_delete_thread_checkpoints_uses_saver(manager):
    n = await manager.delete_thread_checkpoints("thread-A")
    assert "thread-A" in manager.checkpointer.deleted_threads


async def test_no_checkpointer_returns_empty(manager):
    m = CheckpointManager()
    m.checkpointer = None
    assert await m.get_workflow_state("x") is None
    assert await m.list_checkpoints() == []
    assert await m.get_hitl_pending_workflows() == []
    assert await m.get_checkpoint_count() == {"total": 0, "by_status": {}}


def test_no_legacy_schema_columns_in_source():
    """The old broken SQL patterns must not reappear (docstring mentions the
    old column names to document the fix, so check the query patterns)."""
    src = inspect.getsource(cp_utils)
    assert "WHERE checkpoint_namespace" not in src
    assert "ORDER BY created_at" not in src
    assert "checkpoint_id LIKE :thread_pattern" not in src
    assert "async with engine.begin()" not in src
    assert "from db import engine" not in src


def test_module_level_delete_thread_checkpoints_exists():
    """api/chat/session.py imports this — it must exist at module level."""
    assert hasattr(cp_utils, "delete_thread_checkpoints")
