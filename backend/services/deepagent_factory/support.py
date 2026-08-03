# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent factory support helpers.

Tool loading, subagent preparation, middleware resolution, workflow
compilation, callbacks, and the regular-agent fallback — extracted from the
former monolithic deepagent_factory.py.
"""

from typing import Any, List, Optional, Tuple

from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from models.deep_agent import DeepAgentConfig, SubAgentConfig
from models.enums import SubAgentType
from core.agents.factory import AgentFactory
from services.agent_utils import load_agent_tools
from .shared import logger


class _DeepAgentSupportMixin:
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
        """Load tools from configuration using shared agent_utils."""
        workspace_context = {
            "project_id": project_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "custom_output_path": custom_output_path,
        } if (custom_output_path or workflow_id) else None
        return await load_agent_tools(
            native_tool_names=config.native_tools or [],
            cli_tool_names=config.cli_tools or [],
            custom_tool_ids=config.custom_tools or [],
            workspace_context=workspace_context,
            project_id=project_id,
            task_id=task_id,
        )

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
                # NOTE: If sub_config.tools is empty/None, DO NOT set "tools" key at all,
                # so the subagent inherits the main agent's tools by default.
                # Setting tools=[] would override inheritance with zero tools.
                subagent_tools = None
                if sub_config.tools:
                    try:
                        from core.agents.tool_loader import ToolLoader
                        subagent_tools = await ToolLoader.load_native(sub_config.tools)
                        logger.info(f"Loaded {len(subagent_tools)} tools for subagent '{sub_config.name}': {sub_config.tools}")
                    except Exception as e:
                        logger.warning(f"Failed to load tools for subagent '{sub_config.name}': {e}")

                subagent = {
                    "name": sub_config.name,
                    "description": sub_config.description,
                    "system_prompt": sub_config.system_prompt or "",
                }

                # Only add tools key if tools were explicitly provided (inherits otherwise)
                if subagent_tools:
                    subagent["tools"] = subagent_tools

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
                logger.info(f"Dictionary subagent prepared: {sub_config.name} with {len(subagent_tools or [])} tools")

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
                # deepagents >= 0.7 removed the built-in TodoListMiddleware;
                # task tracking is covered by the native write_todos/read_todos
                # tools on the main agent, so subagents just skip it.
                try:
                    from deepagents.middleware.todo_list import TodoListMiddleware
                    resolved.append(TodoListMiddleware())
                    logger.info(f"  Subagent '{subagent_name}': added TodoListMiddleware")
                except ImportError:
                    logger.info(
                        f"  Subagent '{subagent_name}': todo_list middleware not "
                        f"available in deepagents >= 0.7, skipping"
                    )
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
