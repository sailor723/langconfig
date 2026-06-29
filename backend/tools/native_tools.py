# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Native Python Tools - MCP Replacement
=====================================

Local-first tools using LangChain Community integrations and native Python.
No Node.js, no subprocess overhead, .exe-friendly.

Replaces:
- @modelcontextprotocol/server-fetch → DuckDuckGo Search (FREE) + httpx + Playwright
- @modelcontextprotocol/server-memory → PostgreSQL (existing)
- @modelcontextprotocol/server-filesystem → Python pathlib
- @modelcontextprotocol/server-sequential-thinking → Custom reasoning
"""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
import asyncio
import sys

from langchain_core.tools import StructuredTool, tool
from langchain_community.tools import DuckDuckGoSearchRun
import httpx
import os

# ---------------------------------------------------------------------------
# Phase 9 integration: prefer Phase 9 LLM-semantic query system over the
# legacy base string-matching. Phase 9 lives at langconfig/learning/phase9/;
# ensure it's importable from this file along with the backend root.
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

TOOL_NAME_MAP = {
    # Web tools
    "web": "web_search",
    "web_search": "web_search",
    "fetch": "web_fetch",
    "web_fetch": "web_fetch",

    # Browser tools (Playwright)
    "browser": "browser",
    "puppeteer": "browser",  # Legacy MCP tool name
    "chrome_devtools": "browser",  # Legacy MCP tool name
    "browser_navigate": "browser_navigate",
    "browser_click": "browser_click",
    "browser_extract": "browser_extract",
    "browser_screenshot": "browser_screenshot",

    # Filesystem tools (DeepAgents standard naming)
    # See: https://docs.langchain.com/oss/python/deepagents/harness
    "filesystem": "read_file",
    "ls": "ls",
    "read_file": "read_file",
    "write_file": "write_file",
    "edit_file": "edit_file",
    "glob": "glob",
    "grep": "grep",
    # Backwards compatibility aliases (LangConfig legacy naming)
    "file_read": "read_file",
    "file_write": "write_file",
    "file_list": "ls",

    # Memory tools (uses existing PostgreSQL)
    "memory": "memory_store",
    "memory_store": "memory_store",
    "memory_recall": "memory_recall",

    # Reasoning tools
    "sequential_thinking": "reasoning_chain",
    "thinking": "reasoning_chain",
    "reasoning": "reasoning_chain",

    # Tavily search
    "tavily": "tavily_search",
    "tavily_search": "tavily_search",

    # Data analysis tools
    "save_analysis_result": "save_analysis_result",
    # Skill management tools
    "create_skill": "create_skill",
    "update_skill": "update_skill",
    "delete_skill": "delete_skill",
}


# =============================================================================
# Web Search Tools (DuckDuckGo - FREE, No API Key Required)
# =============================================================================

# Create a singleton DuckDuckGo search tool instance
_ddg_search = None

def get_ddg_search():
    """Get or create the DuckDuckGo search tool instance."""
    global _ddg_search
    if _ddg_search is None:
        _ddg_search = DuckDuckGoSearchRun()
    return _ddg_search

@tool
async def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo's HTML API (async-safe, no event loop conflicts).

    Perfect for finding current information, news, articles, and general knowledge.
    Uses simple HTTP requests instead of the problematic DuckDuckGo library.

    Args:
        query: The search query
        max_results: Maximum number of results to return

    Returns:
        Search results as formatted text

    Example:
        >>> await web_search("Battlefield 6 best weapons November 2025")
        >>> await web_search("Python async tutorial")
    """
    import re
    import random

    try:
        logger.info(f"Web search (DuckDuckGo HTML): {query}")

        # Use DuckDuckGo's HTML search (no JavaScript, no new event loops)
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}

        # Rotate User-Agents to reduce CAPTCHA rate
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ]

        headers = {
            "User-Agent": random.choice(user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.post(url, data=params)
            response.raise_for_status()

            html = response.text

            # Check for CAPTCHA/rate limiting (DuckDuckGo returns 202 with anomaly challenge)
            if response.status_code == 202 or 'anomaly' in html.lower() or 'challenge' in html.lower():
                logger.warning(f"DuckDuckGo CAPTCHA/rate limit detected for query: {query}")
                return (
                    f"Web search is temporarily unavailable (rate limited by DuckDuckGo). "
                    f"The search provider has blocked requests from this IP address. "
                    f"CRITICAL: Do NOT retry this search. Proceed with your current knowledge or other tools."
                )

            results = []

            # Method 1: Extract snippets using regex (more robust than line-based)
            # DuckDuckGo HTML uses class="result__snippet" for search result snippets
            snippet_pattern = r'class="result__snippet"[^>]*>([^<]+(?:<b>[^<]+</b>[^<]*)*)</'
            matches = re.findall(snippet_pattern, html, re.IGNORECASE)

            for match in matches[:max_results]:
                # Clean up the snippet
                snippet = re.sub(r'<[^>]+>', '', match)  # Remove any HTML tags
                snippet = snippet.replace('&quot;', '"').replace('&amp;', '&')
                snippet = snippet.replace('&lt;', '<').replace('&gt;', '>')
                snippet = snippet.replace('&#x27;', "'").replace('&nbsp;', ' ')
                snippet = snippet.strip()
                if snippet and len(snippet) > 10:
                    results.append(snippet)

            # Method 2: Fallback - try to extract from result__a (titles) if no snippets
            if not results:
                title_pattern = r'class="result__a"[^>]*>([^<]+)</a>'
                title_matches = re.findall(title_pattern, html, re.IGNORECASE)
                for match in title_matches[:max_results]:
                    title = match.strip()
                    if title and len(title) > 5:
                        results.append(f"[Title] {title}")

            # Method 3: Last resort - extract any text between result divs
            if not results:
                # Look for result blocks
                result_blocks = re.findall(r'<div class="result[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
                for block in result_blocks[:max_results]:
                    # Extract text content
                    text = re.sub(r'<[^>]+>', ' ', block)
                    text = ' '.join(text.split())  # Normalize whitespace
                    if text and len(text) > 20:
                        results.append(text[:300])  # Limit length

            if not results:
                logger.warning(f"No DuckDuckGo results found - attempting Yahoo Search as fallback")
                yahoo_results = await _yahoo_search_fallback(query, max_results)
                if yahoo_results:
                    return yahoo_results
                
                logger.warning(f"No results found for: {query}")
                # Log a sample of the HTML for debugging
                logger.debug(f"HTML sample (first 1000 chars): {html[:1000]}")
                return f"No search results found for: {query}. Try a different search query."

            # Format results
            result_text = f"Search results for '{query}' (via DuckDuckGo):\n\n"
            for i, snippet in enumerate(results, 1):
                result_text += f"{i}. {snippet}\n\n"

            logger.info(f"Web search returned {len(results)} results for: {query}")
            return result_text

    except httpx.TimeoutException:
        logger.error(f"Web search timeout for: {query}")
        return f"Search timed out. Please try again with a simpler query."
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        # Try Yahoo fallback on ANY failure
        try:
            return await _yahoo_search_fallback(query, max_results)
        except Exception as fallback_e:
            logger.warning(f"Yahoo fallback also failed: {fallback_e}")
            return f"Error performing web search: {str(e)}"

async def _yahoo_search_fallback(query: str, max_results: int = 5) -> Optional[str]:
    """Fallback search using Yahoo."""
    try:
        from bs4 import BeautifulSoup
        
        # Format query for Yahoo
        formatted_query = query.replace(' ', '+')
        url = f"https://search.yahoo.com/search?p={formatted_query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            # Yahoo search result snippet class (compText covers description)
            for div in soup.select('.compText.aAbs, .compText, .st'):
                snippet = div.get_text().strip()
                if len(snippet) > 20 and snippet not in results:
                    results.append(snippet)
                if len(results) >= max_results:
                    break
            
            if not results:
                return None
                
            result_text = f"Search results for '{query}' (via Yahoo):\n\n"
            for i, snippet in enumerate(results, 1):
                result_text += f"{i}. {snippet}\n\n"
            
            return result_text
    except Exception as e:
        logger.warning(f"Yahoo fallback failed: {e}")
        return None


@tool
async def web_fetch(url: str, timeout: int = 10) -> str:
    """
    Fetch the content of a webpage.

    Useful for reading articles, documentation, and web pages.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds (default: 10)

    Returns:
        The text content of the webpage

    Example:
        >>> await web_fetch("https://example.com/article")
    """
    try:
        logger.info(f"Fetching URL: {url}")

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")

            if "text" in content_type or "html" in content_type:
                text = response.text
                logger.info(f"Fetched {len(text)} characters from {url}")
                return text
            else:
                return f"Content type '{content_type}' is not text-based"

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return f"Error fetching URL: {str(e)}"
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return f"Error: {str(e)}"


# =============================================================================
# Tavily Search (AI-optimized web search, requires API key)
# =============================================================================

@tool
async def tavily_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using Tavily - an AI-optimized search engine.

    Returns structured, summarized results perfect for AI consumption.
    Requires TAVILY_API_KEY configured in Settings > API Keys.

    Use this for more accurate, context-aware search results compared
    to general web search. Especially good for research questions.

    Args:
        query: The search query
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Search results as formatted text

    Example:
        >>> await tavily_search("LangGraph v1.0 middleware system")
        >>> await tavily_search("Python async patterns", max_results=3)
    """
    try:
        from config import get_api_key_from_db

        api_key = get_api_key_from_db("tavily_api_key")
        if not api_key:
            return (
                "Tavily API key not configured.\n\n"
                "To use Tavily search:\n"
                "1. Go to Settings > API Keys\n"
                "2. Add your TAVILY_API_KEY\n"
                "3. Alternatively, use web_search (DuckDuckGo, free, no key required)"
            )

        if not TAVILY_AVAILABLE:
            return (
                "Tavily package not installed.\n\n"
                "Install with: pip install langchain-community tavily-python"
            )

        logger.info(f"Tavily search: {query}")

        tavily = TavilySearchResults(api_key=api_key, max_results=max_results)
        results = await tavily.ainvoke({"query": query})

        if not results:
            return f"No results found for: {query}"

        result_text = f"Search results for '{query}' (via Tavily):\n\n"
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            url = r.get("url", "")
            if url:
                result_text += f"{i}. {content}\n   Source: {url}\n\n"
            else:
                result_text += f"{i}. {content}\n\n"

        logger.info(f"Tavily search returned {len(results)} results for: {query}")
        return result_text

    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return f"Tavily search error: {str(e)}"


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
# File System Tools (DeepAgents standard naming)
# See: https://docs.langchain.com/oss/python/deepagents/harness
# =============================================================================

@tool
def read_file(file_path: str, offset: int = 0, limit: int = None, max_chars: int = 50000) -> str:
    """
    Read the contents of a file with optional line offset and limit.

    Supports text files including .txt, .md, .py, .json, etc.
    Returns content with line numbers for easy reference.

    Args:
        file_path: Path to the file to read
        offset: Line number to start reading from (0-indexed, default: 0)
        limit: Maximum number of lines to read (default: None for all lines)
        max_chars: Maximum characters to read (default: 50000)

    Returns:
        File contents with line numbers

    Example:
        >>> read_file("src/main.py")
        >>> read_file("logs/app.log", offset=100, limit=50)
    """
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return f"Error: File not found: {file_path}"

        if not path.is_file():
            return f"Error: Path is not a file: {file_path}"

        content = path.read_text(encoding="utf-8")
        lines = content.split('\n')

        # Apply offset and limit
        if offset > 0:
            lines = lines[offset:]
        if limit is not None:
            lines = lines[:limit]

        # Add line numbers
        start_line = offset + 1
        numbered_lines = [f"{start_line + i:4d}| {line}" for i, line in enumerate(lines)]
        result = '\n'.join(numbered_lines)

        if len(result) > max_chars:
            result = result[:max_chars] + f"\n\n[Truncated - content exceeds {max_chars} characters]"

        logger.info(f"Read file: {file_path} ({len(lines)} lines)")
        return result

    except UnicodeDecodeError:
        return f"Error: File is not a text file or uses unsupported encoding"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return f"Error reading file: {str(e)}"

# Backwards compatibility alias
file_read = read_file


def _write_file_impl(
    file_path: str,
    content: str,
    _workspace_context: dict = None,
    _agent_context: dict = None
) -> str:
    """
    Implementation of write_file tool with workspace-aware file storage.

    Args:
        file_path: The filename to create
        content: The content to write
        _workspace_context: Context about the workspace (project_id, workflow_id, task_id)
        _agent_context: Context about the agent creating the file (agent_label, agent_type, node_id, etc.)
    """
    try:
        # SECURITY: Sanitize file path to prevent dangerous directory creation
        # Extract just the filename, stripping ALL directory components
        original_path = file_path
        filename = Path(file_path).name  # Gets just "report.md" from any path

        # Block suspicious filenames or paths that could cause issues
        dangerous_patterns = [
            'langconfig', 'backend', 'src', 'node_modules', '.git',
            'frontend', 'api', 'core', 'services', 'models'
        ]
        path_lower = file_path.lower()
        for pattern in dangerous_patterns:
            if pattern in path_lower and pattern not in filename.lower():
                logger.warning(f"Blocked dangerous path: {file_path} (contains '{pattern}')")
                # Still write the file, but only use the filename
                logger.info(f"Sanitized path: {file_path} -> {filename}")

        # Always use organized workspace for better file management
        from services.workspace_manager import get_workspace_manager

        workspace_mgr = get_workspace_manager()

        # If workspace context provided, use it; otherwise use a default workspace
        if _workspace_context:
            # Use custom output path if configured for this workflow
            custom_output_path = _workspace_context.get('custom_output_path')
            workspace = workspace_mgr.get_task_workspace_with_override(
                project_id=_workspace_context.get('project_id'),
                workflow_id=_workspace_context.get('workflow_id'),
                task_id=_workspace_context.get('task_id'),
                custom_output_path=custom_output_path
            )
        else:
            # Default to outputs/default/ - use workspace manager's base_dir for consistent path
            workspace = workspace_mgr.base_dir / "default"
            workspace.mkdir(parents=True, exist_ok=True)

        # Write file to workspace directory (use just the filename, not full path)
        path = (workspace / filename).resolve()  # Use sanitized filename only
        workspace_resolved = workspace.resolve()

        # Security: Ensure file is within workspace
        # Use Path.is_relative_to() for robust cross-platform comparison
        try:
            path.relative_to(workspace_resolved)
        except ValueError:
            logger.warning(f"Security: Blocked write outside workspace: {path} not in {workspace_resolved}")
            return f"Error: Cannot write outside workspace directory"

        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")

        logger.info(f"Wrote file: {path} ({len(content)} chars)")

        # Record file metadata in database if we have context
        _record_file_metadata(
            filename=filename,
            file_path=path,
            workspace=workspace,
            content=content,
            workspace_context=_workspace_context,
            agent_context=_agent_context
        )

        # Record initial version for diff tracking
        _record_file_version(
            file_path=path,
            operation="create",
            content=content,
            workspace_context=_workspace_context,
            agent_context=_agent_context
        )

        return f"Successfully wrote {len(content)} characters to {path.name}"

    except Exception as e:
        logger.error(f"Error writing file {file_path}: {e}")
        return f"Error writing file: {str(e)}"


def _record_file_version(
    file_path: Path,
    operation: str,
    content: str = None,
    old_string: str = None,
    new_string: str = None,
    workspace_context: dict = None,
    agent_context: dict = None
) -> None:
    """
    Record a file version in the database for diff viewing.

    This creates a FileVersion record that tracks changes to files,
    enabling version history and diff viewing in the UI.

    Args:
        file_path: Full path to the file
        operation: "create", "edit", or "replace"
        content: Full content for create/replace operations
        old_string: For edit operations, the string that was replaced
        new_string: For edit operations, the replacement string
        workspace_context: Context about the workspace (project_id, workflow_id, task_id)
        agent_context: Context about the agent making the change
    """
    try:
        import hashlib
        from db.database import SessionLocal
        from models.workspace_file import WorkspaceFile
        from models.file_version import FileVersion
        from services.workspace_manager import get_workspace_manager

        # Compute relative path from outputs/ directory
        workspace_mgr = get_workspace_manager()
        outputs_dir = workspace_mgr.base_dir
        try:
            relative_path = str(file_path.relative_to(outputs_dir))
        except ValueError:
            relative_path = str(file_path)

        db = SessionLocal()
        try:
            # Find or create the WorkspaceFile record
            workspace_file = db.query(WorkspaceFile).filter(
                WorkspaceFile.file_path == relative_path
            ).first()

            if not workspace_file:
                logger.debug(f"No WorkspaceFile record found for {relative_path}, skipping version tracking")
                return

            # Get the current version number
            max_version = db.query(FileVersion).filter(
                FileVersion.workspace_file_id == workspace_file.id
            ).count()
            new_version_number = max_version + 1

            # Compute content hash if we have content
            content_hash = None
            if content:
                content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

            # Calculate line changes for edits
            lines_added = None
            lines_removed = None
            change_summary = None

            if operation == "create":
                lines_added = content.count('\n') + 1 if content else 0
                lines_removed = 0
                change_summary = f"Created file with {lines_added} lines"
            elif operation == "edit" and old_string and new_string:
                old_lines = old_string.count('\n')
                new_lines = new_string.count('\n')
                lines_added = max(0, new_lines - old_lines)
                lines_removed = max(0, old_lines - new_lines)
                change_summary = f"Replaced {len(old_string)} chars with {len(new_string)} chars"
            elif operation == "replace":
                lines_added = content.count('\n') + 1 if content else 0
                change_summary = f"Replaced entire file ({lines_added} lines)"

            # Create the version record
            file_version = FileVersion(
                workspace_file_id=workspace_file.id,
                version_number=new_version_number,
                content_hash=content_hash,
                content_snapshot=content if operation in ("create", "replace") else None,
                operation=operation,
                old_string=old_string,
                new_string=new_string,
                agent_label=agent_context.get('agent_label') if agent_context else None,
                agent_type=agent_context.get('agent_type') if agent_context else None,
                node_id=agent_context.get('node_id') if agent_context else None,
                task_id=workspace_context.get('task_id') if workspace_context else None,
                execution_id=workspace_context.get('execution_id') if workspace_context else None,
                change_summary=change_summary,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )
            db.add(file_version)
            db.commit()

            logger.debug(f"Recorded version {new_version_number} for {relative_path} (operation: {operation})")

        finally:
            db.close()

    except Exception as e:
        # Don't fail the file operation if version recording fails
        logger.warning(f"Could not record file version: {e}")


def _record_file_metadata(
    filename: str,
    file_path: Path,
    workspace: Path,
    content: str,
    workspace_context: dict = None,
    agent_context: dict = None
) -> None:
    """
    Record file metadata in the database for tracking and organization.

    This creates a WorkspaceFile record that tracks which agent created the file,
    the workflow context, and other metadata for later retrieval.
    """
    try:
        from db.database import SessionLocal
        from models.workspace_file import WorkspaceFile
        from services.workspace_manager import get_workspace_manager
        import mimetypes

        # Compute relative path from outputs/ directory (use workspace manager for consistent path)
        workspace_mgr = get_workspace_manager()
        outputs_dir = workspace_mgr.base_dir
        try:
            relative_path = str(file_path.relative_to(outputs_dir))
        except ValueError:
            # File is not under outputs/, use absolute path
            relative_path = str(file_path)

        # Get file extension and mime type
        extension = file_path.suffix.lower() if file_path.suffix else None
        mime_type, _ = mimetypes.guess_type(str(file_path))

        # Create database session
        db = SessionLocal()
        try:
            # Check if file record already exists (update if so)
            existing = db.query(WorkspaceFile).filter(
                WorkspaceFile.file_path == relative_path
            ).first()

            if existing:
                # Update existing record
                existing.size_bytes = len(content.encode('utf-8'))
                existing.mime_type = mime_type
                if agent_context:
                    existing.agent_label = agent_context.get('agent_label')
                    existing.agent_type = agent_context.get('agent_type')
                    existing.node_id = agent_context.get('node_id')
                    existing.description = agent_context.get('description')
                    existing.content_type = agent_context.get('content_type')
                    existing.original_query = agent_context.get('original_query')
                db.commit()
                logger.debug(f"Updated file metadata for: {relative_path}")
            else:
                # Create new record
                file_record = WorkspaceFile(
                    filename=filename,
                    file_path=relative_path,
                    size_bytes=len(content.encode('utf-8')),
                    mime_type=mime_type,
                    extension=extension,
                    # Workspace context
                    project_id=workspace_context.get('project_id') if workspace_context else None,
                    workflow_id=workspace_context.get('workflow_id') if workspace_context else None,
                    workflow_name=workspace_context.get('workflow_name') if workspace_context else None,
                    task_id=workspace_context.get('task_id') if workspace_context else None,
                    execution_id=workspace_context.get('execution_id') if workspace_context else None,
                    # Agent context
                    agent_label=agent_context.get('agent_label') if agent_context else None,
                    agent_type=agent_context.get('agent_type') if agent_context else None,
                    node_id=agent_context.get('node_id') if agent_context else None,
                    description=agent_context.get('description') if agent_context else None,
                    content_type=agent_context.get('content_type') if agent_context else None,
                    original_query=agent_context.get('original_query') if agent_context else None,
                    tags=agent_context.get('tags', []) if agent_context else [],
                )
                db.add(file_record)
                db.commit()
                logger.debug(f"Recorded file metadata for: {relative_path}")

        finally:
            db.close()

    except Exception as e:
        # Don't fail the file write if metadata recording fails
        logger.warning(f"Could not record file metadata: {e}")

def _write_file_error_handler(error: Exception) -> str:
    """Custom error handler for write_file validation errors"""
    error_str = str(error)

    # Check if this is a Pydantic validation error for missing content
    if "ValidationError" in str(type(error)) and "content" in error_str and "Field required" in error_str:
        # Check if this looks like a truncated tool call (max_tokens reached)
        # Pattern: only file_path present, no content (common when LLM runs out of tokens)
        if "input_value={" in error_str and "'file_path':" in error_str:
            return (
                "⚠️ TOKEN LIMIT REACHED - YOUR RESPONSE WAS CUT OFF!\n\n"
                "You tried to write a very long file but ran out of output tokens. "
                "The content parameter was truncated before it could be sent.\n\n"
                "TO FIX THIS, you must split your content into smaller pieces:\n"
                "1. Write Part 1 with write_file() (keep under 3000 chars)\n"
                "2. Then use edit_file() to append Part 2, 3, etc.\n\n"
                "Example:\n"
                "  write_file(file_path='doc.md', content='# My Doc\\n[PART 1 HERE - max 3000 chars]\\n<!-- MORE -->')\n"
                "  edit_file(file_path='doc.md', old_string='<!-- MORE -->', new_string='[PART 2 CONTENT...]')"
            )
        else:
            return (
                "CRITICAL ERROR - STOP AND READ THIS CAREFULLY:\n\n"
                "You called write_file() with ONLY file_path but FORGOT the content parameter.\n\n"
                "WRONG (what you did):   write_file(file_path='report.md')\n"
                "CORRECT (what to do):   write_file(file_path='report.md', content='Your full content here')\n\n"
                "BEFORE your next tool call:\n"
                "1. STOP - Do NOT immediately retry write_file\n"
                "2. First, compose your complete file content as a string\n"
                "3. THEN call write_file with BOTH file_path AND content parameters\n\n"
                "Example of correct usage:\n"
                "write_file(\n"
                "    file_path='analysis.md',\n"
                "    content='# Analysis Report\\n\\nHere is the full content...'\n"
                ")"
            )

    # For other errors, return the original error message
    return f"write_file error: {error_str}"

# Create the tool with custom error handling and explicit args schema
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field as PydanticField

class WriteFileArgs(BaseModel):
    """Arguments for write_file tool - BOTH are REQUIRED"""
    file_path: str = PydanticField(
        ...,  # ... means required in Pydantic
        description="REQUIRED: The filename to create (e.g., 'report.md', 'data.json'). Directory path is ignored."
    )
    content: str = PydanticField(
        ...,  # ... means required in Pydantic
        description="REQUIRED: The COMPLETE text content to write to the file. You MUST provide this parameter."
    )

write_file = StructuredTool.from_function(
    func=_write_file_impl,
    name="write_file",
    args_schema=WriteFileArgs,
    description="""Write content to a file. REQUIRES 2 PARAMETERS: file_path AND content.

MANDATORY PARAMETERS (you MUST provide BOTH):
1. file_path (str): Filename like 'report.md' (directory ignored for security)
2. content (str): The COMPLETE file content - DO NOT omit this parameter!

WRONG: write_file(file_path='test.md')  ← MISSING content, will ERROR
CORRECT: write_file(file_path='test.md', content='# My Report\\nContent here...')

Files are saved to the workflow's organized output directory.
Users can view, preview, and download files from the 'Files' tab.

Best practice filenames: .md (reports), .json (data), .csv (tables), .py (code)

If you don't have content ready yet, DO NOT call this tool until you do.""",
    handle_tool_error=_write_file_error_handler
)

# Backwards compatibility alias
file_write = write_file


@tool
def ls(directory_path: str = ".") -> str:
    """
    List directory contents with metadata.

    Shows files and directories with their types and sizes.

    Args:
        directory_path: Path to the directory (default: current directory)

    Returns:
        Formatted list of directory contents with metadata

    Example:
        >>> ls()
        >>> ls("/home/user/projects")
    """
    try:
        path = Path(directory_path).resolve()

        if not path.exists():
            return f"Error: Directory not found: {directory_path}"

        if not path.is_dir():
            return f"Error: Path is not a directory: {directory_path}"

        entries = list(path.iterdir())

        if not entries:
            return f"Empty directory: {directory_path}"

        # Format with metadata
        lines = []
        for entry in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.is_dir():
                lines.append(f"[DIR]  {entry.name}/")
            else:
                size = entry.stat().st_size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f}KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f}MB"
                lines.append(f"[FILE] {entry.name} ({size_str})")

        logger.info(f"Listed {len(entries)} entries in {directory_path}")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error listing directory {directory_path}: {e}")
        return f"Error listing directory: {str(e)}"

# Backwards compatibility alias
file_list = ls


def _edit_file_impl(
    file_path: str,
    old_string: str,
    new_string: str,
    _workspace_context: dict = None,
    _agent_context: dict = None
) -> str:
    """
    Implementation of edit_file tool with version tracking.

    Finds the old_string in the file and replaces it with new_string.
    The old_string must be unique in the file to avoid ambiguous edits.

    Args:
        file_path: Path to the file to edit
        old_string: The exact string to find and replace
        new_string: The string to replace it with
        _workspace_context: Context about the workspace (for version tracking)
        _agent_context: Context about the agent (for version tracking)

    Returns:
        Success message or error if old_string not found/not unique
    """
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return f"Error: File not found: {file_path}"

        if not path.is_file():
            return f"Error: Path is not a file: {file_path}"

        content = path.read_text(encoding="utf-8")

        # Check if old_string exists and is unique
        count = content.count(old_string)
        if count == 0:
            return f"Error: String not found in file: '{old_string[:50]}...'"
        if count > 1:
            return f"Error: String found {count} times. Must be unique for safe replacement."

        # Perform replacement
        new_content = content.replace(old_string, new_string, 1)
        path.write_text(new_content, encoding="utf-8")

        logger.info(f"Edited file: {file_path}")

        # Record version for diff tracking
        _record_file_version(
            file_path=path,
            operation="edit",
            content=new_content,  # Store full content after edit
            old_string=old_string,
            new_string=new_string,
            workspace_context=_workspace_context,
            agent_context=_agent_context
        )

        return f"Successfully replaced string in {path.name}"

    except UnicodeDecodeError:
        return f"Error: File is not a text file or uses unsupported encoding"
    except Exception as e:
        logger.error(f"Error editing file {file_path}: {e}")
        return f"Error editing file: {str(e)}"


class EditFileArgs(BaseModel):
    """Arguments for edit_file tool"""
    file_path: str = PydanticField(
        ...,
        description="Path to the file to edit"
    )
    old_string: str = PydanticField(
        ...,
        description="The exact string to find and replace (must be unique in file)"
    )
    new_string: str = PydanticField(
        ...,
        description="The string to replace it with"
    )


edit_file = StructuredTool.from_function(
    func=_edit_file_impl,
    name="edit_file",
    args_schema=EditFileArgs,
    description="""Perform exact string replacement in a file.

Finds the old_string in the file and replaces it with new_string.
The old_string must be unique in the file to avoid ambiguous edits.

Example:
    edit_file(file_path="config.py", old_string="DEBUG = False", new_string="DEBUG = True")"""
)


@tool
def glob(pattern: str, path: str = ".") -> str:
    """
    Find files matching a glob pattern.

    Supports patterns like "**/*.py" (all Python files) or "src/*.ts" (TypeScript in src).

    Args:
        pattern: Glob pattern to match (e.g., "**/*.py", "*.md", "src/**/*.tsx")
        path: Base directory to search from (default: current directory)

    Returns:
        List of matching file paths

    Example:
        >>> glob("**/*.py")
        >>> glob("*.md", path="/docs")
        >>> glob("src/**/*.tsx")
    """
    try:
        base_path = Path(path).resolve()

        if not base_path.exists():
            return f"Error: Path not found: {path}"

        matches = list(base_path.glob(pattern))

        if not matches:
            return f"No files found matching pattern '{pattern}' in {path}"

        # Format results with relative paths
        result_lines = []
        for match in sorted(matches):
            try:
                rel_path = match.relative_to(base_path)
                result_lines.append(str(rel_path))
            except ValueError:
                result_lines.append(str(match))

        logger.info(f"Glob '{pattern}' found {len(matches)} files")
        return "\n".join(result_lines)

    except Exception as e:
        logger.error(f"Error with glob pattern {pattern}: {e}")
        return f"Error searching for files: {str(e)}"


@tool
def grep(pattern: str, path: str = ".", file_pattern: str = None) -> str:
    """
    Search file contents for a regex pattern.

    Searches through files and returns matching lines with context.

    Args:
        pattern: Regular expression pattern to search for
        path: File or directory to search (default: current directory)
        file_pattern: Optional glob pattern to filter files (e.g., "*.py")

    Returns:
        Matching lines with file paths and line numbers

    Example:
        >>> grep("def main", path="src/")
        >>> grep("TODO", file_pattern="*.py")
        >>> grep("import.*requests", path=".", file_pattern="*.py")
    """
    import re

    try:
        base_path = Path(path).resolve()

        if not base_path.exists():
            return f"Error: Path not found: {path}"

        # Compile regex
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        results = []

        # Determine files to search
        if base_path.is_file():
            files_to_search = [base_path]
        else:
            glob_pattern = file_pattern or "**/*"
            files_to_search = [f for f in base_path.glob(glob_pattern) if f.is_file()]

        # Search through files
        for file_path in files_to_search:
            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        try:
                            rel_path = file_path.relative_to(base_path)
                        except ValueError:
                            rel_path = file_path.name
                        results.append(f"{rel_path}:{i}: {line.strip()}")

            except (UnicodeDecodeError, PermissionError):
                # Skip binary files or files we can't read
                continue

        if not results:
            return f"No matches found for pattern '{pattern}'"

        # Limit results to prevent huge outputs
        max_results = 100
        if len(results) > max_results:
            output = "\n".join(results[:max_results])
            output += f"\n\n... and {len(results) - max_results} more matches"
        else:
            output = "\n".join(results)

        logger.info(f"Grep '{pattern}' found {len(results)} matches")
        return output

    except Exception as e:
        logger.error(f"Error searching with pattern {pattern}: {e}")
        return f"Error searching: {str(e)}"


# =============================================================================
# Memory Tools (Stub — real implementation in core/agents/memory.py SimpleMemory)
# =============================================================================

# NOTE: These are fallback placeholder functions. The real memory implementation
# is in SimpleMemory (core/agents/memory.py) which is text-based + PostgreSQL.
# The AgentFactory routes native memory tool requests to SimpleMemory
# automatically — these stubs should never be loaded in production unless
# the SimpleMemory system is unavailable.

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


# =============================================================================
# Reasoning Tools (Sequential Thinking replacement)
# =============================================================================

@tool
def reasoning_chain(task: str, steps: int = 5) -> str:
    """
    Break down a complex task into logical reasoning steps.

    Replaces the MCP sequential-thinking server with native Python logic.

    Args:
        task: The task or problem to reason about
        steps: Number of reasoning steps to perform (default: 5)

    Returns:
        Structured reasoning breakdown

    Example:
        >>> reasoning_chain("Plan a marketing strategy for a new product", 5)
    """
    logger.info(f"Reasoning chain for task: {task}")

    # This is a simplified version. The actual LLM will do the reasoning.
    # This tool just provides a structure for the agent to follow.

    reasoning_template = f"""
TASK: {task}

REASONING STEPS:
1. Analyze the requirements and constraints
2. Identify key objectives and success criteria
3. Consider potential approaches and trade-offs
4. Evaluate risks and mitigation strategies
5. Synthesize into a concrete action plan

Note: This is a reasoning framework. The agent should fill in the actual analysis.
"""

    return reasoning_template


# =============================================================================
# Subagent Delegation Tools
# =============================================================================

@tool
def task(
    description: str,
    subagent_type: str = "general",
    context: str = "",
    expected_output: str = ""
) -> str:
    """
    Delegate a task to a specialized subagent for execution.

    Use this tool to spawn work to configured subagents. The subagent will
    execute the task and return the result. This enables parallel processing
    and specialization.

    Args:
        description: Clear description of the task to perform
        subagent_type: Type of subagent to use (e.g., "research", "code", "writer", "general")
        context: Additional context or information for the subagent
        expected_output: Description of expected output format/content

    Returns:
        Result from the subagent execution

    Example:
        >>> task(
        ...     description="Research the latest trends in AI image generation",
        ...     subagent_type="research",
        ...     context="Focus on diffusion models released in 2024",
        ...     expected_output="A summary with key findings and links"
        ... )
    """
    logger.info(f"[TASK DELEGATION] Spawning subagent task: {description[:100]}...")
    logger.info(f"  subagent_type: {subagent_type}")
    logger.info(f"  context: {context[:100] if context else 'None'}...")

    # This is a placeholder - actual subagent execution is handled by the DeepAgents framework
    # The framework intercepts this tool call and routes it to the appropriate subagent
    # based on the subagent configurations in the DeepAgentConfig

    # For now, return a message indicating the tool was called
    # The actual implementation is in the DeepAgents middleware
    return f"""[SUBAGENT TASK QUEUED]
Task: {description}
Type: {subagent_type}
Context: {context if context else 'None'}
Expected Output: {expected_output if expected_output else 'Any relevant output'}

Note: This task has been queued for subagent execution. The DeepAgents framework
will route this to the appropriate configured subagent. If no subagents are
configured, this task will be executed by the main agent."""


# =============================================================================
# Data Analysis Tools
# =============================================================================

@tool
def save_analysis_result(text: str, file_path: str | None = None) -> str:
    """Save analysis results and optionally copy an attached file (e.g. a plot) to the output directory.

    Args:
        text: Text content of the analysis report
        file_path: Optional path of a file attachment in the sandbox
    """
    output_dir = Path("./_analysis_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "analysis_report.txt"
    report_path.write_text(text)
    if file_path:
        fp = Path(file_path)
        if fp.exists():
            local_path = output_dir / fp.name
            local_path.write_bytes(fp.read_bytes())
    return f"Analysis results saved to {output_dir.resolve()}."


# =============================================================================
# Skill Management Tools
# =============================================================================

@tool
def create_skill(name: str, description: str, instructions: str,
                 tags: list[str] | None = None,
                 triggers: list[str] | None = None) -> str:
    """Create a new skill in the database. The skill will appear in the Skills Library and agents can use it.

    Args:
        name: Human-readable name of the skill (e.g. 'Twitter Analyzer')
        description: Brief 1-2 sentence description of what the skill does
        instructions: Detailed step-by-step instructions for the agent to follow
        tags: List of categorization tags (e.g. ['data-analysis', 'social-media'])
        triggers: List of conditions that auto-trigger this skill (e.g. ['when user uploads a CSV'])
    """
    from db.database import SessionLocal
    from models.skill import Skill
    import datetime

    skill_id = name.lower().strip().replace(" ", "-").replace("_", "-")

    db = SessionLocal()
    try:
        existing = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if existing:
            return f"Skill '{skill_id}' already exists (ID={existing.id}). Use update_skill to modify it."

        skill = Skill(
            skill_id=skill_id,
            name=name.strip(),
            description=description.strip(),
            version="1.0.0",
            tags=tags or ["custom"],
            triggers=triggers or [],
            instructions=instructions.strip(),
            source_type="personal",
            source_path=f"db://personal/{skill_id}",
            file_modified_at=datetime.datetime.now(datetime.timezone.utc),
            allowed_tools=None,
            examples=None,
            author="AI Generated",
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return f"✅ Skill '{name}' (ID={skill_id}) created successfully!"
    except Exception as e:
        db.rollback()
        return f"❌ Failed to create skill: {e}"
    finally:
        db.close()


@tool
def update_skill(skill_id: str, name: str | None = None,
                 description: str | None = None,
                 instructions: str | None = None,
                 tags: list[str] | None = None,
                 triggers: list[str] | None = None) -> str:
    """Update an existing skill in the database. Only provided fields are updated.

    Args:
        skill_id: The kebab-case ID of the skill to update
        name: New human-readable name
        description: New description
        instructions: New instructions
        tags: New list of tags
        triggers: New list of triggers
    """
    from db.database import SessionLocal
    from models.skill import Skill
    import datetime

    db = SessionLocal()
    try:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if not skill:
            return f"❌ Skill '{skill_id}' not found. Use create_skill first."

        if name is not None:
            skill.name = name.strip()
        if description is not None:
            skill.description = description.strip()
        if instructions is not None:
            skill.instructions = instructions.strip()
        if tags is not None:
            skill.tags = tags
        if triggers is not None:
            skill.triggers = triggers
        skill.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return f"✅ Skill '{skill_id}' updated successfully!"
    except Exception as e:
        db.rollback()
        return f"❌ Failed to update skill: {e}"
    finally:
        db.close()


@tool
def delete_skill(skill_id: str) -> str:
    """Delete a skill from the database by its skill_id.

    Args:
        skill_id: The kebab-case ID of the skill to delete
    """
    from db.database import SessionLocal
    from models.skill import Skill

    db = SessionLocal()
    try:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if not skill:
            return f"❌ Skill '{skill_id}' not found."
        db.delete(skill)
        db.commit()
        return f"✅ Skill '{skill_id}' deleted successfully!"
    except Exception as e:
        db.rollback()
        return f"❌ Failed to delete skill: {e}"
    finally:
        db.close()


# =============================================================================
# DocIndex Tools (Vectorless RAG)
# =============================================================================

_DOC_INDEX_BASE = None


def _get_doc_index_base() -> str:
    """Get the doc_index workspace base path."""
    global _DOC_INDEX_BASE
    if _DOC_INDEX_BASE is None:
        _DOC_INDEX_BASE = os.environ.get(
            "DOC_INDEX_BASE",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "default")
        )
    return _DOC_INDEX_BASE


def _get_doc_client():
    """Get a DocIndexClient for the current workspace."""
    from services.doc_index_service import DocIndexClient
    return DocIndexClient(_get_doc_index_base())


def doc_index_list(workspace: Optional[str] = None) -> str:
    """
    List all indexed documents with metadata.

    Uses GraphIndex-style vectorless retrieval — no embeddings, no chunking.
    Returns document names, types, and page counts.

    Args:
        workspace: Optional override for the doc_index workspace path
    """
    try:
        if workspace:
            from services.doc_index_service import DocIndexClient
            client = DocIndexClient(workspace)
        else:
            client = _get_doc_client()

        docs = client.list_all()
        if not docs:
            return "No documents indexed yet."

        lines = ["## Indexed Documents", ""]
        for doc_id, meta in docs.items():
            lines.append(f"- **{meta.get('doc_name', 'Unknown')}** ({meta.get('type', '?')})")
            lines.append(f"  ID: `{doc_id}`")
            lines.append(f"  Pages: {meta.get('page_count', 0)}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing documents: {e}"


def doc_index_structure(doc_id: str, workspace: Optional[str] = None) -> str:
    """
    Get the table-of-contents tree structure for a document.

    Returns the document's heading hierarchy with page numbers (no body text).
    Use this to navigate to the right section before reading page content.

    Args:
        doc_id: The document ID (from doc_index_list)
        workspace: Optional override for the doc_index workspace path
    """
    try:
        if workspace:
            from services.doc_index_service import DocIndexClient
            client = DocIndexClient(workspace)
        else:
            client = _get_doc_client()

        doc_meta = client.get_document(doc_id)
        if "error" in doc_meta:
            return doc_meta["error"]

        structure = client.get_document_structure(doc_id)
        if not structure:
            return f"Document '{doc_meta.get('doc_name', doc_id)}' has no TOC structure. Use doc_index_pages to read content directly."

        def _format_tree(nodes, indent=0):
            lines = []
            for n in nodes:
                title = n.get("title", "")
                page = n.get("page", n.get("line", ""))
                prefix = "  " * indent + "- "
                page_str = f" (p.{page})" if page else ""
                lines.append(f"{prefix}**{title}**{page_str}")
                children = n.get("children", [])
                if children:
                    lines.extend(_format_tree(children, indent + 1))
            return lines

        result = [f"## Structure: {doc_meta.get('doc_name', 'Document')}"]
        result.extend(_format_tree(structure))
        return "\n".join(result)

    except Exception as e:
        return f"Error getting document structure: {e}"


def doc_index_pages(doc_id: str, pages: str, workspace: Optional[str] = None) -> str:
    """
    Get the full content of specific pages from a document.

    Args:
        doc_id: The document ID (from doc_index_list)
        pages: Page numbers to retrieve. Examples: '5-7' (range), '3,8' (specific), '12' (single).
               Use '1-3' to read the first few pages (often contains the table of contents).
        workspace: Optional override for the doc_index workspace path
    """
    try:
        if workspace:
            from services.doc_index_service import DocIndexClient
            client = DocIndexClient(workspace)
        else:
            client = _get_doc_client()

        doc_meta = client.get_document(doc_id)
        if "error" in doc_meta:
            return doc_meta["error"]

        content_list = client.get_page_content(doc_id, pages)
        if not content_list:
            return f"No content found for pages: {pages}"

        result = [f"## Content: {doc_meta.get('doc_name', 'Document')} (pages {pages})", ""]
        for entry in content_list:
            page_num = entry.get("page", "?")
            text = entry.get("content", "")
            result.append(f"--- Page {page_num} ---")
            result.append(text)
            result.append("")

        return "\n".join(result)
    except Exception as e:
        return f"Error getting page content: {e}"


# Convert to StructuredTools
_doc_index_list_tool = StructuredTool.from_function(
    func=doc_index_list,
    name="doc_index_list",
    description="List all indexed documents with metadata. Uses vectorless RAG (no embeddings, no chunking). Returns document names, types, and page counts.",
)
_doc_index_structure_tool = StructuredTool.from_function(
    func=doc_index_structure,
    name="doc_index_structure",
    description="Get the table-of-contents tree structure for a document (headings with page numbers, no body text). Use this to navigate before reading pages.",
)
_doc_index_pages_tool = StructuredTool.from_function(
    func=doc_index_pages,
    name="doc_index_pages",
    description="Get the full content of specific pages from a document. Specify pages as ranges like '5-7', specific pages like '3,8', or a single page like '12'.",
)


# =============================================================================
# GraphIndex Tools (vectorless RAG for PDF Chat)
# =============================================================================

# GraphIndex tools — doc scope filter.
# Set by the chat route before calling the agent when the user has
# selected specific docs. None = all docs visible.
_GRAPHINDEX_DOC_SCOPE: Optional[List[str]] = None

def set_graphindex_doc_scope(scope: Optional[List[str]]) -> None:
    """Set the doc scope filter for graphindex tools. Pass None for 'all'."""
    global _GRAPHINDEX_DOC_SCOPE
    _GRAPHINDEX_DOC_SCOPE = scope


def _get_project_id() -> Optional[int]:
    """Get the current project ID from environment (set during agent execution)."""
    pid = os.environ.get("GRAPHINDEX_PROJECT_ID")
    if pid:
        try:
            return int(pid)
        except (ValueError, TypeError):
            return None
    return None


# Note: print_hello has been moved to a custom tool (DB-backed, editable in UI).
# See backend/create_print_hello_tool.py for how it was registered.
# The native implementation was removed to keep a single source of truth.


def graphindex_search(query: str, project_id: Optional[int] = None) -> str:
    """Search project documents using GraphIndex with LLM semantic routing.

    Uses the canonical Phase 9 graphindex modules (learning.phase9.graphindex):
      - route.fetch_catalog to list all docs
      - route.route_by_llm for LLM-based routing
      - index_build.make_llm for the routing LLM

    Returns matching documents with name, type, domain, and supporting list.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided. Either pass project_id "
                "explicitly or set the GRAPHINDEX_PROJECT_ID env var.")

    try:
        from learning.phase9.graphindex.route import fetch_catalog, route_by_llm, route_by_string  # noqa: E402
        from learning.phase9.graphindex.index_build import Neo4jDocumentIndex, make_llm  # noqa: E402

        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        rows = fetch_catalog(idx, project_id, doc_scope=_GRAPHINDEX_DOC_SCOPE or "all")

        # PG fallback: if Neo4j is empty (indexing still in progress),
        # try PostgreSQL ContextDocument table instead.
        if not rows:
            pg_result = _search_pg_fallback(query, project_id)
            if pg_result:
                return pg_result
            return f"No documents found matching '{query}' in project {project_id}."

        llm = make_llm()
        decision, cache_read = route_by_llm(query, rows, llm)

        # Fallback to string match if LLM returned null
        if not decision.primary:
            primary_name = route_by_string(query, rows)
            if not primary_name:
                return (f"No documents found matching '{query}' in project {project_id}. "
                        f"Reasoning: {decision.reasoning if decision.reasoning else 'N/A'}")
            return (f"## GraphIndex Search Results for: '{query}'\n\n"
                    f"**Fallback**: LLM returned null; used string-match.\n\n"
                    f"**[{1}] {primary_name}**\n")

        lines = [f"## GraphIndex Search Results for: '{query}'", ""]
        lines.append(f"_routing: llm-semantic (cache_read={cache_read:,} tokens)_")
        if decision.primary_domain:
            lines.append(f"_primary_domain: {decision.primary_domain}_")
        if decision.reasoning:
            lines.append(f"_reasoning: {decision.reasoning}_")
        lines.append("")

        # Primary
        lines.append(f"**[1] {decision.primary}** (PRIMARY, confidence={decision.primary_confidence:.2f})")
        lines.append(f"   - Name: {decision.primary}")
        lines.append("")

        # Supporting
        for i, sup in enumerate(decision.supporting, 2):
            lines.append(f"**[{i}] {sup.name}** (SUPPORTING)")
            if sup.reason:
                lines.append(f"   - Reason: {sup.reason}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error searching GraphIndex: {e}"


def graphindex_load(context_doc_id: int, max_chars: int = 10_000_000) -> str:
    """Load the full content of a document by its context_doc_id.

    Uses the canonical Phase 9 graphindex modules:
      1. Lookup ContextDocument from DB by context_doc_id
      2. Read full text via route._read_doc_text

    Args:
        context_doc_id: The document's context_doc_id (from graphindex_search results).
        max_chars: Hard cap on returned characters (default 10M = no cap).
    """
    try:
        from db.database import SessionLocal
        from models.core import ContextDocument

        db = SessionLocal()
        try:
            context_doc = db.query(ContextDocument).filter(
                ContextDocument.id == context_doc_id
            ).first()
        finally:
            db.close()

        if not context_doc:
            return f"❌ Document with context_doc_id={context_doc_id} not found."

        from learning.phase9.graphindex.route import _read_doc_text  # noqa: E402
        full_content = _read_doc_text(
            context_doc.file_path or "",
            max_chars=max_chars,
        )
        if not full_content:
            return (f"❌ Could not extract text from {context_doc.filename} "
                    f"(file_path={context_doc.file_path})")

        return (f"## Document: {context_doc.filename}\n"
                f"Source: GraphIndex (Phase 9 read path)\n"
                f"Pages: {full_content.count('--- Page ')}\n"
                f"Total characters: {len(full_content):,}\n\n"
                f"--- Document Content ---\n"
                f"{full_content}\n--- End of Document ---\n")
    except Exception as e:
        return f"❌ Error loading document {context_doc_id}: {e}"


# ---------------------------------------------------------------------------
# PostgreSQL fallback — when Neo4j hasn't been enriched yet (upload still
# indexing), query ContextDocument directly from Postgres + read from disk.
# This lets the user chat about a just-uploaded doc while Neo4j indexing
# runs in the background.
# ---------------------------------------------------------------------------
def _list_docs_from_pg(project_id: int) -> list:
    """Query ContextDocument from PostgreSQL as a fallback catalog.

    Returns list of dicts with keys: name, about, id, file_path, filename.
    """
    try:
        from db.database import SessionLocal
        from models.core import ContextDocument

        db = SessionLocal()
        try:
            docs = db.query(ContextDocument).filter(
                ContextDocument.project_id == project_id,
            ).all()
            return [
                {
                    "name": d.filename or f"doc_{d.id}",
                    "about": d.description or "(no description yet — indexing in progress)",
                    "id": d.id,
                    "file_path": d.file_path or "",
                    "filename": d.filename or f"doc_{d.id}",
                }
                for d in docs
            ]
        finally:
            db.close()
    except Exception:
        return []


def _search_pg_fallback(query: str, project_id: int) -> str:
    """Fallback search: list ContextDocuments from PostgreSQL and match
    by filename. Returns a formatted result string the agent can use."""
    docs = _list_docs_from_pg(project_id)
    if not docs:
        return ""

    # Simple match: find docs whose filename contains query keywords
    keywords = query.lower().split()
    matched = []
    for d in docs:
        name_lower = d["name"].lower()
        score = sum(1 for kw in keywords if kw in name_lower)
        if score > 0:
            matched.append((score, d))

    matched.sort(key=lambda x: -x[0])

    # If nothing matched by keyword, return the first few docs as suggestions
    if not matched:
        lines = [
            f"No exact match for '{query}' — showing {min(len(docs), 5)}"
            f" most recently uploaded docs:",
            "",
        ]
        for d in docs[:5]:
            lines.append(f"**{d['name']}** (id={d['id']}, {d['about'][:60]})")
        lines.append("")
        lines.append("Use `graphindex_load` with the `id` to read a document.")
        return "\n".join(lines)

    lines = [
        f"## GraphIndex Search Results for: '{query}' (PostgreSQL fallback — Neo4j enrichment may still be in progress)",
        "",
    ]
    for i, (score, d) in enumerate(matched, 1):
        label = "PRIMARY" if i == 1 else "SUPPORTING"
        lines.append(f"**[{i}] {d['name']}** ({label})")
        lines.append(f"   - Context Doc ID: {d['id']}")
        lines.append(f"   - {d['about']}")
        lines.append("")

    lines.append("Use `graphindex_load(id)` to read the full content.")
    return "\n".join(lines)


# --- Phase 9 helpers -------------------------------------------------------

def graphindex_list_docs(project_id: Optional[int] = None) -> str:
    """List all documents available in the project.

    First tries Neo4j (``learning.phase9.graphindex.route.fetch_catalog``).
    If empty (indexing still in progress), falls back to PostgreSQL
    ContextDocument table.

    Args:
        project_id: Optional project ID. If not provided, uses the
            current project (from GRAPHINDEX_PROJECT_ID env var).
            Returns an error if neither is set.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided. Either pass project_id "
                "explicitly or set the GRAPHINDEX_PROJECT_ID env var.")

    try:
        from learning.phase9.graphindex.route import fetch_catalog  # noqa: E402
        from learning.phase9.graphindex.index_build import Neo4jDocumentIndex  # noqa: E402

        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        rows = fetch_catalog(idx, project_id, doc_scope=_GRAPHINDEX_DOC_SCOPE or "all")

        if not rows:
            # Fallback: PostgreSQL ContextDocuments (not yet Neo4j-indexed)
            pg_docs = _list_docs_from_pg(project_id)
            if not pg_docs:
                return f"No documents in project {project_id}."
            rows = pg_docs

        lines = [f"## Documents in project {project_id} ({len(rows)} total)", ""]
        for i, r in enumerate(rows, 1):
            about = (r.get("about") or r.get("description") or "(no enrichment)")[:80]
            lines.append(f"**[{i}] {r['name']}**")
            lines.append(f"   {about}…")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing docs: {e}"


def graphindex_multi_doc_load(query: str, project_id: Optional[int] = None) -> str:
    """One-shot: route a query to the best primary document, then load primary
    + 0-3 supporting documents as a combined context string.

    Uses ``learning.phase9.graphindex.route`` (route_by_llm + load_doc_context).

    Args:
        query: Natural language query (e.g., "compare Nike strategy with industry trends")
        project_id: Optional project ID. Uses GRAPHINDEX_PROJECT_ID env var if not set.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided. Either pass project_id "
                "explicitly or set the GRAPHINDEX_PROJECT_ID env var.")

    try:
        from learning.phase9.graphindex.route import (  # noqa: E402
            fetch_catalog, route_by_llm, load_doc_context,
        )
        from learning.phase9.graphindex.index_build import (  # noqa: E402
            Neo4jDocumentIndex, make_llm,
        )
        from learning.phase9.graphindex.tools import tool_query_docs  # noqa: E402

        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        rows = fetch_catalog(idx, project_id, doc_scope=_GRAPHINDEX_DOC_SCOPE or "all")
        if not rows:
            return f"No documents in project {project_id}."

        llm = make_llm()
        decision, _ = route_by_llm(query, rows, llm)
        if not decision.primary:
            return (f"No document matched '{query}'. "
                    f"Reasoning: {decision.reasoning if decision.reasoning else 'N/A'}")

        # Use tool_query_docs to load the matched documents
        doc_names = [decision.primary] + [s.name for s in decision.supporting]
        context = "\n\n".join(
            tool_query_docs(doc_names, project_id) for _ in [1]
        )
        header = (
            f"## Multi-doc context for: '{query}'\n"
            f"primary: {decision.primary}"
            f" (domain={decision.primary_domain}, confidence={decision.primary_confidence:.2f})\n"
        )
        if decision.supporting:
            names = ", ".join(s.name for s in decision.supporting)
            header += f"supporting: {names}\n"
        return header + context
    except Exception as e:
        return f"❌ Error in multi-doc load: {e}"


def _run_capturing_stdout(fn, *args, **kwargs):
    """Run a function and capture its stdout.

    Some cmd_* functions print reports to stdout. We redirect stdout
    into a buffer so the result shows in the agent's tool output.
    """
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args, **kwargs)
    return rc, buf.getvalue().rstrip()


def _make_neo4j_index():
    """Create a Neo4jDocumentIndex from env vars."""
    from learning.phase9.graphindex.index_build import Neo4jDocumentIndex
    idx = Neo4jDocumentIndex(
        base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
        username=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "password"),
    )
    idx.ensure_constraints()
    return idx


def graphindex_rebuild_one(name: str, project_id: Optional[int] = None) -> str:
    """Re-enrich ONE existing document in the graphindex.

    Uses ``learning.phase9.graphindex.index_build.cmd_rebuild_one``.

    Args:
        name: Exact document filename (use graphindex_list_docs to find names).
        project_id: Optional project ID.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided.")

    try:
        from learning.phase9.graphindex.index_build import cmd_rebuild_one, make_llm
        idx = _make_neo4j_index()
        llm = make_llm()
        rc, captured = _run_capturing_stdout(cmd_rebuild_one, idx, llm, name, project_id=project_id)
        return captured or f"## Rebuild one: {name}\nreturn code: {rc}"
    except Exception as e:
        return f"❌ Error rebuilding {name}: {e}"


def graphindex_ingest(file_path: str, project_id: Optional[int] = None,
                      target_dir: Optional[str] = None) -> str:
    """Ingest a file into the graphindex: hash → dedup → enrich → upsert.

    Uses ``learning.phase9.graphindex.index_build.cmd_ingest``.

    Args:
        file_path: Absolute path to the file on disk.
        project_id: Optional project ID.
        target_dir: Optional override for the target directory.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided.")

    try:
        from learning.phase9.graphindex.index_build import cmd_ingest, make_llm
        idx = _make_neo4j_index()
        llm = make_llm()
        rc, captured = _run_capturing_stdout(cmd_ingest, idx, llm, file_path,
                                              target_dir=target_dir, project_id=project_id)
        return captured or f"## Ingest: {file_path}\nreturn code: {rc}"
    except Exception as e:
        return f"❌ Error ingesting {file_path}: {e}"


def graphindex_rebuild_project(project_id: Optional[int] = None) -> str:
    """Re-enrich EVERY document in the project.

    Uses ``learning.phase9.graphindex.index_build.cmd_rebuild_project``.
    WARNING: slow! ~15s per document.

    Args:
        project_id: Optional project ID.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided.")

    try:
        from learning.phase9.graphindex.index_build import cmd_rebuild_project, make_llm
        idx = _make_neo4j_index()
        llm = make_llm()
        rc, captured = _run_capturing_stdout(cmd_rebuild_project, idx, llm, project_id=project_id)
        return captured or f"## Rebuild project (project_id={project_id})\nreturn code: {rc}"
    except Exception as e:
        return f"❌ Error rebuilding project {project_id}: {e}"


def graphindex_show(name: str, project_id: Optional[int] = None) -> str:
    """Show one document's metadata from Neo4j.

    Uses ``learning.phase9.graphindex.index_build.cmd_show``.

    Args:
        name: Exact document filename.
        project_id: Optional project ID.
    """
    if not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided.")

    try:
        from learning.phase9.graphindex.index_build import cmd_show
        idx = _make_neo4j_index()
        rc, captured = _run_capturing_stdout(cmd_show, idx, name, project_id=project_id)
        # cmd_show returns () → but it's used for its print output
        return captured or f"## Show: {name}\nreturn code: {rc}"
    except Exception as e:
        return f"❌ Error showing {name}: {e}"


# StructuredTool wrappers
# Note: _print_hello_tool removed — print_hello is now a custom tool (DB-backed).
# Note: _graphindex_rebuild_one_tool, _graphindex_ingest_tool,
#       _graphindex_rebuild_project_tool, _graphindex_show_tool removed —
#       these tools have been moved to custom tools (DB-backed, editable in UI).
_graphindex_search_tool = StructuredTool.from_function(
    func=graphindex_search,
    name="graphindex_search",
    description="Search project documents using GraphIndex with LLM semantic routing. Returns matching documents with context_doc_id, name, type, page count, primary_domain, and supporting list. Use context_doc_id with graphindex_load to get full content.",
)
_graphindex_load_tool = StructuredTool.from_function(
    func=graphindex_load,
    name="graphindex_load",
    description="Load the full content of a document by its context_doc_id (obtained from graphindex_search). Returns the complete document text for the agent to read. Default is 10M chars (effectively no cap — full doc in one call). Pass max_chars to limit.",
)
_graphindex_list_docs_tool = StructuredTool.from_function(
    func=graphindex_list_docs,
    name="graphindex_list_docs",
    description="List all documents in the project with their about-preview. Use this to discover what docs exist before calling graphindex_search.",
)
_graphindex_multi_doc_load_tool = StructuredTool.from_function(
    func=graphindex_multi_doc_load,
    name="graphindex_multi_doc_load",
    description="One-shot: route a query to the best primary document, then load primary + 0-3 supporting documents as a combined context string. Equivalent to calling graphindex_search + multiple graphindex_load in one step.",
)

# Note: _graphindex_rebuild_one_tool, _graphindex_ingest_tool,
# _graphindex_rebuild_project_tool, _graphindex_show_tool removed —
# these are now custom tools (DB-backed, editable in Studio UI).


# =============================================================================
# Tool Loading Functions
# =============================================================================

def load_native_tools(tool_names: List[str]) -> List[StructuredTool]:
    """
    Load native Python tools by name.

    This replaces the MCP tool adapter with a simpler, synchronous approach.

    Args:
        tool_names: List of tool names to load (e.g., ['web', 'memory', 'filesystem'])

    Returns:
        List of LangChain StructuredTool objects ready for agent binding

    Example:
        >>> tools = load_native_tools(['web_search', 'file_read', 'memory_store'])
        >>> agent = create_agent(llm, tools)
    """
    if not tool_names:
        logger.debug("No tools requested")
        return []

    logger.info(f"Loading native tools: {tool_names}")

    # Available tools registry (DeepAgents standard naming)
    # See: https://docs.langchain.com/oss/python/deepagents/harness
    available_tools = {
        # Web tools
        "web_search": web_search,
        "web_fetch": web_fetch,
        "tavily_search": tavily_search,
        # Filesystem tools (DeepAgents standard)
        "ls": ls,
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "glob": glob,
        "grep": grep,
        # Backwards compatibility aliases
        "file_read": read_file,
        "file_write": write_file,
        "file_list": ls,
        # Memory tools
        "memory_store": memory_store,
        "memory_recall": memory_recall,
        # Reasoning tools
        "reasoning_chain": reasoning_chain,
        # Subagent delegation tools
        "task": task,
        "delegate": task,  # Alias for task
        # Data analysis tools
        "save_analysis_result": save_analysis_result,
        # Skill management tools
        "create_skill": create_skill,
        "update_skill": update_skill,
        "delete_skill": delete_skill,
        # DocIndex tools
        "doc_index_list": _doc_index_list_tool,
        "doc_index_structure": _doc_index_structure_tool,
        "doc_index_pages": _doc_index_pages_tool,
        # Note: print_hello is now a custom tool (DB-backed), not in native factory
        # GraphIndex tools (vectorless RAG for PDF Chat)
        "graphindex_search": _graphindex_search_tool,
        "graphindex_load": _graphindex_load_tool,
        "graphindex_list_docs": _graphindex_list_docs_tool,
        "graphindex_multi_doc_load": _graphindex_multi_doc_load_tool,
        # Note: graphindex_rebuild_one / graphindex_ingest / graphindex_rebuild_project
        # / graphindex_show have been moved to custom tools (DB-backed, editable in UI).
        # The native Python functions are still defined above, but the StructuredTool
        # wrappers are no longer registered in the factory dict.
        # Note: Playwright tools are loaded separately via get_playwright_tools()
        # because they require async initialization
    }

    tools = []

    for tool_name in tool_names:
        # Map old MCP names to new native names
        mapped_name = TOOL_NAME_MAP.get(tool_name, tool_name)

        # File write is now re-enabled
        # if mapped_name == "file_write":
        #     logger.warning(f"  ⚠️ file_write tool is temporarily DISABLED - agents should output content directly instead")
        #     continue

        # Special handling for browser tools (requires async initialization)
        if mapped_name == "browser_navigate" or tool_name == "browser":
            logger.info(f"  ℹ Browser tools requested (Playwright) - will be loaded separately via toolkit")
            # Note: Playwright tools are loaded via get_playwright_tools() which returns
            # the full toolkit. For now, we log this and skip.
            continue

        if mapped_name in available_tools:
            tool = available_tools[mapped_name]
            tools.append(tool)
            logger.info(f"  ✓ Loaded: {mapped_name} (requested as: {tool_name})")
        else:
            logger.warning(f"  ⚠ Tool not found: {tool_name} (mapped to: {mapped_name})")

    logger.info(f"✓ Loaded {len(tools)} native tools total")

    return tools


def get_available_tool_names() -> List[str]:
    """
    Get list of all available native tool names.

    Useful for frontend UI to display available tools.
    Uses DeepAgents standard naming.

    See: https://docs.langchain.com/oss/python/deepagents/harness

    Returns:
        List of tool names that can be loaded
    """
    return [
        # Web tools
        "web_search",
        "web_fetch",
        "tavily_search",
        "browser",  # Playwright browser toolkit (advanced web interaction)
        # Filesystem tools (DeepAgents standard)
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        # Memory tools
        "memory_store",
        "memory_recall",
        # Reasoning tools
        "reasoning_chain",
        # Subagent delegation tools
        "task",
        # DocIndex tools (vectorless RAG)
        "doc_index_list",
        "doc_index_structure",
        "doc_index_pages",
        # Note: print_hello is now a custom tool (DB-backed), not in native available list
        # GraphIndex tools (vectorless RAG for PDF Chat) — Phase 9 backed
        "graphindex_search",
        "graphindex_load",
        "graphindex_list_docs",
        "graphindex_multi_doc_load",
        # Note: graphindex_rebuild_one / graphindex_ingest / graphindex_rebuild_project
        # / graphindex_show have been moved to custom tools (DB-backed, editable in UI)
    ]

# Registry of filesystem tools for DeepAgents harness
FILESYSTEM_TOOLS = ["ls", "read_file", "write_file", "edit_file", "glob", "grep"]


# =============================================================================
# Tool Registry (UI-facing metadata)
# =============================================================================
# Single source of truth for tool metadata displayed in the frontend.
# Add a new tool here (id, name, description, category, requires_api_key) and
# it will automatically appear in both the agent editor and the Studio node
# config panel via GET /api/tools/registry.

TOOL_REGISTRY = [
    # Web tools
    {
        "id": "web_search",
        "name": "Web Search",
        "description": "Search the web (DuckDuckGo, no API key required)",
        "category": "web",
        "requires_api_key": None,
    },
    {
        "id": "tavily_search",
        "name": "Tavily Search",
        "description": "AI-optimized web search (requires TAVILY_API_KEY in Settings > API Keys)",
        "category": "web",
        "requires_api_key": "TAVILY_API_KEY",
    },
    {
        "id": "web_fetch",
        "name": "Web Fetch",
        "description": "Fetch the content of a webpage and convert to markdown",
        "category": "web",
        "requires_api_key": None,
    },
    {
        "id": "browser",
        "name": "Browser Automation",
        "description": "Advanced web interaction via Playwright (navigate, click, type)",
        "category": "web",
        "requires_api_key": None,
    },
    # Filesystem tools
    {
        "id": "ls",
        "name": "List Directory",
        "description": "List directory contents with metadata",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "read_file",
        "name": "Read File",
        "description": "Read file contents with line numbers",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "write_file",
        "name": "Write File",
        "description": "Create new files",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "edit_file",
        "name": "Edit File",
        "description": "Exact string replacements in files",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "glob",
        "name": "Glob",
        "description": "Find files matching patterns",
        "category": "filesystem",
        "requires_api_key": None,
    },
    {
        "id": "grep",
        "name": "Grep",
        "description": "Search file contents with regex",
        "category": "filesystem",
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
        "id": "reasoning_chain",
        "name": "Reasoning Chain",
        "description": "Step-by-step reasoning over complex problems",
        "category": "reasoning",
        "requires_api_key": None,
    },
    # Subagent delegation
    {
        "id": "task",
        "name": "Task (Subagent)",
        "description": "Delegate a task to a subagent",
        "category": "delegation",
        "requires_api_key": None,
    },
    {
        "id": "delegate",
        "name": "Delegate",
        "description": "Alias for task (subagent delegation)",
        "category": "delegation",
        "requires_api_key": None,
    },
    # Data analysis tools
    {
        "id": "save_analysis_result",
        "name": "Save Analysis Result",
        "description": "Save analysis report and optionally copy an attached file (e.g. a plot) to the output directory",
        "category": "data_analysis",
        "requires_api_key": None,
    },
    # Skill management tools
    {
        "id": "create_skill",
        "name": "Create Skill",
        "description": "Create a new skill in the database. Agents use this to save generated skills to the Skills Library.",
        "category": "skills",
        "requires_api_key": None,
    },
    {
        "id": "update_skill",
        "name": "Update Skill",
        "description": "Update an existing skill's name, description, instructions, tags, or triggers.",
        "category": "skills",
        "requires_api_key": None,
    },
    {
        "id": "delete_skill",
        "name": "Delete Skill",
        "description": "Delete a skill from the database by its skill_id.",
        "category": "skills",
        "requires_api_key": None,
    },
    # Document Index tools (vectorless RAG)
    {
        "id": "doc_index_list",
        "name": "Doc Index - List Documents",
        "description": "List all indexed documents with metadata (no embeddings, vectorless RAG)",
        "category": "retrieval",
        "requires_api_key": None,
    },
    {
        "id": "doc_index_structure",
        "name": "Doc Index - Get Document Structure",
        "description": "Get the table-of-contents tree structure for a document",
        "category": "retrieval",
        "requires_api_key": None,
    },
    {
        "id": "doc_index_pages",
        "name": "Doc Index - Get Page Content",
        "description": "Get the full content of specific pages from a document (e.g. '3-5,7')",
        "category": "retrieval",
        "requires_api_key": None,
    },
    # Note: print_hello has been moved to a custom tool (DB-backed, editable in UI).
    # See backend/create_print_hello_tool.py for the registration.
    # GraphIndex tools
    {
        "id": "graphindex_search",
        "name": "GraphIndex - Search Documents",
        "description": "Search project documents using GraphIndex with LLM semantic routing. Returns matching docs (primary + 0-3 supporting).",
        "category": "retrieval",
        "requires_api_key": None,
    },
    {
        "id": "graphindex_load",
        "name": "GraphIndex - Load Document Content",
        "description": "Load the full content of a document by its context_doc_id (from graphindex_search). Returns complete document text.",
        "category": "retrieval",
        "requires_api_key": None,
    },
    {
        "id": "graphindex_list_docs",
        "name": "GraphIndex - List Documents",
        "description": "List all documents available in the project with their about-preview. Use this to discover what docs exist before calling graphindex_search.",
        "category": "retrieval",
        "requires_api_key": None,
    },
    {
        "id": "graphindex_multi_doc_load",
        "name": "GraphIndex - Multi-Doc Load",
        "description": "One-shot: route a query to the best primary document, then load primary + 0-3 supporting documents as a combined context string.",
        "category": "retrieval",
        "requires_api_key": None,
    },
    # Note: graphindex_ingest / graphindex_rebuild_one / graphindex_rebuild_project /
    # graphindex_show have been moved to custom tools (DB-backed, editable in UI).
    # See backend/create_graphindex_workflow_tools.py and rename_studio_tools.py.
    # The native Python functions are still defined in this file (above) and
    # imported by the custom tools' inline code.
]


def get_tool_registry() -> List[Dict[str, Any]]:
    """
    Get the full tool registry with metadata for UI display.

    Returns a list of tool metadata dictionaries consumed by the frontend
    (agent editor, Studio node config). Each entry contains:
      - id: unique tool identifier
      - name: human-readable name
      - description: short description
      - category: grouping key (web, filesystem, memory, reasoning, delegation)
      - requires_api_key: env var name of the required API key, or None

    Returns:
        List of tool metadata dictionaries
    """
    return TOOL_REGISTRY
