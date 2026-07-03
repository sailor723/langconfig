# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent Factory for LangConfig.

Centralizes agent creation with proper configuration, tool binding, and memory integration.
This is the missing piece that connects agent configs from blueprints to actual LLM agents.

Key Responsibilities:
1. Create LLM instances from agent configs (model, temperature, etc.)
2. Load and bind MCP tools based on agent config
3. Add memory tools if enabled
4. Inject context into system prompts
5. Create fully configured LangGraph agents

This replaces the disconnected flow where agents were created without their configs.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Sequence
from datetime import datetime
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.language_models import BaseLanguageModel, BaseChatModel
# IMPORTANT: LangChain v1.0 - Using unified create_agent from langchain.agents
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph
from config import settings
logger = logging.getLogger(__name__)

# =============================================================================
# AGENT GUARDRAILS FRAMEWORK
# =============================================================================
# This prompt is prepended to every agent's system prompt to enforce:
# 1. Stopping criteria - prevents infinite loops and over-exploration
# 2. Tool usage guidelines - ensures tools are called with correct parameters
#
# NOTE: The reasoning loop (Reason → Act → Observe) is handled internally by
# LangChain's create_agent(). These guardrails add production-safety rules.
#
# This can be customized per-agent via the "reasoning_framework" config field.
# =============================================================================

DEFAULT_AGENT_GUARDRAILS = """
# AGENT EXECUTION GUARDRAILS

## STOPPING CRITERIA
- **STOP AFTER 2-3 TOOL CALLS** if you have sufficient information
- **For searches**: One or two searches should provide enough context - do NOT search the same topic repeatedly
- **Quality over quantity**: Provide a good answer with 2-3 sources rather than searching indefinitely
- **When you have relevant information, STOP and provide your answer**
- **Do NOT repeat the same tool call** - if it succeeded, use the results and move on

## TOOL USAGE RULES
- **ALWAYS verify you have ALL required parameters** before calling a tool
- **For write_file**: You MUST provide both `file_path` AND `content` parameters
  - Do NOT call write_file with only file_path
  - Wait until you have complete content ready before writing
- **Do NOT call tools with partial or missing arguments** - this causes validation errors
- **Read tool descriptions carefully** - they specify which parameters are required
"""

# Legacy alias for backward compatibility
REASONING_FRAMEWORK = DEFAULT_AGENT_GUARDRAILS

class AgentFactory:
    """
    Factory for creating fully configured LangGraph tool-calling agents with resilience.
    """

    @staticmethod
    def _validate_agent_config(agent_config: Dict[str, Any]) -> List[str]:
        """Delegate to shared validate_agent_config from services.agent_utils."""
        return validate_agent_config(agent_config)

    @staticmethod
    async def create_agent(
        agent_config: Dict[str, Any],
        project_id: int,
        task_id: int,
        context: str,
        mcp_manager: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        agent_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[CompiledStateGraph, List[BaseTool], List[Any]]:
        """
        Create a fully configured agent ready for execution.

        Tool Parallel Execution:
        - For queries needing multiple tools: "Weather in SF, NYC, and time in EST?"
        - The LLM recognizes it needs 3 tools and creates 3 tool calls in one message
        - create_agent routes all 3 to ToolNode concurrently (maxConcurrency determined by `enable_parallel_tools`)
        - Results aggregated and returned to LLM in single message

        Control via:
        - enable_parallel_tools=True: Tools execute concurrently (fast, default)
        - enable_parallel_tools=False: Tools execute sequentially (slower, if order matters)

        Returns:
            Tuple of (agent, tools, callbacks).
        """

        # 0. Validate Configuration
        config_errors = AgentFactory._validate_agent_config(agent_config)
        if config_errors:
            # Log but don't crash, just warn - resilience
            logger.warning(f"Config validation warnings: {', '.join(config_errors)}")

        # 1. Extract Configuration
        model_name = agent_config.get("model", DEFAULT_MODEL)
        temperature = agent_config.get("temperature", DEFAULT_TEMPERATURE)
        max_tokens = agent_config.get("max_tokens", DEFAULT_MAX_TOKENS)
        enable_streaming = agent_config.get("streaming", True)  # Enable by default for SSE streaming

        base_system_prompt = agent_config.get("system_prompt", "You are a helpful AI assistant.")
        native_tool_names = agent_config.get("native_tools", [])
        # Merge mcp_tools into native_tools (they're the same thing, mcp_tools is legacy name)
        # This ensures tools from both lists are loaded
        mcp_tool_names = agent_config.get("mcp_tools", [])
        if mcp_tool_names:
            # Combine both lists, removing duplicates while preserving order
            combined_tools = list(native_tool_names)
            for tool in mcp_tool_names:
                if tool not in combined_tools:
                    combined_tools.append(tool)
            native_tool_names = combined_tools
            logger.debug(f"Merged native_tools and mcp_tools: {native_tool_names}")
        # Added fallback support
        fallback_models = agent_config.get("fallback_models", [])
        # Memory configuration
        # Frontend sends "enable_long_term_memory", templates use "enable_memory".
        # Check both for compatibility.
        enable_memory = (
            agent_config.get("enable_memory", False) or
            agent_config.get("enable_long_term_memory", False)
        )

        # Long-term memory configuration (LangGraph Store)
        # Check both top-level and guardrails.long_term_memory for compatibility
        long_term_memory = agent_config.get("long_term_memory", False)
        if not long_term_memory and "guardrails" in agent_config:
            long_term_memory = agent_config.get("guardrails", {}).get("long_term_memory", False)

        # Middleware configuration (v1.0: Replaces hooks)
        middleware_list = agent_config.get("middleware", [])
        enable_default_middleware = agent_config.get("enable_default_middleware", True)

        # Backward compatibility: Support legacy hooks
        model_hooks = agent_config.get("model_hooks", [])
        enable_default_hooks = agent_config.get("enable_default_hooks", False)  # Disabled by default in v1.0

        # Structured output configuration (LangChain v1.1: ProviderStrategy support)
        output_schema = agent_config.get("output_schema", None)
        output_schema_name = agent_config.get("output_schema_name", None)
        enable_structured_output = agent_config.get("enable_structured_output", False)

        # Resolve schema name to actual schema if provided
        if not output_schema and output_schema_name and enable_structured_output:
            # Use OutputSchemaRegistry to get both built-in and custom schemas
            from models.custom_schema import OutputSchemaRegistry

            output_schema = OutputSchemaRegistry.get(output_schema_name)
            if output_schema:
                logger.info(f"📋 Resolved schema name '{output_schema_name}' to {output_schema.__name__}")
                agent_config["output_schema"] = output_schema  # Set for later use
            else:
                # Fallback to built-in only (legacy)
                from core.utils.structured_outputs import STRUCTURED_OUTPUT_SCHEMAS
                output_schema = STRUCTURED_OUTPUT_SCHEMAS.get(output_schema_name)
                if output_schema:
                    logger.info(f"📋 Resolved schema name '{output_schema_name}' to {output_schema.__name__} (built-in)")
                    agent_config["output_schema"] = output_schema
                else:
                    logger.warning(f"⚠️ Unknown schema name: {output_schema_name}")
                    enable_structured_output = False  # Disable if schema not found

        # Parallel tool calling configuration
        enable_parallel_tools = agent_config.get("enable_parallel_tools", True)

        # HITL (Human-in-the-Loop) configuration
        interrupt_before = agent_config.get("interrupt_before", False)
        interrupt_after = agent_config.get("interrupt_after", False)

        # Auto-map middleware config → HITL params
        # The frontend UI sends middleware: [{type: 'hitl', enabled: true, ...}]
        # This must be mapped to interrupt_before for AgentFactory.
        if not interrupt_before and not interrupt_after:
            middleware_list = agent_config.get("middleware", [])
            if middleware_list and isinstance(middleware_list, list):
                has_hitl = any(
                    isinstance(m, dict) and m.get("type") == "hitl" and m.get("enabled", True)
                    for m in middleware_list
                )
                if has_hitl:
                    interrupt_before = ["tools"]
                    logger.info("HITL middleware enabled: mapped to interrupt_before=['tools']")

        # Multimodal input configuration
        enable_multimodal_input = agent_config.get("enable_multimodal_input", False)
        multimodal_attachments = agent_config.get("attachments", [])

        logger.info(
            f"Creating agent for task {task_id} (model={model_name}, memory={enable_memory}, "
            f"long_term_memory={long_term_memory}, middleware={len(middleware_list)}, hooks={len(model_hooks)}, "
            f"structured_output={enable_structured_output}, streaming={enable_streaming}, "
            f"multimodal={enable_multimodal_input}, attachments={len(multimodal_attachments)})"
        )

        # 2. Create LLM with Fallbacks (Resilience)
        try:
            # Pass streaming flag to LLM config
            llm_config = {**agent_config, "streaming": enable_streaming}
            llm = await AgentFactory._create_llm_with_fallbacks(
                primary_model=model_name,
                fallback_models=fallback_models,
                temperature=temperature,
                max_tokens=max_tokens,
                config=llm_config
            )
        except ValueError as e:
            logger.error(f"LLM creation failed: {e}")
            raise

        # 3. Load Tools (Native, CLI, Memory, and RAG)
        tools: List[BaseTool] = []

        # Build workspace context for file-writing tools
        workspace_context = {
            "project_id": project_id,
            "task_id": task_id,
            "workflow_id": agent_config.get("workflow_id"),
            "workflow_name": agent_config.get("workflow_name"),
            "execution_id": agent_config.get("execution_id"),
            "custom_output_path": agent_config.get("custom_output_path"),  # Custom output directory
        }

        # Route memory tools from native_tools to the real SimpleMemory.
        # The native_tools.py stubs are placeholders; the real implementation
        # is in core/agents/memory.py via SimpleMemory (text-based + PostgreSQL).
        # Also filter out "enable_memory" config flag from native_tools list.
        MEMORY_NATIVE_TOOLS = {"memory_store", "memory_recall", "enable_memory"}
        requested_memory_native = [t for t in native_tool_names if t in MEMORY_NATIVE_TOOLS]
        if requested_memory_native:
            logger.info(
                f"Detected memory tools in native_tools: {requested_memory_native}. "
                f"Routing to SimpleMemory (text-based + PostgreSQL)."
            )
            # Remove stubs from native tool loading
            native_tool_names = [t for t in native_tool_names if t not in MEMORY_NATIVE_TOOLS]
            # Activate the real memory system
            enable_memory = True

        # Load native tools with context for file tracking
        # Delegated to ToolLoader (extracted 2026-06-24) — see core/agents/tool_loader.py
        from core.agents.tool_loader import ToolLoader
        tools.extend(await ToolLoader.load_native(
            native_tool_names,
            workspace_context=workspace_context,
            agent_context=agent_context
        ))

        # Load CLI tools if specified
        cli_tools = agent_config.get("cli_tools", [])
        if cli_tools:
            tools.extend(await ToolLoader.load_cli(cli_tools))

        # Load custom user-defined tools
        custom_tool_ids = agent_config.get("custom_tools", [])
        logger.info(f"📦 Custom tool IDs from config: {custom_tool_ids}")
        if custom_tool_ids:
            custom_tools_loaded = await ToolLoader.load_custom(custom_tool_ids, project_id)
            logger.info(f"✓ Loaded {len(custom_tools_loaded)} custom tools: {[t.name for t in custom_tools_loaded]}")
            tools.extend(custom_tools_loaded)
        else:
            logger.info("ℹ️ No custom tools specified in agent config")

        if enable_memory:
            tools.extend(await ToolLoader.load_memory(vector_store, project_id, task_id))

        # Check if RAG (codebase search) is enabled
        enable_rag = agent_config.get("enable_rag", False)
        if enable_rag:
            tools.extend(await ToolLoader.load_rag(vector_store, project_id))

        # DIAGNOSTIC: Log final tool list (before constraint wrapping)
        tool_names = [t.name for t in tools]
        logger.info(f"🔧 TOOLS LOADED: {tool_names}")
        if "web_search" in tool_names and not native_tool_names:
            logger.error(f"❌ BUG DETECTED: web_search tool present but native_tools config is empty!")
            logger.error(f"   native_tool_names requested: {native_tool_names}")
            logger.error(f"   cli_tools requested: {cli_tools}")
            logger.error(f"   custom_tools requested: {custom_tool_ids}")

        # 3b. Wrap tools with execution constraints from action presets
        # This enforces timeouts, retries, and exclusive execution based on action preset metadata
        try:
            from core.tools.execution_wrapper import wrap_tools_with_constraints

            # Check if constraint enforcement is enabled (default: True for production safety)
            enforce_constraints = agent_config.get("enforce_tool_constraints", True)

            if enforce_constraints and tools:
                logger.info(f"🛡️ Wrapping {len(tools)} tools with execution constraints from action presets")
                tools = wrap_tools_with_constraints(tools)
                logger.info(f"✓ Tool constraint enforcement enabled")
            else:
                if not enforce_constraints:
                    logger.warning(f"⚠️ Tool constraint enforcement DISABLED by agent config")
        except Exception as e:
            logger.warning(f"Failed to wrap tools with constraints: {e}. Tools will run without constraint enforcement.")
            # Continue without constraint wrapping - tools still work, just without safety enforcement

        # 4. Check if structured output is enabled (v1.1: Support ProviderStrategy)
        structured_output_strategy = None
        if enable_structured_output and output_schema:
            # NOTE: Structured output and tools are mutually exclusive in most models.
            # When tools are bound, the model chooses between tool calls OR structured output,
            # creating unpredictable behavior. We disable structured output in favor of tools.
            if agent_config.get("cli_tools") or agent_config.get("native_tools") or agent_config.get("mcp_tools"):
                logger.info(
                    f"Skipping structured output ({output_schema.__name__}) because tools are enabled; avoiding model/tool mismatch"
                )
                enable_structured_output = False
            else:
                # v1.1: Use ProviderStrategy for native structured output (better performance)
                # Falls back to ToolStrategy for models that don't support native structured output
                try:
                    from langchain.agents.structured_output import ProviderStrategy, ToolStrategy

                    # Determine strategy based on agent config or model capabilities
                    use_provider_strategy = agent_config.get("use_provider_strategy", True)

                    if use_provider_strategy:
                        # ProviderStrategy uses native model structured output (faster, more reliable)
                        structured_output_strategy = ProviderStrategy(output_schema)
                        logger.info(f"🔧 Structured output ENABLED: {output_schema.__name__} (using ProviderStrategy)")
                    else:
                        # ToolStrategy wraps output as a tool call (works with all models)
                        structured_output_strategy = ToolStrategy(output_schema)
                        logger.info(f"🔧 Structured output ENABLED: {output_schema.__name__} (using ToolStrategy)")

                    agent_config["_output_schema"] = output_schema
                    agent_config["_structured_output_strategy"] = structured_output_strategy

                except ImportError:
                    # Fallback for older LangChain versions
                    from langchain.agents.structured_output import ToolStrategy
                    structured_output_strategy = ToolStrategy(output_schema)
                    logger.info(f"🔧 Structured output ENABLED: {output_schema.__name__} (using ToolStrategy - ProviderStrategy not available)")
                    agent_config["_output_schema"] = output_schema
                    agent_config["_structured_output_strategy"] = structured_output_strategy

        # 4b. Check if dynamic model routing is enabled (NEW: LangChain v1-alpha feature)
        # NOTE: Dynamic model routing requires middleware-based model selection
        # Not yet supported in create_agent v1.0. Plan to implement via custom middleware.

            # Use dynamic model selection (60-80% cost savings!)
            from core.models.selector import ModelSelector

            logger.info(f"🚀 Dynamic model routing ENABLED for task {task_id} - optimizing for cost/quality")

            model_selector_instance = ModelSelector(
                primary_model=model_name,
                temperature=temperature,
                enable_routing=True,
                agent_config=agent_config,
                use_model_router_config=True  # Integrate with existing ModelRouter
            )

            # Create selector function that returns model with bound tools
            model_fn = model_selector_instance.create_selector(tools)

            # Store selector instance for stats tracking
            agent_config["_model_selector"] = model_selector_instance

            llm_or_model = model_fn  # This will be a Callable, not a BaseChatModel

        else:
            # Traditional static model
            llm_or_model = llm

            # NOTE: We do NOT bind tools here manually anymore.
            # create_agent handles tool binding internally, supporting parallel execution
            # based on the 'tools' argument passed to it.

        # 5. Augment Context with Pattern Recommendations (Learning Integration)
        augmented_context = await AgentFactory._augment_context_with_patterns(
            context=context,
            agent_config=agent_config,
            project_id=project_id,
            task_id=task_id
        )

        # 6. Create Optimized Prompt (Context Engineering)
        # v1.0: create_agent accepts string for system_prompt, handles messages automatically
        system_prompt_str = AgentFactory._construct_system_prompt_string(
            base_system_prompt,
            augmented_context,
            enable_memory,
            long_term_memory,
            tools,
            custom_guardrails=agent_config.get("guardrails")  # Per-agent customization
        )

        # 6a. Inject Skills (if enabled)
        enable_skills = agent_config.get("enable_skills", False)
        if enable_skills:
            explicit_skills = agent_config.get("skills", [])
            enable_skill_auto_detection = agent_config.get("enable_skill_auto_detection", True)

            # Build context for skill matching
            skill_context = {
                "query": context,  # Original user query/context
                "project_type": agent_config.get("project_type"),
                "tags": agent_config.get("skill_tags", []),
            }

            # Add file path from agent_context if available
            if agent_context:
                skill_context["file_path"] = agent_context.get("file_path")
                skill_context["file_content"] = agent_context.get("file_content")

            system_prompt_str = await AgentFactory._inject_skills(
                system_prompt=system_prompt_str,
                context=skill_context,
                explicit_skills=explicit_skills,
                enable_auto_detection=enable_skill_auto_detection,
                max_skills=agent_config.get("max_skills", 3)
            )

        # 6b. Setup Middleware (v1.0) or Hooks (legacy)
        middleware = None
        hook_manager = None

        # v1.0: Prefer middleware over hooks
        if middleware_list or enable_default_middleware:
            middleware = await AgentFactory._setup_middleware(
                middleware_list=middleware_list,
                enable_default_middleware=enable_default_middleware,
                project_id=project_id,
                task_id=task_id
            )

            # Store middleware in config
            if middleware:
                agent_config["_middleware"] = middleware

        # Backward compatibility: Support legacy hooks if no middleware
        elif model_hooks or enable_default_hooks:
            logger.info("Using legacy hooks (consider migrating to middleware)")
            hook_manager = await AgentFactory._setup_model_hooks(
                model_hooks=model_hooks,
                enable_default_hooks=enable_default_hooks,
                project_id=project_id,
                task_id=task_id
            )

            # Store hook manager in config for later access
            if hook_manager:
                agent_config["_hook_manager"] = hook_manager

        # 6c. Setup Callbacks (e.g., LangFuse Tracing, Token Tracking)
        callbacks = AgentFactory._configure_callbacks(
            project_id=project_id,
            task_id=task_id,
            model_name=model_name,
            temperature=temperature,
            tools_count=len(tools),
            memory_enabled=enable_memory,
            fallbacks=fallback_models,
            mcp_tool_names=native_tool_names,
            agent_config=agent_config
        )

        # 7. Create LangGraph Agent (v1.0 API)
        try:
            # Use the unified agent creator
            create_agent_kwargs = {
                "model": llm_or_model,  # Unbound model (or selector callable)
                "tools": tools or [],   # create_agent handles binding
                "system_prompt": system_prompt_str,  # v1.0: Pass string, messages handled automatically
                # Note: callbacks are passed when invoking the agent, not when creating it
                # Note: streaming is configured on the model object itself, not here
                # "enable_parallel_tools": enable_parallel_tools # If supported by create_agent
            }

            # Add structured output strategy if enabled (v1.0 pattern)
            if structured_output_strategy:
                create_agent_kwargs["response_format"] = structured_output_strategy

            # Add middleware if enabled (v1.0 pattern)
            # Middleware support is now stable in LangChain 1.0
            if middleware:
                create_agent_kwargs["middleware"] = middleware
                middleware_names = [m.__class__.__name__ for m in middleware]
                logger.info(f"✓ Middleware enabled: {', '.join(middleware_names)} ({len(middleware)} total)")
            else:
                logger.debug("No middleware configured for this agent")

            # Add context_schema if provided (v1.0 pattern)
            # Allows agents to use custom runtime context types
            context_schema = agent_config.get("context_schema")
            if context_schema:
                # TODO: When langchain.agents fully supports context_schema parameter, uncomment:
                # create_agent_kwargs["context_schema"] = context_schema
                logger.debug(f"Context schema configured: {context_schema.__name__ if hasattr(context_schema, '__name__') else context_schema}")

            # Add HITL (Human-in-the-Loop) parameters

            # Get PostgreSQL checkpointer for conversation persistence and HITL support
            # Without a checkpointer, interrupt_before/interrupt_after have no effect
            try:
                from core.workflows.checkpointing.manager import get_checkpointer
                checkpointer = get_checkpointer()
                if checkpointer:
                    create_agent_kwargs["checkpointer"] = checkpointer
                    logger.info(f"✓ Checkpointer configured for persistence and HITL")
            except Exception as e:
                logger.warning(f"Failed to configure checkpointer: {e}")
                checkpointer = None
            # interrupt_before: List of node names to pause before execution
            # interrupt_after: List of node names to pause after execution
            # Common node names: ["agent"], ["tools"]
            # FIX: Support custom node lists, not just hardcoded ["agent"]
            if interrupt_before:
                nodes = interrupt_before if isinstance(interrupt_before, list) else ["agent"]
                create_agent_kwargs["interrupt_before"] = nodes
                logger.info(f"✓ HITL: Interrupt before nodes: {nodes}")
            if interrupt_after:
                nodes = interrupt_after if isinstance(interrupt_after, list) else ["agent"]
                create_agent_kwargs["interrupt_after"] = nodes
                logger.info(f"✓ HITL: Interrupt after nodes: {nodes}")

            agent_graph = create_agent(**create_agent_kwargs)

            # FIX: Verify tool binding succeeded
            if tools:
                logger.info(f"✓ Tools bound to agent: {len(tools)} tools configured")
                logger.debug(f"   Tool names: {[t.name for t in tools]}")
                # Verify parallel tool calling configuration
                if enable_parallel_tools:
                    logger.debug("   Parallel tool execution: ENABLED")
                else:
                    logger.debug("   Sequential tool execution: ENABLED")

            # Verify callbacks registered
            if callbacks:
                callback_types = [type(cb).__name__ for cb in callbacks]
                logger.info(f"✓ Callbacks registered: {', '.join(callback_types)}")

            # Log feature status
            features = []
            if enable_structured_output:
                features.append(f"structured output ({output_schema.__name__})")
            if enable_streaming:
                features.append("streaming enabled")
            if middleware:
                features.append(f"{len(middleware)} middleware")
            elif hook_manager:
                features.append(f"{len(hook_manager.hooks)} hooks (legacy)")

            if features:
                logger.info(f"✓ Agent created with: {', '.join(features)}")
            else:
                logger.info(f"✓ Agent created with static model: {model_name}")

            # Return callbacks separately for use during invocation
            return agent_graph, tools, callbacks

        except Exception as e:
            logger.error(f"Failed to create LangGraph agent: {e}", exc_info=True)
            raise

    # =============================================================================
    # Helper Methods
    # =============================================================================

    @staticmethod
    def _construct_system_prompt_string(
        base_prompt: str,
        context: str,
        enable_memory: bool,
        long_term_memory: bool = False,
        tools: List[BaseTool] = None,
        custom_guardrails: str = None
    ) -> str:
        """
        Constructs the system prompt string using Context Engineering principles.
        Structure: Guardrails -> Role/Goal -> Context

        Args:
            base_prompt: The agent's role/goal (user-defined system prompt)
            context: Current task context
            enable_memory: Whether memory tools are enabled
            long_term_memory: Whether workflow-scoped Store memory is enabled
            tools: List of tools available to the agent
            custom_guardrails: Optional custom guardrails (per-agent override)
                              If None, uses DEFAULT_AGENT_GUARDRAILS

        Note: In LangChain v1.0, create_agent handles the reasoning loop internally.
        These guardrails add production-safety rules (stopping criteria, tool usage).
        """
        # Use custom guardrails if provided, otherwise use default
        guardrails = custom_guardrails if custom_guardrails is not None else DEFAULT_AGENT_GUARDRAILS
        if enable_memory:
            guardrails += "\n# MEMORY USAGE\nYou have access to long-term memory tools (e.g., 'memory_recall', 'memory_store'). Use them to access and record knowledge relevant to this project."

        if long_term_memory:
            guardrails += "\n# WORKFLOW-SCOPED LONG-TERM MEMORY\nYou have access to workflow-scoped persistent memory via the LangGraph Store API (runtime.store). Use this to remember important information across workflow executions. Store data using workflow-specific namespaces."

        # CRITICAL: Add explicit tool enforcement if tools are available
        tool_enforcement = ""
        if tools and len(tools) > 0:
            tool_names = [t.name for t in tools]
            tool_enforcement = f"""
# CRITICAL TOOL USAGE REQUIREMENT
You have been equipped with the following tools: {', '.join(tool_names)}

**MANDATORY REQUIREMENT:**
- If your role involves using external services, APIs, or generating content (images, files, etc.), you MUST use the appropriate tool
- DO NOT just describe what you would do or provide meta-commentary
- DO NOT say things like "I understand" or "I need to work with what I have"
- ACTUALLY INVOKE THE TOOL to complete your task
- For example, if you are an "Image Generator" with an image generation tool, you MUST call that tool to generate images
- If you are a "File Writer" with a file writing tool, you MUST call that tool to write files
- Your output should be the RESULT of tool execution, not a description of what you plan to do

**If you fail to use your tools when required, your output will be considered incomplete.**
"""

        system_message_content = f"""{guardrails}
{tool_enforcement}
# YOUR SPECIFIC ROLE AND GOAL
{base_prompt}

# CURRENT CONTEXT AND TASK INFORMATION
<context>
{context}
</context>
---
"""
        return system_message_content

    @staticmethod
    async def _inject_skills(
        system_prompt: str,
        context: Dict[str, Any],
        explicit_skills: Optional[List[str]] = None,
        enable_auto_detection: bool = True,
        max_skills: int = 3
    ) -> str:
        """
        Inject relevant skill instructions into the system prompt.

        Skills are modular, context-aware capabilities that enhance agent behavior.
        They can be explicitly requested or automatically detected based on context.

        Args:
            system_prompt: The base system prompt to enhance
            context: Execution context for matching (query, file_path, project_type, etc.)
            explicit_skills: Optional list of skill IDs to always include
            enable_auto_detection: Whether to auto-detect relevant skills
            max_skills: Maximum number of skills to inject

        Returns:
            Enhanced system prompt with skill instructions
        """
        try:
            from core.skills.registry import get_skill_registry
            from core.skills.matcher import get_skill_matcher

            registry = get_skill_registry()
            matcher = get_skill_matcher()

            # Ensure registry is initialized
            if not registry.is_initialized:
                await registry.initialize()

            skill_instructions = []
            skills_used = []

            # 1. Add explicitly requested skills
            if explicit_skills:
                for skill_id in explicit_skills[:max_skills]:
                    skill = registry.get_skill(skill_id)
                    if skill:
                        skill_instructions.append(AgentFactory._format_skill_for_prompt(skill))
                        skills_used.append(skill_id)

            # 2. Auto-detect relevant skills (if enabled and room for more)
            remaining_slots = max_skills - len(skills_used)
            if enable_auto_detection and remaining_slots > 0 and context:
                matches = await matcher.find_relevant_skills(
                    context=context,
                    max_results=remaining_slots,
                    min_score=0.6
                )
                for match in matches:
                    if match.skill.skill_id not in skills_used:
                        skill_instructions.append(AgentFactory._format_skill_for_prompt(match.skill))
                        skills_used.append(match.skill.skill_id)
                        logger.info(
                            f"Auto-injecting skill '{match.skill.skill_id}' "
                            f"(score={match.score:.2f}, reason={match.match_reason})"
                        )

            # 3. Inject skills into system prompt if any were found
            if skill_instructions:
                skills_section = "\n\n# AVAILABLE SKILLS\n" + \
                    "The following skills provide specialized guidance for your task:\n\n" + \
                    "\n\n---\n\n".join(skill_instructions)

                # Insert skills section before the context section
                if "# CURRENT CONTEXT" in system_prompt:
                    system_prompt = system_prompt.replace(
                        "# CURRENT CONTEXT",
                        f"{skills_section}\n\n# CURRENT CONTEXT"
                    )
                else:
                    system_prompt = system_prompt + skills_section

                logger.info(f"Injected {len(skill_instructions)} skill(s): {skills_used}")

            return system_prompt

        except Exception as e:
            logger.warning(f"Failed to inject skills: {e}")
            return system_prompt  # Return original prompt on error

    @staticmethod
    def _format_skill_for_prompt(skill) -> str:
        """Format a skill for injection into system prompt."""
        parts = [
            f"## Skill: {skill.name}",
            f"**Description:** {skill.description}",
            "",
            skill.instructions
        ]

        if skill.examples:
            parts.extend(["", "**Examples:**", "", skill.examples])

        if skill.allowed_tools:
            parts.extend(["", f"**Allowed Tools:** {', '.join(skill.allowed_tools)}"])

        return "\n".join(parts)

    @staticmethod
    @staticmethod
    def _construct_prompt_template(base_prompt: str, context: str, enable_memory: bool, long_term_memory: bool = False):
        """
        DEPRECATED: Use _construct_system_prompt_string for v1.0 agents.

        Kept for backward compatibility with legacy code that needs ChatPromptTemplate.
        """
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        system_message_content = AgentFactory._construct_system_prompt_string(base_prompt, context, enable_memory, long_term_memory)
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_message_content),
            MessagesPlaceholder(variable_name="messages"),
        ])
        return prompt_template

    @staticmethod
    async def _augment_context_with_patterns(
        context: str,
        agent_config: Dict[str, Any],
        project_id: int,
        task_id: int
    ) -> str:
        """
        Augment context with learned pattern recommendations.

        This integrates pattern learning into agent execution by providing agents with
        proven strategies from past successful workflows.

        Args:
            context: Original context string
            agent_config: Agent configuration (contains pattern hints)
            project_id: Project ID for pattern filtering
            task_id: Task ID for logging

        Returns:
            Augmented context string with pattern recommendations appended
        """
        try:
            # Check if pattern recommendations are enabled for this agent
            enable_patterns = agent_config.get("enable_pattern_recommendations", False)
            if not enable_patterns:
                logger.debug(f"Pattern recommendations disabled for task {task_id}")
                return context

            # Try to extract task description from context for better pattern matching
            # The context usually contains the task description in some form
            task_description = agent_config.get("task_description", "")
            if not task_description:
                # Try to extract from context (simple heuristic)
                lines = context.split('\n')
                # Look for lines that might contain task description
                for line in lines[:10]:  # Check first 10 lines
                    if len(line.strip()) > 20 and not line.strip().startswith('#'):
                        task_description = line.strip()
                        break

            if not task_description:
                logger.debug(f"No task description found for pattern recommendations (task {task_id})")
                return context

            # Get pattern type hints from agent config or default to common useful patterns
            pattern_types = agent_config.get("pattern_types", ["context_strategy", "agent_behavior"])

            # Fetch pattern recommendations
            from services.pattern_learning_service import PatternLearningService
            from models.agent_pattern import PatternType
            from backend.db.session import SessionLocal

            pattern_recommendations = []

            async with SessionLocal() as db:
                service = PatternLearningService(db)

                for pattern_type_str in pattern_types[:2]:  # Limit to 2 pattern types to avoid context bloat
                    try:
                        pattern_type = PatternType(pattern_type_str)
                        patterns = await service.get_pattern_recommendations(
                            task_description=task_description,
                            pattern_type=pattern_type,
                            project_id=project_id,
                            min_confidence=0.7,  # Only high-confidence recommendations
                            limit=2  # Max 2 recommendations per type
                        )

                        if patterns:
                            pattern_recommendations.extend(patterns)
                            logger.info(
                                f"Found {len(patterns)} {pattern_type_str} patterns for task {task_id}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to get {pattern_type_str} patterns: {e}")
                        continue

            # If no patterns found, return original context
            if not pattern_recommendations:
                logger.debug(f"No pattern recommendations found for task {task_id}")
                return context

            # Format pattern recommendations for injection
            pattern_section = "\n\n# LEARNED PATTERNS FROM PAST SUCCESSES\n"
            pattern_section += "The following patterns have proven successful for similar tasks:\n\n"

            for i, pattern in enumerate(pattern_recommendations[:3], 1):  # Max 3 total patterns
                pattern_section += f"**Pattern {i}: {pattern.pattern_name}** (Type: {pattern.pattern_type})\n"
                pattern_section += f"- Success Rate: {pattern.success_rate:.1%} ({pattern.success_count}/{pattern.usage_count} uses)\n"
                pattern_section += f"- Confidence: {pattern.confidence:.2f}\n"

                if pattern.description:
                    pattern_section += f"- Description: {pattern.description}\n"

                if pattern.pattern_config:
                    # Format config as readable text (avoid dumping full JSON)
                    config_highlights = []
                    for key, value in list(pattern.pattern_config.items())[:3]:  # Top 3 config items
                        config_highlights.append(f"{key}: {value}")
                    if config_highlights:
                        pattern_section += f"- Key Settings: {', '.join(config_highlights)}\n"

                pattern_section += "\n"

            pattern_section += "**Recommendation:** Consider applying these proven patterns to improve success probability.\n"
            pattern_section += "---\n"

            # Append patterns to context
            augmented_context = context + pattern_section

            logger.info(
                f"Augmented context with {len(pattern_recommendations)} pattern recommendations "
                f"for task {task_id}"
            )

            return augmented_context

        except Exception as e:
            # Fail gracefully - if pattern retrieval fails, agent should still work with original context
            logger.warning(
                f"Failed to augment context with patterns for task {task_id}: {e}. "
                "Proceeding with original context."
            )
            return context

    @staticmethod
    @staticmethod
    async def _create_llm_with_fallbacks(
        primary_model: str,
        fallback_models: Sequence[str],
        temperature: float,
        max_tokens: Optional[int],
        config: Dict[str, Any]
    ) -> BaseLanguageModel:
        """Delegate to shared create_llm_with_fallbacks from services.agent_utils."""
        return await create_llm_with_fallbacks(primary_model, fallback_models, temperature, max_tokens, config)

    @staticmethod
    @staticmethod
    async def _create_llm(
        model_name: str,
        temperature: float,
        max_tokens: Optional[int],
        config: Dict[str, Any]
    ) -> BaseChatModel:
        """Delegate to shared resolve_model from services.agent_utils."""
        return await resolve_model(model_name, temperature, max_tokens, config)

    async def _setup_middleware(
        middleware_list: List[Any],
        enable_default_middleware: bool,
        project_id: int,
        task_id: int
    ) -> Optional[List]:
        """
        Setup middleware for v1.0 agent execution.

        Middleware provides powerful hooks for:
        - Dynamic prompts (@dynamic_prompt)
        - Pre/post model processing (before_model, after_model)
        - Tool error handling (wrap_tool_call)
        - Summarization and HITL gates

        Args:
            middleware_list: List of middleware instances or configurations
            enable_default_middleware: Whether to add default middleware
            project_id: Project ID for context
            task_id: Task ID for context

        Returns:
            List of middleware instances or None
        """
        from core.middleware.core import (
            AgentMiddleware,
            get_default_middleware,
            create_middleware_from_config,
            migrate_hook_to_middleware
        )

        middleware = []

        # Add default middleware if enabled
        if enable_default_middleware:
            default_middleware = get_default_middleware()
            middleware.extend(default_middleware)
            logger.info(f"✓ Added {len(default_middleware)} default middleware")

        # Add custom middleware
        for item in middleware_list:
            if isinstance(item, AgentMiddleware):
                # Already a middleware instance
                middleware.append(item)
            elif isinstance(item, dict):
                # Configuration dict - create middleware
                try:
                    middleware_instance = create_middleware_from_config(item)
                    middleware.append(middleware_instance)
                except Exception as e:
                    logger.error(f"Failed to create middleware from config: {e}")
            elif hasattr(item, 'pre_model') and hasattr(item, 'post_model'):
                # Legacy hook - migrate to middleware
                logger.info(f"Migrating legacy hook {item.__class__.__name__} to middleware")
                try:
                    middleware_instance = migrate_hook_to_middleware(item)
                    middleware.append(middleware_instance)
                except Exception as e:
                    logger.error(f"Failed to migrate hook to middleware: {e}")
            else:
                logger.warning(f"Unknown middleware type: {type(item)}")

        # Deduplicate middleware by name (custom overrides defaults)
        if middleware:
            seen_names = {}
            deduplicated = []

            # Process in reverse so custom middleware (added last) takes precedence
            for mw in reversed(middleware):
                name = getattr(mw, 'name', mw.__class__.__name__)
                if name not in seen_names:
                    seen_names[name] = True
                    deduplicated.insert(0, mw)  # Insert at beginning to maintain order
                else:
                    logger.debug(f"Skipping duplicate middleware: {name}")

            if len(deduplicated) < len(middleware):
                removed = len(middleware) - len(deduplicated)
                logger.info(f"✓ Removed {removed} duplicate middleware instance(s)")

            logger.info(f"✓ Initialized {len(deduplicated)} total middleware")
            return deduplicated
        else:
            logger.debug("No middleware configured")
            return None

    @staticmethod
    async def _setup_model_hooks(
        model_hooks: List[Any],
        enable_default_hooks: bool,
        project_id: int,
        task_id: int
    ):
        """
        Setup model hooks for context injection and output validation (LEGACY).

        **DEPRECATED in v1.0:** Use _setup_middleware instead.
        This method is kept for backward compatibility.

        Args:
            model_hooks: List of hook instances or configurations
            enable_default_hooks: Whether to add default hooks
            project_id: Project ID for context
            task_id: Task ID for context

        Returns:
            HookManager instance or None
        """
        from core.models.hooks import (
            HookManager,
            ModelHook,
            get_default_hooks,
            create_hook_from_config
        )

        hooks = []

        # Add default hooks if enabled
        if enable_default_hooks:
            default_hooks = get_default_hooks()
            hooks.extend(default_hooks)
            logger.info(f"✓ Added {len(default_hooks)} default hooks")

        # Add custom hooks
        for hook in model_hooks:
            if isinstance(hook, ModelHook):
                # Already a hook instance
                hooks.append(hook)
            elif isinstance(hook, dict):
                # Configuration dict - create hook
                try:
                    hook_instance = create_hook_from_config(hook)
                    hooks.append(hook_instance)
                except Exception as e:
                    logger.error(f"Failed to create hook from config: {e}")
            else:
                logger.warning(f"Unknown hook type: {type(hook)}")

        if hooks:
            hook_manager = HookManager(hooks)
            logger.info(f"✓ Initialized HookManager with {len(hooks)} total hooks")
            return hook_manager
        else:
            logger.debug("No hooks configured")
            return None

    @staticmethod
    async def create_rlm_agent(
        model: str,
        repl_env,  # RLMREPLEnvironment
        query: str,
        depth: int = 0,
        **kwargs
    ) -> CompiledStateGraph:
        """
        Create agent with RLM (Recursive Language Model) capabilities.

        This creates an agent that can recursively analyze large contexts by:
        1. Using Python REPL to explore/partition context
        2. Making recursive LLM calls on specific segments
        3. Synthesizing results hierarchically

        Args:
            model: LLM model name (e.g., "gpt-4o-mini", "claude-haiku-4-5-20251015")
            repl_env: RLM REPL environment with context loaded
            query: User query to answer
            depth: Current recursion depth (0 = root)
            **kwargs: Additional agent config

        Returns:
            Configured LangGraph ReAct agent
        """
        from services.rlm_repl_environment import RLMREPLEnvironment

        logger.info(f"Creating RLM agent at depth {depth} with model {model}")

        # 1. Create LLM
        llm = await AgentFactory._create_llm(
            model_name=model,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens"),
            config=kwargs
        )

        # 2. Create REPL execution tool
        async def execute_python_code(code: str) -> str:
            """Execute Python code in the RLM REPL environment."""
            result = await repl_env.execute_code(code)
            if result['success']:
                output = result.get('output', '')
                return str(output) if output else "Code executed successfully (no output)"
            else:
                return f"Error: {result.get('error', 'Unknown error')}"

        repl_tool = StructuredTool.from_function(
            func=execute_python_code,
            name="execute_python",
            description=(
                "Execute Python code in a secure sandbox to explore and analyze the context. "
                "Use this to filter, search, partition, or manipulate large context data. "
                f"Available modules: {', '.join(repl_env.allowed_modules)}. "
                "The 'context' variable contains the data to analyze. "
                "You can also use lm_query(sub_query, sub_context) for recursive analysis."
            ),
            coroutine=execute_python_code
        )

        # 3. Create tools list
        tools = [repl_tool]

        # 4. Create RLM-specific prompt
        rlm_prompt = f"""You are an RLM (Recursive Language Model) agent at depth {depth}/{repl_env.max_recursion_depth}.

Your goal: {query}

CONTEXT:
The 'context' variable in your Python REPL contains the data you need to analyze. It may be:
- A large string (document, code, log, etc.)
- A list of strings (chunks, files, sections)
- A dict with structured data

AVAILABLE TOOLS:
1. execute_python(code): Run Python code to explore/manipulate context
   - Search with regex: import re; matches = re.findall(r'pattern', context)
   - Filter lists: filtered = [x for x in context if condition]
   - Slice strings: segment = context[1000:2000]
   - Parse JSON: import json; data = json.loads(context)

2. lm_query(sub_query, sub_context): Recursively call an LLM to analyze a specific segment
   - Use when deeper analysis of a section is needed
   - Example: result = lm_query("Find all function definitions", file_content)
   - Available at depth < {repl_env.max_recursion_depth}

RECOMMENDED STRATEGY:
1. First, use execute_python to inspect context structure: type(context), len(context)
2. Use execute_python to search/filter for relevant segments
3. If needed, use lm_query() for deep analysis of specific segments
4. Synthesize findings into a comprehensive answer

IMPORTANT:
- Start by understanding the context structure
- Be systematic in your exploration
- Use recursion wisely (you have {repl_env.max_recursion_depth - depth} levels remaining)

Begin by using execute_python to inspect the context.
"""

        # 5. Create ReAct agent with RLM prompt (v1.0: no pre-binding)
        # v1.0: DO NOT pre-bind tools - pass them to create_agent instead
        agent = create_agent(
            model=llm,  # Pass unbound model
            tools=tools,
            system_prompt=rlm_prompt  # v1.0: use system_prompt, not state_modifier
        )

        logger.info(f"✓ RLM agent created at depth {depth} with {len(tools)} tools")

        return agent

    @staticmethod
    def _configure_callbacks(
        project_id, task_id, model_name, temperature, tools_count,
        memory_enabled, fallbacks, mcp_tool_names=None, agent_config=None
    ):
        """
        Helper to configure callbacks for agent execution.

        Configures TokenTrackingCallback for internal token usage tracking.
        NOTE: We use our custom TokenTrackingCallback system, not LangFuse.

        Returns:
            List of configured callback handlers
        """
        callbacks = []

        # Add token tracking callback (custom internal system)
        try:
            from core.utils.token_tracking import create_token_tracking_callback

            agent_id = agent_config.get("template_id", "unknown") if agent_config else "unknown"
            token_callback = create_token_tracking_callback(
                agent_id=agent_id,
                project_id=project_id,
                task_id=str(task_id),
                mcp_tools=mcp_tool_names or []
            )
            callbacks.append(token_callback)
            logger.info("✓ Token tracking callback configured")
        except Exception as e:
            logger.warning(f"Failed to initialize token tracking callback: {e}")

        # Support for additional custom callbacks from config
        custom_callbacks = agent_config.get("callbacks", []) if agent_config else []
        if custom_callbacks:
            callbacks.extend(custom_callbacks)
            logger.info(f"✓ Added {len(custom_callbacks)} custom callback(s) from config")

        return callbacks


# =============================================================================
# Convenience Functions (No changes needed, relies on the improved Factory)
# =============================================================================

async def create_agent_from_template(
    template_id: str,
    project_id: int,
    task_id: int,
    context: str,
    customizations: Optional[Dict[str, Any]] = None,
    mcp_manager = None,
    vector_store = None
):
    """
    Create an agent from an agent template by ID. (Convenience function)
    """
    # Implementation remains the same as provided in the prompt, assuming AgentTemplateRegistry works.
    from core.agents.templates import AgentTemplateRegistry

    template = AgentTemplateRegistry.get(template_id)
    if not template:
        raise ValueError(f"Agent template not found: {template_id}")

    agent_config = template.to_agent_config()

    if customizations:
        agent_config.update(customizations)

    return await AgentFactory.create_agent(
        agent_config=agent_config,
        project_id=project_id,
        task_id=task_id,
        context=context,
        mcp_manager=mcp_manager,
        vector_store=vector_store
    )
from services.agent_utils import (
    validate_agent_config,
    resolve_model,
    create_llm_with_fallbacks,
    load_agent_tools,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    SUPPORTED_MODELS,
)
