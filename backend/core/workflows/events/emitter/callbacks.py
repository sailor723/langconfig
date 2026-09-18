# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
LangChain callback hooks mixin for the execution-event emitter.

Contains the on_* callback methods extracted verbatim from the former
monolithic emitter.py so the handler class can span multiple modules.
"""

from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from uuid import UUID

# LangChain callback imports
from langchain_core.outputs import LLMResult
from langchain_core.agents import AgentAction, AgentFinish

# Import artifact store from tool factory
from core.tools.factory import get_pending_artifacts

from .shared import logger


class _EventCallbacksMixin:
    # =========================================================================
    # Chain/Node Lifecycle Hooks
    # =========================================================================

    async def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a chain/node starts execution.

        Maps to NODE_START events for workflow visualization.
        """
        # Handle case where serialized might be None
        if not serialized:
            serialized = {}

        # Try to extract node_id from metadata or tags to look up in node_metadata
        node_id = None
        if metadata:
            node_id = metadata.get("node_id")

        # Try tags if no metadata
        if not node_id and tags:
            for tag in tags:
                if isinstance(tag, str) and (tag.startswith("node-") or tag in self.node_metadata):
                    node_id = tag
                    break

        # Look up node info from metadata map (passed from simple_executor)
        node_info = self.node_metadata.get(node_id, {}) if node_id else {}

        # Extract agent info from node_metadata
        agent_label = node_info.get("label")
        agent_type = node_info.get("agent_type")

        # ENHANCED DEBUG: Log full lookup chain
        logger.info(
            f"[CHAIN START DEBUG] run_id={str(run_id)[:8]}, parent_run_id={str(parent_run_id)[:8] if parent_run_id else None}, "
            f"node_id={node_id}, agent_label={agent_label}, "
            f"metadata={metadata}, tags={tags}, "
            f"available_nodes={list(self.node_metadata.keys())}"
        )

        # Build node name with priority: metadata label > metadata agent_type > serialized name > fallback
        node_name = None

        # 1. Try node metadata first (most reliable)
        if agent_label:
            node_name = agent_label
        elif agent_type:
            node_name = agent_type

        # 2. Try serialized name
        elif serialized.get("name"):
            node_name = serialized.get("name")

        # 3. Try kwargs name
        elif kwargs.get("name"):
            node_name = kwargs.get("name")

        # 4. Try to extract from serialized id/repr
        elif serialized.get("id"):
            node_id_from_ser = serialized.get("id")
            if isinstance(node_id_from_ser, list) and len(node_id_from_ser) > 0:
                node_name = str(node_id_from_ser[-1])
            else:
                node_name = str(node_id_from_ser)

        # 5. Try tags (but filter out langsmith tags)
        if not node_name or node_name == "unknown":
            if tags:
                for tag in tags:
                    if isinstance(tag, str) and not tag.startswith("langsmith:") and not tag.startswith("seq:") and not tag.startswith("node-"):
                        node_name = tag
                        break

        # 6. Final fallback
        if not node_name or node_name == "unknown":
            if serialized.get("graph", {}).get("__class__"):
                node_name = serialized["graph"]["__class__"].get("__name__", "Workflow Step")
            else:
                node_name = "Workflow Step"

        # Node type from metadata or serialized
        node_type = agent_type or serialized.get("graph", {}).get("__class__", {}).get("__name__", "agent")

        # Extract input data for more context
        input_preview = None
        if kwargs.get("inputs"):
            inputs = kwargs["inputs"]
            if isinstance(inputs, dict):
                # Try to get meaningful preview
                if "messages" in inputs and inputs["messages"]:
                    last_msg = inputs["messages"][-1] if isinstance(inputs["messages"], list) else inputs["messages"]
                    if hasattr(last_msg, 'content'):
                        input_preview = last_msg.content[:100] + "..." if len(last_msg.content) > 100 else last_msg.content
                elif "query" in inputs:
                    input_preview = str(inputs["query"])[:100]
                elif "input" in inputs:
                    input_preview = str(inputs["input"])[:100]

        logger.debug(f"[CHAIN START] {node_name} (type={node_type}, input_preview={input_preview})")

        # Store current node info for agent_action events (including node_id for tool grouping)
        self.current_node_info[run_id] = {
            "agent_label": agent_label,
            "node_name": node_name,
            "agent_type": agent_type,
            "node_id": node_id  # Needed to group tools with parent agent in frontend
        }

        # SIMPLIFIED EVENT EMISSION:
        # Only emit agent_label (user-friendly name that matches canvas nodes)
        # Removed node_name, node_type, agent_type to prevent duplication/confusion
        # Frontend uses agent_label for matching (see useNodeExecutionStatus.ts:108)
        await self._emit_event(
            event_type="CHAIN_START",
            data={
                "agent_label": agent_label or node_name,  # Primary field for node matching
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "tags": tags or [],
                "metadata": metadata or {},
                "input_preview": input_preview
            }
        )

    async def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a chain/node completes execution.

        Maps to NODE_COMPLETE events for workflow visualization.
        """
        logger.debug(f"[CHAIN END] run_id={run_id}")

        # Sanitize outputs if enabled
        sanitized_outputs = self._sanitize_arguments(outputs) if self.enable_sanitization else outputs

        await self._emit_event(
            event_type="CHAIN_END",
            data={
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "output_keys": list(sanitized_outputs.keys()) if isinstance(sanitized_outputs, dict) else [],
                "success": True
            }
        )

        # Clean up node tracking to prevent memory leaks
        if run_id in self.current_node_info:
            del self.current_node_info[run_id]

    async def on_chain_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a chain/node encounters an error.

        Maps to NODE_COMPLETE events with error details.
        """
        self.error_count += 1
        error_message = str(error)
        error_type = type(error).__name__

        logger.error(f"[CHAIN ERROR] {error_type}: {error_message} (run_id={run_id})")

        await self._emit_event(
            event_type="CHAIN_ERROR",
            data={
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "error_type": error_type,
                "error": error_message,  # Changed from 'error_message' to 'error' for frontend compatibility
                "success": False
            }
        )

        # Clean up node tracking to prevent memory leaks
        if run_id in self.current_node_info:
            del self.current_node_info[run_id]

    # =========================================================================
    # Tool Invocation Hooks
    # =========================================================================

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a tool starts execution.

        Tracks tool usage for observability and debugging.
        """
        self.tool_call_count += 1
        tool_name = serialized.get("name", "unknown_tool")

        logger.debug(f"[TOOL START] {tool_name} (run_id={run_id})")

        # Look up agent_label and node_id from parent_run_id so frontend can map tool to correct node
        node_info = self.current_node_info.get(parent_run_id, {})
        agent_label = node_info.get("agent_label")
        node_id = node_info.get("node_id")  # Frontend needs this to group tool with agent

        # FALLBACK: If no agent_label found, try to find ANY tracked node (for single-agent workflows)
        # This handles cases where parent_run_id chain hierarchy doesn't match what we stored
        if not agent_label and self.current_node_info:
            # Use the most recently added node info as fallback
            fallback_info = list(self.current_node_info.values())[-1] if self.current_node_info else {}
            if fallback_info:
                agent_label = fallback_info.get("agent_label")
                node_id = fallback_info.get("node_id")
                logger.debug(f"[TOOL START] Using fallback agent_label: {agent_label}")

        # DEBUG: Log lookup to diagnose why agent_label is missing
        logger.debug(
            f"[TOOL START] Agent label lookup: tool={tool_name}, "
            f"parent_run_id={parent_run_id}, found_node_info={bool(node_info)}, "
            f"agent_label={agent_label}, node_id={node_id}, tracked_nodes={list(self.current_node_info.keys())}"
        )

        # Store tool info for on_tool_end to use
        self.current_tool_info[run_id] = {
            "tool_name": tool_name,
            "agent_label": agent_label,
            "node_id": node_id  # Pass through to on_tool_end
        }

        # SUBAGENT DETECTION: Check for known subagent invocation tool patterns
        # DeepAgents uses 'task' tool, but other patterns might include:
        # - delegate, handoff, invoke_agent, call_agent, run_agent
        subagent_tool_patterns = ['task', 'delegate', 'handoff', 'invoke_agent', 'call_agent', 'run_agent']
        is_subagent_tool = tool_name.lower() in subagent_tool_patterns or 'subagent' in tool_name.lower()

        # DEBUG: Log all tool calls to help identify subagent patterns
        logger.info(f"[TOOL DEBUG] tool_name={tool_name}, inputs_keys={list(inputs.keys()) if inputs else 'None'}, is_subagent={is_subagent_tool}")

        if is_subagent_tool:
            subagent_name = None
            task_description = None

            if inputs:
                # First try explicit name fields
                subagent_name = (
                    inputs.get('name') or
                    inputs.get('agent') or
                    inputs.get('subagent') or
                    inputs.get('agent_name')
                )

                # Get task description for generating a better name
                task_description = inputs.get('description') or inputs.get('task') or inputs.get('prompt')

                # If no explicit name, try to generate one from description
                if not subagent_name and task_description:
                    # Extract a meaningful task name from the first 50 chars of description
                    desc_preview = task_description[:50].strip()
                    # Find first sentence or meaningful phrase
                    for delim in ['.', ':', '\n', ' - ']:
                        if delim in desc_preview:
                            desc_preview = desc_preview.split(delim)[0].strip()
                            break

                    # Get subagent type for context
                    subagent_type = inputs.get('subagent_type', 'task')

                    # Create descriptive name: "Research: AMD report" instead of "general-purpose"
                    if desc_preview:
                        # Capitalize and shorten the description preview
                        short_desc = desc_preview[:30] + ('...' if len(desc_preview) > 30 else '')
                        subagent_name = f"{subagent_type.title()}: {short_desc}"
                    else:
                        subagent_name = subagent_type.replace('-', ' ').title()

                # Final fallback to subagent_type
                if not subagent_name:
                    subagent_name = inputs.get('subagent_type', 'Subagent').replace('-', ' ').title()

            if not subagent_name and input_str:
                # Try to extract from input string if structured
                import json
                try:
                    parsed = json.loads(input_str)
                    subagent_name = (
                        parsed.get('name') or
                        parsed.get('agent') or
                        parsed.get('agent_name') or
                        parsed.get('subagent_type', 'Subagent').replace('-', ' ').title()
                    )
                except:
                    pass

            # Fallback: use tool name if no subagent name found
            if not subagent_name:
                subagent_name = tool_name.replace('_', ' ').title()

            # Track this as an active subagent run
            self.active_subagents[run_id] = {
                "subagent_name": subagent_name,
                "parent_agent_label": agent_label,
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "task_description": task_description  # Store for reference
            }

            # Emit dedicated SUBAGENT_START event for frontend nested panels
            # Use task_description for human-readable input, not raw dict string
            await self._emit_event(
                event_type="SUBAGENT_START",
                data={
                    "subagent_name": subagent_name,
                    "subagent_run_id": str(run_id),
                    "parent_agent_label": agent_label,
                    "parent_run_id": str(parent_run_id) if parent_run_id else None,
                    "input_preview": task_description if task_description else (input_str[:500] if input_str else "")
                }
            )
            logger.info(f"[SUBAGENT START] {subagent_name} invoked by {agent_label}")
            # IMPORTANT: Return early - don't emit TOOL_START for subagent tools
            # This prevents duplicate events (SUBAGENT_START + TOOL_START)
            return

        # Sanitize tool inputs
        sanitized_inputs = self._sanitize_arguments(inputs or {}) if self.enable_sanitization else inputs

        # Get subagent context for tools used within subagent execution
        subagent_context = self._get_subagent_context_for_run(run_id, parent_run_id)

        await self._emit_event(
            event_type="TOOL_START",
            data={
                "tool_name": tool_name,
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "input_preview": input_str[:200] if input_str else "",  # Truncate for brevity
                "inputs": sanitized_inputs,
                "tags": tags or [],
                "tool_call_number": self.tool_call_count,
                "agent_label": agent_label,  # User-friendly name
                "node_id": node_id,  # Frontend uses this to group tool with agent in same bubble
                # SUBAGENT FIELDS: Enable frontend to route to SubagentPanel
                "subagent_run_id": subagent_context.get("subagent_run_id") if subagent_context else None,
                "subagent_name": subagent_context.get("subagent_name") if subagent_context else None,
            }
        )

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a tool completes execution.

        Captures tool results for agent observation tracking.
        Supports multimodal content (images, audio, files) from MCP tools.
        """
        logger.debug(f"[TOOL END] run_id={run_id}")

        # Look up tool info from on_tool_start (includes tool_name, agent_label, and node_id)
        tool_info = self.current_tool_info.get(run_id, {})
        tool_name = tool_info.get("tool_name", "unknown")
        agent_label = tool_info.get("agent_label")
        node_id = tool_info.get("node_id")  # For grouping with parent agent

        # Extract multimodal content if present (from MCP tools)
        content_blocks = []
        artifacts = []
        has_multimodal = False

        # Check for artifacts stored via context variable (from native tools like image_generation)
        pending_artifacts = get_pending_artifacts()
        if pending_artifacts:
            artifacts.extend(pending_artifacts)
            has_multimodal = True
            logger.info(f"[TOOL END] {tool_name} has {len(pending_artifacts)} pending artifacts from context")

        # Check if output is a dict with multimodal content (MCPToolResult format)
        if isinstance(output, dict):
            content_blocks = output.get("content_blocks", [])
            artifacts.extend(output.get("artifacts", []))
            has_multimodal = has_multimodal or output.get("has_multimodal", False)

            if has_multimodal:
                logger.info(f"[TOOL END] {tool_name} returned multimodal content: "
                           f"{len(content_blocks)} blocks, {len(artifacts)} artifacts")

        # Collect artifacts for final output (images, files, etc.)
        # This enables the final results view to display generated content
        if artifacts:
            for artifact in artifacts:
                artifact_with_meta = {
                    **artifact,
                    "tool_name": tool_name,
                    "agent_label": agent_label,
                }
                self.collected_artifacts.append(artifact_with_meta)
            logger.info(f"[ARTIFACT COLLECTOR] Added {len(artifacts)} artifacts from {tool_name}. "
                       f"Total collected: {len(self.collected_artifacts)}")

        # Also collect image content blocks (not just artifacts)
        for block in content_blocks:
            if block.get("type") in ["image", "audio", "file"]:
                block_with_meta = {
                    **block,
                    "tool_name": tool_name,
                    "agent_label": agent_label,
                }
                self.collected_artifacts.append(block_with_meta)
                logger.info(f"[ARTIFACT COLLECTOR] Added {block.get('type')} content block from {tool_name}")

        # Handle case where output might not be a string
        try:
            if isinstance(output, str):
                full_output = output
                # Increase preview limit for better visibility
                output_preview = output[:2000] if output else ""
            elif isinstance(output, dict):
                # For dict outputs, try to get text content from content_blocks
                text_parts = []
                for block in content_blocks:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                if text_parts:
                    full_output = "\n".join(text_parts)
                else:
                    full_output = str(output) if output else ""
                output_preview = full_output[:2000]
            else:
                # Convert to string if it's not already
                full_output = str(output) if output else ""
                output_preview = full_output[:2000]
        except Exception as e:
            logger.warning(f"Error processing tool output: {e}")
            output_preview = "[Output could not be processed]"
            full_output = output_preview

        # For write_file tool, include the full output (it contains the written content)
        # Supports both new standard naming (write_file) and legacy aliases (file_write)
        include_full_output = tool_name in ['write_file', 'file_write', 'task', 'delegate']

        # SUBAGENT COMPLETION: If this was a subagent (task tool), emit ONLY SUBAGENT_END
        # This mirrors the early return in on_tool_start - we don't emit both TOOL_END and SUBAGENT_END
        if run_id in self.active_subagents:
            subagent_info = self.active_subagents[run_id]
            await self._emit_event(
                event_type="SUBAGENT_END",
                data={
                    "subagent_name": subagent_info["subagent_name"],
                    "subagent_run_id": str(run_id),
                    "parent_agent_label": subagent_info["parent_agent_label"],
                    "parent_run_id": subagent_info["parent_run_id"],
                    "output_preview": output_preview,
                    "full_output": full_output,  # Full output for complete display
                    "success": True,
                    # Include multimodal content for subagent results
                    "content_blocks": content_blocks,
                    "artifacts": artifacts,
                    "has_multimodal": has_multimodal,
                }
            )
            logger.info(f"[SUBAGENT END] {subagent_info['subagent_name']} completed")
            del self.active_subagents[run_id]
            # Clean up tool tracking and return early - don't emit TOOL_END
            if run_id in self.current_tool_info:
                del self.current_tool_info[run_id]
            return

        # Get subagent context for tools used within subagent execution
        subagent_context = self._get_subagent_context_for_run(run_id, parent_run_id)

        await self._emit_event(
            event_type="TOOL_END",
            data={
                "tool_name": tool_name,  # Include tool name so frontend knows which tool completed
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "output_preview": output_preview,
                "full_output": full_output if include_full_output else None,
                "success": True,
                "agent_label": agent_label,  # User-friendly name
                "node_id": node_id,  # Maps tool to correct node for grouping
                # SUBAGENT FIELDS: Enable frontend to route to SubagentPanel
                "subagent_run_id": subagent_context.get("subagent_run_id") if subagent_context else None,
                "subagent_name": subagent_context.get("subagent_name") if subagent_context else None,
                # MULTIMODAL FIELDS: For displaying images, audio, files from MCP tools
                "content_blocks": content_blocks,
                "artifacts": artifacts,
                "has_multimodal": has_multimodal,
            }
        )

        # Clean up tool tracking to prevent memory leaks
        if run_id in self.current_tool_info:
            del self.current_tool_info[run_id]

    async def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a tool encounters an error.

        Critical for debugging tool integration issues.
        """
        self.error_count += 1
        error_message = str(error)
        error_type = type(error).__name__

        # Enhanced error messaging for common tool validation errors
        # This helps the LLM understand what went wrong and how to fix it
        # Support both new (write_file) and legacy (file_write) tool names
        if error_type == "ValidationError" and ("write_file" in error_message or "file_write" in error_message or "WriteFileArgs" in error_message):
            if "content" in error_message and "Field required" in error_message:
                # Check if this might be an incomplete tool call (common with max_tokens truncation)
                # The input only has file_path suggests the response was truncated
                if "input_value={" in error_message and "'file_path':" in error_message:
                    error_message = (
                        "⚠️ TOKEN LIMIT REACHED - YOUR RESPONSE WAS CUT OFF!\n\n"
                        "You tried to write a very long file but ran out of output tokens. "
                        "The content parameter was truncated before it could be sent.\n\n"
                        "TO FIX THIS, you must split your content into smaller pieces:\n"
                        "1. First, write Part 1 of the file with write_file()\n"
                        "2. Then use edit_file() or write_file() to append Part 2, 3, etc.\n"
                        "3. Each part should be 2000-3000 characters MAX\n\n"
                        "Example approach:\n"
                        "  write_file(file_path='doc.md', content='# Part 1\\n...(first 2000 chars)...')\n"
                        "  edit_file(file_path='doc.md', old_string='END_OF_PART1', new_string='REST OF CONTENT...')\n\n"
                        "OR break into multiple files:\n"
                        "  write_file(file_path='doc_part1.md', content='...')\n"
                        "  write_file(file_path='doc_part2.md', content='...')"
                    )
                else:
                    error_message = (
                        "CRITICAL ERROR - STOP AND READ THIS:\n\n"
                        "You called write_file() with ONLY file_path but FORGOT the content parameter.\n\n"
                        "WRONG:   write_file(file_path='report.md')\n"
                        "CORRECT: write_file(file_path='report.md', content='Your full content here')\n\n"
                        "BEFORE retrying:\n"
                        "1. STOP - Do NOT immediately retry write_file\n"
                        "2. First, compose your complete file content\n"
                        "3. THEN call write_file with BOTH file_path AND content parameters"
                    )

        logger.error(f"[TOOL ERROR] {error_type}: {error_message} (run_id={run_id})")

        # Check if this was a subagent tool - emit SUBAGENT_ERROR instead of TOOL_ERROR
        if run_id in self.active_subagents:
            subagent_info = self.active_subagents[run_id]
            await self._emit_event(
                event_type="SUBAGENT_ERROR",
                data={
                    "subagent_name": subagent_info["subagent_name"],
                    "subagent_run_id": str(run_id),
                    "parent_agent_label": subagent_info["parent_agent_label"],
                    "parent_run_id": subagent_info["parent_run_id"],
                    "error_type": error_type,
                    "error": error_message,
                    "success": False
                }
            )
            logger.error(f"[SUBAGENT ERROR] {subagent_info['subagent_name']} failed: {error_message}")
            del self.active_subagents[run_id]
            # Clean up tool tracking
            if run_id in self.current_tool_info:
                del self.current_tool_info[run_id]
            return

        await self._emit_event(
            event_type="TOOL_ERROR",
            data={
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "error_type": error_type,
                "error": error_message,  # Changed from 'error_message' to 'error' for frontend compatibility
                "success": False
            }
        )

        # Clean up tool tracking
        if run_id in self.current_tool_info:
            del self.current_tool_info[run_id]

    # =========================================================================
    # Agent Reasoning Hooks
    # =========================================================================

    async def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when an agent decides to take an action.

        Captures the agent's reasoning process and tool selection.
        This is critical for understanding agent decision-making.
        """
        tool_name = action.tool
        tool_input = action.tool_input
        reasoning = action.log  # Agent's thought process

        logger.debug(f"[AGENT ACTION] Tool={tool_name} (run_id={run_id})")

        # Get current node info from parent_run_id (agent actions are child of chain)
        node_info = self.current_node_info.get(parent_run_id, {})
        agent_label = node_info.get("agent_label")
        node_name = node_info.get("node_name")
        agent_type = node_info.get("agent_type")

        # Sanitize tool inputs
        sanitized_input = self._sanitize_arguments(tool_input) if self.enable_sanitization else tool_input

        await self._emit_event(
            event_type="AGENT_ACTION",
            data={
                "tool_name": tool_name,
                "tool_input": sanitized_input,
                "reasoning": reasoning if reasoning else "",  # Full reasoning for frontend display
                "reasoning_preview": reasoning[:200] if reasoning else "",  # Short preview for lists
                "thought_process": "analyzing",  # Status indicator for UI
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                # Add node identification for frontend matching
                "agent_label": agent_label,
                "node_name": node_name,
                "agent_type": agent_type
            }
        )

    async def on_agent_finish(
        self,
        finish: AgentFinish,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when an agent completes its execution.

        Captures the final output and reasoning.
        """
        output = finish.return_values
        reasoning = finish.log

        logger.debug(f"[AGENT FINISH] run_id={run_id}")

        # Sanitize output
        sanitized_output = self._sanitize_arguments(output) if self.enable_sanitization else output

        await self._emit_event(
            event_type="AGENT_FINISH",
            data={
                "output": sanitized_output,
                "reasoning": reasoning[:500] if reasoning else "",
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "metrics": {
                    "tool_calls": self.tool_call_count,
                    "llm_calls": self.llm_call_count,
                    "total_tokens": self.total_tokens,
                    "errors": self.error_count
                }
            }
        )

    # =========================================================================
    # LLM Hooks (for token tracking)
    # =========================================================================

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when an LLM completes generation.

        Tracks token usage for cost monitoring.
        """
        self.llm_call_count += 1

        # Extract token usage if available
        if response.llm_output and "token_usage" in response.llm_output:
            token_usage = response.llm_output["token_usage"]
            tokens_used = token_usage.get("total_tokens", 0)
            self.total_tokens += tokens_used

            # Lookup agent context from parent_run_id (critical for per-agent cost tracking)
            node_info = self.current_node_info.get(parent_run_id, {})
            agent_label = node_info.get("agent_label", "Unknown")

            # Extract model name from response (try multiple possible locations)
            model_name = "unknown"
            if response.llm_output:
                # Try model_name first (common in OpenAI/Anthropic responses)
                model_name = response.llm_output.get("model_name",
                            response.llm_output.get("model", "unknown"))

            # Fallback: try to extract from generations metadata
            if model_name == "unknown" and response.generations:
                for gen_list in response.generations:
                    if gen_list and hasattr(gen_list[0], 'generation_info'):
                        gen_info = gen_list[0].generation_info or {}
                        model_name = gen_info.get("model", model_name)
                        if model_name != "unknown":
                            break

            logger.debug(f"[LLM END] Agent={agent_label}, Model={model_name}, Tokens={tokens_used} (run_id={run_id})")

            await self._emit_event(
                event_type="LLM_END",
                data={
                    "run_id": str(run_id),
                    "agent_label": agent_label,  # NEW: For per-agent cost aggregation
                    "model": model_name,          # NEW: For accurate cost calculation
                    "tokens_used": tokens_used,
                    "prompt_tokens": token_usage.get("prompt_tokens", 0),
                    "completion_tokens": token_usage.get("completion_tokens", 0),
                    "cumulative_tokens": self.total_tokens
                }
            )

    async def on_chat_model_stream(
        self,
        chunk: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any
    ) -> None:
        """
        Called when a chat model streams a token/chunk.

        Enables real-time streaming of LLM output to frontend for
        "thinking" visualization.
        """
        # Extract content from chunk
        chunk_content = None
        if hasattr(chunk, 'content') and chunk.content:
            chunk_content = chunk.content
        elif isinstance(chunk, dict) and 'content' in chunk:
            chunk_content = chunk['content']
        elif isinstance(chunk, str):
            chunk_content = chunk

        if chunk_content:
            # Look up agent_label from current_node_info using parent_run_id
            # This allows frontend to map streaming tokens to the correct node
            node_info = self.current_node_info.get(parent_run_id, {})
            agent_label = node_info.get("agent_label")

            # SUBAGENT CONTEXT: Check if this streaming token belongs to an active subagent
            # This enables the frontend to route tokens to the correct SubagentPanel
            subagent_context = self._get_subagent_context_for_run(run_id, parent_run_id)
            subagent_run_id = subagent_context.get("subagent_run_id") if subagent_context else None
            subagent_name = subagent_context.get("subagent_name") if subagent_context else None

            # ENHANCED DEBUG: Log streaming event lookup
            logger.info(
                f"[STREAM DEBUG] run_id={str(run_id)[:8]}, parent_run_id={str(parent_run_id)[:8] if parent_run_id else None}, "
                f"agent_label={agent_label}, subagent_run_id={subagent_run_id}, "
                f"tracked_parents={list(self.current_node_info.keys())}"
            )

            await self._emit_event(
                event_type="CHAT_MODEL_STREAM",
                data={
                    "run_id": str(run_id),
                    "parent_run_id": str(parent_run_id) if parent_run_id else None,
                    "content": chunk_content,  # Standardized field name for streaming content
                    "agent_label": agent_label,  # CRITICAL: Maps stream to correct node
                    "tags": tags or [],
                    # SUBAGENT FIELDS: Enable frontend to route to SubagentPanel
                    "subagent_run_id": subagent_run_id,
                    "subagent_name": subagent_name,
                }
            )

    # =========================================================================
    # DeepAgents-Specific Callback Methods
    # =========================================================================

    async def on_deepagent_todo_created(
        self,
        todo_id: str,
        todo_text: str,
        node_name: str = "DeepAgent",
        **kwargs
    ) -> None:
        """
        Called when a DeepAgent creates a new todo item.

        Args:
            todo_id: Unique identifier for the todo
            todo_text: The todo item text
            node_name: Name of the agent node
        """
        await self._emit_event(
            event_type="DEEPAGENT_TODO_CREATED",
            data={
                "todo_id": todo_id,
                "todo_text": todo_text,
                "node_name": node_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def on_deepagent_todo_completed(
        self,
        todo_id: str,
        todo_text: str,
        node_name: str = "DeepAgent",
        **kwargs
    ) -> None:
        """
        Called when a DeepAgent completes a todo item.

        Args:
            todo_id: Unique identifier for the todo
            todo_text: The todo item text
            node_name: Name of the agent node
        """
        await self._emit_event(
            event_type="DEEPAGENT_TODO_COMPLETED",
            data={
                "todo_id": todo_id,
                "todo_text": todo_text,
                "node_name": node_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def on_deepagent_subagent_spawned(
        self,
        subagent_name: str,
        subagent_task: str,
        parent_node: str = "DeepAgent",
        **kwargs
    ) -> None:
        """
        Called when a DeepAgent spawns a subagent.

        Args:
            subagent_name: Name of the spawned subagent
            subagent_task: Task assigned to the subagent
            parent_node: Name of the parent agent node
        """
        await self._emit_event(
            event_type="DEEPAGENT_SUBAGENT_SPAWNED",
            data={
                "subagent_name": subagent_name,
                "subagent_task": subagent_task,
                "parent_node": parent_node,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def on_deepagent_filesystem_operation(
        self,
        operation: str,
        file_path: str,
        node_name: str = "DeepAgent",
        **kwargs
    ) -> None:
        """
        Called when a DeepAgent performs a filesystem operation.

        Args:
            operation: Type of operation (read, write, edit, ls, etc.)
            file_path: Path of the file being operated on
            node_name: Name of the agent node
        """
        await self._emit_event(
            event_type="DEEPAGENT_FILESYSTEM_OP",
            data={
                "operation": operation,
                "file_path": file_path,
                "node_name": node_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def on_deepagent_context_offload(
        self,
        context_size: int,
        offload_path: str,
        node_name: str = "DeepAgent",
        **kwargs
    ) -> None:
        """
        Called when a DeepAgent offloads context to filesystem to manage memory.

        Args:
            context_size: Size of context being offloaded (tokens/bytes)
            offload_path: Path where context is saved
            node_name: Name of the agent node
        """
        await self._emit_event(
            event_type="DEEPAGENT_CONTEXT_OFFLOAD",
            data={
                "context_size": context_size,
                "offload_path": offload_path,
                "node_name": node_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
