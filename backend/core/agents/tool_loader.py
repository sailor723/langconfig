# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
ToolLoader — extracted from AgentFactory (2026-06-24).

Responsible for loading and wrapping the 5 categories of tools that an
agent can have:
  1. Native tools (built-in: web_search, write_file, etc.)
  2. CLI tools (Jira, git, docker)
  3. Custom tools (user-defined in DB)
  4. Memory tools (vector store backed)
  5. RAG tools (codebase search)

This module is pure logic — no agent state, no global state, no side effects
beyond DB reads for custom tools. It was previously embedded in
AgentFactory (factory.py:1332-1604) and grew too large.

Public API:
    ToolLoader.load_all(agent_config, workspace_context, project_id, vector_store, task_id)
        → Returns List[BaseTool] for the entire agent

Each individual loader is also exposed as a staticmethod for callers that
only need one category.

Usage (from AgentFactory):
    from core.agents.tool_loader import ToolLoader

    tools = await ToolLoader.load_all(
        agent_config=agent_config,
        workspace_context=workspace_context,
        project_id=project_id,
        vector_store=vector_store,
        task_id=task_id,
    )
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)


class ToolLoader:
    """Loads and wraps tools for agent creation.

    All methods are static — this is a namespace for related tool-loading
    helpers, not an instance-based service. Keeping them static makes
    the call sites readable (no need to instantiate) and matches the
    original `AgentFactory._load_*_tools()` staticmethod signatures.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @staticmethod
    async def load_all(
        agent_config: Dict[str, Any],
        workspace_context: Optional[Dict[str, Any]],
        project_id: int,
        vector_store: Any = None,
        task_id: int = 0,
    ) -> List[BaseTool]:
        """Load all 5 tool categories and return a flat list.

        Mirrors the original Step-3 logic that lived in
        AgentFactory.create_agent (factory.py ~L425-490). Each category
        is loaded only if its corresponding config flag / list is set.
        """
        tools: List[BaseTool] = []

        # 1. Native tools by name
        native_tool_names = agent_config.get("native_tools", [])
        if native_tool_names:
            agent_context = agent_config.get("agent_context")  # optional
            tools.extend(await ToolLoader.load_native(
                native_tool_names,
                workspace_context=workspace_context,
                agent_context=agent_context,
            ))

        # 2. CLI tools
        cli_tools = agent_config.get("cli_tools", [])
        if cli_tools:
            tools.extend(await ToolLoader.load_cli(cli_tools))

        # 3. Custom tools by DB ID
        custom_tool_ids = agent_config.get("custom_tools", [])
        if custom_tool_ids:
            tools.extend(await ToolLoader.load_custom(custom_tool_ids, project_id))

        # 4. Memory tools (if memory enabled)
        if agent_config.get("enable_memory"):
            tools.extend(await ToolLoader.load_memory(
                vector_store, project_id, task_id,
            ))

        # 5. RAG tools (if RAG enabled)
        if agent_config.get("enable_rag"):
            tools.extend(await ToolLoader.load_rag(vector_store, project_id))

        return tools

    # ------------------------------------------------------------------
    # Category 1: Native tools
    # ------------------------------------------------------------------

    @staticmethod
    async def load_native(
        native_tool_names: List[str],
        workspace_context: Optional[Dict[str, Any]] = None,
        agent_context: Optional[Dict[str, Any]] = None,
    ) -> List[BaseTool]:
        """
        Load native Python tools.

        Special handling for "browser" tool which uses Playwright (async).
        For write_file tool, binds workspace_context and agent_context for
        file metadata tracking.

        Args:
            native_tool_names: List of tool names to load
            workspace_context: Context about the workspace (project_id,
                workflow_id, task_id, etc.)
            agent_context: Context about the agent (agent_label,
                agent_type, node_id, etc.)
        """
        if not native_tool_names:
            return []
        try:
            all_tools: List[BaseTool] = []

            # Check if browser tools are requested (requires special async handling)
            browser_requested = "browser" in native_tool_names
            non_browser_tools = [t for t in native_tool_names if t != "browser"]

            # Load regular native tools (synchronous)
            if non_browser_tools:
                # Local import keeps module-load fast; the function is cheap to import
                from tools.native_tools import load_native_tools
                native_tools = load_native_tools(non_browser_tools)

                # Wrap write_file tool with context for file metadata tracking
                if workspace_context or agent_context:
                    native_tools = ToolLoader._wrap_file_tools_with_context(
                        native_tools,
                        workspace_context,
                        agent_context,
                    )

                all_tools.extend(native_tools)
                logger.info(f"✓ Loaded {len(native_tools)} native Python tools")

            # Load Playwright browser tools (asynchronous) if requested
            if browser_requested:
                try:
                    from tools.native_tools import load_playwright_tools
                    browser_tools = await load_playwright_tools()
                    all_tools.extend(browser_tools)
                    logger.info(f"✓ Loaded {len(browser_tools)} Playwright browser tools")
                except Exception as e:
                    logger.error(f"Failed to load Playwright browser tools: {e}")
                    logger.error("Proceeding without browser automation")

            return all_tools
        except Exception as e:
            logger.error(f"Failed to load native tools: {e}. Proceeding without them.")
            return []

    @staticmethod
    def _wrap_file_tools_with_context(
        tools: List[BaseTool],
        workspace_context: Optional[Dict[str, Any]],
        agent_context: Optional[Dict[str, Any]],
    ) -> List[BaseTool]:
        """
        Wrap file-writing tools with context for metadata tracking.

        This creates a new write_file tool that has workspace_context and
        agent_context pre-bound, so when the agent calls write_file, the
        metadata is automatically recorded.
        """
        from tools.native_tools import (
            _write_file_impl, _write_file_error_handler, WriteFileArgs,
        )

        wrapped_tools: List[BaseTool] = []

        for tool in tools:
            if tool.name == "write_file":
                # Get the original implementation function AND args schema

                # Create a new function with context pre-bound
                def create_bound_write_file(ws_ctx, ag_ctx):
                    def bound_write_file(file_path: str, content: str) -> str:
                        return _write_file_impl(
                            file_path=file_path,
                            content=content,
                            _workspace_context=ws_ctx,
                            _agent_context=ag_ctx,
                        )
                    return bound_write_file

                bound_func = create_bound_write_file(workspace_context, agent_context)

                # Create new StructuredTool with the bound function.
                # CRITICAL: Include args_schema to enforce both parameters are required!
                wrapped_tool = StructuredTool.from_function(
                    func=bound_func,
                    name="write_file",
                    description=tool.description,
                    args_schema=WriteFileArgs,  # CRITICAL: enforces file_path AND content
                    handle_tool_error=_write_file_error_handler,
                )

                wrapped_tools.append(wrapped_tool)
                logger.debug(
                    f"Wrapped write_file tool with context: "
                    f"workspace={workspace_context}, agent={agent_context}"
                )
            else:
                # Keep other tools as-is
                wrapped_tools.append(tool)

        return wrapped_tools

    # ------------------------------------------------------------------
    # Category 2: CLI tools
    # ------------------------------------------------------------------

    @staticmethod
    async def load_cli(cli_tool_names: List[str]) -> List[BaseTool]:
        """
        Load CLI-based tools (e.g., Jira CLI tools).

        Args:
            cli_tool_names: List of CLI tool categories to load
                (e.g., ["jira"])
        """
        if not cli_tool_names:
            return []

        tools: List[BaseTool] = []

        try:
            for tool_category in cli_tool_names:
                if tool_category == "jira":
                    # Import Jira CLI tools
                    from backend.tools.jira_cli_tools import JIRA_CLI_TOOLS
                    tools.extend(JIRA_CLI_TOOLS)
                    logger.info(f"✓ Loaded {len(JIRA_CLI_TOOLS)} Jira CLI tools")
                else:
                    logger.warning(f"Unknown CLI tool category: {tool_category}")

            return tools

        except Exception as e:
            logger.error(f"Failed to load CLI tools: {e}. Proceeding without them.")
            return []

    # ------------------------------------------------------------------
    # Category 3: Custom tools (user-defined, from DB)
    # ------------------------------------------------------------------

    @staticmethod
    async def load_custom(custom_tool_ids: List[str], project_id: int) -> List[BaseTool]:
        """
        Load user-defined custom tools from database.

        Args:
            custom_tool_ids: List of custom tool IDs to load
            project_id: Project ID for scoping
        """
        if not custom_tool_ids:
            return []

        tools: List[BaseTool] = []

        try:
            # Import dependencies
            from core.tools.factory import ToolFactory
            from models.custom_tool import CustomTool
            from db.database import SessionLocal

            # Get database session
            db = SessionLocal()
            try:
                # First, list all available custom tools for debugging
                all_tools = db.query(CustomTool).all()
                logger.info(
                    f"🔍 Available custom tools in database: "
                    f"{[(t.tool_id, t.name) for t in all_tools]}"
                )

                for tool_id in custom_tool_ids:
                    try:
                        logger.info(f"🔍 Attempting to load custom tool with ID: '{tool_id}'")

                        # Fetch tool from database
                        custom_tool = db.query(CustomTool).filter(
                            CustomTool.tool_id == tool_id
                        ).first()

                        if not custom_tool:
                            logger.error(
                                f"❌ Custom tool '{tool_id}' not found in database. "
                                f"Available tools: {[t.tool_id for t in all_tools]}"
                            )
                            continue

                        # Build tool configuration from database model
                        tool_config = {
                            "tool_id": custom_tool.tool_id,
                            "name": custom_tool.name,
                            "description": custom_tool.description,
                            "tool_type": custom_tool.tool_type.value,
                            "template_type": custom_tool.template_type.value if custom_tool.template_type else None,
                            "implementation_config": custom_tool.implementation_config,
                            "input_schema": custom_tool.input_schema,
                            "output_format": custom_tool.output_format,
                        }

                        # Create the tool using ToolFactory
                        tool = await ToolFactory.create_tool(tool_config, project_id)
                        tools.append(tool)

                        # Update usage tracking
                        custom_tool.usage_count += 1
                        custom_tool.last_used_at = datetime.utcnow()
                        db.commit()

                        logger.info(f"✓ Loaded custom tool: {custom_tool.name} ({tool_id})")

                    except Exception as e:
                        logger.error(f"Failed to load custom tool '{tool_id}': {e}")
                        # Track error
                        try:
                            custom_tool_error = db.query(CustomTool).filter(
                                CustomTool.tool_id == tool_id
                            ).first()
                            if custom_tool_error:
                                custom_tool_error.error_count += 1
                                custom_tool_error.last_error_at = datetime.utcnow()
                                db.commit()
                        except Exception:
                            pass
                        continue

                logger.info(f"✓ Loaded {len(tools)} custom tools total")
                return tools

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Failed to load custom tools: {e}. Proceeding without them.")
            return []

    # ------------------------------------------------------------------
    # Category 4: Memory tools (vector store backed)
    # ------------------------------------------------------------------

    @staticmethod
    async def load_memory(
        vector_store: Any,
        project_id: int,
        task_id: int,
    ) -> List[BaseTool]:
        """Load memory tools using SimpleMemory (PostgreSQL-backed).

        Uses a module-level cache so memories persist across agent calls.
        """
        try:
            from core.agents.memory import get_or_create_memory
            from db.database import AsyncSessionLocal

            # Create a fresh DB session for memory operations
            db_session = AsyncSessionLocal()

            memory_system = get_or_create_memory(
                project_id=project_id,
                agent_id=f"task_{task_id}",
                db_session=db_session,
            )
            memory_tools = memory_system.create_memory_tools()

            logger.info(
                f"✓ Loaded {len(memory_tools)} memory tools "
                f"(PG-backed, {memory_system.memory_count} cached)"
            )
            return memory_tools

        except Exception as e:
            logger.error(f"Failed to add memory tools: {e}. Proceeding without them.")
            return []

    # ------------------------------------------------------------------
    # Category 5: RAG tools (codebase search)
    # ------------------------------------------------------------------

    @staticmethod
    async def load_rag(
        vector_store: Any,
        project_id: int,
    ) -> List[BaseTool]:
        """Load RAG (codebase search) tools using LlamaIndex."""
        try:
            from core.tools.adapters.llamaindex import create_llamaindex_rag_tools

            rag_tools = await create_llamaindex_rag_tools(project_id=project_id)

            logger.info(f"✓ Loaded {len(rag_tools)} RAG tools (LlamaIndex)")
            return rag_tools

        except Exception as e:
            logger.error(f"Failed to add RAG tools: {e}. Proceeding without them.")
            return []
