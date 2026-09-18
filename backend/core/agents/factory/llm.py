# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""LLM creation with fallbacks, middleware/hook setup, subagent task tool, and callbacks.

Split out of core/agents/factory.py; moved verbatim. The concrete
``AgentFactory`` class (defined in the package ``__init__``) subclasses
this mixin. Bare ``AgentFactory.`` references in staticmethod bodies are
late-bound into this module's globals by ``_bind_runtime``.
"""

from typing import Any, Dict, List, Optional, Sequence

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel, BaseLanguageModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, BaseTool
from langchain_core.tools import tool as tool_decorator
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

from core.state import DeepAgentState
from services.agent_utils import create_llm_with_fallbacks, resolve_model

from .shared import logger


class _AgentLLMMixin:

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
    async def _build_subagent_task_tool(
        tools: List[BaseTool],
        subagents_config: List[Dict[str, Any]],
        agent_config: Dict[str, Any],
        parent_llm: BaseChatModel,
        temperature: float,
        max_tokens: Optional[int],
        workspace_context: Dict[str, Any],
        agent_context: Optional[Dict[str, Any]],
    ) -> None:
        """
        Build a sub-agent-embedding 'task' tool and append it to ``tools``.

        Each sub-agent in ``subagents_config`` gets its own isolated context,
        inheriting the parent's tools and (optionally) loading additional
        tools by name. The returned 'task' tool delegates to the matching
        sub-agent and propagates its output back to the parent via Command.

        Mutates ``tools`` in place: removes any existing generic 'task' tool
        and appends the new delegation tool.
        """
        # Remove the generic 'task' tool from the parent's toolset so it can
        # be replaced with our sub-agent-embedding version.
        for i, t in enumerate(tools):
            if hasattr(t, 'name') and t.name == 'task':
                tools.pop(i)
                logger.info("Removed generic 'task' tool — replacing with sub-agent-embedding task tool")
                break

        # Build sub-agents with isolated contexts (notebook 2.4_full_agent pattern).
        sub_agents: Dict[str, CompiledStateGraph] = {}
        for sa_config in subagents_config:
            sa_name = sa_config.get("name", "subagent")
            sa_prompt = sa_config.get("system_prompt", "") or sa_config.get("prompt", "")
            sa_tool_names = sa_config.get("tools", [])
            sa_model_name = sa_config.get("model")

            # Sub-agent inherits the parent's LLM unless it specifies its own.
            if sa_model_name:
                try:
                    sa_llm = await AgentFactory._create_llm_with_fallbacks(
                        primary_model=sa_model_name,
                        fallback_models=[],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        config=agent_config
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to create LLM for sub-agent '{sa_name}': {e}. Inheriting parent."
                    )
                    sa_llm = parent_llm
            else:
                sa_llm = parent_llm

            # Sub-agent inherits the parent's tool set, then loads any extra
            # tools it needs but the parent doesn't have.
            sa_tools = list(tools)
            parent_tool_names = {t.name for t in sa_tools if hasattr(t, 'name')}
            extra_tool_names = [n for n in sa_tool_names if n not in parent_tool_names]
            if extra_tool_names:
                try:
                    from core.agents.tool_loader import ToolLoader
                    extra_tools = await ToolLoader.load_native(
                        extra_tool_names,
                        workspace_context=workspace_context,
                        agent_context=agent_context
                    )
                    existing_names = {t.name for t in sa_tools if hasattr(t, 'name')}
                    for t in extra_tools:
                        if hasattr(t, 'name') and t.name not in existing_names:
                            sa_tools.append(t)
                except Exception as e:
                    logger.warning(f"Failed to load extra tools for sub-agent '{sa_name}': {e}")
            logger.info(
                f"Sub-agent '{sa_name}': {len(sa_tools)} tools "
                f"(inherited {len(tools)} parent + {len(extra_tool_names)} extra)"
            )

            sub_agents[sa_name] = create_agent(
                sa_llm,
                system_prompt=sa_prompt,
                tools=sa_tools,
                state_schema=DeepAgentState,
            )

        # Build the 'task' tool description listing all available sub-agents.
        task_description = (
            "Delegate a task to a specialized sub-agent with isolated context. "
            "Available agents for delegation are:\n"
            + "\n".join(
                f"- {sa['name']}: {sa.get('description', 'No description')}"
                for sa in subagents_config
            )
        )

        @tool_decorator(description=task_description)
        async def task(
            description: str,
            subagent_type: str,
            state: Annotated[dict, InjectedState],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ):
            """Delegate a task to a specialized sub-agent with isolated context."""
            if subagent_type not in sub_agents:
                allowed = [f"`{k}`" for k in sub_agents.keys()]
                return f"Error: unknown subagent type '{subagent_type}'. Allowed: {allowed}"

            sub_agent = sub_agents[subagent_type]
            # Isolated context with only the task description.
            state["messages"] = [{"role": "user", "content": description}]
            result = await sub_agent.ainvoke(state)

            # Return results to parent agent via Command state update.
            return Command(
                update={
                    "files": result.get("files", {}),
                    "messages": [
                        ToolMessage(
                            result["messages"][-1].content, tool_call_id=tool_call_id
                        )
                    ],
                }
            )

        tools.append(task)
        logger.info(
            f"Created custom task tool with {len(sub_agents)} sub-agents: "
            f"{list(sub_agents.keys())}"
        )

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
