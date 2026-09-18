# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Internal helper methods mixin for the execution-event emitter.

Contains the event emission, sanitization, and database persistence
helpers extracted verbatim from the former monolithic emitter.py.
"""

import asyncio
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

from .shared import logger


class _EventHandlerMixin:
    def _get_subagent_context_for_run(
        self,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find if this run_id is inside an active subagent's execution scope.

        When a subagent is spawned via task() tool, all events with parent_run_id
        matching the task tool's run_id belong to that subagent.

        Returns:
            Dict with subagent_run_id and subagent_name if found, None otherwise
        """
        # First check if run_id itself is a subagent
        if run_id in self.active_subagents:
            subagent_info = self.active_subagents[run_id]
            return {
                "subagent_run_id": str(run_id),
                "subagent_name": subagent_info.get("subagent_name")
            }

        # Check if parent_run_id is a subagent (streaming happens inside tool execution)
        if parent_run_id and parent_run_id in self.active_subagents:
            subagent_info = self.active_subagents[parent_run_id]
            return {
                "subagent_run_id": str(parent_run_id),
                "subagent_name": subagent_info.get("subagent_name")
            }

        # Walk up the parent chain to find if any ancestor is an active subagent
        current_id = parent_run_id
        visited = set()  # Prevent infinite loops

        while current_id and current_id not in visited:
            visited.add(current_id)

            if current_id in self.active_subagents:
                subagent_info = self.active_subagents[current_id]
                return {
                    "subagent_run_id": str(current_id),
                    "subagent_name": subagent_info.get("subagent_name")
                }

            # Look up parent from current_node_info
            node_info = self.current_node_info.get(current_id)
            if node_info and "parent_run_id" in node_info:
                current_id = node_info.get("parent_run_id")
            else:
                break

        return None

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _emit_event(
        self,
        event_type: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Internal helper to emit events to in-memory event bus AND persist to database.

        Args:
            event_type: Type of event (TOOL_START, CHAIN_END, etc.)
            data: Event-specific data payload
        """
        try:
            # Import here to avoid circular dependencies
            from services.event_bus import get_event_bus

            # Get event bus
            event_bus = get_event_bus()

            # Map internal event types to SSE event types expected by frontend
            sse_event_type_map = {
                "CHAIN_START": "on_chain_start",
                "CHAIN_END": "on_chain_end",
                "CHAIN_ERROR": "error",
                "TOOL_START": "on_tool_start",
                "TOOL_END": "on_tool_end",
                "TOOL_ERROR": "error",
                "AGENT_ACTION": "on_agent_action",
                "AGENT_FINISH": "on_agent_finish",
                "LLM_END": "on_llm_end",
                "CHAT_MODEL_STREAM": "on_chat_model_stream",
                "SUBAGENT_START": "subagent_start",
                "SUBAGENT_END": "subagent_end",
                "SUBAGENT_ERROR": "subagent_error",
                # Debug mode events (emitted when workflow.debug_mode is enabled)
                "DEBUG_STATE_TRANSITION": "debug_state_transition",
                "DEBUG_CHECKPOINT": "debug_checkpoint",
                "DEBUG_GRAPH_STATE": "debug_graph_state",
                # Tool progress events (emitted by tools during long-running operations)
                "TOOL_PROGRESS": "tool_progress",
                # Custom streaming events (LangGraph-style arbitrary events from tools)
                "CUSTOM_EVENT": "custom_event",
            }

            # Get SSE-compatible event type
            sse_event_type = sse_event_type_map.get(event_type, event_type.lower())

            # Build full event payload in SSE format
            event_payload = {
                "type": sse_event_type,
                "data": {
                    **data,
                    "project_id": self.project_id,
                    "task_id": self.task_id,
                    "user_id": self.user_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }

            # Publish to workflow-specific channel (matches SSE endpoint subscription)
            if self.workflow_id:
                channel = f"workflow:{self.workflow_id}"
            else:
                # Fallback to project channel if workflow_id not set
                channel = f"project:{self.project_id}:execution"
                logger.warning(
                    f"No workflow_id set, using fallback channel: {channel}"
                )

            await event_bus.publish(channel, event_payload)

            logger.debug(
                f"Emitted {sse_event_type} event to {channel}: "
                f"project={self.project_id}, task={self.task_id}"
            )

            # Persist event to database for historical replay (non-blocking)
            # Use create_task to avoid blocking the event loop
            import asyncio
            persist_task = asyncio.create_task(self._persist_event_to_database(
                event_type=sse_event_type,
                event_data=event_payload["data"],
                run_id=data.get("run_id"),
                parent_run_id=data.get("parent_run_id")
            ))

            # Track pending persist tasks for cleanup callback
            self._pending_persist_tasks.append(persist_task)

            def cleanup_task(t, event_type=sse_event_type):
                self._handle_persist_error(t, event_type)
                # Remove from pending list when done
                try:
                    self._pending_persist_tasks.remove(t)
                except ValueError:
                    pass

            persist_task.add_done_callback(cleanup_task)

        except Exception as e:
            # Don't let event emission failures break workflow execution
            logger.warning(
                f"Failed to emit {event_type} event: {e}",
                exc_info=False
            )

    # =========================================================================
    # Data Sanitization Helpers
    # =========================================================================

    def _sanitize_arguments(self, data: Any) -> Any:
        """
        Sanitize sensitive data from arguments before emission.

        Redacts common sensitive patterns:
        - API keys (patterns like "sk-", "api_key", etc.)
        - Passwords
        - Tokens
        - Credentials

        Args:
            data: Data to sanitize (dict, list, str, or primitive)

        Returns:
            Sanitized data with sensitive values redacted
        """
        if isinstance(data, dict):
            return {
                key: self._sanitize_value(key, value)
                for key, value in data.items()
            }
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_arguments(item) for item in data]
        elif isinstance(data, str):
            return self._sanitize_string(data)
        else:
            return data

    def _sanitize_value(self, key: str, value: Any) -> Any:
        """Sanitize a single key-value pair."""
        # Check if key contains sensitive terms
        sensitive_keys = [
            "api_key", "apikey", "password", "passwd", "secret", "token",
            "credential", "auth", "bearer", "private_key", "access_key"
        ]

        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            return "[REDACTED]"

        # Recursively sanitize nested structures
        return self._sanitize_arguments(value)

    def _sanitize_string(self, text: str) -> str:
        """Sanitize sensitive patterns in strings."""
        # Redact common API key patterns
        patterns = [
            (r"sk-[a-zA-Z0-9]{32,}", "[API_KEY_REDACTED]"),  # OpenAI style
            (r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]"),  # Bearer tokens
            (r"api[_-]?key[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9_\-]+", "api_key=[REDACTED]"),  # Generic API keys
        ]

        sanitized = text
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        return sanitized

    async def _persist_event_to_database(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        run_id: Optional[str] = None,
        parent_run_id: Optional[str] = None
    ) -> None:
        """
        Persist event to database for historical replay and debugging.

        Events are stored in the execution_events table and linked to the task.
        This enables:
        - Historical workflow replay after completion
        - Debugging and troubleshooting past executions
        - Persistent event logs accessible via API

        Args:
            event_type: Type of event (on_chain_start, on_tool_end, etc.)
            event_data: Full event data payload
            run_id: LangChain run ID for tracking
            parent_run_id: Parent run ID for nested executions
        """
        # Skip if database persistence is disabled
        if not self.save_to_db:
            logger.debug(f"Skipping DB persist for {event_type}: save_to_db={self.save_to_db}")
            return

        try:
            logger.debug(f"Starting DB persist for {event_type} (task={self.task_id})")
            # Import models and database session here to avoid circular deps
            from models.execution_event import ExecutionEvent
            from db.database import get_async_session

            # Create database event record
            event_record = ExecutionEvent(
                task_id=self.task_id,
                workflow_id=self.workflow_id,
                event_type=event_type,
                event_data=event_data,
                run_id=run_id,
                parent_run_id=parent_run_id
            )


            # Save to database using async session
            # CRITICAL: Ensure we're using the CURRENT event loop, not one from a thread
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop - this shouldn't happen in async context but handle it
                logger.warning(f"No running event loop for {event_type} - cannot persist to DB")
                return

            async with get_async_session() as session:
                session.add(event_record)
                await session.commit()
                await session.refresh(event_record)

            # Use debug level for streaming events to reduce log noise
            if event_type == "on_chat_model_stream":
                logger.debug(
                    f"✅ Persisted {event_type} event to database "
                    f"(id={event_record.id}, task={self.task_id})"
                )
            else:
                logger.info(
                    f"✅ Persisted {event_type} event to database "
                    f"(id={event_record.id}, task={self.task_id})"
                )


        except RuntimeError as e:
            # Catch async event loop conflicts (common with tool execution creating new loops)
            error_msg = str(e)
            if "event loop" in error_msg.lower() or "different loop" in error_msg.lower():
                logger.warning(
                    f"⚠️ Event loop conflict during {event_type} persistence - skipping DB save. "
                    f"This is a known issue with certain tools. Execution continues normally."
                )
            else:
                # Re-raise if it's a different RuntimeError
                logger.error(f"❌ RuntimeError persisting {event_type}: {e}", exc_info=True)
        except Exception as e:
            # Log error but don't break execution
            logger.warning(
                f"Failed to persist event {event_type} to database: {e}"
            )

    def _handle_persist_error(self, task: 'asyncio.Task', event_type: str) -> None:
        """Handle exceptions from async persist tasks."""
        try:
            task.result()  # This will raise if the task had an exception
        except Exception as e:
            logger.error(
                f"❌ Async persist task failed for {event_type}: {e}",
                exc_info=True
            )

    async def flush_pending_persists(self, timeout: float = 5.0) -> None:
        """
        Wait for all pending database persist tasks to complete.

        Call this at the end of workflow execution to ensure all events
        are persisted to the database before the workflow handler exits.

        Args:
            timeout: Maximum time to wait for pending tasks (seconds)
        """
        if not self._pending_persist_tasks:
            return

        pending_count = len(self._pending_persist_tasks)
        logger.info(f"🔄 Flushing {pending_count} pending database persist tasks...")

        try:
            # Wait for all pending tasks with timeout
            done, pending = await asyncio.wait(
                self._pending_persist_tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED
            )

            if pending:
                logger.warning(
                    f"⚠️ {len(pending)} persist tasks timed out after {timeout}s - "
                    "some events may not be saved to database"
                )
                # Cancel timed out tasks
                for task in pending:
                    task.cancel()
            else:
                logger.info(f"✅ All {len(done)} persist tasks completed successfully")

        except Exception as e:
            logger.error(f"❌ Error flushing persist tasks: {e}")
        finally:
            self._pending_persist_tasks.clear()

    def get_collected_artifacts(self) -> List[Dict[str, Any]]:
        """
        Get all artifacts (images, files, etc.) collected during execution.

        Returns a list of artifact dictionaries with metadata about the source
        tool and agent. Use this to include generated content in final output.

        Returns:
            List of artifact dicts with type, data, mimeType, tool_name, agent_label
        """
        return self.collected_artifacts.copy()
