# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Workflow execution mixin: the main streaming execution loop and tool validation.

Extracted from the former monolithic executor.py.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

# Task 3: Node-level caching support
from core.workflows.cache_config import get_cache_backend

# Task 10: Official multi-agent pattern wrappers
from core.workflows.official_patterns import (
    build_supervisor_graph, build_swarm_graph,
    SUPERVISOR_AVAILABLE, SWARM_AVAILABLE,
)

from models.workflow import WorkflowProfile
from core.workflows.events.emitter import create_execution_callback_handler
from core.workflows.events.progress import clear_execution_context
from core.workflows.checkpointing.manager import get_store

from .shared import SimpleWorkflowState, logger


class _WorkflowExecutionMixin:
    async def execute_workflow(
        self,
        workflow: WorkflowProfile,
        input_data: Dict[str, Any],
        project_id: int,
        task_id: int
    ) -> Dict[str, Any]:
        """
        Execute a user-created workflow.

        Args:
            workflow: WorkflowProfile from database with nodes/edges
            input_data: Input data from user (e.g., {"query": "..."})
            project_id: Project ID
            task_id: Task ID for tracking

        Returns:
            Final state with results
        """
        logger.info(f"Executing workflow '{workflow.name}' (id={workflow.id}) for task {task_id}")

        # Get event bus for real-time monitoring
        from services.event_bus import get_event_bus
        event_bus = get_event_bus()
        channel = f"workflow:{workflow.id}"

        try:
            # Publish workflow start event
            await event_bus.publish(channel, {
                "type": "status",
                "data": {
                    "status": "starting",
                    "workflow_name": workflow.name,
                    "workflow_id": workflow.id,
                    "task_id": task_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            # 0. Validate and pre-initialize tools BEFORE workflow execution
            logger.info("Validating workflow tools and pre-initializing async tools...")
            await event_bus.publish(channel, {
                "type": "status",
                "data": {
                    "status": "validating_tools",
                    "message": "Validating and initializing workflow tools...",
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            try:
                await self._validate_and_init_tools(workflow, channel, event_bus)
            except Exception as tool_error:
                error_msg = f"Tool validation failed: {str(tool_error)}"
                logger.error(error_msg)
                await event_bus.publish(channel, {
                    "type": "error",
                    "data": {
                        "error": error_msg,
                        "error_type": "ToolValidationError",
                        "workflow_id": workflow.id,
                        "task_id": task_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
                # Emit complete event so UI stops spinner
                await event_bus.publish(channel, {
                    "type": "complete",
                    "data": {
                        "status": "error",
                        "error": error_msg,
                        "error_type": "ToolValidationError",
                        "workflow_id": workflow.id,
                        "task_id": task_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
                raise ValueError(error_msg)

            # 1. Build LangGraph from workflow definition
            logger.info(f"Building graph from workflow configuration")
            await event_bus.publish(channel, {
                "type": "on_chain_start",
                "data": {
                    "name": "build_graph",
                    "message": f"Building workflow graph with {len(workflow.configuration.get('nodes', []))} nodes"
                }
            })

            graph = await self._build_graph_from_workflow(workflow)

            # Task 10: Strategy dispatch for official multi-agent patterns
            strategy_type = getattr(workflow, "strategy_type", None)
            strategy_value = strategy_type.value if strategy_type else None
            use_official_pattern = False

            if strategy_value == "langgraph_supervisor" and SUPERVISOR_AVAILABLE:
                workflow_config = workflow.configuration or {}
                agents_config = workflow_config.get("agents", [])
                supervisor_prompt = workflow_config.get("supervisor_prompt")
                try:
                    compiled_graph = build_supervisor_graph(
                        model=None,  # Will be resolved from config inside builder
                        agents=agents_config,
                        supervisor_prompt=supervisor_prompt,
                    )
                    use_official_pattern = True
                    logger.info(f"Using langgraph-supervisor pattern for workflow '{workflow.name}'")
                except Exception as e:
                    logger.warning(f"Failed to build supervisor graph, falling back to standard: {e}")

            elif strategy_value == "langgraph_swarm" and SWARM_AVAILABLE:
                workflow_config = workflow.configuration or {}
                agents_config = workflow_config.get("agents", [])
                try:
                    compiled_graph = build_swarm_graph(
                        model=None,  # Will be resolved from config inside builder
                        agents=agents_config,
                    )
                    use_official_pattern = True
                    logger.info(f"Using langgraph-swarm pattern for workflow '{workflow.name}'")
                except Exception as e:
                    logger.warning(f"Failed to build swarm graph, falling back to standard: {e}")

            # 2. Get checkpointer for state persistence
            # Only use checkpointer if explicitly enabled in input_data
            checkpointer_enabled = input_data.get("checkpointer_enabled", False)
            from core.workflows.checkpointing.manager import get_checkpointer
            checkpointer = get_checkpointer() if checkpointer_enabled else None

            # 3. Compile the graph with checkpointer and optional cache backend
            # Official patterns (supervisor/swarm) return pre-compiled graphs
            if not use_official_pattern:
                workflow_settings = (workflow.configuration or {}).get("settings", {})
                cache_backend = get_cache_backend(workflow_settings)
                compile_kwargs = {}
                if cache_backend:
                    compile_kwargs["cache"] = cache_backend
                    logger.info(f"[CACHE] Cache backend enabled for workflow '{workflow.name}'")

                if checkpointer:
                    logger.info(f"Compiling workflow '{workflow.name}' with checkpointing enabled")
                    compiled_graph = graph.compile(
                        checkpointer=checkpointer,
                        interrupt_before=[],  # Can add APPROVAL_NODE here for HITL
                        **compile_kwargs,
                    )
                else:
                    logger.warning(
                        f"Compiling workflow '{workflow.name}' WITHOUT checkpointing - "
                        f"state will not be persisted"
                    )
                    compiled_graph = graph.compile(**compile_kwargs)

            # 4. Create initial state with user's query
            query = input_data.get("query", "")
            now = datetime.utcnow()

            # Reconstruct continuation messages if continuing from a previous task
            continuation_messages = []
            raw_continuation = input_data.get("continuation_messages", [])
            if raw_continuation:
                for msg in raw_continuation:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "human":
                        continuation_messages.append(HumanMessage(content=content))
                    elif role == "ai":
                        ai_kwargs = {}
                        if msg.get("tool_calls"):
                            ai_kwargs["tool_calls"] = msg["tool_calls"]
                        if msg.get("name"):
                            ai_kwargs["name"] = msg["name"]
                        continuation_messages.append(AIMessage(content=content, **ai_kwargs))
                    elif role == "tool":
                        continuation_messages.append(ToolMessage(
                            content=content,
                            tool_call_id=msg.get("tool_call_id", "unknown"),
                            name=msg.get("name", "unknown")
                        ))
                    elif role == "system":
                        continuation_messages.append(SystemMessage(content=content))
                logger.info(f"Injected {len(continuation_messages)} continuation messages into initial state")

            initial_state: SimpleWorkflowState = {
                "workflow_id": workflow.id,
                "task_id": task_id,
                "project_id": project_id,
                "messages": continuation_messages,  # Seed with continuation messages (empty list if new conversation)
                "query": query,
                "context_documents": input_data.get("context_documents"),
                "current_node": None,
                "agent_type": None,
                "last_agent_type": None,
                "step_history": [],
                "result": None,
                "error_message": None,
                "started_at": now,
                "completed_at": None,
                "execution_duration_seconds": None,
                # Multimodal attachments from workflow input
                "workflow_attachments": input_data.get("attachments"),
                "agent_attachments": None,  # Will be populated per-agent from node configs
                # Custom output path for file writes (if configured per-workflow)
                "custom_output_path": getattr(workflow, 'custom_output_path', None),
                # Deferred node support: parallel branch outputs merged here
                "branch_results": {},
            }

            # 5. Create callback handler for detailed agent logging
            callback_handler = create_execution_callback_handler(
                project_id=project_id if project_id else 0,
                task_id=task_id,
                workflow_id=workflow.id,  # Required for SSE channel routing
                enable_sanitization=True,
                node_metadata=self.node_metadata  # Pass node metadata for proper event labeling
            )
            logger.info(f"Created execution callback handler for detailed event tracking (workflow:{workflow.id})")

            # Set up execution context for tool progress events
            # This allows tools to emit progress updates via the event bus
            from core.workflows.events.progress import set_execution_context, clear_execution_context
            set_execution_context({
                'workflow_id': workflow.id,
                'task_id': task_id,
                'project_id': project_id,
            })

            # 6. Configure workflow execution with thread_id for checkpointing and callbacks
            # Add Store for long-term memory if available
            store = get_store()
            config = {
                "configurable": {
                    "thread_id": f"workflow_{workflow.id}_task_{task_id}"
                },
                "callbacks": [callback_handler],
                "recursion_limit": input_data.get("recursion_limit", 100)  # Use user-defined limit or default to 100
            }

            # Add Store to config if initialized (enables runtime.store API for long-term memory)
            if store is not None:
                config["configurable"]["store"] = store
                logger.info("Long-term memory (Store) enabled for workflow execution")

            # 7. Execute the workflow with checkpointing config and callbacks
            logger.info(f"Starting execution of workflow '{workflow.name}'")
            await event_bus.publish(channel, {
                "type": "status",
                "data": {
                    "status": "executing",
                    "message": "Executing workflow nodes...",
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            # ========================================================================
            # CRITICAL: WORKFLOW EXECUTION LOOP - DO NOT MODIFY WITHOUT TESTING
            # ========================================================================
            # This loop processes LangGraph events and MUST properly exit or workflows
            # will run forever. Changes to completion detection logic (line ~402) can
            # cause infinite loops. Always test workflow completion after modifications.
            # ========================================================================

            # Use astream_events() to enable LLM token streaming
            # Unlike astream() which only streams node outputs, astream_events() streams ALL events
            # including LLM tokens - but we must manually publish them to SSE!
            final_state = None
            token_buffer = {}  # Buffer tokens per node to batch them and reduce spam
            last_publish_time = {}  # Track last publish time per node for throttling

            # Tool call JSON buffering to aggregate partial_json chunks and extract reasoning
            tool_call_buffer = {}  # {tool_call_id: {"name": str, "json_parts": [], "agent_label": str}}

            # Get cancellation registry for checking cancellation during execution
            from core.workflows.checkpointing.cancellation import get_cancellation_registry
            registry = get_cancellation_registry()

            # SAFETY: Prevent infinite loops with max events and timeout
            # These can be configured per-execution via input_data (frontend settings)
            # Note: astream_events() generates many low-level events (including tool call
            # argument deltas), so the limit needs to be high enough to accommodate
            # workflows with multiple tool calls. A single tool call can generate 100+ events.
            MAX_EVENTS = input_data.get("max_events", 100000)  # Default: 100k events
            TIMEOUT_SECONDS = input_data.get("timeout_seconds", 600)  # Default: 10 minutes

            # Enforce reasonable bounds to prevent abuse
            MAX_EVENTS = max(1000, min(MAX_EVENTS, 500000))  # 1k - 500k range
            TIMEOUT_SECONDS = max(60, min(TIMEOUT_SECONDS, 3600))  # 1 min - 1 hour range

            event_count = 0
            execution_start_time = datetime.utcnow()

            # RECURSION TRACKING: Track agent actions to detect loops
            agent_action_history = []  # List of (agent_label, tool_name, timestamp) tuples
            MAX_HISTORY_SIZE = 200  # Keep last 200 actions for analysis

            # Debug mode flag - when enabled, emits additional state transition events
            debug_mode = getattr(workflow, 'debug_mode', False)
            if debug_mode:
                logger.info(f"Debug mode ENABLED for workflow {workflow.id} - emitting detailed state transitions")

            # ========================================================================
            # SUBGRAPH STREAMING: Enable with subgraphs=True
            # ========================================================================
            # When subgraphs=True, astream_events() yields events from BOTH parent graph
            # AND any nested subgraphs (e.g., subagents called via 'task' tool).
            # Events from subgraphs include a 'langgraph_node' in tags showing the
            # subgraph path (e.g., "task:uuid:model" for a subagent's model node).
            # This is the official LangGraph approach for real-time subagent monitoring.
            # ========================================================================
            async for event in compiled_graph.astream_events(
                initial_state,
                config=config,
                version="v2",
                include_subgraphs=True  # Stream events from nested subgraphs (subagents)
            ):
                event_count += 1

                # Check event count limit
                if event_count > MAX_EVENTS:
                    error_msg = f"Workflow exceeded maximum event limit ({MAX_EVENTS}). Possible infinite loop detected."
                    logger.error(error_msg)
                    await event_bus.publish(channel, {
                        "type": "error",
                        "data": {
                            "error": error_msg,
                            "error_type": "MaxEventsExceeded",
                            "workflow_id": workflow.id,
                            "task_id": task_id,
                            "event_count": event_count,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                    raise RuntimeError(error_msg)

                # Check timeout
                elapsed = (datetime.utcnow() - execution_start_time).total_seconds()
                if elapsed > TIMEOUT_SECONDS:
                    error_msg = f"Workflow execution timeout ({TIMEOUT_SECONDS}s). Stopping execution."
                    logger.error(error_msg)
                    await event_bus.publish(channel, {
                        "type": "error",
                        "data": {
                            "error": error_msg,
                            "error_type": "ExecutionTimeout",
                            "workflow_id": workflow.id,
                            "task_id": task_id,
                            "elapsed_seconds": elapsed,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                    raise TimeoutError(error_msg)
                # Check for cancellation at every event
                if await registry.is_cancelled(task_id):
                    logger.info(f"Task {task_id} cancelled - stopping workflow execution")
                    await event_bus.publish(channel, {
                        "type": "error",
                        "data": {
                            "error": "Workflow cancelled by user",
                            "error_type": "TaskCancelled",
                            "workflow_id": workflow.id,
                            "task_id": task_id,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                    raise asyncio.CancelledError("Task cancelled by user")

                # ====================================================================
                # SUBGRAPH NAMESPACE DETECTION
                # ====================================================================
                # With include_subgraphs=True, events from nested subgraphs have
                # special metadata indicating the subgraph path. Extract this to
                # route events to the correct SubAgentPanel in the frontend.
                # ====================================================================
                tags = event.get("tags", [])
                metadata = event.get("metadata", {})

                # Check for subgraph namespace in metadata (LangGraph convention)
                # Format: "langgraph_node" tag with path like "task:uuid", or
                # metadata with "langgraph_subgraph" or nested run_id references
                subgraph_namespace = None
                subgraph_run_id = None

                # Method 1: Check for langgraph_node tag — any event from a subgraph
                # will have tags from the parent's node PLUS subgraph-specific tags
                for tag in tags:
                    if isinstance(tag, str) and ":" in tag:
                        # Tags like "task:uuid" or "subagent:uuid" indicate subgraph
                        parts = tag.split(":")
                        if len(parts) >= 2 and parts[0] in ("task", "subagent", "delegate"):
                            subgraph_namespace = tag
                            subgraph_run_id = parts[1] if len(parts) > 1 else None
                            break

                # Method 2: Check in metadata for langgraph_checkpoint_ns
                # Format when subgraphs=True: "parent_ns|child_ns" — the pipe indicates nesting
                if not subgraph_namespace:
                    checkpoint_ns = metadata.get("langgraph_checkpoint_ns", "")
                    if checkpoint_ns and "|" in checkpoint_ns:
                        ns_parts = checkpoint_ns.split("|")
                        if len(ns_parts) > 1:
                            subgraph_namespace = ns_parts[-1]
                            if ":" in ns_parts[-1]:
                                subgraph_run_id = ns_parts[-1].split(":")[1]

                # Method 3: Check for langgraph_node tag that resembles a subgraph path
                # DeepAgent SDK creates subgraphs with specific naming
                if not subgraph_namespace:
                    langgraph_node = metadata.get("langgraph_node", "")
                    if langgraph_node and ":" in langgraph_node:
                        parts = langgraph_node.split(":")
                        if len(parts) >= 2:
                            subgraph_namespace = langgraph_node
                            subgraph_run_id = parts[-1]
                    elif not langgraph_node:
                        # No langgraph_node means this could be a parent-level event
                        pass

                # Method 4: Log ALL events that might be from subgraphs for debugging
                if "checkpoint_ns" in metadata or "langgraph_node" in metadata:
                    event_kind = event.get("event", "")
                    lg_node = metadata.get("langgraph_node", "")
                    ckpt_ns = metadata.get("checkpoint_ns", "") or metadata.get("langgraph_checkpoint_ns", "")
                    if lg_node or ckpt_ns:
                        logger.debug(f"[SUBGRAPH CANDIDATE] event={event_kind}, node={lg_node}, ckpt_ns={ckpt_ns}, tags={tags[:3]}")

                # If we have a subgraph namespace, log it for debugging
                if subgraph_namespace:
                    logger.debug(f"[SUBGRAPH EVENT] namespace={subgraph_namespace}, run_id={subgraph_run_id}")

                # astream_events yields ALL events including LLM tokens and state updates
                kind = event.get("event")

                # Handle LLM token streaming - batch and throttle to reduce spam
                if kind == "on_chat_model_stream":
                    # Extract token from event
                    data = event.get("data", {})
                    chunk = data.get("chunk")
                    token_text = None

                    # Get node_id early to determine model provider
                    tags = event.get("tags", [])
                    metadata = event.get("metadata", {})
                    node_id = metadata.get("node_id") or (tags[0] if tags and tags[0].startswith("node-") else None)

                    # Determine model provider from node config
                    model_provider = None
                    if node_id and node_id in self.node_metadata:
                        model_config = self.node_metadata[node_id].get("config", {})
                        model_name = model_config.get("model", "").lower()

                        # Detect provider from model name
                        if "claude" in model_name or "anthropic" in model_name:
                            model_provider = "anthropic"
                        elif "gpt" in model_name or "o1" in model_name or "openai" in model_name:
                            model_provider = "openai"
                        elif "gemini" in model_name or "google" in model_name:
                            model_provider = "google"
                        else:
                            model_provider = "unknown"

                    logger.debug(f"[DEBUG] Provider: {model_provider}, Chunk type: {type(chunk)}, Value preview: {str(chunk)[:100]}")

                    # Provider-specific token extraction
                    if chunk and hasattr(chunk, 'content'):
                        content = chunk.content

                        if model_provider == "anthropic":
                            # DEBUG: Log full content structure for Anthropic
                            logger.debug(f"[ANTHROPIC DEBUG] content type: {type(content)}, content: {repr(content)[:500]}")
                            # Claude/Anthropic: content = [{'text': 'token', 'type': 'text', 'index': 0}]
                            if isinstance(content, list) and len(content) > 0:
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict) and 'text' in item:
                                        text_parts.append(item['text'])
                                    elif isinstance(item, str):
                                        text_parts.append(item)
                                token_text = ''.join(text_parts) if text_parts else None
                            elif isinstance(content, str):
                                token_text = content

                        elif model_provider in ("openai", "google"):
                            # OpenAI/Gemini: content = "token string"
                            if isinstance(content, str):
                                token_text = content
                            elif content:
                                token_text = str(content)

                        else:
                            # Unknown provider - try both approaches as fallback
                            if isinstance(content, str):
                                token_text = content
                            elif isinstance(content, list) and len(content) > 0:
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict) and 'text' in item:
                                        text_parts.append(item['text'])
                                    elif isinstance(item, str):
                                        text_parts.append(item)
                                token_text = ''.join(text_parts) if text_parts else None
                            elif content:
                                token_text = str(content)

                    # Also check for tool call streaming (partial_json chunks)
                    if chunk and hasattr(chunk, 'content') and isinstance(chunk.content, list):
                        for item in chunk.content:
                            if isinstance(item, dict):
                                # Check for tool call with partial_json
                                if item.get('type') == 'input_json_delta' and 'partial_json' in item:
                                    partial_json = item['partial_json']
                                    tool_call_index = item.get('index', 0)

                                    # Get tool call ID from chunk metadata
                                    tool_call_id = f"{node_id}_{tool_call_index}"

                                    # Initialize buffer for this tool call
                                    if tool_call_id not in tool_call_buffer:
                                        tool_call_buffer[tool_call_id] = {
                                            "name": None,
                                            "json_parts": [],
                                            "agent_label": None,
                                            "notified": False  # Track if we've sent notification
                                        }

                                    # Accumulate JSON parts
                                    tool_call_buffer[tool_call_id]["json_parts"].append(partial_json)

                                    # Store agent label if we have node_id
                                    if node_id and node_id in self.node_metadata:
                                        tool_call_buffer[tool_call_id]["agent_label"] = self.node_metadata[node_id]["label"]

                                    # Try to extract filename early for write_file tool
                                    # Support both new (write_file) and legacy (file_write) tool names
                                    tool_name = tool_call_buffer[tool_call_id].get("name")
                                    if tool_name in ("write_file", "file_write") and not tool_call_buffer[tool_call_id].get("notified"):
                                        # Reconstruct JSON so far to check if we have file_path
                                        json_so_far = ''.join(tool_call_buffer[tool_call_id]["json_parts"])

                                        # Try to extract file_path using regex (faster than JSON parse)
                                        import re
                                        match = re.search(r'"file_path"\s*:\s*"([^"]+)"', json_so_far)

                                        if match:
                                            filename = match.group(1)
                                            agent_label = tool_call_buffer[tool_call_id].get("agent_label")

                                            if agent_label and filename:
                                                # Check if file exists to determine message
                                                import os
                                                file_exists = os.path.exists(filename)
                                                action = "Working on" if file_exists else "Creating"

                                                # Extract just the filename from path
                                                display_name = os.path.basename(filename)

                                                await event_bus.publish(channel, {
                                                    "type": "tool_start",
                                                    "data": {
                                                        "tool_name": tool_name,
                                                        "agent_label": agent_label,
                                                        "file_action": action,
                                                        "filename": display_name,
                                                        "full_path": filename,
                                                        "run_id": str(event.get("run_id", "")),
                                                        "timestamp": datetime.utcnow().isoformat()
                                                    }
                                                })
                                                logger.info(f"[TOOL START] {agent_label}: {action} {display_name}")
                                                tool_call_buffer[tool_call_id]["notified"] = True

                                # Check for tool_use start (contains tool name)
                                # This fires when we first see a tool being called, BEFORE the JSON args stream
                                if item.get('type') == 'tool_use' and 'name' in item:
                                    tool_name = item['name']
                                    tool_call_index = item.get('index', 0)
                                    tool_call_id = f"{node_id}_{tool_call_index}"

                                    logger.info(f"[TOOL_USE DETECTED] tool={tool_name}, index={tool_call_index}, node_id={node_id}")

                                    # Initialize buffer if not exists
                                    if tool_call_id not in tool_call_buffer:
                                        tool_call_buffer[tool_call_id] = {
                                            "name": None,
                                            "json_parts": [],
                                            "agent_label": None,
                                            "notified": False,
                                            "preparing_notified": False  # Track if we've sent preparing notification
                                        }

                                    tool_call_buffer[tool_call_id]["name"] = tool_name
                                    tool_call_buffer[tool_call_id]["tool_use_id"] = item.get('id')

                                    # Get agent label for this node
                                    agent_label = None
                                    if node_id and node_id in self.node_metadata:
                                        agent_label = self.node_metadata[node_id]["label"]
                                        tool_call_buffer[tool_call_id]["agent_label"] = agent_label

                                    # IMMEDIATE: Emit tool_preparing event so frontend shows something right away
                                    # This fires as soon as we know the tool name, before JSON streaming completes
                                    if not tool_call_buffer[tool_call_id].get("preparing_notified"):
                                        logger.info(f"[TOOL PREPARING - EMITTING] {agent_label}: {tool_name}")
                                        await event_bus.publish(channel, {
                                            "type": "tool_preparing",
                                            "data": {
                                                "tool_name": tool_name,
                                                "agent_label": agent_label,
                                                "node_id": node_id,
                                                "run_id": str(event.get("run_id", "")),
                                                "message": f"Preparing {tool_name}...",
                                                "timestamp": datetime.utcnow().isoformat()
                                            }
                                        })
                                        logger.info(f"[TOOL PREPARING] {agent_label}: {tool_name}")
                                        tool_call_buffer[tool_call_id]["preparing_notified"] = True

                    # DEBUG: Log what we extracted (debug level to avoid spam)
                    logger.debug(f"[EXTRACTED TOKEN] Provider: {model_provider}, Type: {type(token_text)}, Value: {repr(token_text)[:200]}")

                    if token_text and isinstance(token_text, str):
                        # Try to extract agent_label from event tags/metadata
                        tags = event.get("tags", [])
                        metadata = event.get("metadata", {})
                        agent_label = None

                        # Look for node_id in tags or metadata to find agent_label
                        node_id = metadata.get("node_id") or (tags[0] if tags and tags[0].startswith("node-") else None)
                        if node_id and node_id in self.node_metadata:
                            agent_label = self.node_metadata[node_id]["label"]

                        # Skip if we don't have a node_id (can't buffer properly)
                        if not node_id:
                            continue

                        # Buffer tokens per node (use node_id as key to keep agents separate)
                        if node_id not in token_buffer:
                            token_buffer[node_id] = ""
                            last_publish_time[node_id] = 0

                        token_buffer[node_id] += token_text

                        # Throttle: only publish every 50ms OR when buffer reaches 20 chars
                        current_time = datetime.utcnow().timestamp()
                        time_since_last = current_time - last_publish_time[node_id]
                        buffer_size = len(token_buffer[node_id])

                        if time_since_last > 0.1 or buffer_size > 40:  # 100ms throttle or 40 char buffer
                            stream_data = {
                                "token": token_buffer[node_id],
                                "content": token_buffer[node_id],  # Also include as 'content' for consistency
                                "agent_label": agent_label,
                                "node_id": node_id,  # Include node_id for proper grouping in frontend
                                "run_id": str(event.get("run_id", "")),
                                "parent_run_id": str(event.get("parent_run_id", "")) if event.get("parent_run_id") else None,
                                # SUBGRAPH ROUTING: Include subgraph context for SubAgentPanel
                                "subgraph_run_id": subgraph_run_id,  # Routes to correct SubAgentPanel
                                "subgraph_namespace": subgraph_namespace,  # Full namespace path
                                "timestamp": datetime.utcnow().isoformat()
                            }

                            # _emit_event handles BOTH:
                            # 1. Publishing to event bus (for live SSE streaming)
                            # 2. Persisting to database (for historical replay)
                            # Do NOT also call event_bus.publish() - that causes duplicate tokens!
                            await callback_handler._emit_event(
                                event_type="CHAT_MODEL_STREAM",
                                data=stream_data
                            )

                            logger.debug(f"[STREAMING] {agent_label or node_id}: {token_buffer[node_id][:50]}...")
                            token_buffer[node_id] = ""  # Clear buffer
                            last_publish_time[node_id] = current_time

                # ========================================================================
                # LLM END EVENT CAPTURE (for token tracking)
                # ========================================================================
                # Capture token usage from LLM completion events and save to database
                # This enables per-agent cost tracking in the workflow library
                elif kind == "on_llm_end" or kind == "on_chat_model_end":
                    logger.info(f"[TOKEN CAPTURE] Received {kind} event")
                    try:
                        # Extract token usage from event
                        data = event.get("data", {})
                        output = data.get("output", {})

                        # Get token usage - try multiple paths for different LangChain versions
                        tokens_used = 0
                        prompt_tokens = 0
                        completion_tokens = 0

                        # Path 1: llm_output.token_usage (older LangChain)
                        llm_output = output.get("llm_output", {})
                        token_usage = llm_output.get("token_usage", {})
                        if token_usage:
                            tokens_used = token_usage.get("total_tokens", 0)
                            prompt_tokens = token_usage.get("prompt_tokens", 0)
                            completion_tokens = token_usage.get("completion_tokens", 0)

                        # Path 2: usage_metadata (newer LangChain)
                        if tokens_used == 0:
                            usage_metadata = output.get("usage_metadata") or data.get("usage_metadata")
                            if usage_metadata:
                                if isinstance(usage_metadata, dict):
                                    tokens_used = usage_metadata.get("total_tokens", 0)
                                    prompt_tokens = usage_metadata.get("input_tokens", 0)
                                    completion_tokens = usage_metadata.get("output_tokens", 0)
                                else:
                                    tokens_used = getattr(usage_metadata, 'total_tokens', 0)
                                    prompt_tokens = getattr(usage_metadata, 'input_tokens', 0)
                                    completion_tokens = getattr(usage_metadata, 'output_tokens', 0)

                        if tokens_used == 0:
                            logger.warning(f"[TOKEN CAPTURE] No tokens found. Event structure: data keys={list(data.keys())}, output keys={list(output.keys()) if output else None}")

                        logger.info(f"[TOKEN CAPTURE] Extracted tokens: {tokens_used} (prompt: {prompt_tokens}, completion: {completion_tokens})")

                        if tokens_used > 0:
                            # Get node context for agent_label
                            tags = event.get("tags", [])
                            metadata = event.get("metadata", {})
                            node_id = metadata.get("node_id") or next((tag for tag in tags if tag.startswith("node-")), None)

                            agent_label = "Unknown"
                            model_name = "unknown"

                            if node_id and node_id in self.node_metadata:
                                agent_label = self.node_metadata[node_id].get("label", "Unknown")
                                model_config = self.node_metadata[node_id].get("config", {})
                                model_name = model_config.get("model", "unknown")

                            # Also try to get model from llm_output
                            if model_name == "unknown":
                                model_name = llm_output.get("model_name", llm_output.get("model", "unknown"))

                            # Save LLM_END event to database via callback handler
                            run_id = event.get("run_id", "")
                            await callback_handler._emit_event(
                                event_type="LLM_END",
                                data={
                                    "run_id": str(run_id),
                                    "agent_label": agent_label,
                                    "model": model_name,
                                    "tokens_used": tokens_used,
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "cumulative_tokens": 0  # Will be calculated in aggregation
                                }
                            )

                            logger.info(f"[LLM END] Captured token usage: agent={agent_label}, model={model_name}, tokens={tokens_used}")
                    except Exception as e:
                        logger.warning(f"Failed to capture LLM_END event: {e}")

                # ========================================================================
                # CRITICAL: STATE CAPTURE FROM GRAPH EVENTS
                # ========================================================================
                # Capture state from chain_end events as the graph progresses.
                # The loop will exit naturally when astream_events completes.
                # ========================================================================

                # Capture state from chain completion events
                elif kind == "on_chain_end":
                    event_name = event.get("name", "")
                    event_data = event.get("data", {})

                    # RECURSION TRACKING: Record node executions
                    tags = event.get("tags", [])
                    node_id = next((tag for tag in tags if tag.startswith("node-")), None)
                    if node_id and node_id in self.node_metadata:
                        agent_label = self.node_metadata[node_id]["label"]
                        agent_action_history.append((agent_label, "node_end", datetime.utcnow()))

                        # Keep history size bounded
                        if len(agent_action_history) > MAX_HISTORY_SIZE:
                            agent_action_history.pop(0)

                        # Check for simple loop patterns (same node 5+ times in a row)
                        # DISABLED: These warnings were too noisy and disrupted streaming
                        # if len(agent_action_history) >= 5:
                        #     recent = agent_action_history[-5:]
                        #     if all(action[0] == agent_label for action in recent):
                        #         logger.warning(f"⚠️  RECURSION WARNING: {agent_label} executed 5 times in a row")
                        #         logger.warning(f"Recent actions: {[(a[0], a[1]) for a in agent_action_history[-20:]]}")

                        # EARLY WARNING: If we're getting close to the limit, log it
                        # DISABLED: Too noisy for long-running workflows
                        # if len(agent_action_history) >= 20:
                        #     logger.warning(f"🚨 HIGH ITERATION COUNT: {len(agent_action_history)} actions so far")
                        #     logger.warning(f"⚠️  If this continues, check:")
                        #     logger.warning(f"   1. Agent system prompt has completion criteria")
                        #     logger.warning(f"   2. Agent isn't stuck in tool loop")
                        #     logger.warning(f"   3. Workflow graph doesn't have cycles")

                    # Capture any valid output state we encounter
                    # This ensures we have the latest state when loop exits naturally
                    potential_state = event_data.get("output")
                    if potential_state and isinstance(potential_state, dict):
                        final_state = potential_state
                        logger.debug(f"[STATE] Captured state from {event_name} event")

                    # Debug mode: emit detailed state transition events
                    if debug_mode:
                        await callback_handler._emit_event(
                            event_type="DEBUG_STATE_TRANSITION",
                            data={
                                "event_kind": "on_chain_end",
                                "event_name": event_name,
                                "tags": event.get("tags", []),
                                "node_id": node_id,
                                "agent_label": self.node_metadata.get(node_id, {}).get("label") if node_id else None,
                                "run_id": str(event.get("run_id", "")),
                                "parent_run_id": str(event.get("parent_run_id", "")) if event.get("parent_run_id") else None,
                                "state_keys": list(potential_state.keys()) if potential_state else [],
                            }
                        )

                        # ========================================================================
                        # HITL (Human-in-the-Loop) Detection
                        # ========================================================================
                        # Check if agent requested an interrupt (e.g., asking a question)
                        if potential_state.get("interrupt_requested"):
                            interrupt_reason = potential_state.get("interrupt_reason", "unknown")
                            pending_question = potential_state.get("pending_question", "")

                            logger.warning(f"🛑 HITL interrupt requested: {interrupt_reason}")
                            logger.info(f"Question: {pending_question[:200]}...")

                            # Publish HITL event to frontend
                            await event_bus.publish(channel, {
                                "type": "hitl_required",
                                "data": {
                                    "workflow_id": workflow.id,
                                    "task_id": task_id,
                                    "reason": interrupt_reason,
                                    "question": pending_question,
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                            })

                            # For now, continue execution (Question Detection is informational)
                            # TODO: Implement proper pause/resume with LangGraph checkpointing
                            # This would require:
                            # 1. Break from astream_events loop
                            # 2. Save checkpoint state
                            # 3. Wait for user approval via HITL API
                            # 4. Resume from checkpoint when approved
                            logger.info("⚠️  HITL detection active but not pausing (informational mode)")
                            # In future: break  # Exit loop and wait for approval

                # ========================================================================
                # INTERRUPT HANDLING (Deep Agent HITL)
                # ========================================================================
                # When a deep agent inside a node calls interrupt() (via HumanInTheLoopMiddleware),
                # LangGraph yields an __interrupt__ event. We capture this and emit an SSE
                # event to the frontend so the user can approve/reject the tool call.
                elif kind == "__interrupt__":
                    interrupt_data = event.get("data", {})
                    logger.info(f"🛑 __interrupt__ detected: {str(interrupt_data)[:200]}")

                    # Extract node_id from tags for context
                    interrupt_tags = event.get("tags", [])
                    interrupt_metadata = event.get("metadata", {})
                    interrupt_node_id = interrupt_metadata.get("node_id") or (
                        interrupt_tags[0] if interrupt_tags else None
                    )

                    # Extract action requests from interrupt data
                    interrupt_value = interrupt_data.get("value") or interrupt_data.get("resumption")
                    action_requests = []
                    if interrupt_value and isinstance(interrupt_value, dict):
                        # Deep agent HITL format: {"action_requests": [...]}
                        action_requests = interrupt_value.get("action_requests", [])
                        if not action_requests and "tool_calls" in interrupt_value:
                            # Normal agent HITL format: {"tool_calls": [...]}
                            action_requests = interrupt_value["tool_calls"]

                    # Also try to get tool calls from the state
                    if not action_requests:
                        try:
                            state = await compiled_graph.aget_state(config)
                            if state and hasattr(state, 'values') and state.values:
                                messages = state.values.get("messages", [])
                                for msg in reversed(messages):
                                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                        action_requests = [
                                            {"name": tc["name"], "args": tc["args"]}
                                            for tc in msg.tool_calls
                                        ]
                                        break
                        except Exception as e:
                            logger.debug(f"Could not get state for interrupt data: {e}")

                    # Emit interrupt event to frontend via SSE
                    await event_bus.publish(channel, {
                        "type": "interrupt",
                        "data": {
                            "action_requests": action_requests,
                            "workflow_id": workflow.id,
                            "task_id": task_id,
                            "node_id": node_id,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                    logger.info(f"✅ Emitted interrupt event to frontend: {len(action_requests)} action(s) pending")

            # Loop has exited naturally - LangGraph is done
            logger.info(f"[COMPLETION] Graph execution completed after {event_count} events")

            # Flush any remaining buffered tokens
            for node_id, buffered_text in token_buffer.items():
                if buffered_text:
                    # Get agent_label from node_metadata
                    agent_label = self.node_metadata.get(node_id, {}).get("label")
                    await event_bus.publish(channel, {
                        "type": "on_chat_model_stream",
                        "data": {
                            "token": buffered_text,
                            "agent_label": agent_label,
                            "node_id": node_id,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })

            # Process completed tool calls to extract reasoning
            for tool_call_id, tool_data in tool_call_buffer.items():
                tool_name = tool_data.get("name")
                json_parts = tool_data.get("json_parts", [])
                agent_label = tool_data.get("agent_label")

                # Only process reasoning_chain tool calls with content
                if tool_name == "reasoning_chain" and json_parts and agent_label:
                    try:
                        # Reconstruct full JSON from partial chunks
                        full_json_str = ''.join(json_parts)
                        tool_input = json.loads(full_json_str)

                        # Extract reasoning text from tool input
                        reasoning_text = tool_input.get("task", "") or tool_input.get("query", "") or tool_input.get("reasoning", "")

                        if reasoning_text:
                            logger.info(f"[TOOL REASONING] {agent_label}: {reasoning_text[:100]}...")

                            # Stream the reasoning as if it were thinking text
                            await event_bus.publish(channel, {
                                "type": "on_chat_model_stream",
                                "data": {
                                    "token": f"\n🧠 Reasoning: {reasoning_text}",
                                    "agent_label": agent_label,
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                            })
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse tool call JSON for {tool_call_id}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing tool call reasoning: {e}")

            # If no state captured (shouldn't happen but defensive), fall back to initial state
            if final_state is None:
                logger.warning("No final state from astream_events - using initial state")
                final_state = initial_state

            logger.info(f"Workflow '{workflow.name}' completed successfully")
            await event_bus.publish(channel, {
                "type": "on_chain_end",
                "data": {
                    "name": "workflow_execution",
                    "message": "Workflow execution completed",
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            # CRITICAL: Flush all pending database persist tasks before querying
            # This ensures all tool_start, tool_end, and LLM events are saved to DB
            # before we aggregate the workflow summary
            await callback_handler.flush_pending_persists(timeout=10.0)

            # 7. Aggregate workflow execution summary (tool calls, token usage by agent)
            from models.execution_event import ExecutionEvent
            from db.database import get_db, SessionLocal

            workflow_summary = {
                "tool_calls_by_agent": {},
                "tokens_by_agent": {},
                "total_tool_calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0
            }

            # Query all execution events for this task
            db = SessionLocal()
            try:
                tool_events = db.query(ExecutionEvent).filter(
                    ExecutionEvent.task_id == task_id,
                    ExecutionEvent.event_type == "on_tool_start"
                ).all()

                token_events = db.query(ExecutionEvent).filter(
                    ExecutionEvent.task_id == task_id,
                    ExecutionEvent.event_type == "LLM_END"
                ).all()

                # Aggregate tool calls by agent
                for event in tool_events:
                    agent_name = event.event_data.get("agent_label", "Unknown")
                    tool_name = event.event_data.get("tool_name", "unknown")

                    if agent_name not in workflow_summary["tool_calls_by_agent"]:
                        workflow_summary["tool_calls_by_agent"][agent_name] = []

                    workflow_summary["tool_calls_by_agent"][agent_name].append({
                        "tool": tool_name,
                        "timestamp": event.timestamp.isoformat() if event.timestamp else None
                    })
                    workflow_summary["total_tool_calls"] += 1

                # Aggregate tokens by agent
                for event in token_events:
                    agent_name = event.event_data.get("agent_label", "Unknown")
                    tokens = event.event_data.get("tokens_used", 0)
                    model = event.event_data.get("model", "unknown")

                    if agent_name not in workflow_summary["tokens_by_agent"]:
                        workflow_summary["tokens_by_agent"][agent_name] = {
                            "tokens": 0,
                            "model": model,
                            "calls": 0
                        }

                    workflow_summary["tokens_by_agent"][agent_name]["tokens"] += tokens
                    workflow_summary["tokens_by_agent"][agent_name]["calls"] += 1
                    workflow_summary["total_tokens"] += tokens

                # Cost estimation based on current model pricing (Updated December 2025)
                cost_per_1m_tokens = {
                    # OpenAI Reasoning Models
                    "o3": 20.00,
                    "o3-mini": 4.00,
                    "o4-mini": 3.00,
                    # OpenAI GPT-4o Series
                    "gpt-4o": 2.50,
                    "gpt-4o-mini": 0.15,
                    # Anthropic Claude 4.5
                    "claude-opus-4-5": 15.00,
                    "claude-sonnet-4-5": 3.00,
                    "claude-sonnet-4-5-20250929": 3.00,
                    "claude-haiku-4-5": 1.00,
                    # Google Gemini 3
                    "gemini-3-pro-preview": 2.00,
                    # Google Gemini 2.5
                    "gemini-2.5-flash": 0.075,
                    # Google Gemini 2.0
                    "gemini-2.0-flash": 0.075,
                    "default": 1.00
                }

                for agent_name, data in workflow_summary["tokens_by_agent"].items():
                    model = data["model"].lower()
                    rate = next((v for k, v in cost_per_1m_tokens.items() if k in model), cost_per_1m_tokens["default"])
                    agent_cost = (data["tokens"] / 1_000_000) * rate
                    data["estimated_cost_usd"] = round(agent_cost, 4)
                    workflow_summary["total_cost_usd"] += agent_cost

                workflow_summary["total_cost_usd"] = round(workflow_summary["total_cost_usd"], 4)

                logger.info(f"Workflow summary: {workflow_summary['total_tool_calls']} tool calls, {workflow_summary['total_tokens']} tokens, ${workflow_summary['total_cost_usd']}")

            except Exception as e:
                logger.error(f"Failed to aggregate workflow summary: {e}")
            finally:
                db.close()

            # 8. Format output for frontend display
            from services.output_formatter import format_workflow_output

            await event_bus.publish(channel, {
                "type": "status",
                "data": {
                    "status": "formatting",
                    "message": "Formatting output...",
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            formatted_output = format_workflow_output(
                raw_output=final_state,
                workflow_name=workflow.name,
                task_id=task_id
            )

            # Publish completion event with clean formatted output AND workflow summary
            await event_bus.publish(channel, {
                "type": "complete",
                "data": {
                    "status": "completed",
                    "workflow_id": workflow.id,
                    "task_id": task_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "formatted_output": formatted_output,
                    "workflow_summary": workflow_summary  # NEW: Comprehensive execution summary
                }
            })

            # Clear execution context for tool progress events
            clear_execution_context()

            # Collect artifacts (images, files, etc.) generated during execution
            collected_artifacts = callback_handler.get_collected_artifacts()
            if collected_artifacts:
                logger.info(f"Workflow execution produced {len(collected_artifacts)} artifacts (images, files, etc.)")

            # Return formatted output, messages, artifacts, AND workflow summary for task result
            return {
                "formatted_output": formatted_output,
                "messages": final_state.get("messages", []),
                "workflow_summary": workflow_summary,
                "collected_artifacts": collected_artifacts  # Images, files generated by tools
            }

        except asyncio.CancelledError as e:
            logger.info(f"Workflow execution cancelled for task {task_id}")

            # Publish cancellation event
            await event_bus.publish(channel, {
                "type": "error",
                "data": {
                    "error": "Workflow cancelled by user",
                    "error_type": "TaskCancelled",
                    "workflow_id": workflow.id,
                    "task_id": task_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            # Clear execution context for tool progress events
            clear_execution_context()

            return {
                "error": "Workflow cancelled by user",
                "workflow_status": "CANCELLED",
                "task_id": task_id
            }

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            logger.error(f"Workflow execution failed: {e}", exc_info=True)

            # Enhanced diagnostics for recursion errors
            if "recursion" in error_msg.lower() or error_type == "GraphRecursionError":
                logger.error("=" * 80)
                logger.error("RECURSION LIMIT EXCEEDED - DIAGNOSTIC INFO")
                logger.error("=" * 80)
                logger.error(f"Workflow: {workflow.name} (ID: {workflow.id})")
                logger.error(f"Task: {task_id}")
                logger.error(f"Error: {error_msg}")
                logger.error("")

                # Analyze action history to find patterns
                if 'agent_action_history' in locals() and agent_action_history:
                    logger.error("EXECUTION PATTERN ANALYSIS:")
                    logger.error(f"Total actions before failure: {len(agent_action_history)}")

                    # Count actions per agent
                    from collections import Counter
                    agent_counts = Counter(action[0] for action in agent_action_history)
                    logger.error("Actions per agent:")
                    for agent, count in agent_counts.most_common():
                        logger.error(f"  - {agent}: {count} times")

                    # Show last 30 actions to reveal the loop pattern
                    logger.error("")
                    logger.error("Last 30 actions before error:")
                    for i, (agent, action_type, timestamp) in enumerate(agent_action_history[-30:], 1):
                        logger.error(f"  {i}. {agent} ({action_type})")

                    # Detect simple cycle patterns
                    if len(agent_action_history) >= 10:
                        last_10 = [action[0] for action in agent_action_history[-10:]]
                        if len(set(last_10)) <= 3:
                            logger.error("")
                            logger.error(f"🔍 LOOP DETECTED: Only {len(set(last_10))} unique agents in last 10 actions")
                            logger.error(f"   Pattern: {' → '.join(last_10)}")
                logger.error("")
                logger.error("POSSIBLE CAUSES:")
                logger.error("1. Agent system prompt lacks completion criteria")
                logger.error("2. Agent stuck in tool loop (calling same tool repeatedly)")
                logger.error("3. Workflow graph has a cycle without exit condition")
                logger.error("")
                logger.error("SOLUTIONS:")
                logger.error("1. ADD COMPLETION RULES TO SYSTEM PROMPT:")
                logger.error("   - 'Stop after 10-15 tool calls'")
                logger.error("   - 'Finish when you have sufficient information'")
                logger.error("   - 'Do not continue researching indefinitely'")
                logger.error("2. Check workflow graph for cycles - ensure conditional edges have proper exit")
                logger.error("3. Review browser console for repeated agent actions")
                logger.error("4. If task legitimately needs >40 steps, break it into smaller sub-tasks")
                logger.error("=" * 80)

                # Add helpful context to error message
                pattern_info = ""
                if 'agent_action_history' in locals() and agent_action_history:
                    last_agents = [action[0] for action in agent_action_history[-10:]]
                    pattern_info = f"\n5. Last 10 agents executed: {' → '.join(last_agents)}"

                error_msg = (
                    f"{error_msg}\n\n"
                    "💡 DIAGNOSIS HELP:\n"
                    "1. Check browser console for repeated agent actions (🤔 AGENT ACTION logs)\n"
                    "2. Verify workflow graph doesn't have infinite loops\n"
                    "3. Ensure conditional edges have proper exit conditions\n"
                    "4. Review agent system prompt for task completion logic"
                    f"{pattern_info}"
                )

                # Perform comprehensive diagnostics
                from core.utils.recursion_diagnostics import RecursionDiagnostics

                diagnostic_data = RecursionDiagnostics.analyze_recursion_error(
                    workflow=workflow,
                    task_id=task_id,
                    agent_action_history=agent_action_history if 'agent_action_history' in locals() else [],
                    workflow_state=workflow_state if 'workflow_state' in locals() else {},
                    error_msg=error_msg
                )

                # Update error message with detected issues
                if diagnostic_data.get("detected_issues"):
                    error_msg = (
                        f"{error_msg}\n\n"
                        "💡 DETECTED ISSUES:\n" +
                        "\n".join(f"  • {issue}" for issue in diagnostic_data["detected_issues"])
                    )

                # Emit special recursion_limit_hit event for HITL intervention with full diagnostics
                # DO NOT emit error event - let the workflow complete and show output
                await event_bus.publish(channel, {
                    "type": "recursion_limit_hit",
                    "data": {
                        "workflow_id": workflow.id,
                        "task_id": task_id,
                        "agent_name": agent_action_history[-1][0] if 'agent_action_history' in locals() and agent_action_history else "Unknown",
                        "iteration_count": len(agent_action_history) if 'agent_action_history' in locals() else 0,
                        "current_limit": 100,  # Match the actual workflow recursion_limit
                        "current_output": diagnostic_data.get("agent_output_preview", error_msg[:500]),
                        "diagnostics": diagnostic_data,  # Full diagnostic report
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
                logger.info(f"📢 Emitted recursion_limit_hit event - stream will continue")

            # Publish error event for ALL errors EXCEPT RecursionError
            # RecursionError should NOT stop the stream - user wants to see the output
            if "recursion" not in error_msg.lower() and error_type != "GraphRecursionError":
                await event_bus.publish(channel, {
                    "type": "error",
                    "data": {
                        "error": error_msg,
                        "error_type": error_type,
                        "workflow_id": workflow.id,
                        "task_id": task_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })

            # ALWAYS emit complete event so UI knows workflow has finished
            # This ensures the spinner stops even on errors
            await event_bus.publish(channel, {
                "type": "complete",
                "data": {
                    "status": "error",
                    "error": error_msg,
                    "error_type": error_type,
                    "workflow_id": workflow.id,
                    "task_id": task_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            # Clear execution context for tool progress events
            clear_execution_context()

            return {
                "error": error_msg,
                "workflow_status": "FAILED",
                "task_id": task_id
            }

    async def _validate_and_init_tools(
        self,
        workflow: WorkflowProfile,
        channel: str,
        event_bus
    ) -> None:
        """
        Validate and pre-initialize tools before workflow execution.

        This ensures all tools (especially async ones like Playwright browser) are
        ready before the workflow starts, preventing mid-execution failures.

        Args:
            workflow: The workflow profile to validate
            channel: SSE channel for event publishing
            event_bus: Event bus for publishing progress

        Raises:
            ValueError: If any tools are missing or fail to initialize
        """
        logger.info("Starting tool validation and pre-initialization...")

        # Extract all tools from workflow nodes
        nodes = workflow.configuration.get("nodes", [])
        all_tools = set()
        browser_needed = False

        for node in nodes:
            # Skip control nodes
            node_type = node.get("type", "default")
            if node_type in ['START_NODE', 'END_NODE', 'CHECKPOINT_NODE', 'OUTPUT_NODE',
                            'CONDITIONAL_NODE', 'APPROVAL_NODE']:
                continue

            # Get tools from node config
            node_config = node.get("config", {})
            native_tools = node_config.get("native_tools", [])
            mcp_tools = node_config.get("mcp_tools", [])
            cli_tools = node_config.get("cli_tools", [])
            custom_tools = node_config.get("custom_tools", [])

            # SAFETY: Filter out enable_memory and enable_rag - they're config flags, not tools
            # This handles old workflows saved before the frontend fix
            native_tools = [t for t in native_tools if t not in ['enable_memory', 'enable_rag']]
            mcp_tools = [t for t in mcp_tools if t not in ['enable_memory', 'enable_rag']]
            cli_tools = [t for t in cli_tools if t not in ['enable_memory', 'enable_rag']]
            custom_tools = [t for t in custom_tools if t not in ['enable_memory', 'enable_rag']]

            # Collect all tools
            for tool in native_tools + mcp_tools + cli_tools + custom_tools:
                all_tools.add(tool)
                if tool == "browser":
                    browser_needed = True

        if not all_tools:
            logger.info("No tools required for this workflow")
            return

        logger.info(f"Workflow requires tools: {list(all_tools)}")

        # Publish validation progress
        await event_bus.publish(channel, {
            "type": "status",
            "data": {
                "status": "validating_tools",
                "message": f"Validating {len(all_tools)} tool(s)...",
                "tools": list(all_tools),
                "timestamp": datetime.utcnow().isoformat()
            }
        })

        # Get available tool names from native_tools
        from tools.native_tools import get_available_tool_names, TOOL_NAME_MAP
        available_native_tools = get_available_tool_names()

        # Get available custom tools from database
        from models.custom_tool import CustomTool
        from db.database import SessionLocal
        available_custom_tools = set()
        try:
            db = SessionLocal()
            custom_tools_in_db = db.query(CustomTool.tool_id).all()
            available_custom_tools = {t.tool_id for t in custom_tools_in_db}
            db.close()
            if available_custom_tools:
                logger.info(f"Found {len(available_custom_tools)} custom tools in database: {available_custom_tools}")
        except Exception as e:
            logger.warning(f"Could not query custom tools from database: {e}")

        # Combine native and custom tools for validation
        available_tools = list(available_native_tools) + list(available_custom_tools)

        # Apply legacy tool name mapping for backward compatibility
        # This allows old workflows/agents with names like "sequential_thinking" to work
        mapped_tools = set()
        for tool in all_tools:
            # Map old name to new name if it exists in the legacy map
            mapped_tool = TOOL_NAME_MAP.get(tool, tool)
            mapped_tools.add(mapped_tool)
            if tool != mapped_tool:
                logger.info(f"Mapped legacy tool name '{tool}' -> '{mapped_tool}'")

        # Check if all requested tools (after mapping) are available
        missing_tools = []
        for tool in mapped_tools:
            if tool not in available_tools:
                missing_tools.append(tool)

        if missing_tools:
            error_msg = f"Missing tools: {missing_tools}. Available tools: {available_tools}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info("✓ All requested tools are available in registry")

        # Pre-initialize Playwright browser if needed
        if browser_needed:
            logger.info("Browser tools requested - pre-initializing Playwright...")

            await event_bus.publish(channel, {
                "type": "status",
                "data": {
                    "status": "initializing_browser",
                    "message": "Initializing Playwright browser (this may take a few seconds)...",
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            try:
                from tools.native_tools import load_playwright_tools

                # This will initialize the browser and return the toolkit
                browser_tools = await load_playwright_tools()

                if not browser_tools:
                    raise ValueError("Playwright browser initialization returned no tools")

                logger.info(f"✓ Playwright browser initialized successfully ({len(browser_tools)} tools)")

                await event_bus.publish(channel, {
                    "type": "status",
                    "data": {
                        "status": "browser_ready",
                        "message": f"Playwright browser ready ({len(browser_tools)} tools available)",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })

            except Exception as e:
                error_msg = f"Failed to initialize Playwright browser: {str(e)}"
                logger.warning(error_msg)
                logger.warning("Browser tools will not be available for this workflow")
                logger.warning("To enable browser tools, run: playwright install chromium")

                # Non-fatal: notify user but continue workflow without browser tools
                await event_bus.publish(channel, {
                    "type": "warning",
                    "data": {
                        "message": "Browser tools unavailable - Playwright failed to initialize",
                        "details": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })

        # All tools validated and ready
        logger.info("✓ Tool validation complete - all tools ready")
        await event_bus.publish(channel, {
            "type": "status",
            "data": {
                "status": "tools_validated",
                "message": "All tools validated and ready",
                "timestamp": datetime.utcnow().isoformat()
            }
        })
