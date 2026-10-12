# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Main agent assembly entrypoints: create_agent and create_rlm_agent.

Split out of core/agents/factory.py; moved verbatim. The concrete
``AgentFactory`` class (defined in the package ``__init__``) subclasses
this mixin. Bare ``AgentFactory.`` references in staticmethod bodies are
late-bound into this module's globals by ``_bind_runtime``.
"""

from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph.state import CompiledStateGraph

from core.state import DeepAgentState
from services.agent_utils import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE

from .shared import logger


class _AgentAssemblyMixin:

    @staticmethod
    async def create_agent(
        agent_config: Dict[str, Any],
        project_id: int,
        task_id: int,
        context: str,
        mcp_manager: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        agent_context: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[str] = None,
        agent_id: Optional[int] = None,
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
        from core.tools.defaults import resolve_native_tools
        native_tool_names = resolve_native_tools(
            agent_config.get("native_tools"),
            enable_default_tools=agent_config.get("enable_default_tools", True),
        )
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
            # Per-agent workspace root: file-writing tools (write_file,
            # save_document) land here when the caller provides it.
            "workspace_root": workspace_root,
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

        # Bind per-agent tool default params (e.g. neo4j_agent_tool.database)
        # so the agent knows its configured target at runtime.
        from core.tools.tool_params import apply_tool_params
        tools = apply_tool_params(tools, agent_config.get("tool_params"))

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

        # 3c. Sub-agent support for regular agents (notebook 2.4_full_agent pattern)
        # Replaces the generic 'task' tool with one that embeds sub-agents via _create_task_tool
        subagents_config = agent_config.get("subagents", [])
        if subagents_config and isinstance(subagents_config, list) and len(subagents_config) > 0:
            await AgentFactory._build_subagent_task_tool(
                tools=tools,
                subagents_config=subagents_config,
                agent_config=agent_config,
                parent_llm=llm,
                temperature=temperature,
                max_tokens=max_tokens,
                workspace_context=workspace_context,
                agent_context=agent_context,
            )

        # 3d. Per-agent workspace document tool. Regular agents have no
        # FilesystemMiddleware (deep agents get one via their backend), so
        # without this tool a regular agent literally cannot persist a file —
        # it will *claim* it saved a report while writing nothing (the "file
        # missing from the Files panel" bug). Inject a workspace-scoped
        # save_document tool whenever the caller provides a workspace root.
        if workspace_root:
            existing_names = {getattr(t, "name", "") for t in tools}
            if "save_document" not in existing_names:
                try:
                    from langchain_core.tools import StructuredTool
                    from tools.native_impl import _write_file_impl

                    def _save_to_agent_workspace(file_path: str, content: str) -> str:
                        return _write_file_impl(
                            file_path,
                            content,
                            _workspace_context={"workspace_root": workspace_root},
                            _agent_context={"agent_id": agent_id},
                        )

                    tools.append(StructuredTool.from_function(
                        func=_save_to_agent_workspace,
                        name="save_document",
                        description=(
                            "Persist a document (report.md / report.docx / "
                            "report.pdf / report.html — format chosen by the "
                            "file extension) into the agent's workspace so the "
                            "user can see and download it in the Files panel. "
                            "Use this whenever the user asks to save, persist, "
                            "or export a document."
                        ),
                    ))
                    logger.info(f"Added workspace-scoped save_document tool (root={workspace_root})")
                except Exception as e:
                    logger.warning(f"Failed to add workspace save_document tool: {e}")

        # 3e. DSH-style execution pipeline (Phase B, docs/tools-refactor.md):
        # wrap tools whose declarative definition requests enforcement
        # (approval guard, timeout, output schema). Additive — tools without
        # enforcement pass through unchanged.
        try:
            from core.tools.pipeline import apply_tool_pipeline
            tools = apply_tool_pipeline(tools)
        except Exception as e:
            logger.warning(f"Tool pipeline wrap failed (non-fatal): {e}")

        # 3f. Code Mode (Phase C, docs/tools-refactor.md): when enabled, expose
        # ONLY `run_code`; the agent's other tools become the generated Python
        # SDK surface the program calls. Off by default — opt-in per agent.
        if agent_config.get("code_mode") and tools:
            try:
                from core.tools.code_mode import create_run_code_tool
                sdk_tool_count = len(tools)
                tools = [create_run_code_tool(tools)]
                logger.info(
                    "Code Mode enabled: agent calls run_code (SDK exposes %d tools)",
                    sdk_tool_count,
                )
            except Exception as e:
                logger.warning(f"Code Mode setup failed (non-fatal): {e}")

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

        # NOTE: We do NOT bind tools here manually anymore.
        # create_agent handles tool binding internally, supporting parallel execution
        # based on the 'tools' argument passed to it.
        llm_or_model = llm

        # 5+6+6a+6b. Build the system prompt and wire up middleware/hooks.
        system_prompt_str, middleware, hook_manager = await AgentFactory._build_prompt_and_middleware(
            context=context,
            base_system_prompt=base_system_prompt,
            enable_memory=enable_memory,
            long_term_memory=long_term_memory,
            tools=tools,
            agent_config=agent_config,
            agent_context=agent_context,
            middleware_list=middleware_list,
            enable_default_middleware=enable_default_middleware,
            model_hooks=model_hooks,
            enable_default_hooks=enable_default_hooks,
            project_id=project_id,
            task_id=task_id,
        )

        # Filesystem middleware — default for regular agents too (deep agents
        # get the SDK's own via their backend). Rooted at the agent workspace so
        # write_file/read_file land in the Files panel, with the format-aware
        # backend wrap for .html/.pdf/.docx/.pptx (multi-format documents).
        # Skip when the agent's config already declares a filesystem middleware
        # (built by create_middleware_from_config) to avoid a duplicate.
        _has_fs_mw = any(
            getattr(m, "name", None) == "FilesystemMiddleware"
            or getattr(m, "__class__", None).__name__ == "FilesystemMiddleware"
            for m in (middleware or [])
        )
        if not _has_fs_mw:
            try:
                from deepagents.middleware.filesystem import FilesystemMiddleware
                from services.workspace_filesystem_backend import (
                    WorkspaceFilesystemBackend,
                )
                from services.format_backend import FormatAwareBackend

                _fs_root = workspace_root
                if not _fs_root:
                    from services.workspace_manager import get_workspace_manager
                    _ws_mgr = get_workspace_manager()
                    _fs_root = str(_ws_mgr.get_task_workspace_with_override(
                        project_id=project_id, workflow_id=None, task_id=task_id,
                    ))
                Path(_fs_root).mkdir(parents=True, exist_ok=True)
                # WorkspaceFilesystemBackend re-bases absolute paths that fall
                # inside the workspace (so write_file with the full workspace
                # path lands in the workspace, not a nested <ws>/Users/...).
                fs_mw = FilesystemMiddleware(
                    backend=FormatAwareBackend(
                        WorkspaceFilesystemBackend(root_dir=_fs_root)
                    ),
                )
                middleware = list(middleware or []) + [fs_mw]
                logger.info(f"✓ Filesystem middleware added (regular agent) root={_fs_root}")

                # Normal-agent analogue of the deepagents harness profile
                # (`services/harness_profiles.py`): strip excluded tools from
                # the model-visible surface. The SDK's `read_file` returns
                # images as base64 image blocks, which a *tool* message cannot
                # carry — it is tokenised per character (2.1 MB → 1.47M tokens
                # → HTTP 400). Must be appended AFTER the tool-injecting
                # middleware so it can filter what that middleware added.
                try:
                    from services.harness_profiles import (
                        build_tool_exclusion_middleware,
                        excluded_tool_names,
                    )

                    _excl_mw = build_tool_exclusion_middleware()
                    if _excl_mw is not None:
                        middleware.append(_excl_mw)
                        logger.info(
                            "✓ Tool exclusion middleware added (regular agent) "
                            f"excluded={sorted(excluded_tool_names())}"
                        )
                except Exception as e:
                    logger.warning(f"Tool exclusion middleware unavailable: {e}")
            except Exception as e:
                logger.warning(f"Filesystem middleware not available for regular agent: {e}")

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
                "state_schema": DeepAgentState,  # Extends AgentState with todos + files for VFS/todo tools
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
            system_prompt=rlm_prompt,  # v1.0: use system_prompt, not state_modifier
            state_schema=DeepAgentState,
        )

        logger.info(f"✓ RLM agent created at depth {depth} with {len(tools)} tools")

        return agent


def _bind_runtime() -> None:
    """Bind the concrete AgentFactory class into this module's globals.

    Staticmethod bodies reference the concrete class by its bare name
    (e.g. ``AgentFactory._create_llm``), which must resolve in this
    module's globals at call time. The concrete class is defined in the
    package ``__init__``, which imports this module first — hence this
    late binding avoids a circular import.
    """
    from core.agents.factory import AgentFactory
    globals()["AgentFactory"] = AgentFactory
