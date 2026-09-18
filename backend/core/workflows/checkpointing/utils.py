# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Utility functions for managing LangGraph checkpoints and workflow recovery.

This module provides tools for:
- Inspecting checkpoint state
- Resuming interrupted workflows
- Recovering from crashes
- Managing HITL workflows

FIX (2026-08): the previous implementation queried the ``checkpoints``
table directly with columns that do not exist in LangGraph's schema
(``checkpoint_namespace``, ``created_at``) and used ``async with
engine.begin()`` on the SYNC engine — every method raised and silently
returned empty results. This rewrite goes through the ``AsyncPostgresSaver``
API (``aget_tuple`` / ``alist`` / ``adelete_thread``), which handles
serialization, and uses the real schema (``thread_id`` / ``checkpoint_ns`` /
``checkpoint_id``) for the two raw-SQL deletions.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db.database import async_engine
from .manager import get_checkpointer
from ..state import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

_HITL_STATUSES = ("AWAITING_HITL", "HITL_REVIEWING")
_FAILED_STATUSES = ("FAILED_EXECUTION", "FAILED_VALIDATION", "TERMINATED")
_DONE_STATUSES = ("PASSED", "TERMINATED")


def _channel_values(tup) -> Dict[str, Any]:
    """Extract channel_values from a CheckpointTuple."""
    return (tup.checkpoint or {}).get("channel_values", {}) or {}


def _checkpoint_ts(tup) -> Optional[str]:
    """ISO timestamp of the checkpoint (from the checkpoint blob)."""
    return (tup.checkpoint or {}).get("ts")


def _is_older_than(ts: Optional[str], delta: timedelta) -> bool:
    """True if the checkpoint timestamp is older than `delta` from now."""
    if not ts:
        return False
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < datetime.now(timezone.utc) - delta


class CheckpointManager:
    """Manager for workflow checkpoint operations (AsyncPostgresSaver-backed)."""

    def __init__(self):
        self.checkpointer = None

    async def initialize(self):
        """Initialize the checkpoint manager."""
        try:
            self.checkpointer = get_checkpointer()
            logger.info("CheckpointManager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize CheckpointManager: {e}")
            raise

    def _thread_config(self, thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        return config

    # ── reads ────────────────────────────────────────────────────────

    async def get_workflow_state(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[WorkflowState]:
        """
        Retrieve the workflow state from a checkpoint.

        Args:
            thread_id: The workflow thread ID (e.g. ``workflow_<id>_task_<id>``)
            checkpoint_id: Optional specific checkpoint ID, defaults to latest

        Returns:
            channel_values dict (WorkflowState) or None if not found
        """
        if self.checkpointer is None:
            logger.warning("Checkpointer not initialized — cannot read workflow state")
            return None
        try:
            tup = await self.checkpointer.aget_tuple(
                self._thread_config(thread_id, checkpoint_id)
            )
            if not tup:
                logger.debug(f"No checkpoint found for thread {thread_id}")
                return None
            state = _channel_values(tup)
            logger.info(f"Retrieved checkpoint for thread {thread_id} "
                        f"(checkpoint {checkpoint_id or 'latest'})")
            return state
        except Exception as e:
            logger.error(f"Failed to retrieve workflow state for {thread_id}: {e}")
            return None

    async def list_checkpoints(
        self,
        thread_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List checkpoints matching the given criteria.

        Args:
            thread_id: Optional filter by thread ID
            status: Optional filter by workflow status
            limit: Maximum number of results

        Returns:
            List of checkpoint summaries
        """
        if self.checkpointer is None:
            logger.warning("Checkpointer not initialized — cannot list checkpoints")
            return []
        try:
            config = (
                {"configurable": {"thread_id": thread_id}}
                if thread_id else {}
            )
            rows: List[Dict[str, Any]] = []
            async for tup in self.checkpointer.alist(config):
                cv = _channel_values(tup)
                if status and cv.get("workflow_status") != status.value:
                    continue
                cfg = tup.config.get("configurable", {})
                rows.append({
                    "checkpoint_id": cfg.get("checkpoint_id") or (tup.checkpoint or {}).get("id"),
                    "thread_id": cfg.get("thread_id"),
                    "task_id": cv.get("task_id"),
                    "workflow_status": cv.get("workflow_status"),
                    "current_step": cv.get("current_step"),
                    "retry_count": cv.get("retry_count"),
                    "created_at": _checkpoint_ts(tup),
                    "metadata": tup.metadata,
                })
                if len(rows) >= limit:
                    break
            logger.info(f"Found {len(rows)} checkpoints")
            return rows
        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}")
            return []

    async def get_hitl_pending_workflows(self) -> List[Dict[str, Any]]:
        """
        Find all workflows awaiting Human-in-the-Loop intervention.

        Returns:
            List of workflows in AWAITING_HITL or HITL_REVIEWING status
            (latest checkpoint per thread)
        """
        if self.checkpointer is None:
            logger.warning("Checkpointer not initialized — cannot list HITL workflows")
            return []
        try:
            latest_per_thread: Dict[str, Dict[str, Any]] = {}
            async for tup in self.checkpointer.alist({}):
                cv = _channel_values(tup)
                status = cv.get("workflow_status")
                if status not in _HITL_STATUSES:
                    continue
                cfg = tup.config.get("configurable", {})
                thread_id = cfg.get("thread_id", "")
                row = {
                    "checkpoint_id": cfg.get("checkpoint_id") or (tup.checkpoint or {}).get("id"),
                    "thread_id": thread_id,
                    "task_id": cv.get("task_id"),
                    "workflow_status": status,
                    "hitl_reason": cv.get("hitl_reason"),
                    "execution_plan": cv.get("execution_plan"),
                    "created_at": _checkpoint_ts(tup),
                }
                # Keep the newest checkpoint per thread.
                if thread_id not in latest_per_thread:
                    latest_per_thread[thread_id] = row
            hitl = list(latest_per_thread.values())
            logger.info(f"Found {len(hitl)} workflows awaiting HITL")
            return hitl
        except Exception as e:
            logger.error(f"Failed to retrieve HITL pending workflows: {e}")
            return []

    async def get_failed_workflows(
        self,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Find workflows that failed within the specified time window.

        Args:
            hours: Look back this many hours

        Returns:
            List of failed workflows (latest checkpoint per thread)
        """
        if self.checkpointer is None:
            logger.warning("Checkpointer not initialized — cannot list failed workflows")
            return []
        cutoff = timedelta(hours=hours)
        try:
            latest_per_thread: Dict[str, Dict[str, Any]] = {}
            async for tup in self.checkpointer.alist({}):
                cv = _channel_values(tup)
                status = cv.get("workflow_status")
                if status not in _FAILED_STATUSES:
                    continue
                # Failures *within* the window (ts >= now - hours), unlike
                # cleanup which targets checkpoints older than the cutoff.
                if _is_older_than(_checkpoint_ts(tup), cutoff):
                    continue
                cfg = tup.config.get("configurable", {})
                thread_id = cfg.get("thread_id", "")
                row = {
                    "checkpoint_id": cfg.get("checkpoint_id") or (tup.checkpoint or {}).get("id"),
                    "thread_id": thread_id,
                    "task_id": cv.get("task_id"),
                    "workflow_status": status,
                    "error_message": cv.get("error_message"),
                    "retry_count": cv.get("retry_count"),
                    "current_step": cv.get("current_step"),
                    "created_at": _checkpoint_ts(tup),
                }
                if thread_id not in latest_per_thread:
                    latest_per_thread[thread_id] = row
            failed = list(latest_per_thread.values())
            logger.info(f"Found {len(failed)} failed workflows in last {hours} hours")
            return failed
        except Exception as e:
            logger.error(f"Failed to retrieve failed workflows: {e}")
            return []

    # ── deletes ──────────────────────────────────────────────────────

    async def delete_checkpoint(
        self,
        checkpoint_id: str
    ) -> bool:
        """
        Delete a specific checkpoint (by its globally-unique checkpoint ID).

        Args:
            checkpoint_id: The checkpoint ID to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            async with async_engine.begin() as conn:
                result = await conn.execute(
                    text("""
                        DELETE FROM checkpoints
                        WHERE checkpoint_id = :checkpoint_id
                        RETURNING thread_id
                    """),
                    {"checkpoint_id": checkpoint_id},
                )
                deleted = result.fetchone()
                if deleted:
                    logger.info(f"Deleted checkpoint {checkpoint_id}")
                    return True
                logger.warning(f"Checkpoint {checkpoint_id} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}")
            return False

    async def delete_thread_checkpoints(
        self,
        thread_id: str
    ) -> int:
        """
        Delete all checkpoints for a specific thread.

        Args:
            thread_id: The thread ID whose checkpoints to delete

        Returns:
            Number of checkpoints deleted (approximation via RETURNING)
        """
        try:
            # Prefer the saver's own method (handles checkpoint_writes/blobs).
            if self.checkpointer is not None:
                await self.checkpointer.adelete_thread(thread_id)
                logger.info(f"Deleted checkpoints for thread {thread_id} (via saver)")
                return 1
            async with async_engine.begin() as conn:
                result = await conn.execute(
                    text("DELETE FROM checkpoints WHERE thread_id = :thread_id RETURNING checkpoint_id"),
                    {"thread_id": thread_id},
                )
                count = len(result.fetchall())
                logger.info(f"Deleted {count} checkpoints for thread {thread_id}")
                return count
        except Exception as e:
            logger.error(f"Failed to delete checkpoints for thread {thread_id}: {e}")
            return 0

    async def get_checkpoint_count(self) -> Dict[str, int]:
        """
        Get statistics about checkpoints in the database.

        Returns:
            Dictionary with checkpoint counts by status
        """
        if self.checkpointer is None:
            logger.warning("Checkpointer not initialized — cannot count checkpoints")
            return {"total": 0, "by_status": {}}
        try:
            total = 0
            by_status: Dict[str, int] = {}
            async for tup in self.checkpointer.alist({}):
                total += 1
                status = _channel_values(tup).get("workflow_status")
                if status:
                    by_status[status] = by_status.get(status, 0) + 1
            stats = {"total": total, "by_status": by_status}
            logger.debug(f"Checkpoint stats: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Failed to get checkpoint count: {e}")
            return {"total": 0, "by_status": {}}


# Global checkpoint manager instance
_checkpoint_manager: Optional[CheckpointManager] = None


async def get_checkpoint_manager() -> CheckpointManager:
    """Get or create the global checkpoint manager instance."""
    global _checkpoint_manager

    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
        await _checkpoint_manager.initialize()

    return _checkpoint_manager


# Convenience functions for common operations
async def get_workflow_checkpoint(task_id: int) -> Optional[WorkflowState]:
    """
    Get the latest checkpoint for a specific task.

    Args:
        task_id: The task ID

    Returns:
        WorkflowState or None if not found
    """
    manager = await get_checkpoint_manager()
    thread_id = f"task_{task_id}"
    return await manager.get_workflow_state(thread_id)


async def list_pending_hitl_workflows() -> List[Dict[str, Any]]:
    """Get all workflows awaiting HITL intervention."""
    manager = await get_checkpoint_manager()
    return await manager.get_hitl_pending_workflows()


async def delete_thread_checkpoints(thread_id: str) -> int:
    """Delete all checkpoints for a thread (module-level convenience).

    Also imported by api/chat/session.py for session cleanup.
    """
    manager = await get_checkpoint_manager()
    return await manager.delete_thread_checkpoints(thread_id)


async def cleanup_completed_workflows(days_old: int = 7) -> int:
    """
    Clean up checkpoints for completed workflows older than specified days.

    Args:
        days_old: Delete checkpoints for workflows completed more than this
                  many days ago

    Returns:
        Number of checkpoints deleted
    """
    manager = await get_checkpoint_manager()
    if manager.checkpointer is None:
        logger.warning("Checkpointer not initialized — cannot clean up workflows")
        return 0
    cutoff = timedelta(days=days_old)
    try:
        targets: List[str] = []
        async for tup in manager.checkpointer.alist({}):
            cv = _channel_values(tup)
            if cv.get("workflow_status") not in _DONE_STATUSES:
                continue
            if not _is_older_than(_checkpoint_ts(tup), cutoff):
                continue
            cfg = tup.config.get("configurable", {})
            cid = cfg.get("checkpoint_id") or (tup.checkpoint or {}).get("id")
            if cid:
                targets.append(cid)

        if not targets:
            return 0
        # Delete in batches to keep the SQL parameter list bounded.
        deleted = 0
        batch_size = 500
        for i in range(0, len(targets), batch_size):
            batch = targets[i:i + batch_size]
            async with async_engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "DELETE FROM checkpoints "
                        "WHERE checkpoint_id = ANY(:ids) RETURNING checkpoint_id"
                    ),
                    {"ids": batch},
                )
                deleted += len(result.fetchall())
        logger.info(
            f"Cleaned up {deleted} completed workflow checkpoints "
            f"older than {days_old} days"
        )
        return deleted
    except Exception as e:
        logger.error(f"Failed to cleanup completed workflows: {e}")
        return 0


async def get_checkpoint_statistics() -> Dict[str, Any]:
    """
    Get comprehensive statistics about workflow checkpoints.

    Returns:
        Dictionary with various checkpoint statistics
    """
    manager = await get_checkpoint_manager()

    # Get basic counts
    counts = await manager.get_checkpoint_count()

    # Get HITL workflows
    hitl_workflows = await manager.get_hitl_pending_workflows()

    # Get recent failures
    recent_failures = await manager.get_failed_workflows(hours=24)

    return {
        "total_checkpoints": counts["total"],
        "by_status": counts["by_status"],
        "hitl_pending": len(hitl_workflows),
        "recent_failures_24h": len(recent_failures),
        "hitl_workflows": hitl_workflows,
        "recent_failures": recent_failures
    }
