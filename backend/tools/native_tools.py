# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Native Tools - Runtime Facade (Phase 4: DB-backed built-in tools)
================================================================

The 43 seedable built-in tools now live in PostgreSQL (``custom_tools`` rows
with ``is_builtin=True``) and are compiled at runtime by ``ToolFactory`` —
exactly like custom tools. Their implementations live in
``tools/native_impl.py``, which exists only as the seed-time source that
``tools/seed_builtin_tools.py`` bakes into self-contained row code.

This module is the thin runtime facade and keeps ONLY the parts that cannot
live in the DB:

- the 10 **legacy-only** tools that need special runtime handling
  (injected agent state, Playwright, TODO/VFS harness helpers):
  ``tavily_summary``, ``browser`` (Playwright), ``memory_store``,
  ``memory_recall``, ``think_tool``, ``write_todos``, ``read_todos``,
  ``vfs_ls``, ``vfs_read_file``, ``vfs_write_file``;
- the legacy alias map ``TOOL_NAME_MAP`` and ``FILESYSTEM_TOOLS``;
- the UI registry (``TOOL_REGISTRY`` / ``get_tool_registry``) for those 10;
- DB-backed helpers: ``get_available_tool_names`` reads ``is_builtin`` rows,
  ``load_native_tools_from_db`` is a sync bridge for exported agent scripts;
- re-exports of the GraphIndex helpers (from ``native_impl``) and the
  ``write_file`` context helpers used by ``ToolLoader``.

The legacy ``load_native_tools`` loader is REMOVED — runtime tool loading is
DB-first via ``ToolLoader`` / ``ToolFactory``.
"""

import base64
import uuid
import logging
import asyncio
import sys
import os
from pathlib import Path
from typing import Annotated, List, Literal, Optional, Dict, Any

from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from core.state import DeepAgentState, Todo

from markdownify import markdownify as md_convert
import httpx

# ---------------------------------------------------------------------------
# Phase 9 integration: keep the backend root and the Phase 9 package
# importable (GraphIndex helpers re-exported from tools/native_impl use it).
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path and os.path.isdir(_REPO_ROOT):
    sys.path.insert(0, _REPO_ROOT)
_PHASE9_DIR = os.path.abspath(
    os.path.join(_REPO_ROOT, "learning", "phase9")
)
if _PHASE9_DIR not in sys.path and os.path.isdir(_PHASE9_DIR):
    sys.path.insert(0, _PHASE9_DIR)

logger = logging.getLogger(__name__)

# Playwright imports - conditional to avoid import errors if not available
try:
    from playwright.async_api import async_playwright
    from langchain_community.agent_toolkits import PlayWrightBrowserToolkit
    from langchain_community.tools.playwright.utils import create_async_playwright_browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not available. Browser automation tools will be disabled.")

# Tavily search - conditional to avoid import errors if not installed
try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    logger.warning("Tavily not available. Install with: pip install langchain-community tavily-python")

# Global Playwright browser instance (lazy-loaded)
_playwright_browser = None


# =============================================================================
# Tool Name Mapping (compatible with existing agent configs)
# =============================================================================
#
# Legacy alias -> canonical name map. Only true aliases are listed here;
# identity entries (e.g. "web_search": "web_search") were removed because
# every consumer resolves via TOOL_NAME_MAP.get(name, name). Stored agent
# configs use canonical names already (verified against deep_agent_templates),
# so this is a backwards-compatibility shim for older/exported configs.

TOOL_NAME_MAP = {
    # Web tools
    "web": "web_search",
    "fetch": "web_fetch",

    # Browser tools (Playwright)
    "puppeteer": "browser",  # Legacy MCP tool name
    "chrome_devtools": "browser",  # Legacy MCP tool name

    # Filesystem tools (DeepAgents standard naming)
    "filesystem": "read_file",
    # Backwards compatibility aliases (LangConfig legacy naming)
    "file_read": "read_file",
    "file_write": "write_file",
    "file_list": "ls",

    # Memory tools (uses existing PostgreSQL)
    "memory": "memory_store",

    # Reasoning tools
    "sequential_thinking": "reasoning_chain",
    "thinking": "reasoning_chain",
    "reasoning": "reasoning_chain",

    # Tavily search
    "tavily": "tavily_search",
}


# =============================================================================
# GraphIndex helpers (re-exported from the seed source tools/native_impl.py).
# Re-exporting (not redefining) keeps ``set_graphindex_doc_scope`` and the
# ``graphindex_*`` tools on the SAME module-level ``_GRAPHINDEX_DOC_SCOPE``
# state, so API/script importers of these names behave exactly as before.
# =============================================================================
from tools.native_impl import (  # noqa: E402
    set_graphindex_doc_scope,
    graphindex_search,
    graphindex_load,
    graphindex_list_docs,
    graphindex_multi_doc_load,
    graphindex_rebuild_one,
    graphindex_ingest,
    graphindex_rebuild_project,
    graphindex_show,
)


# =============================================================================
# write_file context helpers (re-exported for ToolLoader._wrap_file_tools_with_context).
# =============================================================================
from tools.native_impl import (  # noqa: E402
    _write_file_impl,
    _write_file_error_handler,
    WriteFileArgs,
)


# =============================================================================
# Legacy-only tools
# =============================================================================
# These tools CANNOT be seeded into custom_tools because they need injected
# agent state / tool-call ids (LangGraph harness), Playwright, or module-level
# helpers. They are materialized by load_legacy_native_tools() below; the 43
# seedable built-ins are served from PostgreSQL via ToolLoader/ToolFactory.

@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?
    - How complex is the question: Have I reached the search limits?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


# =============================================================================
# tavily_summary — Tavily + summarization + file offloading (notebook 2.4)
# =============================================================================
# Unlike the basic tavily_search, this tool:
# 1. Fetches full webpage content via HTTP
# 2. Converts HTML to markdown
# 3. Summarizes content using a lightweight LLM (or falls back to truncation)
# 4. Saves full content to files (context offloading)
# 5. Returns only a minimal summary via ToolMessage + Command
#
# This prevents context bloat in long-running research trajectories.

# Lazily-initialized summarization model
_summarization_model = None


def _get_summarization_model():
    """Lazy-init a lightweight model for webpage summarization."""
    global _summarization_model
    if _summarization_model is None:
        try:
            from langchain.chat_models import init_chat_model
            # Use configurable model; defaults to a lightweight model for cost efficiency
            model_name = os.getenv("SUMMARIZATION_MODEL", "gpt-4o-mini")
            _summarization_model = init_chat_model(model=model_name, temperature=0.0)
            logger.info(f"Summarization model initialized: {model_name}")
        except Exception as e:
            logger.warning(f"Failed to init summarization model: {e}. Will use truncation fallback.")
            _summarization_model = False  # Sentinel to avoid retry
    return _summarization_model if _summarization_model is not False else None


def _get_today_str() -> str:
    """Get current date in a human-readable format."""
    from datetime import datetime
    return datetime.now().strftime("%a %b %d, %Y")


class _SearchSummary(BaseModel):
    """Schema for webpage content summarization."""
    filename: str = Field(description="Name of the file to store.")
    summary: str = Field(description="Key learnings from the webpage.")


def _summarize_content(content: str) -> _SearchSummary:
    """Summarize webpage content using the configured summarization model.

    Falls back to simple truncation if model is unavailable.
    """
    model = _get_summarization_model()
    if model is None:
        return _SearchSummary(
            filename="search_result.md",
            summary=content[:1000] + "..." if len(content) > 1000 else content,
        )

    try:
        structured_model = model.with_structured_output(_SearchSummary)
        result = structured_model.invoke([
            HumanMessage(content=(
                f"Summarize the following webpage content. Generate a descriptive "
                f"filename (ending in .md) and a concise summary of key learnings.\n\n"
                f"Date: {_get_today_str()}\n\n"
                f"Content:\n{content[:8000]}"  # Truncate input to save tokens
            ))
        ])
        return result
    except Exception as e:
        logger.warning(f"Summarization failed: {e}. Using fallback.")
        return _SearchSummary(
            filename="search_result.md",
            summary=content[:1000] + "..." if len(content) > 1000 else content,
        )


async def _fetch_and_convert_url(url: str) -> str:
    """Fetch URL content and convert HTML to markdown."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return md_convert(response.text)
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
    return ""


@tool(parse_docstring=True)
async def tavily_summary(
    query: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_results: int = 3,
    topic: Literal["general", "news", "finance"] = "general",
) -> Command:
    """Deep research search with content summarization and file offloading.

    Searches the web via Tavily, fetches full page content, summarizes each result,
    and saves complete content to files. Returns only minimal summary to the agent
    to prevent context window bloat.

    This is designed for long-running research trajectories — raw content is
    stored in files (accessible via read_file) while the agent gets only the
    essential information needed to decide next steps.

    Args:
        query: Search query to execute
        state: Injected agent state for file storage
        tool_call_id: Injected tool call identifier
        max_results: Maximum number of results (default: 3)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Command that saves full results to files and provides minimal summary
    """
    try:
        from config import get_api_key_from_db
        from tavily import TavilyClient

        api_key = get_api_key_from_db("tavily_api_key")
        if not api_key:
            return Command(update={
                "messages": [ToolMessage(
                    "Tavily API key not configured. Set TAVILY_API_KEY in Settings > API Keys.",
                    tool_call_id=tool_call_id,
                )]
            })

        tavily_client = TavilyClient(api_key=api_key)
        search_results = tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=True,
            topic=topic,
        )

        files = state.get("files", {})
        saved_files = []
        summaries = []

        for result in search_results.get("results", []):
            url = result.get("url", "")
            title = result.get("title", "Untitled")

            # Fetch full content and summarize
            raw_content = await _fetch_and_convert_url(url)
            if not raw_content:
                raw_content = result.get("raw_content", result.get("content", ""))

            summary_obj = _summarize_content(raw_content)

            # Uniquify filename
            uid = base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode("ascii")[:8]
            name, ext = os.path.splitext(summary_obj.filename)
            filename = f"{name}_{uid}{ext}"

            # Save full content to file
            file_content = (
                f"# Search Result: {title}\n\n"
                f"**URL:** {url}\n"
                f"**Query:** {query}\n"
                f"**Date:** {_get_today_str()}\n\n"
                f"## Summary\n{summary_obj.summary}\n\n"
                f"## Raw Content\n{raw_content}\n"
            )
            files[filename] = file_content
            saved_files.append(filename)
            summaries.append(f"- {filename}: {summary_obj.summary[:200]}...")

        summary_text = (
            f"Found {len(saved_files)} result(s) for '{query}':\n\n"
            f"{chr(10).join(summaries)}\n\n"
            f"Files: {', '.join(saved_files)}\n"
            f"Use read_file() to access full details."
        )

        return Command(update={
            "files": files,
            "messages": [ToolMessage(summary_text, tool_call_id=tool_call_id)],
        })

    except ImportError:
        return Command(update={
            "messages": [ToolMessage(
                "Tavily package not installed. Install with: pip install tavily-python",
                tool_call_id=tool_call_id,
            )]
        })
    except Exception as e:
        return Command(update={
            "messages": [ToolMessage(
                f"Research search error: {str(e)}",
                tool_call_id=tool_call_id,
            )]
        })


@tool
def memory_store(key: str, value: str, context: str = "general") -> str:
    """
    [FALLBACK] Store information in agent memory for later recall.

    This is a fallback stub. The real implementation is in
    core/agents/memory.py via SimpleMemory.
    If this is being used, check that SimpleMemory is configured.

    Args:
        key: Unique identifier for this memory
        value: The information to store
        context: Optional context/category (default: "general")
    """
    logger.warning(
        f"memory_store fallback used (key={key}). "
        f"Real implementation is in SimpleMemory."
    )
    return f"Stored memory: {key} in context '{context}'"


@tool
def memory_recall(key: str, context: str = "general") -> str:
    """
    [FALLBACK] Recall previously stored information from memory.

    This is a fallback stub. The real implementation is in
    core/agents/memory.py via SimpleMemory.
    If this is being used, check that SimpleMemory is configured.

    Args:
        key: The key to look up
        context: Optional context/category (default: "general")
    """
    logger.warning(
        f"memory_recall fallback used (key={key}). "
        f"Real implementation is in SimpleMemory."
    )
    return f"Memory lookup for '{key}' - Not yet implemented (use PostgreSQL checkpointer)"


WRITE_TODOS_DESCRIPTION = """Create and manage structured task lists for tracking progress through complex workflows.

## When to Use
- Multi-step or non-trivial tasks requiring coordination
- When user provides multiple tasks or explicitly requests todo list  
- Avoid for single, trivial actions unless directed otherwise

## Structure
- Maintain one list containing multiple todo objects (content, status, id)
- Use clear, actionable content descriptions
- Status must be: pending, in_progress, or completed

## Best Practices  
- Only one in_progress task at a time
- Mark completed immediately when task is fully done
- Always send the full updated list when making changes
- Prune irrelevant items to keep list focused

## Progress Updates
- Call TodoWrite again to change task status or edit content
- Reflect real-time progress; don't batch completions  
- If blocked, keep in_progress and add new task describing blocker

## Parameters
- todos: List of TODO items with content and status fields

## Returns
Updates agent state with new todo list."""


@tool(description=WRITE_TODOS_DESCRIPTION, parse_docstring=True)
def write_todos(
    todos: list[Todo],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Create or update the agent's TODO list for task planning and tracking.

    Args:
        todos: List of Todo items with content and status
        tool_call_id: Tool call identifier for message response

    Returns:
        Command to update agent state with new TODO list
    """
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id),
            ],
        }
    )


@tool(parse_docstring=True)
def read_todos(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str:
    """Read the current TODO list from the agent state.

    This tool allows the agent to retrieve and review the current TODO list
    to stay focused on remaining tasks and track progress through complex workflows.

    Args:
        state: Injected agent state containing the current TODO list
        tool_call_id: Injected tool call identifier for message tracking

    Returns:
        Formatted string representation of the current TODO list
    """
    todos = state.get("todos", [])
    if not todos:
        return "No todos currently in the list."

    result = "Current TODO List:\n"
    for i, todo in enumerate(todos, 1):
        status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}
        emoji = status_emoji.get(todo["status"], "❓")
        result += f"{i}. {emoji} {todo['content']} ({todo['status']})\n"

    return result.strip()


# =============================================================================
# Virtual File System (VFS) Tools — vendored from notebook 2.2_files.ipynb
# =============================================================================

LS_DESCRIPTION = """List all files in the virtual filesystem stored in agent state.

Shows what files currently exist in agent memory. Use this to orient yourself before other file operations and maintain awareness of your file organization.

No parameters required - simply call ls() to see all available files."""

READ_FILE_DESCRIPTION = """Read content from a file in the virtual filesystem with optional pagination.

This tool returns file content with line numbers (like `cat -n`) and supports reading large files in chunks to avoid context overflow.

Parameters:
- file_path (required): Path to the file you want to read. **CRITICAL: The parameter name MUST be "file_path", NOT "file".**
- offset (optional, default=0): Line number to start reading from
- limit (optional, default=2000): Maximum number of lines to read

**IMPORTANT**: When calling this tool, use the parameter name "file_path" exactly as shown. Do NOT use "file" or any other variation.

Essential before making any edits to understand existing content. Always read a file before editing it."""

WRITE_FILE_DESCRIPTION = """Create a new file or completely overwrite an existing file in the virtual filesystem.

This tool creates new files or replaces entire file contents. Use for initial file creation or complete rewrites. Files are stored persistently in agent state.

Parameters:
- file_path (required): Path where the file should be created/overwritten
- content (required): The complete content to write to the file

Important: This replaces the entire file content."""


# =============================================================================
# File Usage Instructions — from notebook 2.2_files.ipynb
# =============================================================================
# Guides the model to use VFS tools in a specific workflow:
# 1. write_file("user_request.txt") — save user request
# 2. ls() — orient
# 3. web_search — research
# 4. read_file — review sources
# 5. write_file("final_answer.txt") — save final answer

FILE_USAGE_INSTRUCTIONS = """You have access to a virtual file system to help you retain and save context.

## Workflow Process (FOLLOW IN ORDER):

1. **FIRST ACTION REQUIRED**: Before doing anything else, you MUST call the vfs_write_file tool with file_path="user_request.txt" and content=<the user's exact request>. This is MANDATORY - do not proceed without calling vfs_write_file first.

2. **Orient**: Use the vfs_ls tool to see existing files

3. **Research**: Make a single call to the web_search tool and use the result provided by the tool to answer the user's question.

4. **Read**: Once you are satisfied with the collected sources, read the saved file using the vfs_read_file tool and use it to ensure that you directly answer the user's question.

5. **FINAL ACTION REQUIRED**: After formulating your complete answer, you MUST call the vfs_write_file tool with file_path="final_answer.txt" and content=<your complete answer>. This is MANDATORY - do not finish without calling vfs_write_file for the final answer.

CRITICAL: 
- Your FIRST tool call MUST be vfs_write_file with file_path="user_request.txt". Do not call any other tools until you have called vfs_write_file. Do not skip this step.
- Your LAST tool call (before responding to the user) MUST be vfs_write_file with file_path="final_answer.txt" to save your final answer. Do not skip this step."""


@tool(description=LS_DESCRIPTION)
def vfs_ls(state: Annotated[DeepAgentState, InjectedState]) -> list[str]:
    """List all files in the virtual filesystem."""
    return list(state.get("files", {}).keys())


@tool(description=READ_FILE_DESCRIPTION, parse_docstring=True)
def vfs_read_file(
    file_path: str,
    state: Annotated[DeepAgentState, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read file content from virtual filesystem with optional offset and limit.

    Args:
        file_path: Path to the file to read
        state: Agent state containing virtual filesystem (injected in tool node)
        offset: Line number to start reading from (default: 0)
        limit: Maximum number of lines to read (default: 2000)

    Returns:
        Formatted file content with line numbers, or error message if file not found
    """
    files = state.get("files", {})
    if file_path not in files:
        return f"Error: File '{file_path}' not found"

    content = files[file_path]
    if not content:
        return "System reminder: File exists but has empty contents"

    lines = content.splitlines()
    start_idx = offset
    end_idx = min(start_idx + limit, len(lines))

    if start_idx >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

    result_lines = []
    for i in range(start_idx, end_idx):
        line_content = lines[i][:2000]
        result_lines.append(f"{i + 1:6d}\t{line_content}")

    return "\n".join(result_lines)


@tool(description=WRITE_FILE_DESCRIPTION, parse_docstring=True)
def vfs_write_file(
    file_path: str,
    content: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Write content to a file in the virtual filesystem.

    Args:
        file_path: Path where the file should be created/updated
        content: Content to write to the file
        state: Agent state containing virtual filesystem (injected in tool node)
        tool_call_id: Tool call identifier for message response (injected in tool node)

    Returns:
        Command to update agent state with new file content
    """
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)
            ],
        }
    )


# =============================================================================
# Browser Tools (Playwright - Advanced web interaction)
# =============================================================================

def _init_sync_playwright():
    """
    Initialize sync Playwright in a dedicated thread (Windows workaround).

    This runs in a separate thread with no event loop, avoiding
    the SelectorEventLoop vs ProactorEventLoop conflict.
    """
    from playwright.sync_api import sync_playwright

    # This runs in a thread - no asyncio event loop here
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    return browser


async def get_playwright_browser():
    """
    Get or create the Playwright browser instance.
    Lazy-loads the browser to avoid startup overhead.

    Windows-specific handling:
    - Main app uses WindowsSelectorEventLoopPolicy (for psycopg)
    - Playwright needs subprocess support (ProactorEventLoop)
    - Solution: Run sync Playwright in a separate thread (no event loop)
    """
    global _playwright_browser
    if _playwright_browser is None:
        logger.info("Initializing Playwright browser (headless mode)...")
        try:
            if sys.platform == 'win32':
                # Windows: Run sync Playwright in thread to avoid event loop conflicts
                logger.info("Windows detected: Using sync Playwright in thread pool")
                import concurrent.futures

                # Execute in thread pool - the thread has no event loop,
                # so sync_playwright can create its own subprocess handling
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    _playwright_browser = await loop.run_in_executor(
                        executor,
                        _init_sync_playwright
                    )
                logger.info("✓ Playwright browser initialized successfully (thread mode)")
            else:
                # Unix: Use async Playwright directly
                from playwright.async_api import async_playwright

                playwright = await async_playwright().start()
                _playwright_browser = await playwright.chromium.launch(headless=True)

                logger.info("✓ Playwright browser initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Playwright browser: {e}")
            logger.error("Make sure you ran: playwright install chromium")
            logger.exception("Full traceback:")
            raise
    return _playwright_browser


async def load_playwright_tools() -> List[StructuredTool]:
    """
    Load Playwright browser tools from LangChain's PlaywrightBrowserToolkit.

    This is an ASYNC function that must be called with await.

    Returns tools for:
    - navigate_browser: Navigate to a URL and render JavaScript
    - click_element: Click an element on the page
    - extract_text: Extract visible text from the current page
    - extract_hyperlinks: Get all links from the page
    - get_elements: Get elements matching a CSS selector
    - current_webpage: Get current page URL and content

    These tools enable JavaScript rendering, dynamic content interaction,
    and sophisticated web scraping that simple HTTP requests cannot achieve.

    Example usage:
        >>> browser_tools = await load_playwright_tools()
        >>> # browser_tools now contains all Playwright browser automation tools
    """
    try:
        logger.info("Loading Playwright browser toolkit...")

        # Initialize the browser
        browser = await get_playwright_browser()

        # Create the toolkit - use sync_browser on Windows, async_browser on Unix
        if sys.platform == 'win32':
            toolkit = PlayWrightBrowserToolkit.from_browser(sync_browser=browser)
        else:
            toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=browser)

        # Get the tools
        tools = toolkit.get_tools()

        logger.info(f"✓ Loaded {len(tools)} Playwright browser tools")
        for tool in tools:
            logger.info(f"  - {tool.name}: {tool.description}")

        return tools

    except Exception as e:
        logger.error(f"Failed to load Playwright tools: {e}")
        logger.error("Proceeding without browser automation tools")
        return []


# =============================================================================
# Registry & loaders
# =============================================================================

# Registry of filesystem tools for DeepAgents harness
FILESYSTEM_TOOLS = ["ls", "read_file", "write_file", "edit_file", "glob", "grep"]


# =============================================================================
# Tool Registry (UI-facing metadata — legacy-only tools)
# =============================================================================
# Metadata for the tools that CANNOT be seeded into custom_tools (special
# runtime handling required). The other 43 built-in tools are seeded into
# custom_tools by tools/seed_builtin_tools.py — their display metadata lives
# in the DB rows and GET /api/tools/registry (api/tools/registry.py) merges
# the two sources.

TOOL_REGISTRY = [
    # Web tools
    {
        "id": "tavily_summary",
        "name": "Tavily Summary",
        "description": "Deep Tavily search with content summarization and file offloading. Fetches full pages, summarizes via LLM, saves to files (requires TAVILY_API_KEY)",
        "category": "web",
        "requires_api_key": "TAVILY_API_KEY",
    },
    {
        "id": "browser",
        "name": "Browser Automation",
        "description": "Advanced web interaction via Playwright (navigate, click, type)",
        "category": "web",
        "requires_api_key": None,
    },
    # Memory tools
    {
        "id": "memory_store",
        "name": "Memory Store",
        "description": "Store a fact in long-term memory",
        "category": "memory",
        "requires_api_key": None,
    },
    {
        "id": "memory_recall",
        "name": "Memory Recall",
        "description": "Recall relevant facts from long-term memory",
        "category": "memory",
        "requires_api_key": None,
    },
    # Reasoning tools
    {
        "id": "think_tool",
        "name": "Think Tool",
        "description": "Strategic reflection for research progress. Analyze findings, assess gaps, and plan next steps",
        "category": "reasoning",
        "requires_api_key": None,
    },
    # TODO management tools (notebook 2.1 parity)
    {
        "id": "write_todos",
        "name": "Write TODOs",
        "description": "Create or update the agent's TODO list for task planning and tracking. Notebook 2.1 parity — bound as a native tool, bypasses TodoListMiddleware.",
        "category": "todo",
        "requires_api_key": None,
    },
    {
        "id": "read_todos",
        "name": "Read TODOs",
        "description": "Read the current TODO list from agent state. Pairs with write_todos for full notebook-2.1 parity (works in both Regular and Deep Agent types).",
        "category": "todo",
        "requires_api_key": None,
    },
    # VFS (Virtual File System) tools — notebook 2.2_files.ipynb parity
    {
        "id": "vfs_ls",
        "name": "VFS - List Files",
        "description": "List all files in the virtual filesystem stored in agent state. Notebook 2.2 parity — context offloading via state-based file management.",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "vfs_read_file",
        "name": "VFS - Read File",
        "description": "Read content from a file in the virtual filesystem with line numbers and pagination. Notebook 2.2 parity.",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "vfs_write_file",
        "name": "VFS - Write File",
        "description": "Create or overwrite a file in the virtual filesystem. Files are stored persistently in agent state. Notebook 2.2 parity.",
        "category": "filesystem",
        "requires_api_key": None,
    },
]


def get_tool_registry() -> List[Dict[str, Any]]:
    """
    Get the legacy-only tool registry with metadata for UI display.

    Returns metadata for the built-in tools that cannot be seeded into the
    DB (special runtime handling). Seeded built-in tools are served from the
    custom_tools table by GET /api/tools/registry instead. Each entry:
      - id: unique tool identifier
      - name: human-readable name
      - description: short description
      - category: grouping key (web, filesystem, memory, reasoning, delegation)
      - requires_api_key: env var name of the required API key, or None

    Returns:
        List of tool metadata dictionaries
    """
    return TOOL_REGISTRY


# Mapping of the 10 legacy-only tool names to their objects. The 43 seedable
# built-in tools are intentionally NOT here — they are compiled from
# PostgreSQL rows by ToolFactory at runtime.
_LEGACY_ONLY_TOOLS: Dict[str, Any] = {
    "tavily_summary": tavily_summary,
    "think_tool": think_tool,
    "memory_store": memory_store,
    "memory_recall": memory_recall,
    "write_todos": write_todos,
    "read_todos": read_todos,
    "vfs_ls": vfs_ls,
    "vfs_read_file": vfs_read_file,
    "vfs_write_file": vfs_write_file,
}


def load_legacy_native_tools(tool_names) -> List[StructuredTool]:
    """
    Materialize the legacy-only built-in tools (injected-state harness tools,
    TODO/VFS helpers) that cannot be seeded into ``custom_tools``.

    This replaces the removed ``load_native_tools`` for the small set of
    tools that still require module-level Python. The 43 DB-seeded built-ins
    (``web_search``, ``ls``, ``sqlite_execute``, ...) are deliberately
    ignored here — async callers should use ``await ToolLoader.load_native``,
    which reads them from PostgreSQL. ``browser`` is also skipped: it is
    loaded via ``load_playwright_tools()``.

    Args:
        tool_names: List of tool names (aliases in ``TOOL_NAME_MAP`` resolve
            to canonical names first).

    Returns:
        List of tool objects for the legacy-only names that were requested.
    """
    result: List[StructuredTool] = []
    for name in tool_names:
        canonical = TOOL_NAME_MAP.get(name, name)
        if canonical == "browser":
            logger.info("Browser tools are loaded via load_playwright_tools(); skipping")
            continue
        tool_obj = _LEGACY_ONLY_TOOLS.get(canonical)
        if tool_obj is not None:
            result.append(tool_obj)
        else:
            logger.debug(
                f"load_legacy_native_tools: '{name}' is a DB-seeded built-in "
                f"or unknown; use ToolLoader.load_native() instead."
            )
    return result


def load_native_tools_from_db(tool_names) -> List[StructuredTool]:
    """
    Synchronous DB-backed built-in tool loader, for standalone/exported agent
    scripts (sync CLI entry points, generated ``agent.py`` code).

    Reads the requested built-in tools from the seeded ``custom_tools`` rows
    via ``ToolLoader`` and materializes the legacy-only tools from this
    module. Async code (FastAPI handlers, workflow executor, deepagent
    factory) must call ``await ToolLoader.load_native(...)`` directly instead
    of using this bridge.

    Args:
        tool_names: List of tool names (aliases in ``TOOL_NAME_MAP`` resolve
            to canonical names first).

    Returns:
        List of tool objects.

    Raises:
        RuntimeError: If called from inside a running event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "load_native_tools_from_db() is sync-only; "
            "use 'await ToolLoader.load_native(names)' in async code."
        )

    from core.agents.tool_loader import ToolLoader

    return asyncio.run(ToolLoader.load_native(list(tool_names)))


def get_available_tool_names() -> List[str]:
    """
    Return the names of every available built-in tool.

    Reads the seeded ``is_builtin`` rows from ``custom_tools`` (PostgreSQL) —
    no hardcoded tool list — plus the 10 legacy-only tools that stay in this
    module. On DB failure (e.g. migrations not run) it degrades to the
    legacy-only names rather than crashing tool validation.

    Returns:
        Sorted list of canonical tool names.
    """
    names = {entry["id"] for entry in TOOL_REGISTRY}
    try:
        from models.custom_tool import CustomTool
        from db.database import SessionLocal

        db = SessionLocal()
        try:
            rows = db.query(CustomTool.tool_id).filter(
                CustomTool.is_builtin.is_(True)
            ).all()
            names.update(row.tool_id for row in rows)
        finally:
            db.close()
    except Exception as exc:
        logger.warning(
            f"get_available_tool_names: DB read failed ({exc}); "
            f"returning legacy-only names only."
        )
    return sorted(names)
