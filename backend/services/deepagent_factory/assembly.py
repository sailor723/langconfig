# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent factory assembly.

The main ``create_deep_agent`` orchestration, extracted from the former
monolithic deepagent_factory.py.
"""

import shutil
from pathlib import Path
from typing import Any, List, Optional, Tuple

from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from models.deep_agent import DeepAgentConfig
from models.enums import MiddlewareType
from core.middleware.deep import DeepAgentsMiddlewareFactory
from services.agent_utils import resolve_model, DEFAULT_MODEL
from .shared import logger


def _is_filesystem_middleware(mw) -> bool:
    """True if `mw` is (a wrapper around) a filesystem middleware.

    The deepagents SDK always injects its own FilesystemMiddleware when a
    backend is active, so the assembly's instrumented copy would duplicate
    the ls/read_file/write_file/... tool set.
    """
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from services.deepagents_instrumentation import (
        InstrumentedFilesystemMiddleware,
    )

    return (
        isinstance(mw, InstrumentedFilesystemMiddleware)
        or isinstance(getattr(mw, "middleware_instance", None), FilesystemMiddleware)
        or isinstance(mw, FilesystemMiddleware)
    )


def _stage_skill_catalog(
    config: DeepAgentConfig,
    local_sandbox_backend: Optional[Any],
    sandbox_path: Optional[Path],
    project_id: Optional[int],
    workflow_id: Optional[int],
    task_id: int,
    custom_output_path: Optional[str],
    workspace_root: Optional[str] = None,
) -> Tuple[Optional[Path], Optional[List[str]], Optional[Any]]:
    """Stage the full skill catalog for SkillsMiddleware (progressive disclosure).

    Classic Anthropic pattern: every agent sees the ENTIRE skill library —
    builtin + personal roots. SkillsMiddleware preloads metadata (name +
    description + path) into the system prompt and the agent reads each
    SKILL.md body on demand with read_file. config.skills, when set, only pins
    extra skills (custom locations / DB-only) for availability; it no longer
    limits what the agent can discover.

    Returns (skills_staging_root, skills_sources, db_skills_backend):
    - db mode: all skills persisted to storage, served via DbBackend.
    - local mode: all skills staged under the backend root, served via
      FilesystemBackend. Builtin root is staged first so personal skills win
      name collisions (later sources override earlier ones in the middleware).
    """
    try:
        from config import settings

        if settings.storage_mode == "db":
            # DB mode: skills are 100% DB-managed (docs/system-architecture.md
            # §15). Persist the FULL catalog under canonical storage keys and
            # serve them via DbBackend, so no FS staging happens in db mode.
            from db.database import SessionLocal
            from models.skill import Skill
            from core.skills.sync import (
                normalize_source_type,
                skill_row_to_markdown,
                skill_storage_key,
            )
            from services.storage import DbBackend, get_storage

            db = SessionLocal()
            try:
                skill_records = db.query(Skill).all()
            finally:
                db.close()

            if not skill_records:
                return None, None, None
            storage = get_storage()
            for s in skill_records:
                storage.save(
                    skill_storage_key(s),
                    skill_row_to_markdown(s).encode("utf-8"),
                    "text/markdown",
                )
            types = sorted({
                normalize_source_type(getattr(s, "source_type", "builtin"))
                for s in skill_records
            })
            skills_sources = [f"/skills/{t}" for t in types]
            logger.info(
                f"Registered {len(skill_records)} skill(s) from storage "
                f"(progressive disclosure via DbBackend, sources={skills_sources})"
            )
            return None, skills_sources, DbBackend()

        # ── local mode ──
        from core.skills.sync import DEFAULT_BUILTIN_SKILLS_ROOT, PERSONAL_SKILLS_ROOT

        if local_sandbox_backend is not None and sandbox_path is not None:
            skills_staging_root = sandbox_path
        elif workspace_root:
            # Per-agent chat workspace: stage skills under the workspace root.
            skills_staging_root = Path(workspace_root).resolve()
        else:
            from services.workspace_manager import get_workspace_manager
            skills_staging_root = get_workspace_manager().get_task_workspace_with_override(
                project_id=project_id,
                workflow_id=workflow_id,
                task_id=task_id,
                custom_output_path=custom_output_path,
            )

        skills_dir = skills_staging_root / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        staged = 0
        for root, target_sub in (
            (DEFAULT_BUILTIN_SKILLS_ROOT, "builtin"),
            (PERSONAL_SKILLS_ROOT, None),
        ):
            if not root.is_dir():
                continue
            for skill_dir in sorted(root.iterdir()):
                if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
                    continue
                dst = skills_dir if target_sub is None else skills_dir / target_sub
                shutil.copytree(skill_dir, dst / skill_dir.name, dirs_exist_ok=True)
                staged += 1
        skills_sources = ["skills/builtin", "skills"]

        # Optional pins: any config.skills entry living outside the global
        # roots is staged additionally (custom-location or DB-only skills).
        pinned = getattr(config, "skills", None) or []
        if pinned:
            from db.database import SessionLocal
            from models.skill import Skill

            db = SessionLocal()
            try:
                skill_records = db.query(Skill).filter(
                    Skill.skill_id.in_(pinned)
                ).all()
            finally:
                db.close()
            for s in skill_records:
                src = Path(s.source_path)
                inside_catalog = (
                    src.is_relative_to(PERSONAL_SKILLS_ROOT)
                    or src.is_relative_to(DEFAULT_BUILTIN_SKILLS_ROOT)
                )
                if not inside_catalog and src.is_dir():
                    shutil.copytree(src, skills_dir / s.skill_id, dirs_exist_ok=True)
                    staged += 1

        logger.info(
            f"Staged {staged} skill(s) from global roots into {skills_dir} "
            f"(progressive disclosure via SkillsMiddleware, sources={skills_sources})"
        )
        return skills_staging_root, skills_sources, None
    except Exception as e:
        logger.warning(f"Failed to register skills: {e}")
        return None, None, None


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
        workspace_root: Optional[str] = None,
        user_message: Optional[str] = None,  # First user message for skill routing
        agent_id: Optional[int] = None,      # Agent id (for file/metadata association)
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
            workspace_root: Explicit root directory for the agent's filesystem
                sandbox and file-writing tools. When set, it is used directly
                (no workflow/task subdirectories appended), e.g. per-agent
                chat workspaces: outputs/agents/agent_{id}.
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
            custom_output_path=custom_output_path,
            workspace_root=workspace_root,
            agent_id=agent_id,
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
            workspace_root=workspace_root,
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
                if workspace_root:
                    # Per-agent chat workspace: use the root as-is (no
                    # workflow/task subdirectories appended).
                    workspace_path = Path(workspace_root).resolve()
                    workspace_path.mkdir(parents=True, exist_ok=True)
                else:
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

                # langchain >= 1.3.14 renamed the context-size kind "token" -> "tokens"
                trigger = ("tokens", config.guardrails.token_limits.get("summarization_threshold", 60000))
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
                if workspace_root:
                    sandbox_path = Path(workspace_root).resolve()
                    sandbox_path.mkdir(parents=True, exist_ok=True)
                elif workflow_id is None:
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

        # ── Skills (progressive disclosure via SkillsMiddleware) ──
        # Classic Anthropic pattern: the FULL skill catalog (builtin + personal
        # roots) is exposed to every agent, not just config.skills. The
        # middleware injects a metadata catalog (name + description + path)
        # into the system prompt and the agent reads each SKILL.md body on
        # demand with the built-in read_file tool. config.skills, when set,
        # only *pins* skills for availability (and feeds skill-subagent
        # synthesis in deep_agents.py); discovery is metadata-driven for the
        # whole catalog.
        skills_staging_root, skills_sources, db_skills_backend = _stage_skill_catalog(
            config=config,
            local_sandbox_backend=local_sandbox_backend,
            sandbox_path=sandbox_path,
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            custom_output_path=custom_output_path,
            workspace_root=workspace_root,
        )

        # Deduplicate filesystem tools when a disk backend is used.
        # deepagents always adds its own FilesystemMiddleware (required, cannot
        # be excluded), which ships ls/read_file/write_file/edit_file/glob/grep
        # scoped to the backend root. create_agent/bind_tools do NOT dedupe by
        # name, so keeping our native copies would double those tools in the
        # model schema. With a backend in play the library's versions are
        # workspace-scoped (same directory), so we drop our native duplicates.
        # Without a backend (plain chat) the library's fs tools are in-memory
        # StateBackend no-ops, so our natives stay and keep disk writes working.
        has_disk_backend = (
            local_sandbox_backend is not None
            or skills_staging_root is not None
            or db_skills_backend is not None
        )
        if has_disk_backend:
            # deepagents ALWAYS injects its own FilesystemMiddleware (verified
            # in deepagents/graph.py) scoped to the backend root. Our
            # instrumented copy would add a second ls/read_file/write_file/…
            # set with a DIFFERENT root — duplicated tools resolved last-wins
            # by accident. Drop ours; the SDK's is the workspace-scoped one.
            before = len(middleware_instances)
            middleware_instances = [
                mw for mw in middleware_instances
                if not _is_filesystem_middleware(mw)
            ]
            if len(middleware_instances) != before:
                logger.info(
                    f"Dropped duplicate FilesystemMiddleware from the middleware "
                    f"stack ({before - len(middleware_instances)} removed — the "
                    "deepagents SDK injects its own when a backend is active)"
                )
        if has_disk_backend:
            native_fs_collisions = {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
            all_tools = [t for t in all_tools if t.name not in native_fs_collisions]
            logger.info(
                "Dropped native fs tools (library provides them via backend): "
                f"{sorted(native_fs_collisions)}"
            )

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
            }

            # Backend selection (docs/system-architecture.md §15):
            # - db mode + skills: DbBackend serves /skills from storage; when a
            #   sandbox is active, a CompositeBackend routes /skills/ to storage
            #   and keeps everything else (incl. `execute`) in the sandbox.
            # - sandbox only: LocalShellBackend (execute tool).
            # - local mode + staged skills: FilesystemBackend over the workspace.
            if db_skills_backend is not None:
                if local_sandbox_backend is not None:
                    from deepagents.backends.composite import CompositeBackend
                    from services.storage import DbBackend
                    agent_kwargs["backend"] = CompositeBackend(
                        default=local_sandbox_backend,
                        routes={"/skills/": DbBackend(storage_prefix="skills")},
                    )
                else:
                    agent_kwargs["backend"] = db_skills_backend
                agent_kwargs["skills"] = skills_sources
            elif local_sandbox_backend is not None:
                # Pass LocalShellBackend so the agent gains the `execute` tool for
                # running scripts (Python, shell commands, pip install, etc.)
                agent_kwargs["backend"] = local_sandbox_backend
            elif skills_staging_root is not None:
                # Skills need a disk-backed backend (StateBackend is in-memory)
                # so SkillsMiddleware can list the staged SKILL.md files.
                from deepagents.backends.filesystem import FilesystemBackend
                agent_kwargs["backend"] = FilesystemBackend(
                    root_dir=str(skills_staging_root)
                )
                # Relative sources: <root>/skills is a container of personal skill
                # dirs; <root>/skills/builtin is the container of builtin skills.
                agent_kwargs["skills"] = skills_sources

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
                        # The profile key must match what the SDK's
                        # _harness_profile_for_model derives for a pre-built
                        # model: "provider:identifier". Derive it from the
                        # resolved model (previously an undefined `_model_str`
                        # NameError made this whole block dead code).
                        from deepagents._models import (
                            get_model_identifier, get_model_provider,
                        )
                        _profile_key = (
                            f"{get_model_provider(main_chat_model)}:"
                            f"{get_model_identifier(main_chat_model)}"
                        )
                        register_harness_profile(
                            _profile_key,
                            HarnessProfile(
                                excluded_tools=frozenset({
                                    "write_todos", "update_todo_status", "get_todos",
                                    "ls", "glob", "grep", "execute",
                                    "task",
                                }),
                            ),
                        )
                        logger.info(
                            f"Registered harness profile for {_profile_key} "
                            f"with built-in tools excluded"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to register harness profile: {e}")

                # deepagents 0.7.x has NO `guardrails=` parameter (verified
                # signature) — passing it always raised TypeError and the
                # guardrails config was silently dropped. Only `interrupts`
                # is enforceable here via agent_kwargs["interrupt_on"] above;
                # token limits / auto-eviction are not enforced by the SDK.
                if guardrails_config:
                    if guardrails_config.get("enable_auto_eviction") or (
                        guardrails_config.get("token_limits")
                        and guardrails_config.get("enable_summarization")
                    ):
                        logger.warning(
                            "deepagents 0.7.x does not accept guardrails= — "
                            "token_limits/auto_eviction are not enforced. "
                            "Summarization is handled by SummarizationMiddleware; "
                            "configure token limits there instead."
                        )
                agent = create_deep_agent(**agent_kwargs)
                logger.info(f"DeepAgent created (guardrails.interrupts → interrupt_on={bool(interrupt_on)})")
            except Exception:
                logger.error("Failed to configure guardrails/interrupts", exc_info=True)
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
            # Only the missing-deepagents case (handled above, ImportError)
            # is a legitimate reason to silently degrade to a regular agent.
            # Any other build failure must surface to the caller instead of
            # quietly producing a plain agent with no skills/subagents/
            # sandbox/memory.
            logger.error(
                "DeepAgent build failed (NOT falling back to a regular agent) — "
                "surface the error to the caller",
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to build DeepAgent: {type(e).__name__}: {e}"
            ) from e


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
