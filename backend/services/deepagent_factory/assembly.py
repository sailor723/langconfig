# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent factory assembly.

The main ``create_deep_agent`` orchestration, extracted from the former
monolithic deepagent_factory.py.
"""

from typing import Any, List, Optional, Tuple

from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from models.deep_agent import DeepAgentConfig
from models.enums import MiddlewareType
from core.middleware.deep import DeepAgentsMiddlewareFactory
from services.agent_utils import resolve_model, DEFAULT_MODEL
from .shared import logger


class _DeepAgentAssemblyMixin:
    @staticmethod
    async def create_deep_agent(
        config: DeepAgentConfig,
        project_id: int,
        task_id: int,
        context: str,
        mcp_manager=None,
        vector_store=None,
        workflow_id: Optional[int] = None,
        custom_output_path: Optional[str] = None,
        user_message: Optional[str] = None  # First user message for skill routing
    ) -> Tuple[CompiledStateGraph, List[BaseTool], List[Any]]:
        """
        Create a DeepAgent with middleware, subagents, and backends.

        Args:
            config: DeepAgent configuration
            project_id: Project ID for context
            task_id: Task ID for context
            context: Additional context string
            mcp_manager: MCP manager for tool loading
            vector_store: Vector store for RAG
            workflow_id: Workflow ID for file organization
            custom_output_path: Custom output directory for file writes (overrides default)
            user_message: First user message, used by Skill Router LLM if skill_router_model is set

        Returns:
            Tuple of (agent, tools, callbacks)
        """
        try:
            from deepagents import create_deep_agent
        except ImportError:
            logger.error("deepagents library not installed. Falling back to regular agent.")
            return await DeepAgentFactory._fallback_to_regular_agent(
                config, project_id, task_id, context, mcp_manager, vector_store
            )

        # Validate configuration
        config_errors = DeepAgentFactory._validate_deep_agent_config(config)
        if config_errors:
            logger.warning(f"DeepAgent config validation warnings: {', '.join(config_errors)}")

        logger.info(
            f"Creating DeepAgent for task {task_id} "
            f"(model={config.model}, middleware={len(config.middleware)}, "
            f"subagents={len(config.subagents)})"
        )

        # Setup observability callbacks (Langfuse, etc.)
        callbacks = await DeepAgentFactory._setup_callbacks(project_id, task_id)
        callback_handler = callbacks[0] if callbacks else None

        # Load base tools from configuration (with custom_output_path for file writes)
        base_tools = await DeepAgentFactory._load_base_tools(
            config, mcp_manager, vector_store, project_id, task_id,
            workflow_id=workflow_id,
            custom_output_path=custom_output_path
        )

        # Create middleware-specific tools
        middleware_tools = await DeepAgentsMiddlewareFactory.create_all_tools(
            middleware_configs=[m.dict() for m in config.middleware],
            mcp_manager=mcp_manager,
            template_registry=None,
            agent_factory=None
        )

        # Combine all available tools
        all_tools = base_tools + middleware_tools
        logger.info(f"Total tools: {len(all_tools)} (base={len(base_tools)}, middleware={len(middleware_tools)})")

        # Prepare subagent configurations (with workspace context for file-writing tools)
        subagents_config = await DeepAgentFactory._prepare_subagents(
            config.subagents,
            enable_compiled=getattr(config, 'enable_compiled_subagents', True),
            project_id=project_id,
            task_id=task_id,
            workflow_id=workflow_id,
            custom_output_path=custom_output_path,
            mcp_manager=mcp_manager,
            vector_store=vector_store
        )

        # Initialize middleware instances with instrumentation
        middleware_instances = []

        # Import instrumentation utilities
        from services.deepagents_instrumentation import (
            instrument_deepagents_middleware,
            create_todo_tracker
        )

        # Initialize MemoryMiddleware (loads project AGENTS.md into system prompt)
        # Default: ON. Library-idiomatic per deepagents. Can opt-out via
        # config.disable_memory_middleware = True.
        if not getattr(config, 'disable_memory_middleware', False):
            try:
                from deepagents.middleware.memory import MemoryMiddleware
                from services.agents_md_service import ensure_agents_md_exists

                agents_md_path = ensure_agents_md_exists(project_id)
                # FilesystemBackend is scoped to the project root so the agent
                # can only read/write files within its own project directory.
                # AGENTS.md lives at projects/{id}/AGENTS.md, so we use a
                # backend with root_dir = projects/{id}.
                from deepagents.backends.filesystem import FilesystemBackend
                mem_backend = FilesystemBackend(
                    root_dir=str(agents_md_path.parent)
                )
                mem_middleware = MemoryMiddleware(
                    backend=mem_backend,
                    sources=[agents_md_path.name],  # relative to root_dir
                    add_cache_control=True,         # for Anthropic prompt caching
                )
                from services.deepagents_instrumentation import (
                    instrument_deepagents_middleware,
                )
                instrumented_mem = instrument_deepagents_middleware(
                    mem_middleware,
                    callback_handler=callback_handler
                )
                middleware_instances.append(instrumented_mem)
                logger.info(
                    f"MemoryMiddleware initialized: AGENTS.md={agents_md_path}"
                )
            except Exception as e:
                logger.warning(f"MemoryMiddleware not available: {e}")

        # Initialize FilesystemMiddleware if enabled
        filesystem_config = next(
            (m for m in config.middleware if m.type == MiddlewareType.FILESYSTEM),
            None
        )
        if filesystem_config and filesystem_config.enabled:
            try:
                from deepagents.middleware.filesystem import FilesystemMiddleware
                from deepagents.backends.filesystem import FilesystemBackend
                from services.workspace_manager import get_workspace_manager

                # Get task workspace for file storage (with custom path override if configured)
                workspace_mgr = get_workspace_manager()
                workspace_path = workspace_mgr.get_task_workspace_with_override(
                    project_id=project_id,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    custom_output_path=custom_output_path
                )

                # Use FilesystemBackend with task workspace as root (files persist to disk)
                fs_backend = FilesystemBackend(root_dir=str(workspace_path))
                fs_middleware = FilesystemMiddleware(backend=fs_backend)
                instrumented_fs = instrument_deepagents_middleware(
                    fs_middleware,
                    callback_handler=callback_handler
                )
                middleware_instances.append(instrumented_fs)
                logger.info(f"FilesystemMiddleware initialized with workspace: {workspace_path}")
            except ImportError as e:
                logger.warning(f"FilesystemMiddleware not available: {e}")

        # Initialize SummarizationMiddleware if enabled (deepagents built-in)
        # This automatically compresses conversation history when token count exceeds threshold.
        if config.guardrails and config.guardrails.enable_summarization:
            try:
                from deepagents.middleware.summarization import SummarizationMiddleware
                from deepagents.backends import StateBackend

                trigger = ("token", config.guardrails.token_limits.get("summarization_threshold", 60000))
                keep = ("messages", 20)
                summarization_mw = SummarizationMiddleware(
                    model=config.model,
                    backend=StateBackend(),
                    trigger=trigger,
                    keep=keep,
                )
                instrumented_summ = instrument_deepagents_middleware(
                    summarization_mw,
                    callback_handler=callback_handler
                )
                middleware_instances.append(instrumented_summ)
                logger.info(
                    f"SummarizationMiddleware initialized: trigger={trigger}, keep={keep}"
                )
            except Exception as e:
                logger.warning(f"SummarizationMiddleware not available: {e}")

        # NOTE: SubAgentMiddleware is added LATER (after all_subagents is built)
        # to provide the `task` tool. The deepagents library does NOT auto-create it.
        # See: https://docs.langchain.com/oss/python/deepagents/subagents
        if subagents_config:
            logger.info(f"SubAgents configured ({len(subagents_config)}) - will be added via SubAgentMiddleware")

        # Get PostgreSQL checkpointer for conversation persistence
        from core.workflows.checkpointing.manager import get_checkpointer
        checkpointer = get_checkpointer()

        if checkpointer:
            logger.info("Conversation persistence enabled")
        else:
            logger.warning("Checkpointer unavailable - conversations will not persist")

        # Prepare guardrails configuration for memory management
        guardrails_config = None
        if config.guardrails:
            guardrails_config = {
                "token_limits": config.guardrails.token_limits,
                "enable_auto_eviction": config.guardrails.enable_auto_eviction,
                "enable_summarization": config.guardrails.enable_summarization,
                "interrupts": config.guardrails.interrupts
            }

        # Assemble the full system prompt from user parts
        # Order: USER + custom_prompt (replaces BASE) + custom_suffix
        prompt_parts = [config.system_prompt]
        if getattr(config, 'custom_prompt', None):
            prompt_parts.append(config.custom_prompt)
        if getattr(config, 'custom_suffix', None):
            prompt_parts.append(config.custom_suffix)
        final_system_prompt = "\n\n".join(prompt_parts)

        # Initialize LocalShellBackend if sandbox mode is enabled.
        # This gives the agent an `execute` tool for running shell commands / Python scripts
        # scoped to the task workspace directory on the host machine.
        local_sandbox_backend = None
        sandbox_path = None
        if getattr(config, 'use_local_sandbox', False):
            try:
                from deepagents.backends import LocalShellBackend
                from services.workspace_manager import get_workspace_manager

                workspace_mgr = get_workspace_manager()

                # If no project/workflow/task context (standalone/chat sessions),
                # fall back to outputs/default/ to stay consistent with
                # FilesystemMiddleware and write_file's default location.
                if workflow_id is None:
                    sandbox_path = workspace_mgr.base_dir / "default"
                    sandbox_path.mkdir(parents=True, exist_ok=True)
                else:
                    sandbox_path = workspace_mgr.get_task_workspace_with_override(
                        project_id=project_id,
                        workflow_id=workflow_id,
                        task_id=task_id,
                        custom_output_path=custom_output_path,
                    )
                    sandbox_path.mkdir(parents=True, exist_ok=True)

                local_sandbox_backend = LocalShellBackend(
                    root_dir=str(sandbox_path),
                    timeout=120,
                    max_output_bytes=100000,
                    inherit_env=True,  # Inherit PATH so pip/python etc. are available
                )
                logger.info(f"LocalShellBackend sandbox enabled at: {sandbox_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize LocalShellBackend: {e}. Proceeding without sandbox.")

        # ── Skills (notebook-style progressive disclosure) ──
        # Pattern (from backend/notebooks/module-5):
        # - Each skill's SKILL.md path goes directly into the main agent
        # - Library creates SkillsMiddleware on main agent: injects metadata
        #   catalog (name + description + path) into the system prompt
        # - Main agent reads SKILL.md body on demand via built-in read_file
        # - No subagent wrapping — LLM matches via description
        agent_kwargs_skills: list = []
        if getattr(config, 'skills', None):
            try:
                from db.database import SessionLocal
                from models.skill import Skill

                db = SessionLocal()
                try:
                    skill_records = db.query(Skill).filter(
                        Skill.skill_id.in_(config.skills)
                    ).all()
                finally:
                    db.close()

                for s in skill_records:
                    agent_kwargs_skills.append(s.source_path)
                logger.info(
                    f"Registered {len(agent_kwargs_skills)} skill(s) on main agent "
                    f"(notebook-style progressive disclosure)"
                )
            except Exception as e:
                logger.warning(f"Failed to register skills: {e}")

        # Create DeepAgent with all components
        try:
            # Build a BaseChatModel instance from config.model using shared resolve_model
            main_chat_model = await resolve_model(
                config.model,
                config.temperature,
                config.max_tokens or 4096,
                {"streaming": True}
            ) if config.model else await resolve_model(DEFAULT_MODEL, config.temperature, config.max_tokens or 4096, {"streaming": True})
            agent_kwargs = {
                "model": main_chat_model,  # Pass BaseChatModel, not string
                "tools": all_tools,
                "system_prompt": final_system_prompt,
                "middleware": middleware_instances if middleware_instances else None,
                "subagents": subagents_config if subagents_config else None,
                "checkpointer": checkpointer,
                # Notebook-style: skills registered directly on main agent.
                # Library creates SkillsMiddleware which injects metadata catalog.
                "skills": agent_kwargs_skills if agent_kwargs_skills else None,
            }

            # Pass LocalShellBackend so the agent gains the `execute` tool for
            # running scripts (Python, shell commands, pip install, etc.)
            if local_sandbox_backend is not None:
                agent_kwargs["backend"] = local_sandbox_backend

            # Try to pass guardrails if supported
            try:
                # Map guardrails.interrupts to interrupt_on for HITL support
                raw_interrupts = guardrails_config.get("interrupts") or None
                interrupt_on = None
                if raw_interrupts:
                    # Convert bool values to proper InterruptOnConfig dicts
                    # e.g. {"tools": True} → {"tools": {"allowed_decisions": [...], ...}}
                    # Note: DecisionType is typing.Literal, not an iterable enum,
                    # so we use the literal list instead of iterating.

                    # Collect available tool names for resolving "tools" wildcard
                    # HumanInTheLoopMiddleware checks interrupt_on[tool_call["name"]],
                    # so keys must be actual tool names, not "tools".
                    available_tool_names = [
                        getattr(t, "name", str(t)) for t in all_tools
                    ] if all_tools else []

                    interrupt_on = {}
                    for key, val in raw_interrupts.items():
                        # Resolve "tools" wildcard → all available tool names
                        if key == "tools":
                            targets = available_tool_names
                        else:
                            targets = [key]

                        if isinstance(val, bool) and val:
                            config_dict = {
                                "allowed_decisions": ["approve", "edit", "reject", "respond"],
                                "description": f"Approve tool action?"
                            }
                        elif isinstance(val, dict):
                            config_dict = val
                        elif val:
                            config_dict = {
                                "allowed_decisions": ["approve", "edit", "reject", "respond"],
                                "description": f"Approve tool action?"
                            }
                        else:
                            continue

                        for tname in targets:
                            interrupt_on[tname] = config_dict

                    if interrupt_on:
                        agent_kwargs["interrupt_on"] = interrupt_on
                        logger.info(f"  HITL interrupt_on configured for {len(interrupt_on)} tools: {list(interrupt_on.keys())}")

                    # Register a harness profile to exclude built-in tools we don't want.
                    try:
                        from deepagents import (
                            HarnessProfile, register_harness_profile,
                        )
                        # The model is a ChatOpenAI instance, which the library
                        # resolves with provider="openai". The key must match
                        # what _harness_profile_for_model generates.
                        _profile_key = f"openai:{_model_str}"
                        register_harness_profile(
                            _profile_key,
                            HarnessProfile(
                                excluded_tools=frozenset({
                                    "write_todos", "update_todo_status", "get_todos",
                                    "ls", "glob", "grep", "execute",
                                    "task",
                                }),
                                excluded_middleware=[
                                    "TodoListMiddleware",
                                    "SkillsMiddleware",
                                ],
                            ),
                        )
                        logger.info(
                            f"Registered harness profile for {_profile_key} "
                            f"with built-in tools excluded"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to register harness profile: {e}")

                agent = create_deep_agent(**agent_kwargs, guardrails=guardrails_config)
                logger.info(f"Guardrails configuration applied")
            except TypeError as e:
                if "guardrails" in str(e):
                    logger.warning("Guardrails parameter not supported, creating without it")
                    agent = create_deep_agent(**agent_kwargs)
                else:
                    raise

            # Log tools available to the agent for debugging
            tool_names = [getattr(t, "name", str(t)) for t in all_tools] if all_tools else []
            logger.info(f"=== Agent created with {len(tool_names)} tools: {tool_names} ===")

            logger.info(f"DeepAgent created for task {task_id}")
            logger.info(f"  Persistence: {'enabled' if checkpointer else 'disabled'}")
            logger.info(f"  Token limits: {config.guardrails.token_limits}")
            logger.info(f"  Auto-eviction: {config.guardrails.enable_auto_eviction}")
            logger.info(f"  Summarization: {config.guardrails.enable_summarization}")

            return agent, all_tools, callbacks

        except Exception as e:
            logger.error(f"Error creating DeepAgent: {e}")
            logger.info("Falling back to regular agent")
            return await DeepAgentFactory._fallback_to_regular_agent(
                config, project_id, task_id, context, mcp_manager, vector_store
            )


def _bind_runtime() -> None:
    """Bind the concrete DeepAgentFactory class into this module's globals.

    The staticmethod bodies reference the concrete class by its bare name
    (e.g. ``DeepAgentFactory._validate_deep_agent_config``), which must
    resolve in this module's globals at call time. The concrete class is
    defined in the package ``__init__``, which imports this module first —
    hence this late binding avoids a circular import.
    """
    from services.deepagent_factory import DeepAgentFactory
    globals()["DeepAgentFactory"] = DeepAgentFactory
