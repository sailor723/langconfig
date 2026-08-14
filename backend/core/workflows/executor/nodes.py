# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Node executor factory mixin: creates per-node executor functions for the workflow graph.

Extracted from the former monolithic executor.py.
"""

import json
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage

from .shared import INTERRUPT_AVAILABLE, SimpleWorkflowState, logger


class _WorkflowNodesMixin:
    def _create_node_executor(
        self,
        node_id: str,
        agent_type: str,
        node_data: Dict[str, Any]
    ):
        """
        Create an executor function for a node.

        This function will be called by LangGraph when executing the node.
        """
        # Handle control nodes (START_NODE and END_NODE are filtered out in _build_graph_from_workflow)
        if agent_type in ['CHECKPOINT_NODE', 'OUTPUT_NODE', 'CONDITIONAL_NODE', 'APPROVAL_NODE', 'LOOP_NODE']:
            return self._create_control_node_executor(node_id, agent_type, node_data)

        # Handle TOOL_NODE (direct tool execution)
        if agent_type == 'TOOL_NODE':
            return self._create_tool_node_executor(node_id, node_data)

        # Handle LLM_NODE (simple direct LLM call, no tools/agents)
        if agent_type == 'LLM_NODE':
            return self._create_llm_node_executor(node_id, node_data)

        async def node_executor(state: SimpleWorkflowState, config: dict = None) -> Dict[str, Any]:
            """Execute a single node in the workflow."""
            # Get the actual display label from node_data if available
            node_label = node_data.get("data", {}).get("label")
            # Convert agent_type to human-readable name as fallback
            display_name = node_label or agent_type.replace('_', ' ').title()
            logger.info(f"[{display_name}] Executing agent (node: {node_id})")

            try:
                # Get agent configuration from node data
                agent_config = node_data.get("config", {})
                logger.info(f"[{display_name}] RAW node_data keys: {list(node_data.keys())}")
                logger.info(f"[{display_name}] RAW agent_config keys: {list(agent_config.keys())}")
                logger.info(f"[{display_name}] RAW agent_config.custom_tools: {agent_config.get('custom_tools', 'NOT_FOUND')}")
                # Get model with fallback - treat "none" as missing (control nodes use this)
                model = agent_config.get("model")
                if not model or model == "none":
                    # Use the app-wide default model (root .env DEFAULT_MODEL)
                    # instead of a hardcoded one.
                    try:
                        from config import settings as app_settings
                        model = app_settings.default_model or "gpt-4o-mini"
                    except Exception:
                        model = "gpt-4o-mini"  # last resort
                temperature = agent_config.get("temperature", 0.7)
                system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")

                # Get current messages from state
                messages = state.get("messages", [])

                # Get the user's query
                query = state.get("query", "")

                # Check if we're in a loop iteration (LOOP_NODE sets these in state)
                loop_iteration = state.get("loop_iteration", 0)
                is_loop_continuation = loop_iteration > 0 and messages

                # If continuing a loop, inject continuation prompt so agent knows to pick up where it left off
                if is_loop_continuation:
                    continuation_msg = HumanMessage(content=f"""[LOOP ITERATION {loop_iteration + 1}]

Continue working on the original task. Here's what you need to know:
- Original request: {query}
- You have access to the file system and can see changes from previous iterations
- Review what was accomplished and continue from where you left off
- If the task is complete, indicate completion in your response

Continue:""")
                    messages = list(messages) + [continuation_msg]
                    logger.info(f"[{display_name}] Injected loop continuation message for iteration {loop_iteration + 1}")

                logger.info(f"[{display_name}] ===== NODE START =====")
                logger.info(f"[{display_name}] Received {len(messages)} messages from previous nodes")
                logger.info(f"[{display_name}] Query: {query[:100] if query else 'None'}...")

                # Log received message types for debugging context passing
                if messages:
                    msg_summary = {}
                    for msg in messages:
                        msg_type = msg.__class__.__name__
                        msg_summary[msg_type] = msg_summary.get(msg_type, 0) + 1
                    logger.info(f"[{display_name}] Message breakdown: {msg_summary}")
                    # Log last message preview
                    last_msg = messages[-1]
                    last_content = str(last_msg.content)[:200] if hasattr(last_msg, 'content') else 'N/A'
                    logger.info(f"[{display_name}] Last message ({last_msg.__class__.__name__}): {last_content}...")
                else:
                    logger.warning(f"[{display_name}] No messages received from previous nodes!")

                # Collect multimodal attachments BEFORE creating initial message
                # Combine workflow-level attachments with agent-specific attachments
                workflow_attachments = state.get("workflow_attachments", []) or []
                agent_attachments = agent_config.get("attachments", []) or []
                all_attachments = workflow_attachments + agent_attachments

                # If no messages yet, create initial message from user's query
                # Use multimodal message if attachments exist
                if not messages and query:
                    if all_attachments:
                        # DEBUG: Log attachment data structure
                        for i, att in enumerate(all_attachments):
                            data_preview = att.get('data', '')[:50] if att.get('data') else 'NO_DATA'
                            url_preview = att.get('url', '')[:50] if att.get('url') else 'NO_URL'
                            logger.info(f"[{display_name}] Attachment {i}: type={att.get('type')}, mime={att.get('mime_type')}, data_preview={data_preview}, url_preview={url_preview}")

                        # Create multimodal message with attachments
                        from core.agents.multimodal import create_multimodal_message
                        messages = [create_multimodal_message(query, all_attachments)]
                        logger.info(f"[{display_name}] Created multimodal HumanMessage with {len(all_attachments)} attachments")
                    else:
                        messages = [HumanMessage(content=query)]
                        logger.info(f"[{display_name}] Created initial HumanMessage from query")

                # Create agent for this node using AgentFactory
                # Build agent_config dict matching AgentFactory.create_agent() API
                mcp_tools_list = agent_config.get("mcp_tools", [])
                cli_tools_list = agent_config.get("cli_tools", [])
                custom_tools_list = agent_config.get("custom_tools", [])

                logger.info(f"[{display_name}] Agent config - MCP tools: {mcp_tools_list}, CLI tools: {cli_tools_list}, Custom tools: {custom_tools_list}")

                # DIAGNOSTIC: Log if web_search appears unexpectedly
                if "web_search" in mcp_tools_list or "web" in mcp_tools_list:
                    logger.warning(f"⚠️  [{display_name}] HAS WEB_SEARCH TOOL - This may be unexpected!")
                    logger.warning(f"   Full agent_config keys: {list(agent_config.keys())}")
                    logger.warning(f"   mcp_tools from config: {agent_config.get('mcp_tools', [])}")

                full_agent_config = {
                    "model": model,
                    "temperature": temperature,
                    "system_prompt": system_prompt,
                    # Source of truth for built-in tools
                    "native_tools": agent_config.get("native_tools", []),
                    # Legacy/auxiliary tool groups
                    "mcp_tools": mcp_tools_list,
                    "cli_tools": cli_tools_list,
                    "custom_tools": custom_tools_list,
                    "enable_memory": agent_config.get("enable_memory", False),
                    # Frontend saves memory as "enable_long_term_memory" — pass both for compatibility
                    "enable_long_term_memory": agent_config.get("enable_long_term_memory", False),
                    "enable_rag": agent_config.get("enable_rag", False),
                    "max_tokens": agent_config.get("max_tokens"),
                    # Add middleware configuration if present (LangChain 1.0)
                    "middleware": agent_config.get("middleware", []),
                    # Workflow context for file organization
                    "workflow_id": state.get("workflow_id"),
                    "workflow_name": state.get("workflow_name"),
                    "execution_id": state.get("execution_id"),
                    # Custom output path for file writes (per-workflow configuration)
                    "custom_output_path": state.get("custom_output_path"),
                    # Multimodal input configuration
                    "enable_multimodal_input": agent_config.get("enable_multimodal_input", False),
                    "supported_input_types": agent_config.get("supported_input_types", ["image"]),
                    # HITL/Guardrails configuration (preserved from agent template)
                    "guardrails": agent_config.get("guardrails", {}),
                    "interrupt_before": agent_config.get("interrupt_before", []),
                }


                # Add attachments to agent config (already collected above)
                if all_attachments:
                    full_agent_config["attachments"] = all_attachments
                    logger.info(f"[{display_name}] Multimodal attachments: {len(all_attachments)} total ({len(workflow_attachments)} workflow + {len(agent_attachments)} agent)")

                # Build agent context for file metadata tracking
                agent_context = {
                    "agent_label": display_name,
                    "agent_type": agent_type,
                    "node_id": node_id,
                    "original_query": query,
                }

                # Emit agent context event for debugging (shows what agent has access to)
                from core.workflows.events.progress import emit_agent_context
                all_tools = (
                    agent_config.get("native_tools", []) +
                    mcp_tools_list + cli_tools_list + custom_tools_list
                )
                await emit_agent_context(
                    agent_label=display_name,
                    node_id=node_id,
                    system_prompt=system_prompt,
                    tools=all_tools,
                    attachments=all_attachments,
                    input_messages=messages,
                    model_config={
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": agent_config.get("max_tokens"),
                        "enable_memory": agent_config.get("enable_memory", False),
                        "enable_rag": agent_config.get("enable_rag", False),
                    },
                    metadata={"query": query[:200] if query else None}
                )

                # Shared setup: MCP manager and vector store
                from services.mcp_manager import get_mcp_manager
                from services.llama_config import get_vector_store

                mcp_manager = await get_mcp_manager()

                # Get vector store for RAG or Memory (if project_id available and either enabled)
                vector_store = None
                project_id_val = state.get("project_id")
                enable_rag = agent_config.get("enable_rag", False)
                enable_memory = (
                    agent_config.get("enable_memory", False) or
                    agent_config.get("enable_long_term_memory", False)
                )

                if project_id_val and (enable_rag or enable_memory):
                    try:
                        vector_store = get_vector_store(project_id_val)
                        logger.info(f"[Node: {node_id}] ✓ Vector store initialized (enable_rag={enable_rag}, enable_memory={enable_memory})")
                    except Exception as e:
                        logger.warning(f"[Node: {node_id}] Could not load vector store: {e}")

                # Check if this should be a DeepAgent (based on config flag OR if subagents exist)
                use_deepagents = agent_config.get("use_deepagents", False)
                subagents_list = agent_config.get("subagents", [])
                # Auto-enable DeepAgents if subagents are configured
                if subagents_list and not use_deepagents:
                    logger.info(f"[{display_name}] Auto-enabling DeepAgents (subagents configured)")
                    use_deepagents = True
                logger.info(f"[{display_name}] DeepAgent check: use_deepagents={use_deepagents}, subagents={len(subagents_list)}")

                if use_deepagents:
                    logger.info(f"[{display_name}] Creating DeepAgent with harness")

                    # Import DeepAgentFactory and models
                    from services.deepagent_factory import DeepAgentFactory
                    from models.deep_agent import DeepAgentConfig, MiddlewareConfig, SubAgentConfig

                    # Build DeepAgentConfig from agent_config
                    # Get native_tools from config (these are the main tools like web_search, file ops, etc.)
                    native_tools_list = list(agent_config.get("native_tools", []))
                    # Merge mcp_tools into native_tools for backward compatibility with older workflow versions
                    mcp_tools_list_extra = agent_config.get("mcp_tools", [])
                    if mcp_tools_list_extra:
                        for t_name in mcp_tools_list_extra:
                            if t_name not in native_tools_list:
                                native_tools_list.append(t_name)

                    logger.info(f"[{display_name}] Component tools for DeepAgent: {native_tools_list}")

                    # Resolve guardrails: prefer node config, fall back to original agent template
                    guardrails_config = agent_config.get("guardrails", {})
                    if not guardrails_config or not guardrails_config.get("interrupts"):
                        # Try to load from the original deep agent template
                        deep_agent_template_id = agent_config.get("deep_agent_template_id")
                        if deep_agent_template_id and isinstance(deep_agent_template_id, str) and deep_agent_template_id.startswith("custom_"):
                            try:
                                template_id = int(deep_agent_template_id.replace("custom_", ""))
                                from db.database import engine
                                from sqlalchemy import text
                                with engine.connect() as conn:
                                    row = conn.execute(
                                        text("SELECT config::text FROM deep_agent_templates WHERE id = :tid"),
                                        {"tid": template_id}
                                    ).fetchone()
                                    if row:
                                        template_config = json.loads(row[0])
                                        template_guardrails = template_config.get("guardrails", {})
                                        if template_guardrails and template_guardrails.get("interrupts"):
                                            guardrails_config = template_guardrails
                                            logger.info(f"[{display_name}] Loaded guardrails from template #{template_id}: {guardrails_config}")
                            except Exception as templ_err:
                                logger.warning(f"[{display_name}] Failed to load template guardrails: {templ_err}")

                    # Debug: Log raw subagent configuration before Pydantic parsing
                    raw_subagents = agent_config.get("subagents", [])
                    if raw_subagents:
                        logger.info(f"[{display_name}] Raw subagents from config ({len(raw_subagents)}): {raw_subagents}")
                        for i, sub in enumerate(raw_subagents):
                            logger.info(f"  Subagent {i}: type={sub.get('type')}, workflow_id={sub.get('workflow_id')}, name={sub.get('name')}")

                    deep_agent_config = DeepAgentConfig(
                        model=model,
                        temperature=temperature,
                        max_tokens=agent_config.get("max_tokens"),
                        system_prompt=system_prompt,
                        tools=[],
                        # IMPORTANT: Pass native_tools - these are the main agent tools (web_search, etc.)
                        native_tools=native_tools_list,
                        mcp_tools=mcp_tools_list,
                        cli_tools=cli_tools_list,
                        custom_tools=custom_tools_list,
                        use_deepagents=True,
                        # Middleware: Enable filesystem and todo_list by default for DeepAgents
                        middleware=[
                            MiddlewareConfig(
                                type="filesystem",
                                enabled=True,
                                config={}
                            ),
                            MiddlewareConfig(
                                type="todo_list",
                                enabled=True,
                                config={}
                            )
                        ],
                        # Subagents can be added from agent_config if specified
                        subagents=raw_subagents,
                        # IMPORTANT: Preserve HITL/guardrails from original agent config
                        guardrails=guardrails_config,
                        interrupt_before=agent_config.get("interrupt_before", []),
                    )

                    # Build context with completion criteria
                    context_with_criteria = ""
                    if query:
                        context_with_criteria = f"""Task: {query}

CRITICAL - STOP CONDITIONS:
You MUST stop executing once you have completed the task and provided your output.
Do NOT continue iterating after your final response.
Do NOT loop or repeat actions unnecessarily.
When your work is complete, deliver the final result and END."""

                    # Create DeepAgent
                    logger.info(f"[{display_name}] Creating DeepAgent with:")
                    logger.info(f"  - native_tools: {native_tools_list}")
                    logger.info(f"  - mcp_tools: {mcp_tools_list}")
                    logger.info(f"  - cli_tools: {cli_tools_list}")
                    logger.info(f"  - custom_tools: {custom_tools_list}")
                    logger.info(f"  - deep_agent_config.custom_tools will be: {custom_tools_list}")
                    agent_graph, tools, callbacks = await DeepAgentFactory.create_deep_agent(
                        config=deep_agent_config,
                        project_id=state.get("project_id", 0),
                        task_id=state.get("task_id", 0),
                        context=context_with_criteria,
                        mcp_manager=mcp_manager,
                        vector_store=vector_store,
                        workflow_id=state.get("workflow_id"),
                        custom_output_path=state.get("custom_output_path")
                    )

                    logger.info(f"[{display_name}] ✓ DeepAgent created with {len(tools)} tools: {[t.name for t in tools]}")

                else:
                    logger.info(f"[{display_name}] Creating regular agent")

                    # Build context with completion criteria
                    context_with_criteria = ""
                    if query:
                        context_with_criteria = f"""Task: {query}

CRITICAL - STOP CONDITIONS:
You MUST stop executing once you have completed the task and provided your output.
Do NOT continue iterating after your final response.
Do NOT loop or repeat actions unnecessarily.
When your work is complete, deliver the final result and END."""

                    # Create regular agent using AgentFactory
                    from core.agents.factory import AgentFactory

                    agent_graph, tools, callbacks = await AgentFactory.create_agent(
                        agent_config=full_agent_config,
                        project_id=state.get("project_id", 0),
                        task_id=state.get("task_id", 0),
                        context=context_with_criteria,
                        mcp_manager=mcp_manager,
                        vector_store=vector_store,
                        agent_context=agent_context
                    )

                # Execute the agent graph with messages
                if messages:
                    # Get the parent config to inherit callbacks
                    parent_config = config if config else {}

                    # Build agent config with callbacks from parent AND agent
                    thread_id = f"workflow_{state.get('workflow_id', 0)}_node_{node_id}"
                    agent_config_dict = {
                        "configurable": {"thread_id": thread_id},
                        # Pass node_id in metadata so callback handler can look up agent_label
                        "metadata": {"node_id": node_id},
                        # Also add as tag for fallback lookup
                        "tags": [node_id],
                        # RECURSION LIMIT: Default 300 accounts for middleware overhead (~6 steps per iteration)
                        "recursion_limit": agent_config.get("recursion_limit", 300)
                    }

                    # Combine callbacks from parent workflow AND agent factory
                    all_callbacks = []
                    if "callbacks" in parent_config:
                        parent_callbacks = parent_config["callbacks"]
                        if isinstance(parent_callbacks, list):
                            all_callbacks.extend(parent_callbacks)
                        else:
                            all_callbacks.append(parent_callbacks)

                    # Add agent's own callback handlers (for streaming events)
                    if callbacks:
                        if isinstance(callbacks, list):
                            all_callbacks.extend(callbacks)
                        else:
                            all_callbacks.append(callbacks)

                    if all_callbacks:
                        agent_config_dict["callbacks"] = all_callbacks
                        logger.debug(f"[{display_name}] Attached {len(all_callbacks)} callback handlers")

                    # RETRY LOOP for handling UNEXPECTED_TOOL_CALL (Gemini quirk)
                    # Gemini sometimes stops with "UNEXPECTED_TOOL_CALL" but doesn't execute the tool
                    # We catch this and force a retry with an explicit instruction
                    max_retries = 2

                    # CONTEXT WINDOW MANAGEMENT: Trim messages if they exceed model's context limit
                    # This prevents "context_length_exceeded" errors from crashing the workflow
                    try:
                        from services.context_window_manager import ContextWindowManager, ContextStrategy

                        model_name = agent_config.get("model", "gpt-4o")

                        # Get strategy from multiple possible sources (in priority order):
                        # 1. guardrails.compaction_strategy (DeepAgent UI)
                        # 2. context_management_strategy (AgentTemplate)
                        # 3. context_mode (NodeConfigPanel)
                        guardrails = agent_config.get("guardrails", {})
                        compaction_strategy = guardrails.get("compaction_strategy", "none") if guardrails else "none"

                        # Map DeepAgent compaction_strategy to ContextStrategy
                        compaction_to_strategy = {
                            "none": "smart",  # Default to smart when no compaction
                            "trim_messages": "recent",
                            "summarization": "summary",
                            "filter_custom": "quarantine",
                        }

                        # Priority: guardrails.compaction_strategy > context_management_strategy > context_mode
                        if compaction_strategy and compaction_strategy != "none":
                            strategy_name = compaction_to_strategy.get(compaction_strategy, "smart")
                        else:
                            strategy_name = agent_config.get("context_management_strategy") or agent_config.get("context_mode", "smart")

                        strategy_map = {
                            "recent": ContextStrategy.RECENT,
                            "smart": ContextStrategy.SMART,
                            "full": ContextStrategy.FULL,
                            "summary": ContextStrategy.SUMMARY,
                            "quarantine": ContextStrategy.QUARANTINE,
                        }
                        strategy = strategy_map.get(strategy_name.lower(), ContextStrategy.SMART)

                        # Get max tokens from guardrails.token_limits or direct config
                        token_limits = guardrails.get("token_limits", {}) if guardrails else {}
                        max_context_tokens = (
                            token_limits.get("max_total_tokens") or
                            agent_config.get("max_context_tokens")
                        )

                        context_manager = ContextWindowManager(
                            model_name=model_name,
                            max_tokens=max_context_tokens,
                            strategy=strategy
                        )

                        original_token_count = context_manager.count_tokens(messages)

                        # Only process if messages exist and might exceed limits (80% threshold)
                        if original_token_count > context_manager.available_context_tokens * 0.8:
                            logger.warning(
                                f"[{display_name}] Context nearing limit: {original_token_count} tokens "
                                f"(limit: {context_manager.available_context_tokens}, strategy: {strategy.value})"
                            )

                            # Apply configured trimming strategy
                            current_messages = context_manager.apply_strategy(messages, strategy)
                            trimmed_token_count = context_manager.count_tokens(current_messages)

                            logger.info(
                                f"[{display_name}] Context managed: {original_token_count} → {trimmed_token_count} tokens "
                                f"({len(messages)} → {len(current_messages)} messages)"
                            )
                        else:
                            current_messages = messages

                    except ImportError:
                        logger.debug(f"[{display_name}] Context window manager not available, using messages as-is")
                        current_messages = messages
                    except Exception as e:
                        logger.warning(f"[{display_name}] Context management failed: {e}, using messages as-is")
                        current_messages = messages

                    for attempt in range(max_retries + 1):
                        if attempt > 0:
                            logger.warning(f"[{display_name}] Retry attempt {attempt}/{max_retries} due to UNEXPECTED_TOOL_CALL")

                        # WORKFLOW CONVERSATION MEMORY: Load previous messages from DB
                        # Deep agent & regular agent: load stored conversation history
                        thread_id = agent_config_dict.get("configurable", {}).get("thread_id", "")
                        if thread_id and current_messages:
                            try:
                                from db.database import engine as mem_engine
                                from sqlalchemy import text as mem_text
                                import json as mem_json
                                with mem_engine.connect() as conn:
                                    row = conn.execute(
                                        mem_text("SELECT CAST(messages AS text) FROM workflow_conversations WHERE thread_id = :tid"),
                                        {"tid": thread_id}
                                    ).fetchone()
                                    if row and row[0]:
                                        stored_msgs = mem_json.loads(row[0])
                                        # Filter out messages already in current_messages
                                        existing = {str(m.content) for m in current_messages if hasattr(m, 'content')}
                                        unique_prev = [m for m in stored_msgs if m.get("content") not in existing]
                                        if unique_prev:
                                            from langchain_core.messages import HumanMessage as _HM, AIMessage as _AM, ToolMessage as _TM
                                            restored = []
                                            for m in unique_prev:
                                                role = m.get("role", "user")
                                                content = m.get("content", "")
                                                if role == "assistant" or role == "ai":
                                                    restored.append(_AM(content=content))
                                                elif role == "tool":
                                                    restored.append(_TM(content=content, tool_call_id=m.get("tool_call_id", "")))
                                                else:
                                                    restored.append(_HM(content=content))
                                            current_messages = list(restored) + list(current_messages)
                                            logger.info(f"[{display_name}] Loaded {len(restored)} msgs from conversation memory ({thread_id})")
                            except Exception as mem_err:
                                logger.debug(f"[{display_name}] No conversation memory: {mem_err}")

                        # SAVE INPUT MESSAGES to conversation memory BEFORE agent runs
                        if thread_id:
                            try:
                                from db.database import engine as save_eng
                                from sqlalchemy import text as save_txt
                                import json as save_j
                                input_save = [{"role": "user" if hasattr(m, '__class__') and 'Human' in m.__class__.__name__ else "ai", "content": str(getattr(m, 'content', ''))} for m in current_messages if hasattr(m, 'content')]
                                with save_eng.connect() as c:
                                    c.execute(
                                        save_txt("INSERT INTO workflow_conversations (thread_id, messages, updated_at) VALUES (:tid, CAST(:msgs AS jsonb), NOW()) ON CONFLICT (thread_id) DO UPDATE SET messages = CAST(:msgs AS jsonb), updated_at = NOW()"),
                                        {"tid": thread_id, "msgs": save_j.dumps(input_save)}
                                    )
                                    c.commit()
                                logger.info(f"[{display_name}] Saved {len(input_save)} input msgs ({thread_id})")
                            except Exception as se:
                                logger.warning(f"[{display_name}] Failed to save input conv: {se}")

                        # Try astream_events() first for streaming, fall back to ainvoke() if streaming unsupported
                        response = None
                        try:
                            # Use astream_events() to enable LLM token streaming callbacks
                            # This allows on_chat_model_stream events to fire for real-time thinking
                            async for event in agent_graph.astream_events(
                                {"messages": current_messages},
                                config=agent_config_dict,
                                version="v2"
                            ):
                                # astream_events yields ALL events including LLM tokens and state updates
                                # We only care about the final state for the agent response
                                kind = event.get("event")
                                if kind == "on_chain_end" and event.get("name") == "LangGraph":
                                    # Extract final state from the agent completion event
                                    response = event.get("data", {}).get("output")
                                    # Debug: log response type for deep agent debugging
                                    if response is not None:
                                        rt = type(response).__name__
                                        logger.debug(f"[{display_name}] on_chain_end response type={rt}")
                                        if isinstance(response, dict):
                                            logger.debug(f"[{display_name}] response keys={list(response.keys())}")
                                # All other events (on_chat_model_stream, on_chain_start, etc.)
                                # are handled by the callback handler automatically
                        except Exception as stream_error:
                            # Streaming failed (e.g., OpenAI doesn't support streaming)
                            # Fall back to non-streaming execution
                            error_msg = str(stream_error)
                            if "stream" in error_msg.lower() or "unsupported" in error_msg.lower():
                                logger.warning(f"[{display_name}] Streaming not supported, falling back to non-streaming: {error_msg}")
                                # Use ainvoke() instead - no streaming but still works
                                response = await agent_graph.ainvoke(
                                    {"messages": current_messages},
                                    config=agent_config_dict
                                )
                            else:
                                # Different error - re-raise
                                raise

                        # Extract ONLY NEW AI messages from response
                        # The agent returns ALL messages (input + output), but LangGraph reducer
                        # appends them, so we only want the NEW messages not already in state
                        new_messages = []
                        all_response_messages = []

                        # CHECK FOR INTERRUPT: if response is None but agent has checkpointer,
                        # the graph may have been interrupted (HITL paused execution)
                        if response is None:
                            logger.info(f"[{display_name}] Response is None - checking for interrupt")
                            try:
                                # Check if agent graph was interrupted
                                agent_state = await agent_graph.aget_state(agent_config_dict)
                                if agent_state and agent_state.next:
                                    logger.info(f"[{display_name}] ✅ Agent INTERRUPTED! Next nodes: {agent_state.next}")
                                    
                                    # Extract tool calls from the last AI message
                                    tool_calls_data = []
                                    if agent_state.values:
                                        agent_messages = agent_state.values.get("messages", [])
                                        for msg in reversed(agent_messages):
                                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                                tool_calls_data = [
                                                    {"name": tc["name"], "args": tc["args"]}
                                                    for tc in msg.tool_calls
                                                ]
                                                break
                                    
                                    # Emit interrupt event to frontend
                                    try:
                                        from services.event_bus import get_event_bus
                                        wf_event_bus = get_event_bus()
                                        wf_id = state.get('workflow_id', 0)
                                        wf_task_id = state.get('task_id', 0)
                                        wf_channel = f"workflow:{wf_id}"
                                        await wf_event_bus.publish(wf_channel, {
                                            "type": "interrupt",
                                            "data": {
                                                "action_requests": tool_calls_data,
                                                "workflow_id": wf_id,
                                                "task_id": wf_task_id,
                                                "node_id": node_id,
                                                "agent_label": display_name,
                                                "timestamp": datetime.utcnow().isoformat()
                                            }
                                        })
                                        logger.info(f"[{display_name}] ✅ Emitted interrupt event ({len(tool_calls_data)} actions)")
                                    except Exception as pub_err:
                                        logger.warning(f"[{display_name}] Failed to emit interrupt event: {pub_err}")
                                    
                                    # Return empty result - workflow continues
                                    response = {"messages": []}
                                else:
                                    logger.info(f"[{display_name}] No interrupt detected (state.next is empty)")
                                    response = {"messages": []}
                            except Exception as state_err:
                                logger.warning(f"[{display_name}] Failed to check agent state: {state_err}")
                                response = {"messages": []}

                        if isinstance(response, dict) and "messages" in response:
                            all_response_messages = response["messages"]
                            # Find messages that weren't in the input
                            input_message_count = len(current_messages)

                            logger.debug(f"[{display_name}] Response has {len(all_response_messages)} messages, input had {input_message_count}")

                            # Safety check: ensure we don't slice beyond the list
                            if len(all_response_messages) > input_message_count:
                                new_messages = all_response_messages[input_message_count:]  # Only new messages
                            elif len(all_response_messages) == input_message_count:
                                # Agent returned same number of messages - might have modified existing ones
                                # Check if the last message is different
                                logger.warning(f"[{display_name}] Agent returned same message count ({input_message_count}), checking for modifications")
                                if all_response_messages and current_messages:
                                    last_response = all_response_messages[-1]
                                    last_input = current_messages[-1]
                                    if str(last_response.content) != str(last_input.content):
                                        new_messages = [last_response]
                                        logger.info(f"[{display_name}] Detected modified last message")
                            else:
                                # Response has fewer messages than input - something wrong
                                logger.warning(f"[{display_name}] Response has fewer messages ({len(all_response_messages)}) than input ({input_message_count})")

                        if not new_messages:
                            # Fallback: if no new messages detected, take last AI message
                            logger.warning(f"[{display_name}] No new messages detected, using fallback to get last AI message")
                            for msg in reversed(all_response_messages):
                                if hasattr(msg, '__class__') and 'AI' in msg.__class__.__name__:
                                    new_messages = [msg]
                                    logger.info(f"[{display_name}] Fallback found AI message: {str(msg.content)[:100]}...")
                                    break

                        # SAVE CONVERSATION MEMORY: Store messages for recall on next workflow run
                        if thread_id and all_response_messages:
                            try:
                                from db.database import engine as save_engine
                                from sqlalchemy import text as save_text
                                import json as save_json
                                
                                # Convert messages to serializable dicts
                                serialized = []
                                for m in all_response_messages:
                                    role = "user"
                                    if hasattr(m, '__class__'):
                                        cn = m.__class__.__name__
                                        if 'AI' in cn:
                                            role = "ai"
                                        elif 'Tool' in cn or 'tool' in cn:
                                            role = "tool"
                                        elif 'Human' in cn or 'human' in cn:
                                            role = "user"
                                    serialized.append({
                                        "role": role,
                                        "content": str(getattr(m, 'content', '')),
                                        "tool_call_id": getattr(m, 'tool_call_id', '') if hasattr(m, 'tool_call_id') else ''
                                    })
                                
                                with save_engine.connect() as conn:
                                    conn.execute(
                                        save_text("""
                                            INSERT INTO workflow_conversations (thread_id, messages, updated_at)
                                            VALUES (:tid, :msgs::jsonb, NOW())
                                            ON CONFLICT (thread_id) 
                                            DO UPDATE SET messages = :msgs::jsonb, updated_at = NOW()
                                        """),
                                        {"tid": thread_id, "msgs": save_json.dumps(serialized)}
                                    )
                                    conn.commit()
                                    logger.info(f"[{display_name}] Saved {len(serialized)} msgs to conversation memory ({thread_id})")
                            except Exception as save_err:
                                logger.debug(f"[{display_name}] Failed to save conversation: {save_err}")

                        # CHECK FOR UNEXPECTED_TOOL_CALL FAILURE
                        # If the last message has finish_reason='UNEXPECTED_TOOL_CALL' but NO tool calls were executed
                        # (meaning the agent stopped prematurely), we force a retry.
                        should_retry = False
                        if new_messages:
                            last_msg = new_messages[-1]
                            # Check response metadata for Gemini's specific error code
                            meta = getattr(last_msg, 'response_metadata', {})
                            finish_reason = meta.get('finish_reason')

                            # If Gemini says "UNEXPECTED_TOOL_CALL" but we didn't see a tool execution in the graph
                            # (Note: If tool WAS executed, the last message would be a ToolMessage or an AI message AFTER the tool)
                            if finish_reason == 'UNEXPECTED_TOOL_CALL':
                                logger.warning(f"[{display_name}] Detected UNEXPECTED_TOOL_CALL finish reason")

                                # Check if we actually have tool calls in the message
                                tool_calls = getattr(last_msg, 'tool_calls', [])
                                if not tool_calls:
                                    logger.warning(f"[{display_name}] Agent stopped with UNEXPECTED_TOOL_CALL but no tool_calls found. Retrying...")
                                    should_retry = True

                        # CHECK FOR FAKE IMAGE GENERATION (Hallucination)
                        # If the agent claims to have generated images but didn't call the tool
                        if not should_retry and new_messages:
                            last_msg = new_messages[-1]
                            last_content = str(last_msg.content) if hasattr(last_msg, 'content') else ""

                            # If the agent claims to have generated images but didn't call the tool
                            # We check for the specific marker [GENERATED IMAGES] which is in the system prompt
                            if "[GENERATED IMAGES]" in last_content and "image_generation" in str(agent_config.get("custom_tools", [])):
                                # Check if a tool was actually called in this turn
                                # We need to scan 'new_messages' for any ToolMessage or AIMessage with tool_calls
                                has_tool_calls = False
                                for msg in new_messages:
                                    if getattr(msg, 'tool_calls', []):
                                        has_tool_calls = True
                                        break
                                    if msg.__class__.__name__ == 'ToolMessage':
                                        has_tool_calls = True
                                        break

                                if not has_tool_calls:
                                    logger.warning(f"[{display_name}] Detected FAKE image generation (hallucination). Retrying...")
                                    should_retry = True
                                    retry_instruction = HumanMessage(content=
                                        "SYSTEM ERROR: You claimed to generate images but you did NOT call the 'image_generation' tool. "
                                        "You simply wrote a description. This is a failure. "
                                        "You MUST call the 'image_generation' tool to get a real URL. "
                                        "Try again and actually invoke the tool."
                                    )
                                    current_messages = list(all_response_messages) + [retry_instruction]
                                    continue

                        if should_retry and attempt < max_retries:
                            # Add a system/human message instructing the agent to fix its format
                            if not 'retry_instruction' in locals():
                                retry_instruction = HumanMessage(content=
                                    "SYSTEM ERROR: Your last response stopped with 'UNEXPECTED_TOOL_CALL'. "
                                    "You attempted to call a tool but the format was incorrect or not recognized. "
                                    "Please TRY AGAIN. Ensure you are using the correct tool calling format for 'image_generation'. "
                                    "Do not just describe the image - actually CALL the tool."
                                )
                            current_messages = list(all_response_messages) + [retry_instruction]
                            continue

                        # If we get here, we're done (success or max retries reached)
                        break

                else:
                    # Fallback: wrap response as AIMessage
                    new_messages = [AIMessage(content=str(response))]

                # Check for suspiciously short output (potential early termination)
                if new_messages:
                    last_content = ""
                    if hasattr(new_messages[-1], 'content'):
                        last_content = str(new_messages[-1].content)

                    # Warning conditions:
                    # 1. Output is very short (< 200 chars)
                    # 2. This is a downstream node (has previous messages)
                    # 3. Output contains meta-commentary keywords
                    is_short = len(last_content) < 200
                    is_downstream = len([m for m in messages if hasattr(m, '__class__') and 'AI' in m.__class__.__name__]) > 0
                    has_meta_commentary = any(keyword in last_content.lower() for keyword in [
                        '# executing', '# analysis', '# planning', 'based on the context provided',
                        'i will', 'i need to', 'let me'
                    ])

                    if is_short and is_downstream and has_meta_commentary:
                        warning_msg = (
                            f"⚠️ WARNING: {display_name} produced very short output ({len(last_content)} chars) "
                            f"that appears to be meta-commentary instead of actual content. "
                            f"This often indicates the agent's system prompt causes it to describe its task "
                            f"rather than execute it. Consider revising the system prompt to be more direct."
                        )
                        logger.warning(warning_msg)

                        # Emit warning event to frontend
                        from services.event_bus import get_event_bus
                        event_bus = get_event_bus()
                        channel = f"workflow:{state.get('workflow_id')}"
                        await event_bus.publish(channel, {
                            "type": "warning",
                            "data": {
                                "node": node_id,
                                "agent_label": display_name,
                                "warning_type": "short_output",
                                "message": f"{display_name} output may be incomplete (only {len(last_content)} characters)",
                                "suggestion": "Check the agent's system prompt - it may need to be more direct",
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        })

                    # ===== EMIT NODE COMPLETION WITH TOKEN & TOOL METRICS =====
                    # Extract token usage from the response messages
                    token_usage = None
                    tool_calls_info = []

                    for msg in new_messages:
                        # Extract token usage from response_metadata
                        if hasattr(msg, 'response_metadata') and msg.response_metadata:
                            metadata = msg.response_metadata
                            # OpenAI/Anthropic format
                            if 'usage' in metadata:
                                usage = metadata['usage']
                                token_usage = {
                                    'promptTokens': usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0),
                                    'completionTokens': usage.get('completion_tokens', 0) or usage.get('output_tokens', 0),
                                    'totalTokens': usage.get('total_tokens', 0),
                                }
                                if not token_usage['totalTokens']:
                                    token_usage['totalTokens'] = token_usage['promptTokens'] + token_usage['completionTokens']
                            # Google/LangChain format
                            elif 'usage_metadata' in metadata:
                                usage = metadata['usage_metadata']
                                token_usage = {
                                    'promptTokens': usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0),
                                    'completionTokens': usage.get('output_tokens', 0) or usage.get('completion_tokens', 0),
                                    'totalTokens': usage.get('total_tokens', 0),
                                }
                                if not token_usage['totalTokens']:
                                    token_usage['totalTokens'] = token_usage['promptTokens'] + token_usage['completionTokens']

                        # Extract tool call information
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_calls_info.append({
                                    'name': tc.get('name', 'unknown'),
                                    'id': tc.get('id', ''),
                                })

                    # Count tool results from earlier messages
                    tool_results_count = sum(1 for m in all_response_messages if hasattr(m, '__class__') and 'Tool' in m.__class__.__name__)

                    # Calculate estimated cost if we have token data
                    if token_usage:
                        try:
                            from lib.model_pricing import get_model_cost
                            cost = get_model_cost(model, token_usage['promptTokens'], token_usage['completionTokens'])
                            token_usage['costString'] = f"${cost:.6f}"
                        except Exception:
                            # Fallback cost estimation
                            estimated_cost = (token_usage['promptTokens'] * 0.000003) + (token_usage['completionTokens'] * 0.000015)
                            token_usage['costString'] = f"${estimated_cost:.6f}"

                    # Emit node_completed event with all metrics
                    try:
                        from services.event_bus import get_event_bus
                        event_bus = get_event_bus()
                        channel = f"workflow:{state.get('workflow_id')}"

                        completion_event = {
                            "type": "node_completed",
                            "data": {
                                "node_id": node_id,
                                "agent_label": display_name,
                                "model": model,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        }

                        if token_usage:
                            completion_event["data"]["tokenCost"] = token_usage

                        if tool_calls_info:
                            completion_event["data"]["toolCalls"] = tool_calls_info
                            completion_event["data"]["toolCallCount"] = len(tool_calls_info)

                        if tool_results_count:
                            completion_event["data"]["toolResultCount"] = tool_results_count

                        await event_bus.publish(channel, completion_event)
                        logger.debug(f"[{display_name}] Emitted node_completed event with token usage: {token_usage}")
                    except Exception as event_error:
                        logger.warning(f"[{display_name}] Failed to emit node_completed event: {event_error}")

                    logger.info(f"[{display_name}] Returning {len(new_messages)} new messages to be added to state")

                    # Log message content preview for debugging context passing
                    for i, msg in enumerate(new_messages):
                        msg_type = msg.__class__.__name__
                        content_preview = str(msg.content)[:150] if hasattr(msg, 'content') else 'N/A'
                        logger.debug(f"[{display_name}] Message {i+1}/{len(new_messages)} ({msg_type}): {content_preview}...")

                    # Extract critic output if this is a critic node
                    # We check if 'critic' is in the display_name or agent_type
                    current_critic_output = None
                    if "critic" in display_name.lower() or "critic" in agent_type.lower():
                        if new_messages:
                            # Use the last contentful message from the critic
                            for msg in reversed(new_messages):
                                content = str(msg.content)
                                if content and len(content) > 10:
                                    current_critic_output = content
                                    logger.info(f"[{display_name}] Captured critic_output: {current_critic_output[:100]}...")
                                    break

                    # Return new messages (reducer will append them)
                    # Return new messages (reducer will append them)
                    update = {
                        "messages": new_messages,
                        "current_node": node_id,
                        "agent_type": agent_type,
                        "last_agent_type": agent_type
                    }

                    if current_critic_output:
                        update["critic_output"] = current_critic_output

                    return update
                else:
                    logger.warning(f"[Node: {node_id}] No messages to process")
                    return {
                        "messages": [],  # Always include messages key for reducer
                        "current_node": node_id,
                        "agent_type": agent_type,
                        "last_agent_type": agent_type
                    }

            except Exception as e:
                logger.error(f"[Node: {node_id}] Execution failed: {e}", exc_info=True)
                return {
                    "messages": [],  # Always include messages key for reducer
                    "error_message": str(e),
                    "current_node": node_id,
                    "agent_type": agent_type,
                    "last_agent_type": agent_type
                }

        return node_executor

    def _create_control_node_executor(
        self,
        node_id: str,
        control_type: str,
        node_data: Dict[str, Any]
    ):
        """
        Create an executor function for control nodes.

        Control nodes handle workflow coordination, state management, and output formatting.
        """
        async def control_node_executor(state: SimpleWorkflowState) -> Dict[str, Any]:
            """Execute a control node."""
            logger.info(f"[Control Node: {node_id}] Executing {control_type}")

            try:
                if control_type == 'CHECKPOINT_NODE':
                    # Explicit checkpoint - state is automatically persisted by LangGraph
                    # Note: Only works if checkpointer is configured during compilation
                    checkpoint_data = {
                        "step": node_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "message_count": len(state.get("messages", []))
                    }
                    logger.info(f"[CHECKPOINT_NODE] Checkpoint marker set: {checkpoint_data}")
                    logger.debug(f"[CHECKPOINT_NODE] Note: Actual persistence depends on checkpointer configuration")

                    # Checkpoint state is already persisted by the LangGraph checkpointer;
                    # the legacy execution_events emitter module no longer exists, so
                    # nothing extra is emitted here.
                    return {
                        "current_step": node_id,
                        "workflow_status": "CHECKPOINTED",
                        "checkpoint_metadata": checkpoint_data
                    }

                elif control_type == 'OUTPUT_NODE':
                    # Format and return output
                    messages = state.get("messages", [])
                    message_count = len(messages)

                    output = {
                        "formatted_output": {
                            "messages": [msg.content if hasattr(msg, 'content') else str(msg) for msg in messages],
                            "workflow_status": state.get("workflow_status", "COMPLETED"),
                            "steps_completed": state.get("current_step", "unknown")
                        }
                    }

                    logger.info(f"[OUTPUT_NODE] Output formatted successfully ({message_count} messages)")
                    if message_count == 0:
                        logger.warning(f"[OUTPUT_NODE] No messages in output")

                    return {
                        "current_step": node_id,
                        **output
                    }

                elif control_type == 'CONDITIONAL_NODE':
                    # Conditional routing based on state evaluation.
                    # NOTE: the builder wires conditional edges by EDGE LABEL
                    # ("true"/"false"/"default" -> target node), so this node
                    # writes the route KEY into state.conditional_route, not a
                    # target node id (routing to node ids was the old, broken
                    # behavior - see LOOP_NODE for the same label-key pattern).
                    config = node_data.get("config", {})
                    # Support both "condition" and "condition_expression" keys
                    condition_expr = (config.get("condition", "") or config.get("condition_expression", "")).strip()

                    logger.info(f"[CONDITIONAL_NODE] Evaluating condition: '{condition_expr}'")

                    # Extract decision from recent messages if not yet in state
                    # Critic agents output **[DECISION: PASS]** or **[DECISION: REVISE]** markers
                    # which get merged into state.messages by the LangGraph reducer
                    if "decision" not in state:
                        import re
                        messages = state.get("messages", [])
                        for msg in reversed(messages):
                            content = str(msg.content) if hasattr(msg, 'content') else str(msg)
                            match = re.search(r'\[DECISION:\s*(PASS|REVISE)\]', content)
                            if match:
                                state["decision"] = match.group(1)
                                logger.info(f"[CONDITIONAL_NODE] Extracted decision from messages: {state['decision']}")
                                break

                    # Capture for durable merge: LangGraph only persists keys a
                    # node RETURNS - mutating the passed state dict alone is
                    # discarded after the node finishes.
                    decision_value = state.get("decision")

                    # Default route if no condition specified
                    if not condition_expr:
                        logger.warning(f"[CONDITIONAL_NODE] No condition expression provided - using default route")
                        return {
                            "current_step": node_id,
                            "conditional_route": "default",
                            "decision": decision_value,
                        }

                    # Reflection-loop guard: track iterations through condition nodes
                    # to prevent infinite Writer→Critic→Conditional→Writer loops
                    condition_hits = state.get("condition_hits", {})
                    condition_count = condition_hits.get(node_id, 0)
                    condition_count += 1
                    condition_hits[node_id] = condition_count

                    MAX_CONDITION_ITERATIONS = 5  # Max reflection/critique rounds
                    if condition_count > MAX_CONDITION_ITERATIONS:
                        # Force forward exit (PASS route) to break infinite critique loops
                        logger.warning(
                            f"[CONDITIONAL_NODE] Max iterations ({MAX_CONDITION_ITERATIONS}) reached. "
                            f"Forcing exit via 'true' route."
                        )
                        return {
                            "current_step": node_id,
                            "conditional_route": "true",
                            "condition_result": True,
                            "condition_hits": condition_hits,
                            "decision": decision_value,
                            "forced_exit": True
                        }

                    # Evaluate condition expression safely
                    try:
                        # Build safe evaluation context with state values
                        eval_context = {
                            "state": state,
                            # Common helper functions
                            "len": len,
                            "str": str,
                            "int": int,
                            "float": float,
                            "bool": bool,
                            "list": list,
                            "dict": dict,
                            # Math operations
                            "abs": abs,
                            "min": min,
                            "max": max,
                            "sum": sum,
                        }

                        # Evaluate the condition expression
                        # Supports expressions like: state.get("retry_count", 0) < 3
                        #                           state.get("validation_passed") == True
                        #                           len(state.get("messages", [])) > 0
                        # AST-validated safe evaluation (no raw eval of the
                        # user string — object-graph escapes are rejected).
                        from core.utils.safe_eval import safe_eval_expression
                        result = safe_eval_expression(condition_expr, eval_context)

                        # Convert to boolean
                        condition_met = bool(result)

                        logger.info(f"[CONDITIONAL_NODE] Condition '{condition_expr}' evaluated to: {condition_met}")

                        # Determine route based on condition result.
                        # The builder maps edge labels ("true"/"false") to target
                        # nodes, so we emit the route KEY (not a node id) here.
                        if condition_met:
                            route_key = "true"
                        else:
                            route_key = "false"

                        logger.debug(f"[CONDITIONAL_NODE] Routing via '{route_key}' (condition: {condition_met})")

                        return {
                            "current_step": node_id,
                            "conditional_route": route_key,
                            "condition_result": condition_met,
                            "condition_hits": condition_hits,
                            "decision": decision_value,
                        }

                    except Exception as e:
                        logger.error(f"[CONDITIONAL_NODE] Failed to evaluate condition '{condition_expr}': {e}")
                        logger.warning(f"[CONDITIONAL_NODE] Using fallback 'default' route")
                        return {
                            "current_step": node_id,
                            "conditional_route": "default",
                            "decision": decision_value,
                            "condition_error": str(e)
                        }

                elif control_type == 'LOOP_NODE':
                    # Loop control with iteration tracking
                    config = node_data.get("config", {})
                    max_iterations = config.get("max_iterations", 10)
                    exit_condition = config.get("exit_condition", "").strip()
                    loop_target = config.get("loop_target")  # Node to loop back to

                    # Initialize loop state if not present
                    loop_iterations = state.get("loop_iterations", {})
                    current_iteration = loop_iterations.get(node_id, 0)

                    logger.info(f"[LOOP_NODE] Iteration {current_iteration + 1}/{max_iterations}")

                    # Increment iteration count
                    current_iteration += 1
                    loop_iterations[node_id] = current_iteration

                    # Check exit conditions
                    should_exit = False
                    exit_reason = None

                    # 1. Check max iterations
                    if current_iteration >= max_iterations:
                        should_exit = True
                        exit_reason = f"max_iterations ({max_iterations}) reached"
                        logger.info(f"[LOOP_NODE] Exiting loop: {exit_reason}")

                    # 2. Check exit condition expression (if provided)
                    elif exit_condition:
                        try:
                            # Build safe evaluation context
                            eval_context = {
                                "state": state,
                                "iteration": current_iteration,
                                "max_iterations": max_iterations,
                                # Helper functions
                                "len": len,
                                "str": str,
                                "int": int,
                                "float": float,
                                "bool": bool,
                                "abs": abs,
                                "min": min,
                                "max": max,
                                "sum": sum,
                            }

                            # Evaluate exit condition (AST-validated safe eval)
                            from core.utils.safe_eval import safe_eval_expression
                            result = safe_eval_expression(exit_condition, eval_context)
                            should_exit = bool(result)

                            if should_exit:
                                exit_reason = f"exit_condition '{exit_condition}' evaluated to True"
                                logger.info(f"[LOOP_NODE] Exiting loop: {exit_reason}")

                        except Exception as e:
                            logger.error(f"[LOOP_NODE] Failed to evaluate exit condition '{exit_condition}': {e}")
                            # Don't exit on error, continue looping (safer than infinite loop)
                            should_exit = False

                    # Determine routing
                    if should_exit:
                        loop_route = "exit"
                        logger.debug(f"[LOOP_NODE] Routing to exit (reason: {exit_reason})")
                    else:
                        loop_route = "continue"
                        logger.debug(f"[LOOP_NODE] Routing to continue (iteration {current_iteration})")

                    return {
                        "current_step": node_id,
                        "loop_iterations": loop_iterations,
                        "loop_route": loop_route,
                        "loop_iteration": current_iteration,
                        "loop_should_exit": should_exit,
                        "loop_exit_reason": exit_reason
                    }

                elif control_type == 'APPROVAL_NODE':
                    # Human-in-the-loop approval gate
                    approval_context = {
                        "node_id": node_id,
                        "current_step": state.get("current_step"),
                        "message_count": len(state.get("messages", []))
                    }
                    logger.info(f"[APPROVAL_NODE] Workflow paused for human approval: {approval_context}")
                    if INTERRUPT_AVAILABLE:
                        decision = interrupt({
                            "type": "approval_required",
                            "context": approval_context,
                            "message": "Please review and approve before continuing."
                        })
                        if decision == "reject":
                            return {
                                "current_step": node_id,
                                "workflow_status": "REJECTED",
                                "error_message": "Rejected by human reviewer"
                            }
                        return {
                            "current_step": node_id,
                            "workflow_status": "APPROVED"
                        }
                    else:
                        logger.debug(f"[APPROVAL_NODE] This node requires 'interrupt_before' compilation config")
                        return {
                            "current_step": node_id,
                            "workflow_status": "AWAITING_APPROVAL",
                            "requires_human_approval": True,
                            "approval_context": approval_context
                        }

                else:
                    valid_types = ['CHECKPOINT_NODE', 'OUTPUT_NODE', 'CONDITIONAL_NODE', 'APPROVAL_NODE', 'LOOP_NODE']
                    logger.error(
                        f"[Control Node: {node_id}] Unknown control type: '{control_type}'. "
                        f"Valid types: {valid_types}"
                    )
                    return {
                        "current_step": node_id,
                        "error_message": f"Unknown control node type: {control_type}"
                    }

            except Exception as e:
                logger.error(f"[Control Node: {node_id}] Execution failed: {e}", exc_info=True)
                return {
                    "error_message": str(e),
                    "current_step": node_id,
                    "workflow_status": "FAILED"
                }

        return control_node_executor

    def _create_tool_node_executor(
        self,
        node_id: str,
        node_data: Dict[str, Any]
    ):
        """
        Create an executor for TOOL_NODE that directly executes a tool.

        Args:
            node_id: Unique node identifier
            node_data: Node configuration including tool_type, tool_id, and tool_params

        Returns:
            Async function that executes the tool
        """
        async def tool_node_executor(state: SimpleWorkflowState, config: dict = None) -> Dict[str, Any]:
            """Execute a tool node."""
            from core.workflows.nodes import execute_tool_node

            # Get tool configuration from node_data
            node_config = node_data.get("config", {})

            logger.info(f"[TOOL_NODE {node_id}] Executing with config: {node_config}")

            # Call the tool execution function
            result = await execute_tool_node(
                state=state,
                config=config,
                node_tool_config=node_config
            )

            return {
                "current_step": node_id,
                **result
            }

        return tool_node_executor

    def _create_llm_node_executor(
        self,
        node_id: str,
        node_data: Dict[str, Any]
    ):
        """
        Create an executor for LLM_NODE — a simple direct LLM call without tools or agent middleware.

        Properties configured in the frontend:
            - prompt: System prompt / instruction text
            - llm: Which model to use
            - input: How data flows in (query or previous node's output)
            - output: What the node produces (appended to messages)

        In LangGraph terms, this is the simplest possible node:
        a RunnableLambda that invokes a chat model with a system prompt + input.
        """
        agent_config = node_data.get("config", {})
        model_name = agent_config.get("model")
        if not model_name:
            # Fall back to the app-wide default model instead of a hardcoded one
            try:
                from config import settings as app_settings
                model_name = app_settings.default_model
            except Exception:
                model_name = "gpt-4o-mini"
        temperature = agent_config.get("temperature", 0.7)
        system_prompt = agent_config.get(
            "system_prompt",
            "You are a helpful assistant. Respond to the user's input concisely."
        )

        async def llm_node_executor(state: SimpleWorkflowState, config: dict = None) -> Dict[str, Any]:
            """Execute a direct LLM call — no tools, no agent, just prompt → model → response."""
            node_label = node_data.get("data", {}).get("label") or "LLM"
            logger.info(f"[{node_label} (LLM_NODE)] Invoking model={model_name}")

            try:
                # ── Build messages for the LLM call ──
                # Start with system prompt
                llm_messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]

                # Append any existing messages from the workflow state
                existing_messages = state.get("messages", [])
                llm_messages.extend(existing_messages)

                # Always include the current query as the user input when present,
                # unless the last message is already that same query (e.g. a prior
                # node or the initial state seeded it) to avoid duplication.
                query = state.get("query", "")
                if query:
                    last_msg = llm_messages[-1] if llm_messages else None
                    if not (isinstance(last_msg, HumanMessage) and last_msg.content == query):
                        llm_messages.append(HumanMessage(content=query))

                # ── Create the LLM instance ──
                # Use the shared model resolver so provider/API key/base URL config applies.
                from services.agent_utils import resolve_model
                max_tokens = agent_config.get("max_tokens")
                llm = await resolve_model(model_name, temperature, max_tokens, agent_config)

                # ── Invoke ──
                response = await llm.ainvoke(llm_messages)

                logger.info(f"[{node_label} (LLM_NODE)] Response received (tokens: {len(str(response.content))})")

                updates = {
                    "messages": [response],
                    "current_node": node_id,
                    "agent_type": "LLM_NODE",
                    "last_agent_type": "LLM_NODE",
                }

                # Optional named handoff: store the response under
                # config["output_key"] so a downstream node can consume it,
                # e.g. a TOOL_NODE tool_params value like "{{my_key}}".
                output_key = agent_config.get("output_key")
                if output_key:
                    node_outputs = dict(state.get("node_outputs") or {})
                    node_outputs[output_key] = str(response.content)
                    updates["node_outputs"] = node_outputs
                    logger.info(f"[{node_label} (LLM_NODE)] Stored response under node_outputs['{output_key}']")

                return updates

            except Exception as e:
                logger.error(f"[{node_label} (LLM_NODE)] Error: {e}")
                return {
                    "error_message": f"LLM node error: {str(e)}",
                    "current_node": node_id,
                    "agent_type": "LLM_NODE",
                    "last_agent_type": "LLM_NODE",
                }

        return llm_node_executor
