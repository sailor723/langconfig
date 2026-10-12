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
            # Plugins (LangChain-style, backend/plugins/<name>): their skills
            # are filesystem SKILL.md dirs, not DB rows — persist them under
            # the same storage keys so DbBackend serves them alongside the
            # catalog. Each plugin gets its OWN source path
            # (/skills/plugins/<plugin>) because the SkillsMiddleware expects
            # source/<skill-name>/SKILL.md (one level of skill dirs below the
            # source); the plugin name is the namespace.
            plugin_sources = _stage_plugin_skills_to_storage(
                getattr(config, "plugins", None) or [],
                storage,
                skill_storage_key,
            )
            skills_sources = [f"/skills/{t}" for t in types] + [
                f"/skills/plugins/{p}" for p in plugin_sources
            ]
            logger.info(
                f"Registered {len(skill_records)} skill(s) from storage + "
                f"{len(plugin_sources)} plugin source(s) "
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

        # Plugins (LangChain-style, backend/plugins/<name>): stage their skills
        # into the same catalog. Each plugin's skills land under
        # skills/plugins/<plugin>/<skill>/SKILL.md and the plugin namespace dir
        # becomes its own source ("skills/plugins/<plugin>") so the
        # SkillsMiddleware sees source/<skill-name>/SKILL.md — one level of
        # skill dirs below each source, exactly what it expects.
        plugin_names = getattr(config, "plugins", None) or []
        if plugin_names:
            try:
                from core.plugins import get_plugin_loader

                loader = get_plugin_loader()
                plugins = loader.resolve_many(plugin_names)
                staged_paths = loader.stage_plugin_skills(
                    plugins,
                    skills_dir,
                    namespace="plugins",
                )
                plugin_sources = []
                for p in plugins:
                    if any(
                        f"plugins/{p.name}/" in sp for sp in staged_paths
                    ):
                        plugin_sources.append(f"skills/plugins/{p.name}")
                if plugin_sources:
                    staged += len(staged_paths)
                    skills_sources = skills_sources + plugin_sources
                    logger.info(
                        "Staged %d plugin skill(s) from plugins=%s into %s "
                        "(sources=%s)",
                        len(staged_paths), plugin_names, skills_dir, plugin_sources,
                    )
            except Exception as exc:  # noqa: BLE001 — plugins must never break agent build
                logger.warning(f"Plugin skill staging failed (non-fatal): {exc}")

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


def _stage_plugin_skills_to_storage(
    plugin_names: List[str],
    storage: Any,
    skill_storage_key,
) -> List[str]:
    """Persist plugin skills (filesystem SKILL.md dirs) into DB storage.

    DbBackend serves ``/skills/<source>/...`` from storage. Plugin skills are
    not DB rows, so we write them under ``skills/plugins/<plugin>/<skill>/``
    keys. The SKILL.md body is stored; bundled scripts are referenced from
    SKILL.md but not persisted (same limitation as DB-synced skills).

    Returns the list of plugin names that staged at least one skill (each
    becomes a separate /skills/plugins/<plugin> source for the middleware).
    """
    try:
        from core.plugins import get_plugin_loader

        loader = get_plugin_loader()
        plugins = loader.resolve_many(plugin_names)
        staged_plugins: List[str] = []
        for plugin in plugins:
            staged_any = False
            for skill_dir in plugin.skill_dirs:
                md = skill_dir / "SKILL.md"
                if not md.is_file():
                    continue
                rel = f"skills/plugins/{plugin.name}/{skill_dir.name}/SKILL.md"
                storage.save(rel, md.read_bytes(), "text/markdown")
                staged_any = True
            if staged_any:
                staged_plugins.append(plugin.name)
        if staged_plugins:
            logger.info(
                f"Persisted plugin skill(s) to storage for plugins={staged_plugins}"
            )
        return staged_plugins
    except Exception as exc:  # noqa: BLE001 — plugins must never break agent build
        logger.warning(f"Plugin skill storage staging failed (non-fatal): {exc}")
        return []


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
                # Imported here, not later in the function: the filesystem
                # block further down binds this name, and a name bound anywhere
                # in a function is function-local, so referencing it before that
                # assignment raised UnboundLocalError — the warning was
                # swallowed and MemoryMiddleware silently never loaded.
                from deepagents.backends.filesystem import FilesystemBackend
                from services.agents_md_service import ensure_agents_md_exists
                from pathlib import Path as _Path

                # If the agent has its own AGENTS.md (materialized into its
                # workspace by the chat path from agent_docs), MemoryMiddleware
                # reads that — the agent's instructions take precedence over
                # the project default.
                if workspace_root and (_Path(workspace_root) / "AGENTS.md").exists():
                    mem_dir = _Path(workspace_root)
                    mem_backend = FilesystemBackend(root_dir=str(mem_dir))
                    mem_sources = ["AGENTS.md"]
                    logger.info(f"MemoryMiddleware using agent AGENTS.md at {mem_dir}")
                else:
                    agents_md_path = ensure_agents_md_exists(project_id)
                    # FilesystemBackend is scoped to the project root so the
                    # agent can only read/write files within its own project
                    # directory. AGENTS.md lives at projects/{id}/AGENTS.md,
                    # so we use a backend with root_dir = projects/{id}.
                    mem_backend = FilesystemBackend(
                        root_dir=str(agents_md_path.parent)
                    )
                    mem_sources = [agents_md_path.name]  # relative to root_dir
                    logger.info(
                        f"MemoryMiddleware initialized: AGENTS.md={agents_md_path}"
                    )
                mem_middleware = MemoryMiddleware(
                    backend=mem_backend,
                    sources=mem_sources,
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
                from services.workspace_filesystem_backend import (
                    WorkspaceFilesystemBackend,
                )
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

                # Use WorkspaceFilesystemBackend with task workspace as root:
                # same disk persistence as FilesystemBackend, but re-bases
                # absolute paths that fall inside the workspace so an agent
                # that passes its full workspace path (from the identity
                # block) writes into the workspace instead of creating a
                # nested <workspace>/Users/... tree.
                fs_backend = WorkspaceFilesystemBackend(root_dir=str(workspace_path))
                fs_middleware = FilesystemMiddleware(backend=fs_backend)
                instrumented_fs = instrument_deepagents_middleware(
                    fs_middleware,
                    callback_handler=callback_handler
                )
                middleware_instances.append(instrumented_fs)
                logger.info(f"FilesystemMiddleware initialized with workspace: {workspace_path}")
            except ImportError as e:
                logger.warning(f"FilesystemMiddleware not available: {e}")

        # Summarization: decide it here, ATTACH it after the agent's backend is
        # chosen (see the "SummarizationMiddleware" block further down). It
        # offloads evicted history to that backend, so the file it writes must
        # be one the agent can re-open through its own file tools.
        summarization_spec = None
        if config.guardrails and config.guardrails.enable_summarization:
            try:
                # langchain >= 1.3.14 renamed the context-size kind "token" -> "tokens"
                trigger = ("tokens", config.guardrails.token_limits.get("summarization_threshold", 60000))
                # How many recent messages survive compaction; everything older
                # is folded into the running summary (and offloaded to the
                # backend). 20 is the historical default — raise it to keep more
                # verbatim, lower it to reclaim more context per compaction.
                keep = ("messages", int(config.guardrails.token_limits.get("keep_last_messages", 20)))
                # Resolve the summarizer model exactly like the agent's own
                # model: provider from the `models` table and credentials from
                # the `models.api_keys` document, both in PostgreSQL.
                #
                # Passing the bare id string (model=config.model) used to route
                # through LangChain's init_chat_model, which reads credentials
                # from os.environ ONLY. Nothing in this app exports keys to the
                # environment (they live in the DB), so the constructor always
                # raised ValidationError and the warning was swallowed below —
                # summarization was silently absent no matter how low the
                # threshold was set.
                summarization_spec = {
                    "model": await resolve_model(
                        config.model or DEFAULT_MODEL,
                        config.temperature,
                        config.max_tokens or 4096,
                        {"streaming": False},
                    ),
                    "trigger": trigger,
                    "keep": keep,
                }
                logger.info(
                    "Summarization enabled: model=%s trigger=%s keep=%s",
                    config.model or DEFAULT_MODEL, trigger, keep,
                )
            except Exception as e:
                summarization_spec = None
                logger.warning(f"Summarization configuration failed: {e}")

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

        # Web-research efficiency hints (same as regular agents): without
        # these, research questions loop through dozens of one-at-a-time
        # web_search calls with rate-limit retries.
        _tool_names = {getattr(t, "name", "") for t in all_tools}
        if _tool_names & {"web_search", "tavily_search", "web_fetch", "ddg_search"}:
            final_system_prompt += (
                "\n\n# Web research efficiency\n"
                "- Batch independent searches: when you need several facts, "
                "issue multiple search tool calls in ONE parallel round.\n"
                "- Never re-search the same fact — reuse results already "
                "returned this conversation.\n"
                "- Prefer fewer, broader queries: aim to finish research "
                "within ~8 search calls; use web_fetch only for a promising "
                "page.\n"
                "- If a search is rate-limited or returns nothing, move on — "
                "do not retry variations of the same query."
            )

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
            #   Without a sandbox we now default to the agent workspace
            #   filesystem (writes land on disk → Files panel) and route only
            #   /skills/ to storage — previously the bare DbBackend made every
            #   file write invisible (stored in the DB seam).
            # - sandbox only: LocalShellBackend (execute tool).
            # - local mode + staged skills: FilesystemBackend over the workspace.
            if db_skills_backend is not None:
                from deepagents.backends.composite import CompositeBackend
                from deepagents.backends.filesystem import FilesystemBackend
                from services.storage import DbBackend
                if local_sandbox_backend is not None:
                    agent_kwargs["backend"] = CompositeBackend(
                        default=local_sandbox_backend,
                        routes={"/skills/": DbBackend(storage_prefix="skills")},
                    )
                else:
                    # Default filesystem root: the agent workspace (chat) or the
                    # staged skills root (workflow). Agent files must land on
                    # disk so the Files panel can show them.
                    _fs_root = workspace_root or (
                        str(skills_staging_root) if skills_staging_root else None
                    )
                    if _fs_root:
                        Path(_fs_root).mkdir(parents=True, exist_ok=True)
                        from services.workspace_filesystem_backend import (
                            WorkspaceFilesystemBackend,
                        )
                        agent_kwargs["backend"] = CompositeBackend(
                            default=WorkspaceFilesystemBackend(root_dir=_fs_root),
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
                from services.workspace_filesystem_backend import (
                    WorkspaceFilesystemBackend,
                )
                agent_kwargs["backend"] = WorkspaceFilesystemBackend(
                    root_dir=str(skills_staging_root)
                )
                # Relative sources: <root>/skills is a container of personal skill
                # dirs; <root>/skills/builtin is the container of builtin skills.
                agent_kwargs["skills"] = skills_sources

            # Multi-format documents: wrap whatever backend was selected so the
            # SDK's write_file/read_file render/extract .html/.pdf/.docx/.pptx
            # (docs/tools-refactor.md — native format-aware renderers reused).
            try:
                from services.format_backend import FormatAwareBackend
                agent_kwargs["backend"] = FormatAwareBackend(agent_kwargs["backend"])
            except Exception as e:
                logger.warning(f"FormatAwareBackend wrap failed (non-fatal): {e}")

            # SummarizationMiddleware — attached here, after the backend is
            # final, so evicted history lands where the agent's own read_file
            # looks for it (/conversation_history/<thread>.md). The model was
            # resolved from PostgreSQL when the spec was built.
            if summarization_spec:
                try:
                    from deepagents.middleware.summarization import SummarizationMiddleware

                    summarization_backend = agent_kwargs.get("backend")
                    if summarization_backend is None:
                        from deepagents.backends import StateBackend
                        summarization_backend = StateBackend()

                    summarization_mw = SummarizationMiddleware(
                        model=summarization_spec["model"],
                        backend=summarization_backend,
                        trigger=summarization_spec["trigger"],
                        keep=summarization_spec["keep"],
                    )
                    middleware_instances.append(
                        instrument_deepagents_middleware(
                            summarization_mw, callback_handler=callback_handler
                        )
                    )
                    # agent_kwargs captured the list object, but it may have
                    # been None when the list was empty — keep them in sync.
                    agent_kwargs["middleware"] = middleware_instances
                    logger.info(
                        "SummarizationMiddleware attached (offload backend=%s)",
                        type(summarization_backend).__name__,
                    )
                except Exception as e:
                    logger.warning(f"SummarizationMiddleware not available: {e}")

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

                # Register a harness profile that documents the multi-format
                # write_file/read_file capability (the SDK's default tool
                # descriptions say only "Writes content to a file" — the model
                # never learns .docx/.pdf/.html are supported unless told).
                # Registered for every deep agent so the SDK's injected
                # FilesystemMiddleware uses our descriptions.
                try:
                    from deepagents import (
                        HarnessProfile as _HP, register_harness_profile as _rhp,
                    )
                    from deepagents._models import (
                        get_model_identifier as _gmi, get_model_provider as _gmp,
                    )
                    from services.fs_tool_descriptions import filesystem_tool_descriptions
                    _mk = f"{_gmp(main_chat_model)}:{_gmi(main_chat_model)}"
                    _rhp(
                        _mk,
                        _HP(tool_description_overrides=filesystem_tool_descriptions()),
                    )
                    logger.info(
                        f"Registered multi-format tool descriptions for {_mk}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to register multi-format descriptions: {e}")

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
