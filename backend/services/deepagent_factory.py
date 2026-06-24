# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent Factory Service.

Creates DeepAgents using the deepagents library while integrating
with LangConfig's existing agent factory infrastructure.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from openai import OpenAI

from models.deep_agent import (
    DeepAgentConfig,
    SubAgentConfig,
    MiddlewareConfig,
    BackendConfig,
    GuardrailsConfig
)
from models.enums import SubAgentType, MiddlewareType, BackendType
from core.middleware.deep import DeepAgentsMiddlewareFactory
from core.agents.factory import AgentFactory

logger = logging.getLogger(__name__)


class DeepAgentFactory:
    """
    Factory for creating DeepAgents with full middleware and backend support.
    Wraps the deepagents library while integrating with LangConfig infrastructure.
    """
    # Note: Type validation now handled by Pydantic enums in models.enums
    # No need for VALID_* constants anymore

    @staticmethod
    def _validate_deep_agent_config(config: DeepAgentConfig) -> List[str]:
        """
        Basic validation of DeepAgent configuration.

        Returns:
            List of error/warning messages (empty if valid)
        """
        errors = []

        # 1. Required: model must be set
        if not config.model:
            errors.append("model is required")

        # 2. Required: system_prompt must be set
        if not config.system_prompt:
            errors.append("system_prompt is required")

        # 3. Validate temperature bounds (0.0 to 2.0)
        if not (0.0 <= config.temperature <= 2.0):
            errors.append(f"temperature must be between 0.0 and 2.0, got {config.temperature}")

        # 4-6. Type and consistency validation now handled by Pydantic validators
        # Enum types ensure only valid values are accepted
        # @model_validator decorators check cross-field constraints
        # No runtime validation needed here

        return errors

    @staticmethod
    async def _run_skill_router(
        router_model: str,
        skill_records: list,
        user_message: str
    ) -> Optional[str]:
        """
        Call the router LLM to classify which skill matches the user's request.

        Args:
            router_model: Model name (e.g. "deepseek:deepseek-chat")
            skill_records: List of Skill DB records with skill_id and description
            user_message: The user's first message

        Returns:
            Matched skill_id string, or None if no skill matches
        """
        try:
            # Build skill descriptions list
            skill_lines = []
            for s in skill_records:
                desc = s.description or ""
                skill_lines.append(f"- {s.skill_id}: {desc}")

            skills_text = "\n".join(skill_lines)

            routing_prompt = (
                f"You are a skill router. Classify the user's request to the most relevant skill.\n\n"
                f"Available skills:\n{skills_text}\n\n"
                f"Return ONLY the skill_id (one word) that best matches, or 'none' if no skill matches. "
                f"Do NOT include any other text, explanation, or formatting.\n\n"
                f"User: {user_message}"
            )

            # Normalize model name — strip provider prefix
            model_name = router_model.replace("deepseek:", "").replace("agnes:", "")

            # Get API key from DB settings (not from env)
            from config import get_api_key_from_db
            if router_model.startswith("deepseek"):
                api_key = get_api_key_from_db("deepseek_api_key")
                base_url = "https://api.deepseek.com/v1"
            elif router_model.startswith("agnes"):
                api_key = get_api_key_from_db("agnes_api_key")
                base_url = None  # uses default
            else:
                api_key = get_api_key_from_db("openai_api_key")
                base_url = None

            if not api_key:
                logger.warning(f"Skill Router: no API key found for {router_model}. Falling back to all skills.")
                return None

            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": routing_prompt}],
                temperature=0.1,
                max_tokens=20,
            )

            result = response.choices[0].message.content.strip().lower()

            # Validate result is a known skill_id
            valid_ids = {s.skill_id.lower() for s in skill_records}
            if result in valid_ids:
                logger.info(f"Skill Router selected: {result}")
                return result
            else:
                logger.info(f"Skill Router returned '{result}' — no matching skill, using all skills")
                return None

        except Exception as e:
            logger.warning(f"Skill Router failed: {e}. Falling back to all skills.")
            return None

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

        # NOTE: SubAgentMiddleware is NOT manually created here.
        # The deepagents library automatically creates SubAgentMiddleware (with the `task` tool)
        # when `subagents=` is passed to create_deep_agent().
        # Manually creating it causes conflicts and prevents the `task` tool from working.
        # See: https://docs.langchain.com/oss/python/deepagents/subagents
        if subagents_config:
            logger.info(f"SubAgents configured ({len(subagents_config)}) - will be auto-initialized by create_deep_agent")

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

        # Sync selected skills from DB to sandbox filesystem.
        # Skills are written as SKILL.md files and made available via
        # create_deep_agent(skills=["/skills/"]) for progressive disclosure.
        skills_config = []
        agent_kwargs_skills = None
        if sandbox_path and getattr(config, 'skills', None):
            try:
                from db.database import SessionLocal
                from models.skill import Skill

                skills_root = sandbox_path / "skills"
                skills_root.mkdir(parents=True, exist_ok=True)

                db = SessionLocal()
                try:
                    skill_records = db.query(Skill).filter(
                        Skill.skill_id.in_(config.skills)
                    ).all()
                finally:
                    db.close()

                for s in skill_records:
                    skill_dir = skills_root / s.skill_id
                    skill_dir.mkdir(parents=True, exist_ok=True)

                    lines = [
                        "---",
                        f'name: {s.skill_id}',
                        f'description: "{s.description}"',
                        f'version: {s.version}',
                    ]
                    if s.tags:
                        lines.append("tags:\n" + "\n".join(f"  - {t}" for t in s.tags))
                    if s.triggers:
                        lines.append("triggers:\n" + "\n".join(f'  - "{t}"' for t in s.triggers))
                    if s.allowed_tools:
                        lines.append("allowed_tools:\n" + "\n".join(f"  - {t}" for t in s.allowed_tools))
                    lines.append("---")

                    skill_md = "\n".join(lines) + "\n\n" + s.instructions
                    if s.examples:
                        skill_md += "\n\n## Examples\n\n" + s.examples

                    (skill_dir / "SKILL.md").write_text(skill_md)
                    skills_config.append(s.skill_id)

                if skills_config:
                    # ── Skill Router (first message only hint, not exclusion) ──
                    # The router suggests the best skill but does NOT exclude others.
                    # All skills remain in the system prompt so the agent can switch
                    # on subsequent turns. Deleting skills (old approach) broke
                    # multi-turn — agent had no other skills to switch to.
                    if (config.skill_router_model and user_message and skill_records):
                        matched_skill = await DeepAgentFactory._run_skill_router(
                            router_model=config.skill_router_model,
                            skill_records=skill_records,
                            user_message=user_message,
                        )
                        if matched_skill:
                            logger.info(f"Skill Router suggested: {matched_skill}")

                    agent_kwargs_skills = [str(skills_root.resolve())]
                    logger.info(f"Skills synced to sandbox: {skills_config}")

                    # ── Build a subagent per skill with isolated SkillsMiddleware ──
                    # Each subagent gets its own SkillsMiddleware so Skill A's SKILL.md
                    # never leaks into Skill B's context on subsequent turns.
                    # The main agent stays clean (no skills=[]) and delegates via task().
                    from deepagents.middleware.skills import SkillsMiddleware
                    from deepagents.backends import FilesystemBackend
                    skill_backend = FilesystemBackend(root_dir=str(skills_root))
                    skill_subagents = []
                    for s in skill_records:
                        skill_mw = SkillsMiddleware(
                            backend=skill_backend,
                            sources=[s.skill_id],
                            system_prompt=None,
                        )
                        skill_subagents.append({
                            "name": s.skill_id,
                            "description": s.description,
                            "system_prompt": (
                                f"You are a {s.skill_id} specialist. "
                                "Read the SKILL.md and follow its instructions exactly. "
                                "Return only the result."
                            ),
                            "middleware": [skill_mw],
                        })

                    # Build delegation hints (replaces <available_skills> catalog)
                    delegation_hints = "\n".join(
                        f"  - {s.skill_id}: {s.description}" for s in skill_records
                    )
                    final_system_prompt += (
                        "\n\n## SKILLS\n"
                        "You have access to specialized subagents. When a task requires "
                        "specialized knowledge, delegate using task() with the matching subagent name:\n"
                        f"{delegation_hints}\n\n"
                        "For simple questions, answer directly. "
                        "For skill tasks, always delegate."
                    )

            except Exception as e:
                logger.warning(f"Failed to sync skills to sandbox: {e}")

        # Create DeepAgent with all components
        try:
            agent_kwargs = {
                "model": config.model,
                "tools": all_tools,
                "system_prompt": final_system_prompt,
                "middleware": middleware_instances if middleware_instances else None,
                "subagents": subagents_config if subagents_config else None,
                "checkpointer": checkpointer,
            }

            # Pass LocalShellBackend so the agent gains the `execute` tool for
            # running scripts (Python, shell commands, pip install, etc.)
            if local_sandbox_backend is not None:
                agent_kwargs["backend"] = local_sandbox_backend

            # Merge user subagents with skill subagents.
            # Skill subagents have isolated SkillsMiddleware instances — one per skill.
            # See the "## SKILLS" section above for how they're built.
            # The main agent does NOT have skills=[] — it delegates via task().
            all_subagents = []
            if subagents_config:
                all_subagents.extend(subagents_config)
            if 'skill_subagents' in dir() and skill_subagents:
                all_subagents.extend(skill_subagents)
            if all_subagents:
                agent_kwargs["subagents"] = all_subagents

            # Debug logging for subagent configuration
            logger.info(f"All subagents: {len(all_subagents)} (user: {len(subagents_config or [])}, skill: {len(skill_subagents if 'skill_subagents' in dir() else [])})")
            for i, sub in enumerate(all_subagents):
                if isinstance(sub, dict):
                    sub_tools = sub.get('tools', [])
                    tool_names = [getattr(t, 'name', str(t)) for t in sub_tools] if sub_tools else []
                    has_skills = 'skills' in sub
                    has_mw = len(sub.get('middleware', [])) > 0
                    mw_info = f"mw={len(sub.get('middleware', []))}" if has_mw else ""
                    skills_info = "skills=[]" if has_skills else ""
                    logger.info(f"  [{i}] {sub.get('name')}: {len(sub_tools)} tools {skills_info} {mw_info}")
                else:
                    logger.info(f"  [{i}] CompiledSubAgent: {getattr(sub, 'name', 'unknown')}")

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

                agent = create_deep_agent(**agent_kwargs, guardrails=guardrails_config)
                logger.info("Guardrails configuration applied")
            except TypeError as e:
                if "guardrails" in str(e):
                    logger.warning("Guardrails parameter not supported, creating without it")
                    agent = create_deep_agent(**agent_kwargs)
                else:
                    raise

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

    @staticmethod
    async def _load_base_tools(
        config: DeepAgentConfig,
        mcp_manager,
        vector_store,
        project_id: int,
        task_id: int,
        workflow_id: Optional[int] = None,
        custom_output_path: Optional[str] = None
    ) -> List[BaseTool]:
        """Load base tools from configuration (native, CLI, and custom tools).

        Args:
            config: DeepAgent configuration
            mcp_manager: MCP manager for tool loading
            vector_store: Vector store for RAG
            project_id: Project ID for context
            task_id: Task ID for context
            workflow_id: Workflow ID for file organization
            custom_output_path: Custom output directory for file writes (overrides default)
        """
        tools = []

        # DEBUG: Log incoming config
        logger.info(f"[_load_base_tools] Config received:")
        logger.info(f"  - config.native_tools: {config.native_tools}")
        logger.info(f"  - config.cli_tools: {config.cli_tools}")
        logger.info(f"  - config.custom_tools: {config.custom_tools}")
        logger.info(f"  - custom_output_path: {custom_output_path}")

        # Build workspace context for file-writing tools (enables custom_output_path)
        workspace_context = {
            "project_id": project_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "custom_output_path": custom_output_path,
        }

        # Load native tools (file operations, web search, etc.)
        MEMORY_NATIVE_TOOLS = {"memory_store", "memory_recall", "enable_memory"}
        native_tool_names = config.native_tools or []
        requested_memory_native = [t for t in native_tool_names if t in MEMORY_NATIVE_TOOLS]
        if requested_memory_native:
            logger.info(
                f"Detected memory tools in native_tools: {requested_memory_native}. "
                f"Routing to SimpleMemory (PostgreSQL-backed)."
            )
            # Remove stubs/config flags from native tool loading
            native_tool_names = [t for t in native_tool_names if t not in MEMORY_NATIVE_TOOLS]

        if native_tool_names:
            try:
                from core.agents.factory import AgentFactory
                native_tools = await AgentFactory._load_native_tools(
                    native_tool_names,
                    workspace_context=workspace_context
                )
                tools.extend(native_tools)
                logger.info(f"Loaded {len(native_tools)} native tools with workspace_context")
            except Exception as e:
                logger.error(f"Failed to load native tools: {e}")

        # Load real memory tools if requested (PostgreSQL-backed SimpleMemory)
        if requested_memory_native:
            try:
                from db.database import AsyncSessionLocal
                from core.agents.memory import get_or_create_memory

                db_session = AsyncSessionLocal()
                memory_system = get_or_create_memory(
                    project_id=project_id,
                    agent_id=f"task_{task_id}",
                    db_session=db_session,
                )
                memory_tools = memory_system.create_memory_tools()
                tools.extend(memory_tools)
                logger.info(
                    f"✓ Loaded {len(memory_tools)} memory tools "
                    f"(PG-backed, {memory_system.memory_count} cached)"
                )
            except Exception as e:
                logger.error(f"Failed to add memory tools: {e}. Proceeding without them.")

        # Load CLI tools (command-line integrations)
        if config.cli_tools:
            try:
                cli_tools = await AgentFactory._load_cli_tools(config.cli_tools)
                tools.extend(cli_tools)
                logger.info(f"Loaded {len(cli_tools)} CLI tools")
            except Exception as e:
                logger.error(f"Failed to load CLI tools: {e}")

        # Load custom tools (user-defined tools from database)
        if config.custom_tools:
            try:
                logger.info(f"Custom tools requested: {config.custom_tools}")
                custom_tools = await AgentFactory._load_custom_tools(config.custom_tools, project_id)
                tools.extend(custom_tools)
                logger.info(f"Loaded {len(custom_tools)} custom tools: {[t.name for t in custom_tools]}")
            except Exception as e:
                logger.error(f"Failed to load custom tools: {e}")
                logger.exception("Custom tool loading stack trace:")

        return tools

    @staticmethod
    async def _prepare_subagents(
        subagent_configs: List[SubAgentConfig],
        enable_compiled: bool = True,
        project_id: int = None,
        task_id: int = None,
        workflow_id: int = None,
        custom_output_path: Optional[str] = None,
        mcp_manager=None,
        vector_store=None
    ) -> List[Any]:
        """
        Prepare subagent configurations for DeepAgents.

        Supports both dictionary-based and CompiledSubAgent (workflow-based).

        Args:
            subagent_configs: List of subagent configurations
            enable_compiled: Whether to enable CompiledSubAgent support
            project_id: Project ID for workflow loading
            task_id: Task ID for context
            workflow_id: Workflow ID for file organization
            custom_output_path: Custom output directory for file writes
            mcp_manager: MCP manager instance
            vector_store: Vector store instance

        Returns:
            List of subagent configurations (dicts or CompiledSubAgent objects)
        """
        from deepagents import CompiledSubAgent
        from sqlalchemy.orm import Session
        from db.database import get_db

        subagents = []
        visited_workflows = set()  # For circular dependency detection

        # Build workspace context for file-writing tools in subagents
        workspace_context = {
            "project_id": project_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "custom_output_path": custom_output_path,
        } if custom_output_path or workflow_id else None

        for sub_config in subagent_configs:
            # Dictionary-based subagent (simple)
            if sub_config.type == SubAgentType.DICTIONARY:
                # IMPORTANT: Load actual tool objects, not just tool names
                # The deepagents library expects tools as BaseTool/Callable/dict objects,
                # not string names. We need to resolve tool names to actual tools.
                subagent_tools = []
                if sub_config.tools:
                    try:
                        from core.agents.factory import AgentFactory
                        # Load native tools by name (with workspace context for file writes)
                        subagent_tools = await AgentFactory._load_native_tools(
                            sub_config.tools,
                            workspace_context=workspace_context
                        )
                        logger.info(f"Loaded {len(subagent_tools)} tools for subagent '{sub_config.name}': {sub_config.tools}")
                    except Exception as e:
                        logger.warning(f"Failed to load tools for subagent '{sub_config.name}': {e}")

                subagent = {
                    "name": sub_config.name,
                    "description": sub_config.description,
                    "system_prompt": sub_config.system_prompt or "",
                    "tools": subagent_tools,  # Actual tool objects, not string names
                }

                if sub_config.model:
                    subagent["model"] = sub_config.model

                if sub_config.interrupt_on:
                    subagent["interrupt_on"] = sub_config.interrupt_on

                if sub_config.middleware:
                    # Convert middleware string names to actual middleware instances via factory
                    try:
                        resolved_middleware = await DeepAgentFactory._resolve_subagent_middleware(
                            sub_config.middleware,
                            sub_config.name
                        )
                        subagent["middleware"] = resolved_middleware
                    except Exception as e:
                        logger.warning(f"Failed to resolve middleware for subagent '{sub_config.name}': {e}")

                if sub_config.skills:
                    subagent["skills"] = sub_config.skills

                if sub_config.response_format:
                    subagent["response_format"] = sub_config.response_format

                subagents.append(subagent)
                logger.info(f"Dictionary subagent prepared: {sub_config.name} with {len(subagent_tools)} tools")

            # Workflow-based CompiledSubAgent
            elif sub_config.type == SubAgentType.COMPILED:
                if not enable_compiled:
                    logger.warning(
                        f"CompiledSubAgent '{sub_config.name}' skipped - feature disabled. "
                        f"Enable with enable_compiled_subagents=True"
                    )
                    continue

                if not sub_config.workflow_id:
                    logger.error(f"CompiledSubAgent '{sub_config.name}' missing workflow_id")
                    continue

                # Detect circular dependencies
                if sub_config.workflow_id in visited_workflows:
                    logger.error(
                        f"Circular dependency detected: workflow {sub_config.workflow_id} "
                        f"already in subagent chain"
                    )
                    continue

                visited_workflows.add(sub_config.workflow_id)

                try:
                    # Load and compile the workflow
                    compiled_workflow = await DeepAgentFactory._load_and_compile_workflow(
                        workflow_id=sub_config.workflow_id,
                        project_id=project_id,
                        task_id=task_id,
                        mcp_manager=mcp_manager,
                        vector_store=vector_store,
                        visited_workflows=visited_workflows
                    )

                    if compiled_workflow:
                        compiled_subagent = CompiledSubAgent(
                            name=sub_config.name,
                            description=sub_config.description,
                            runnable=compiled_workflow
                        )
                        subagents.append(compiled_subagent)
                        logger.info(f"CompiledSubAgent prepared: {sub_config.name} (workflow {sub_config.workflow_id})")
                    else:
                        logger.error(f"Failed to compile workflow {sub_config.workflow_id} for subagent {sub_config.name}")

                except Exception as e:
                    logger.error(f"Error preparing CompiledSubAgent '{sub_config.name}': {e}", exc_info=True)
                    continue

            else:
                logger.warning(f"Unknown subagent type: {sub_config.type} for {sub_config.name}")

        logger.info(f"Prepared {len(subagents)} subagents total")
        return subagents

    @staticmethod
    async def _resolve_subagent_middleware(
        middleware_names: List[str],
        subagent_name: str
    ) -> list:
        """
        Resolve middleware string names to actual middleware instances for subagents.

        Args:
            middleware_names: List of middleware names (e.g. ['todo_list', 'filesystem'])
            subagent_name: Subagent name for logging

        Returns:
            List of middleware instances
        """
        resolved = []
        for name in middleware_names:
            if name == 'todo_list':
                from deepagents.middleware.todo_list import TodoListMiddleware
                resolved.append(TodoListMiddleware())
                logger.info(f"  Subagent '{subagent_name}': added TodoListMiddleware")
            elif name == 'filesystem':
                from deepagents.middleware.filesystem import FilesystemMiddleware
                from deepagents.backends.filesystem import FilesystemBackend
                resolved.append(FilesystemMiddleware(backend=FilesystemBackend()))
                logger.info(f"  Subagent '{subagent_name}': added FilesystemMiddleware")
            else:
                logger.warning(f"  Subagent '{subagent_name}': unknown middleware '{name}', skipping")
        return resolved

    @staticmethod
    async def _load_and_compile_workflow(
        workflow_id: int,
        project_id: int,
        task_id: int,
        mcp_manager,
        vector_store,
        visited_workflows: set
    ):
        """
        Load and compile a workflow to use as a CompiledSubAgent.

        Args:
            workflow_id: ID of the workflow to load
            project_id: Project ID for context
            task_id: Task ID for context
            mcp_manager: MCP manager instance
            vector_store: Vector store instance
            visited_workflows: Set of already visited workflow IDs (for circular detection)

        Returns:
            Compiled LangGraph workflow ready to use as a subagent
        """
        from db.database import get_db
        from models.workflow import WorkflowProfile
        from core.workflows.executor import SimpleWorkflowExecutor

        logger.info(f"Loading workflow {workflow_id} for CompiledSubAgent...")

        # Acquire session BEFORE try block - guarantees finally can close it
        db = next(get_db())
        try:
            # Load workflow from database
            workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == workflow_id).first()

            if not workflow:
                logger.error(f"Workflow {workflow_id} not found in database")
                return None

            # Check for circular dependencies in workflow nodes
            # If any node in this workflow has a subagent that references a workflow in visited_workflows,
            # we have a circular dependency
            workflow_data = workflow.workflow_data or {}
            nodes = workflow_data.get('nodes', [])

            for node in nodes:
                node_config = node.get('data', {}).get('config', {})
                node_subagents = node_config.get('subagents', [])

                for subagent in node_subagents:
                    if isinstance(subagent, dict) and subagent.get('type') == 'compiled':
                        sub_workflow_id = subagent.get('workflow_id')
                        if sub_workflow_id in visited_workflows:
                            logger.error(
                                f"Circular dependency detected in workflow {workflow_id}: "
                                f"node references workflow {sub_workflow_id} which is already in the chain"
                            )
                            return None

            # Create executor and build the graph
            executor = SimpleWorkflowExecutor()
            graph = await executor._build_graph_from_workflow(workflow)

            # Compile the graph (without checkpointing for subagents - they use parent's checkpoint)
            compiled_graph = graph.compile()

            logger.info(f"Successfully compiled workflow {workflow_id} ({workflow.name}) for CompiledSubAgent")
            return compiled_graph

        except Exception as e:
            logger.error(f"Error loading/compiling workflow {workflow_id}: {e}", exc_info=True)
            return None
        finally:
            db.close()  # Always closes - no conditional check needed

    @staticmethod
    async def _setup_callbacks(project_id: int, task_id: int) -> List[Any]:
        """Setup callbacks for logging and monitoring."""
        callbacks = []

        # Add Langfuse callback if available
        try:
            from langfuse.callback import CallbackHandler
            callback = CallbackHandler(
                tags=[f"project_{project_id}", f"task_{task_id}", "deepagent"]
            )
            callbacks.append(callback)
            logger.info("Langfuse callback added")
        except ImportError:
            pass

        return callbacks

    @staticmethod
    async def _fallback_to_regular_agent(
        config: DeepAgentConfig,
        project_id: int,
        task_id: int,
        context: str,
        mcp_manager,
        vector_store
    ) -> Tuple[CompiledStateGraph, List[BaseTool], List[Any]]:
        """
        Fallback to regular AgentFactory if DeepAgents fails.

        This ensures backward compatibility and graceful degradation.
        """
        logger.info("Using regular AgentFactory as fallback")

        # Convert DeepAgentConfig to regular agent_config for fallback
        agent_config = {
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "system_prompt": config.system_prompt,
            "native_tools": config.native_tools,
            "cli_tools": config.cli_tools,
            "custom_tools": config.custom_tools,
            "enable_memory": False,
            "enable_rag": False,
        }

        # Use existing AgentFactory
        return await AgentFactory.create_agent(
            agent_config=agent_config,
            project_id=project_id,
            task_id=task_id,
            context=context,
            mcp_manager=mcp_manager,
            vector_store=vector_store
        )

    @staticmethod
    def create_default_config(
        template_id: Optional[str] = None,
        **overrides
    ) -> DeepAgentConfig:
        """
        Create a default DeepAgent configuration.

        Args:
            template_id: Optional base template to extend
            **overrides: Override specific config values

        Returns:
            DeepAgentConfig with defaults
        """
        from models.deep_agent import (
            create_default_middleware_config,
            create_default_backend_config,
            create_default_guardrails_config
        )

        # Use DeepAgents standard filesystem tools + web_search for research
        # See: https://docs.langchain.com/oss/python/deepagents/harness
        from tools.native_tools import FILESYSTEM_TOOLS

        # Default tools: filesystem + web_search for research capabilities
        default_tools = FILESYSTEM_TOOLS + ["web_search"]

        config = {
            "model": "claude-sonnet-4-5-20250929",
            "temperature": 0.7,
            "system_prompt": "You are a helpful AI assistant with planning and research capabilities.",
            "tools": [],
            "native_tools": default_tools,  # Filesystem + web_search for research
            "cli_tools": [],
            "custom_tools": [],
            "use_deepagents": True,
            "middleware": create_default_middleware_config(),
            "subagents": [],
            "backend": create_default_backend_config(),
            "guardrails": create_default_guardrails_config(),
        }

        # Apply template if specified
        if template_id:
            template_config = DeepAgentFactory._load_template_config(template_id)
            config.update(template_config)

        # Apply overrides
        config.update(overrides)

        return DeepAgentConfig(**config)

# DeepAgent library v0.6.8 already provides:
#   - StateBackend, StoreBackend, CompositeBackend (deepagents.backends)
#   - FilesystemBackend, LocalShellBackend, LangSmithSandbox
# Use those directly. See https://docs.langchain.com/oss/python/deepagents/backends

