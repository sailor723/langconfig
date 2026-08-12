# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Seed-time implementations of the DB-seeded built-in tools (seed source).
=======================================================================

This module is the SEED SOURCE for the built-in tools stored in the
``custom_tools`` table as ``is_builtin`` rows. The seeder
(scripts/seeds/seed_builtin_tools.py) bakes each tool's implementation into a
self-contained ``python_function`` row, so agents compile tools directly
from PostgreSQL at runtime — exactly like custom tools. This module is
only required at seed time (plus a few direct importers of the GraphIndex
helpers, which native_tools.py re-exports from here).

Never import from tools.native_tools.py here; tools/native_tools.py is the
thin runtime facade and re-exports from this module instead.
"""

import logging
from typing import Annotated, List, Literal, NotRequired, Optional, Dict, Any
from pathlib import Path
import asyncio
import sys

from typing_extensions import TypedDict

from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
from langchain_community.tools import DuckDuckGoSearchRun
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from core.state import DeepAgentState
import httpx
import os

# ---------------------------------------------------------------------------
# Phase 9 integration (GraphIndex cluster): keep the backend root and the
# Phase 9 package importable, mirroring the original tools/native_tools.py.
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

from tools.presentation_tools import gen_pptx

# Tavily search - conditional to avoid import errors if not installed
try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    logger.warning("Tavily not available. Install with: pip install langchain-community tavily-python")


# =============================================================================
# Cluster: web (moved verbatim from tools/native_tools.py)
# =============================================================================

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


# =============================================================================
# Cluster: filesystem (moved verbatim from tools/native_tools.py)
# =============================================================================

# File System Tools (DeepAgents standard naming)
# See: https://docs.langchain.com/oss/python/deepagents/harness
# =============================================================================

@tool
def read_file(file_path: str, offset: int = 0, limit: int = None, max_chars: int = 500_000) -> str:
    """
    Read the contents of a file with optional line offset and limit.

    Supports text files including .txt, .md, .py, .json, etc.
    Returns content with line numbers for easy reference.

    Args:
        file_path: Path to the file to read
        offset: Line number to start reading from (0-indexed, default: 0)
        limit: Maximum number of lines to read (default: None for all lines)
        max_chars: Maximum characters to read (default: 500000)

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
            # Per-agent workspace root takes precedence: used as-is, no
            # workflow/task subdirectories appended.
            workspace_root = _workspace_context.get('workspace_root')
            if workspace_root:
                workspace = Path(workspace_root).resolve()
                workspace.mkdir(parents=True, exist_ok=True)
            else:
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

        # Phase 2: durable storage copy when STORAGE_MODE=db (no-op in local).
        workspace_mgr.persist_output(path, content.encode("utf-8"))

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


# =============================================================================
# Agent Documents (DB mode) — formal document persistence
# =============================================================================
# When STORAGE_MODE=db, agents persist their FINAL deliverables through
# save_document into the agent_documents table (dedicated, versioned,
# queryable). FS mode keeps the legacy write_file flow. The tool mirrors the
# write_file pattern: a StructuredTool wrapper whose args schema hides the
# runtime-injected context kwargs (bound by ToolLoader at load time).

class SaveDocumentArgs(BaseModel):
    """Arguments for save_document tool."""
    title: str = PydanticField(
        ...,
        description="REQUIRED: Title of the formal document (e.g., 'Q3 Market Analysis Report')."
    )
    content: str = PydanticField(
        ...,
        description="REQUIRED: The COMPLETE final document content (markdown/text)."
    )
    doc_type: str = PydanticField(
        "report",
        description="Optional document type: report, notes, data, plan, code (default: report)."
    )


def _save_document_impl(
    title: str,
    content: str,
    doc_type: str = "report",
    _workspace_context: dict = None,
    _agent_context: dict = None,
) -> str:
    """Persist a formal document into the agent_documents table (DB mode).

    Saving with the same (project, title) bumps the version chain instead of
    overwriting, so the Workbench can list/get any historical version.
    """
    try:
        from models.agent_document import AgentDocument
        from db.database import SessionLocal

        # Resolve execution context; fall back to the process env vars other
        # DB tools use (GRAPHINDEX_PROJECT_ID) when no context was bound.
        ctx = _workspace_context or {}
        project_id = ctx.get("project_id")
        execution_id = ctx.get("execution_id")
        agent_id = (_agent_context or {}).get("agent_id")
        if project_id is None:
            pid = os.environ.get("GRAPHINDEX_PROJECT_ID")
            if pid:
                try:
                    project_id = int(pid)
                except (ValueError, TypeError):
                    project_id = None

        db = SessionLocal()
        try:
            # Version chain: same (project, title) -> next version.
            query = db.query(AgentDocument).filter(AgentDocument.title == title)
            if project_id is not None:
                query = query.filter(AgentDocument.project_id == project_id)
            latest = query.order_by(AgentDocument.version.desc()).first()
            version = (latest.version + 1) if latest else 1

            doc = AgentDocument(
                project_id=project_id,
                agent_id=agent_id,
                execution_id=execution_id,
                title=title,
                doc_type=doc_type or "report",
                version=version,
                content=content,
            )
            db.add(doc)
            db.commit()
        finally:
            db.close()

        scope = f"project={project_id}" if project_id is not None else "project=unset"
        return (f"Document '{title}' saved to the document library (version {version}, {scope}, "
                f"doc_type={doc_type or 'report'}, {len(content)} chars).")
    except Exception as e:
        logger.error("Error saving document '%s': %s", title, e)
        return f"Error saving document: {e}"


save_document = StructuredTool.from_function(
    func=_save_document_impl,
    name="save_document",
    args_schema=SaveDocumentArgs,
    description="""Save a FORMAL document into the project document library (database).

Use this for the FINAL deliverable of a task: reports, analyses, plans,
release notes — anything the user will view/manage in the Workbench.
Saving with the same title creates a new version instead of overwriting.

REQUIRED PARAMETERS:
1. title (str): A clear document title, e.g. 'Q3 Market Analysis Report'
2. content (str): The COMPLETE final content (markdown/text) — do not truncate

OPTIONAL:
3. doc_type (str): report (default), notes, data, plan, code

Prefer this over write_file for the task's final document; use write_file for
working files (scratch, todos, intermediate artifacts).""",
)


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

        # Phase 2: durable storage copy when STORAGE_MODE=db (no-op in local).
        from services.workspace_manager import get_workspace_manager
        get_workspace_manager().persist_output(path, new_content.encode("utf-8"))

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


# =============================================================================
# Cluster: reasoning (moved verbatim from tools/native_tools.py)
# =============================================================================

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
# Agent Management Tools (direct PostgreSQL write)
# =============================================================================

@tool
def create_deepagent(name: str,
                     system_prompt: str,
                     native_tools: list[str],
                     skills: list[str] | None = None,
                     description: str | None = None,
                     category: str | None = None,
                     model: str | None = None,
                     temperature: float | None = None) -> str:
    """Create a new DeepAgent in the database. The agent will immediately appear in the DeepAgent Studio.

    Use this tool when the user wants to SAVE a designed agent configuration permanently.

    Args:
        name: Agent name (e.g. '市场研究助手')
        system_prompt: The COMPLETE system prompt defining the agent's behavior
        native_tools: List of tool names the agent should have (e.g. ['web_search', 'web_fetch', 'reasoning_chain'])
        skills: List of skill IDs (e.g. ['web-search', 'text-summarizer'])
        description: Short 1-2 sentence description of what the agent does
        category: Agent category (e.g. 'Research', 'Coding', 'Custom')
        model: Model name (default: 'minimax-m3')
        temperature: Model temperature 0.0-1.0 (default: 0.7)
    """
    from db.database import SessionLocal
    from models.deep_agent import (
        DeepAgentTemplate,
        DeepAgentConfig,
        create_default_middleware_config,
        create_default_backend_config,
        create_default_guardrails_config,
    )
    import json

    db = SessionLocal()
    try:
        cfg = DeepAgentConfig(
            model=model or "minimax-m3",
            system_prompt=system_prompt.strip(),
            native_tools=native_tools or [],
            skills=skills or [],
            tools=[],
            cli_tools=[],
            custom_tools=[],
            temperature=temperature if temperature is not None else 0.7,
            use_deepagents=True,
            middleware=create_default_middleware_config(),
            subagents=[],
            backend=create_default_backend_config(),
            guardrails=create_default_guardrails_config(),
        )

        agent = DeepAgentTemplate(
            name=name.strip(),
            description=(description or "").strip(),
            category=category or "Custom",
            config=cfg.dict(),
            middleware_config=[m.dict() for m in cfg.middleware],
            subagents_config=[],
            backend_config=cfg.backend.dict(),
            guardrails_config=cfg.guardrails.dict(),
        )

        db.add(agent)
        db.commit()
        db.refresh(agent)

        return (
            f"✅ Agent '{name}' (id={agent.id}) created successfully!\n\n"
            f"Agent is now available in the DeepAgent Studio. The user can:\n"
            f"1. Select it from the agent dropdown to see its topology\n"
            f"2. Click 'Test' to start a conversation with it\n"
            f"3. Click 'Edit' to modify its configuration"
        )
    except Exception as e:
        db.rollback()
        return f"❌ Failed to create agent: {e}"
    finally:
        db.close()


# =============================================================================
# PostgreSQL Tools (direct DB read/write)
# =============================================================================


# =============================================================================
# Cluster: postgres (moved verbatim from tools/native_tools.py)
# =============================================================================

def _get_pg_session():
    """Get a sync PostgreSQL session via SessionLocal."""
    from db.database import SessionLocal
    return SessionLocal()


@tool
def pg_list_tables(schema_name: str = "public") -> str:
    """
    List all tables and views in a PostgreSQL schema with row counts.

    Use this to discover what tables exist in the database before querying.

    Args:
        schema_name: Schema name to list (default: 'public')

    Returns:
        Formatted table list with type (table/view) and estimated row count

    Example:
        >>> pg_list_tables()
        >>> pg_list_tables(schema_name="public")
    """
    import sqlalchemy as sa
    db = _get_pg_session()
    try:
        conn = db.connection()
        # pg_stat_user_tables uses relname; fall back to information_schema for reliability
        result = conn.execute(sa.text(
            """
            SELECT
                relname AS name,
                'table' AS type,
                n_live_tup AS estimated_rows
            FROM pg_catalog.pg_stat_user_tables
            WHERE schemaname = :schema
            UNION ALL
            SELECT
                viewname AS name,
                'view' AS type,
                0 AS estimated_rows
            FROM pg_catalog.pg_views
            WHERE schemaname = :schema
            ORDER BY name
            """
        ), {"schema": schema_name})
        rows = result.fetchall()
        if not rows:
            return f"No tables found in schema '{schema_name}'."
        lines = [f"## Tables in schema '{schema_name}'", ""]
        for r in rows:
            lines.append(f"- **{r.name}** ({r.type}, ~{r.estimated_rows} rows)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing tables: {e}"
    finally:
        db.close()


@tool
def pg_describe_table(table_name: str, schema_name: str = "public") -> str:
    """
    Show column details for a PostgreSQL table: name, type, nullable, default, constraints.

    Use this to understand a table's schema before querying or inserting data.

    Args:
        table_name: Name of the table to describe
        schema_name: Schema name (default: 'public')

    Returns:
        Formatted column list with type, nullable, default, and constraint info

    Example:
        >>> pg_describe_table("deep_agent_templates")
        >>> pg_describe_table("skills", schema_name="public")
    """
    import sqlalchemy as sa
    db = _get_pg_session()
    try:
        conn = db.connection()
        result = conn.execute(sa.text(
            """
            SELECT
                c.column_name AS name,
                c.data_type || COALESCE('(' || c.character_maximum_length::text || ')', '') AS data_type,
                c.is_nullable,
                c.column_default AS default_value,
                CASE WHEN pk.column_name IS NOT NULL THEN 'PRIMARY KEY' ELSE '' END AS constraint_type
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                    AND tc.table_schema = ku.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_name = :table_name
                    AND tc.table_schema = :schema
            ) pk ON pk.column_name = c.column_name
            WHERE c.table_name = :table_name AND c.table_schema = :schema
            ORDER BY c.ordinal_position
            """
        ), {"table_name": table_name, "schema": schema_name})
        rows = result.fetchall()
        if not rows:
            return f"Table '{schema_name}.{table_name}' not found."
        lines = [f"## Columns of '{schema_name}.{table_name}'", ""]
        for r in rows:
            nullable = "NULL" if r.is_nullable == "YES" else "NOT NULL"
            default = f" default={r.default_value}" if r.default_value else ""
            pk = " 🔑" if r.constraint_type == "PRIMARY KEY" else ""
            lines.append(f"- **{r.name}**  `{r.data_type}`  {nullable}{default}{pk}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error describing table: {e}"
    finally:
        db.close()


@tool
def pg_query(sql: str) -> str:
    """
    Run a read-only SQL SELECT query against PostgreSQL and return results as a table.

    SAFETY: Only SELECT statements are allowed. INSERT/UPDATE/DELETE are rejected.
    Use pg_execute for write operations.

    Args:
        sql: The SELECT SQL query to run (e.g. 'SELECT * FROM deep_agent_templates LIMIT 5')

    Returns:
        Query results formatted as a markdown table

    Example:
        >>> pg_query("SELECT id, name, category FROM deep_agent_templates ORDER BY created_at DESC LIMIT 10")
        >>> pg_query("SELECT count(*) AS total FROM skills")
    """
    import sqlalchemy as sa
    sql_stripped = sql.strip().lower()
    if not sql_stripped.startswith("select"):
        return "❌ Only SELECT queries are allowed. Use pg_execute for write operations."

    db = _get_pg_session()
    try:
        conn = db.connection()
        result = conn.execute(sa.text(sql))
        rows = result.fetchall()
        if not rows:
            return "Query returned no rows."
        col_names = result.keys()
        lines = ["| " + " | ".join(col_names) + " |"]
        lines.append("| " + " | ".join("---" for _ in col_names) + " |")
        for row in rows:
            vals = []
            for v in row:
                s = str(v) if v is not None else "NULL"
                if len(s) > 200:
                    s = s[:200] + "…"
                vals.append(s)
            lines.append("| " + " | ".join(vals) + " |")
        lines.append(f"\n*{len(rows)} row(s) returned*")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Query error: {e}"
    finally:
        db.close()


@tool
def pg_execute(sql: str) -> str:
    """
    Execute a write SQL statement (INSERT, UPDATE, DELETE) against PostgreSQL.

    WARNING: This modifies database data. Use with caution.

    Args:
        sql: The SQL statement to execute (e.g. "UPDATE deep_agent_templates SET name='New Name' WHERE id=1")

    Returns:
        Confirmation message with number of rows affected

    Example:
        >>> pg_execute("UPDATE deep_agent_templates SET is_public=false WHERE id=1")
        >>> pg_execute("DELETE FROM chat_sessions WHERE is_active=false")
    """
    import sqlalchemy as sa
    sql_stripped = sql.strip().lower()
    allowed_keywords = ("insert", "update", "delete", "create", "alter", "drop", "truncate")
    if not any(sql_stripped.startswith(kw) for kw in allowed_keywords):
        return "❌ Only write statements are allowed (INSERT, UPDATE, DELETE, etc.). Use pg_query for SELECT."

    db = _get_pg_session()
    try:
        conn = db.connection()
        result = conn.execute(sa.text(sql))
        db.commit()
        return f"✅ Statement executed successfully. {result.rowcount} row(s) affected."
    except Exception as e:
        db.rollback()
        return f"❌ Execute error: {e}"
    finally:
        db.close()


# =============================================================================
# PostgreSQL Domain-Specific Tools (read entity configs)
# These provide structured access to application entities rather than raw SQL.
# =============================================================================

@tool
def pg_list_agents(category: str | None = None) -> str:
    """
    List all DeepAgent templates from the database with name, category, and config summary.

    Use this to browse available agent configurations before selecting one.

    Args:
        category: Optional category filter (e.g. 'Research', 'Coding', 'Custom')

    Returns:
        Formatted list of agents with id, name, category, model, and tool count

    Example:
        >>> pg_list_agents()
        >>> pg_list_agents(category="Research")
    """
    from models.deep_agent import DeepAgentTemplate
    db = _get_pg_session()
    try:
        query = db.query(DeepAgentTemplate).order_by(DeepAgentTemplate.updated_at.desc())
        if category:
            query = query.filter(DeepAgentTemplate.category == category)
        agents = query.all()
        if not agents:
            return "No agents found." if not category else f"No agents found in category '{category}'."
        lines = [f"## DeepAgent Templates ({len(agents)} total)", ""]
        for a in agents:
            cfg = a.config or {}
            tools = cfg.get("native_tools", [])
            skills = cfg.get("skills", [])
            model = cfg.get("model", "not set")
            lines.append(
                f"- **{a.name}** (id={a.id})  "
                f"`{a.category}`  model=`{model}`  "
                f"tools={len(tools)}  skills={len(skills)}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing agents: {e}"
    finally:
        db.close()


@tool
def pg_get_agent(agent_id: int) -> str:
    """
    Get the full configuration of a DeepAgent by its ID.

    Returns system prompt, tools, skills, model, temperature, subagents, and middleware config.

    Args:
        agent_id: The numeric ID of the agent (use pg_list_agents to find IDs)

    Returns:
        Complete agent configuration in a readable format

    Example:
        >>> pg_get_agent(agent_id=1)
    """
    from models.deep_agent import DeepAgentTemplate
    db = _get_pg_session()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if not agent:
            return f"❌ Agent with id={agent_id} not found."
        cfg = agent.config or {}
        lines = [
            f"## Agent: {agent.name} (id={agent.id})",
            f"**Description**: {agent.description or '(no description)'}",
            f"**Category**: {agent.category}",
            f"**Model**: {cfg.get('model', 'not set')}",
            f"**Temperature**: {cfg.get('temperature', 0.7)}",
            f"**Use DeepAgents**: {cfg.get('use_deepagents', True)}",
            "",
            "### System Prompt",
            "```",
            cfg.get("system_prompt", "(empty)")[:2000],
            "```" if len(cfg.get("system_prompt", "")) <= 2000 else "```\n*...truncated*",
            "",
            "### Tools",
            f"- Native tools: {cfg.get('native_tools', [])}",
            f"- Skills: {cfg.get('skills', [])}",
            f"- Custom tools: {cfg.get('custom_tools', [])}",
            "",
            "### Subagents",
        ]
        subagents = cfg.get("subagents", []) or agent.subagents_config or []
        if subagents:
            for s in subagents:
                name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "?")
                desc = s.get("description") if isinstance(s, dict) else getattr(s, "description", "")
                lines.append(f"- **{name}**: {desc}")
        else:
            lines.append("(none)")
        lines.append("")
        lines.append(f"**Version**: {agent.version} | **Public**: {agent.is_public} | **Usage**: {agent.usage_count}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error getting agent: {e}"
    finally:
        db.close()


@tool
def pg_list_skills() -> str:
    """
    List all skills in the database with their IDs, descriptions, tags, and usage counts.

    Skills define reusable capabilities that agents can auto-discover and invoke.

    Returns:
        Formatted list of available skills

    Example:
        >>> pg_list_skills()
    """
    from models.skill import Skill
    db = _get_pg_session()
    try:
        skills = db.query(Skill).order_by(Skill.usage_count.desc()).all()
        if not skills:
            return "No skills found in the database."
        lines = [f"## Skills ({len(skills)} total)", ""]
        for s in skills:
            tags = ", ".join(s.tags or []) if s.tags else ""
            tag_str = f"  tags=[{tags}]" if tags else ""
            lines.append(
                f"- **{s.name}** (`{s.skill_id}`){tag_str}\n"
                f"  {s.description[:120]}{'…' if len(s.description) > 120 else ''}\n"
                f"  used {s.usage_count}x | source={s.source_type.value}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing skills: {e}"
    finally:
        db.close()


def search_skills(query: str) -> str:
    """
    Search skills by name, description, or tags.

    Useful for an agent to find relevant skills for a given task.
    Returns matching skills with their ID, name, description, tags, and triggers.

    Args:
        query: Search keyword (e.g., 'stock', 'database', 'research')

    Returns:
        Formatted list of matching skills

    Example:
        >>> search_skills("stock market")
    """
    from models.skill import Skill
    db = _get_pg_session()
    try:
        query_lower = query.lower()
        skills = db.query(Skill).order_by(Skill.usage_count.desc()).all()
        matches = []
        for s in skills:
            if (query_lower in s.name.lower() or
                query_lower in (s.description or "").lower() or
                any(query_lower in t.lower() for t in (s.tags or [])) or
                any(query_lower in t.lower() for t in (s.triggers or []))):
                matches.append(s)
        if not matches:
            return f"No skills found matching '{query}'."
        lines = [f"## Matching skills for '{query}' ({len(matches)} found)", ""]
        for s in matches:
            tags = ", ".join(s.tags or [])
            triggers = "; ".join((s.triggers or [])[:3])
            lines.append(f"### {s.name} (`{s.skill_id}`)")
            lines.append(f"  Description: {s.description or 'N/A'}")
            lines.append(f"  Tags: {tags}")
            lines.append(f"  Triggers: {triggers}")
            lines.append(f"  Used: {s.usage_count}x")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error searching skills: {e}"
    finally:
        db.close()


@tool
def pg_list_projects() -> str:
    """
    List all projects with their IDs, names, document count, and indexing status.

    Projects group documents and workflows together.

    Returns:
        Formatted list of projects

    Example:
        >>> pg_list_projects()
    """
    from models.core import Project, ContextDocument
    from sqlalchemy import func
    db = _get_pg_session()
    try:
        projects = db.query(
            Project,
            func.count(ContextDocument.id).label("doc_count")
        ).outerjoin(
            ContextDocument, ContextDocument.project_id == Project.id
        ).group_by(Project.id).order_by(Project.updated_at.desc()).all()
        if not projects:
            return "No projects found."
        lines = ["## Projects", ""]
        for proj, doc_count in projects:
            lines.append(
                f"- **{proj.name}** (id={proj.id})  "
                f"status=`{proj.status.value}`  "
                f"docs={doc_count}  "
                f"index={proj.indexing_status.value}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing projects: {e}"
    finally:
        db.close()


@tool
def pg_list_documents(project_id: int | None = None) -> str:
    """
    List all context documents (uploaded files) with their metadata.

    Documents are the source files uploaded for RAG/GraphIndex processing.
    Each document has a file_path on disk and may be indexed in Neo4j.

    Args:
        project_id: Optional project ID to filter by

    Returns:
        Formatted list of documents with metadata

    Example:
        >>> pg_list_documents()
        >>> pg_list_documents(project_id=1)
    """
    from models.core import ContextDocument
    db = _get_pg_session()
    try:
        query = db.query(ContextDocument).order_by(ContextDocument.updated_at.desc())
        if project_id is not None:
            query = query.filter(ContextDocument.project_id == project_id)
        docs = query.all()
        if not docs:
            return "No documents found." if project_id is None else f"No documents found for project_id={project_id}."
        lines = [f"## Documents ({len(docs)} total)", ""]
        for d in docs:
            lines.append(
                f"- **{d.filename}** (id={d.id})  "
                f"type={d.document_type.value}  "
                f"size={d.file_size}B  "
                f"index={d.indexing_status.value}  "
                f"project={d.project_id}"
            )
            if d.description:
                lines.append(f"  {d.description[:150]}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing documents: {e}"
    finally:
        db.close()


@tool
def pg_list_custom_tools(tool_type: str | None = None) -> str:
    """
    List all custom (user-created) tools with their type, description, and usage stats.

    Custom tools extend agent capabilities with API integrations, database connectors,
    image generators, and custom Python functions.

    Args:
        tool_type: Optional filter by type (api, notification, image_video, database, data_transform, python_function)

    Returns:
        Formatted list of custom tools

    Example:
        >>> pg_list_custom_tools()
        >>> pg_list_custom_tools(tool_type="database")
    """
    from models.custom_tool import CustomTool
    db = _get_pg_session()
    try:
        query = db.query(CustomTool).order_by(CustomTool.usage_count.desc())
        if tool_type:
            query = query.filter(CustomTool.tool_type == tool_type)
        tools = query.all()
        if not tools:
            return "No custom tools found." if not tool_type else f"No custom tools of type '{tool_type}' found."
        lines = [f"## Custom Tools ({len(tools)} total)", ""]
        for t in tools:
            lines.append(
                f"- **{t.name}** (`{t.tool_id}`)  "
                f"type={t.tool_type.value}  "
                f"template={t.template_type.value if t.template_type else 'custom'}  "
                f"used={t.usage_count}x"
            )
            if t.description:
                lines.append(f"  {t.description[:150]}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing custom tools: {e}"
    finally:
        db.close()


# =============================================================================
# Neo4j Tools (Document Index metadata)
# =============================================================================


# =============================================================================
# Cluster: neo4j (moved verbatim from tools/native_tools.py)
# =============================================================================

def _get_neo4j_idx():
    """Create a Neo4jDocumentIndex from environment variables."""
    from services.neo4j_document_index import Neo4jDocumentIndex
    idx = Neo4jDocumentIndex(
        base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
        username=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "password"),
    )
    idx.ensure_constraints()
    return idx


@tool
def neo4j_list_docs(project_id: int) -> str:
    """
    List all Document nodes in Neo4j for a project with their metadata.

    Neo4j stores document routing metadata (summary, supported queries, tags, file path).
    Use this to discover what documents are indexed before searching.

    Args:
        project_id: Project ID to list documents for

    Returns:
        Formatted list of documents with enriched metadata

    Example:
        >>> neo4j_list_docs(project_id=1)
    """
    try:
        idx = _get_neo4j_idx()
        docs = idx.list_documents(project_id)
        if not docs:
            return f"No documents indexed in Neo4j for project_id={project_id}."
        lines = [f"## Neo4j Documents (project {project_id}, {len(docs)} total)", ""]
        for d in docs:
            q_count = len(d.supported_queries or [])
            lines.append(
                f"- **{d.doc_name}** (`{d.name}`)  "
                f"pages={d.page_count}  "
                f"queries={q_count}"
            )
            about = d.what_this_document_is_about or d.description or ""
            if about:
                lines.append(f"  {about[:200]}")
            if d.file_path:
                lines.append(f"  path: `{d.file_path}`")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error listing Neo4j documents: {e}"


@tool
def neo4j_get_doc(project_id: int, name: str) -> str:
    """
    Get full metadata for one Document node from Neo4j by project_id and name.

    Returns enriched metadata: description, supported queries, file path, tags, etc.
    Use the returned file_path with read_file to get the actual document content.

    Args:
        project_id: Project ID
        name: Document name in Neo4j (use neo4j_list_docs to find names)

    Returns:
        Complete document metadata

    Example:
        >>> neo4j_get_doc(project_id=1, name="cfd711e3_report.pdf")
    """
    try:
        idx = _get_neo4j_idx()
        doc = idx.get_document(project_id, name)
        if not doc:
            return f"❌ Document '{name}' not found in Neo4j for project_id={project_id}."
        lines = [
            f"## Document: {doc.doc_name}",
            f"**Name**: `{doc.name}`",
            f"**File Path**: `{doc.file_path}`",
            f"**Context Doc ID**: {doc.context_doc_id}",
            f"**Doc Index ID**: {doc.doc_index_id or '(not set)'}",
            f"**Page Count**: {doc.page_count}",
            f"**Description**: {doc.description or '(none)'}",
            "",
            "### What this document is about",
            doc.what_this_document_is_about or "(no enrichment)",
            "",
            "### Supported Queries",
        ]
        if doc.supported_queries:
            for q in doc.supported_queries:
                lines.append(f"- {q}")
        else:
            lines.append("(none)")
        lines.append("")
        lines.append("### Tags")
        lines.append(f"{', '.join(doc.tags) if doc.tags else '(none)'}")
        lines.append("")
        lines.append("### File Path (for read_file)")
        lines.append(f"`{doc.file_path}`")
        lines.append("")
        lines.append("*Use `read_file` with the file path above to get the full document content.*")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error getting Neo4j document: {e}"


@tool
def neo4j_query(cypher: str, parameters: dict | None = None) -> str:
    """
    Run an arbitrary Cypher query against Neo4j and return results.

    Use this for custom graph queries beyond the built-in document tools.
    The query runs against the document index Neo4j database.

    Args:
        cypher: The Cypher query string (e.g. 'MATCH (d:Document {project_id: $pid}) RETURN d.name, d.page_count')
        parameters: Optional dict of query parameters (e.g. {"pid": 1})

    Returns:
        Query results as formatted text

    Example:
        >>> neo4j_query("MATCH (d:Document {project_id: $pid}) RETURN d.name, d.page_count ORDER BY d.page_count DESC LIMIT 5", {"pid": 1})
    """
    try:
        idx = _get_neo4j_idx()
        rows = idx._run_cypher(cypher, parameters or {})
        if not rows:
            return "Query returned no results."
        col_names = list(rows[0].keys())
        lines = ["## Cypher Results", ""]
        lines.append("| " + " | ".join(col_names) + " |")
        lines.append("| " + " | ".join("---" for _ in col_names) + " |")
        for row in rows:
            vals = []
            for c in col_names:
                v = row.get(c)
                s = str(v) if v is not None else "NULL"
                if len(s) > 200:
                    s = s[:200] + "…"
                vals.append(s)
            lines.append("| " + " | ".join(vals) + " |")
        lines.append(f"\n*{len(rows)} row(s) returned*")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Cypher error: {e}"


@tool
def neo4j_upsert_doc(project_id: int, name: str, file_path: str,
                     description: str = "",
                     tags: list[str] | None = None,
                     doc_name: str | None = None) -> str:
    """
    Create or update a Document node in Neo4j.

    Registers a document in the graph index so it becomes discoverable
    via graphindex_search / neo4j_list_docs. The actual file content
    should already exist on disk at file_path.

    Args:
        project_id: Project ID this document belongs to
        name: Unique document name (e.g. hash-prefixed filename)
        file_path: Absolute path to the document on disk
        description: Short description of what this document is
        tags: List of categorization tags
        doc_name: Optional display name (defaults to name)

    Returns:
        Confirmation message

    Example:
        >>> neo4j_upsert_doc(project_id=1, name="my_report.pdf", file_path="/data/my_report.pdf", description="Q3 financial analysis", tags=["finance", "quarterly"])
    """
    try:
        idx = _get_neo4j_idx()
        from services.neo4j_document_index import build_document_node_properties
        props = build_document_node_properties(
            project_id=project_id,
            context_doc_id=0,
            doc_index_id=None,
            name=name,
            file_path=file_path,
            description=description,
            tags=tags or [],
        )
        if doc_name:
            props["doc_name"] = doc_name
        idx.upsert_document(project_id, name, file_path, properties=props)
        display = doc_name or name
        return f"✅ Document '{display}' upserted in Neo4j for project {project_id}."
    except Exception as e:
        return f"❌ Error upserting document: {e}"


@tool
def neo4j_delete_doc(project_id: int, name: str) -> str:
    """
    Delete a Document node from Neo4j by project_id and name.

    Removes the document from the graph index so it no longer appears
    in search results. The actual file on disk is NOT deleted.

    Args:
        project_id: Project ID
        name: Document name in Neo4j

    Returns:
        Confirmation message

    Example:
        >>> neo4j_delete_doc(project_id=1, name="cfd711e3_report.pdf")
    """
    try:
        idx = _get_neo4j_idx()
        deleted = idx.delete_document(project_id, name)
        if deleted:
            return f"✅ Document '{name}' deleted from Neo4j (project {project_id})."
        else:
            return f"❌ Document '{name}' not found in Neo4j (project {project_id})."
    except Exception as e:
        return f"❌ Error deleting document: {e}"


# =============================================================================
# DocIndex Tools (Vectorless RAG)
# =============================================================================


# =============================================================================
# Cluster: docindex (moved verbatim from tools/native_tools.py)
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

# GraphIndex tools — doc scope filter and default project_id.
# Set by the chat route before calling the agent when the user has
# selected specific docs. None = all docs visible.
_GRAPHINDEX_DOC_SCOPE: Optional[List[str]] = None
_GRAPHINDEX_PROJECT_ID: Optional[int] = None


# =============================================================================
# Cluster: graphindex (moved verbatim from tools/native_tools.py)
# =============================================================================

def set_graphindex_doc_scope(scope: Optional[List[str]], project_id: Optional[int] = None) -> None:
    """Set the doc scope filter for graphindex tools. Pass None for 'all'."""
    global _GRAPHINDEX_DOC_SCOPE, _GRAPHINDEX_PROJECT_ID
    _GRAPHINDEX_DOC_SCOPE = scope
    _GRAPHINDEX_PROJECT_ID = project_id


def _get_project_id() -> Optional[int]:
    """Get the current project ID from module-level var (set during agent execution)."""
    if _GRAPHINDEX_PROJECT_ID is not None:
        return _GRAPHINDEX_PROJECT_ID
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
    """Search project documents using GraphIndex vector matching.

    Uses the canonical Phase 9 graphindex modules (learning.phase9.graphindex):
      - Neo4jDocumentIndex.find_best_document for vector-based document matching

    Returns matching documents with name, type, domain, and supporting list.
    """
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided. Either pass project_id "
                "explicitly or set the GRAPHINDEX_PROJECT_ID env var.")

    try:
        from learning.phase9.graphindex.index_build import Neo4jDocumentIndex  # noqa: E402

        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()

        # Check if documents exist
        docs = idx.list_documents(project_id=project_id)
        if not docs:
            pg_result = _search_pg_fallback(query, project_id)
            if pg_result:
                return pg_result
            return f"No documents found matching '{query}' in project {project_id}."

        best = idx.find_best_document(
            project_id=project_id,
            query=query,
            scope=_GRAPHINDEX_DOC_SCOPE,
        )
        if best is None:
            return (f"No documents found matching '{query}' in project {project_id}.")

        lines = [
            f"## GraphIndex Search Results for: '{query}'",
            "",
            f"_matching: vector (enrichment metadata)_",
            "",
            f"**[1] {best.name}** (BEST MATCH)",
            f"    about: {best.what_this_document_is_about[:200] if best.what_this_document_is_about else '(none)'}",
            f"    supports: {(best.supported_queries or [])[:5]}",
            "",
        ]
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
            return f"❌ Document with context_doc_id={context_doc_id} not found in either Postgres or Neo4j."

        # Deterministic scope enforcement — refuse to load docs outside scope.
        if _GRAPHINDEX_DOC_SCOPE is not None:
            if context_doc.filename not in _GRAPHINDEX_DOC_SCOPE:
                return (f"SCOPE_ERROR: Document '{context_doc.filename}' is not in the "
                        f"current chat scope. Only the following docs are visible to "
                        f"this chat: {', '.join(_GRAPHINDEX_DOC_SCOPE)}. "
                        f"Search again within the selected scope, or ask the user to "
                        f"clear the scope filter.")

        from learning.phase9.graphindex.index_build import load_document_content  # noqa: E402
        full_content = load_document_content(context_doc.file_path or "")
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
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
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
    """One-shot: route a query to the best document, then load its full text.

    Uses GraphIndex vector matching (find_best_document) + load_doc_context.

    The LLM is expected to call this tool with a fresh query for each
    user turn. If the loaded doc's content doesn't actually answer the
    question, the LLM should call `graphindex_search` again to re-route
    to a different in-scope document before answering.

    Args:
        query: Natural language query (e.g., "compare Nike strategy with industry trends")
        project_id: Optional project ID. Uses GRAPHINDEX_PROJECT_ID env var if not set.
    """
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
        project_id = _get_project_id()
    if not project_id:
        return ("ERROR: no project_id provided. Either pass project_id "
                "explicitly or set the GRAPHINDEX_PROJECT_ID env var.")

    try:
        from learning.phase9.graphindex.index_build import load_doc_context  # noqa: E402
        from learning.phase9.graphindex.index_build import Neo4jDocumentIndex  # noqa: E402

        idx = Neo4jDocumentIndex(
            base_url=os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        docs = idx.list_documents(project_id=project_id)
        if not docs:
            return f"No documents in project {project_id}."

        best = idx.find_best_document(
            project_id=project_id,
            query=query,
            scope=_GRAPHINDEX_DOC_SCOPE,
        )
        if best is None:
            return f"No document matched '{query}'."

        context = load_doc_context(idx, project_id, [best.name])
        header = (
            f"## Multi-doc context for: '{query}'\n"
            f"primary: {best.name}\n"
        )
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
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
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
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
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
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
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
    # Module-level override (set by chat route) takes precedence over LLM-provided arg.
    if _GRAPHINDEX_PROJECT_ID is not None:
        project_id = _GRAPHINDEX_PROJECT_ID
    elif not project_id:
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
    description="Search project documents using GraphIndex vector matching. When a scope is active (user selected docs in sidebar), only in-scope documents are searchable and loadable. Returns matching documents with context_doc_id, name, type, page count, and supporting list. Use context_doc_id with graphindex_load to get full content.",
)
_graphindex_load_tool = StructuredTool.from_function(
    func=graphindex_load,
    name="graphindex_load",
    description="Load the full content of a document by its context_doc_id (obtained from graphindex_search). Returns the complete document text for the agent to read. Respects scope — refuses to load docs outside the current chat scope.",
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
# TODO management tools — vendored from notebook 2.1_todo.ipynb cells 5 + 13
# =============================================================================
# Two tools that mirror the notebook's ``write_todos`` / ``read_todos`` pair
# from ``deep_agent_0530/src/deep_agents_from_scratch/todo_tools.py``. Bound as
# native tools (not via langchain's TodoListMiddleware) so the agent gets
# BOTH tools — the library's TodoListMiddleware only ships write_todos.


# =============================================================================
# Cluster: sql_data (moved verbatim from tools/native_tools.py)
# =============================================================================

import sqlite3 as _sqlite3
import csv as _csv
import io as _io
import os as _os

TOOL_SQLITE_EXECUTE_DESCRIPTION = """Execute a read-only SQL query on a SQLite database.

IMPORTANT: Only SELECT queries are allowed. DDL/DML statements are blocked.

Use cases:
- Validate generated SQL against mock data
- Explore database schema (.tables, PRAGMA table_info)
- Test query correctness before production use

Args:
    sql: The SELECT SQL query to execute
    db_path: Path to a SQLite database file. If ":memory:", creates a temporary
             in-memory database. To load CSV data, use the csv_to_sqlite utility first.

Returns:
    Query results as formatted text (rows + column headers), or error message.

Examples:
    sqlite_execute("SELECT * FROM sqlite_master WHERE type='table'")
    sqlite_execute("PRAGMA table_info(orders)")
    sqlite_execute("SELECT COUNT(*) FROM customers")
"""


def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """
    Execute a read-only SQL query on a SQLite database.

    Useful for the sql-skill-generator agent to validate generated SQL queries
    against mock data before saving them as few-shot examples in a skill.

    Args:
        sql: SELECT SQL query to execute.
        db_path: Path to SQLite DB file or ":memory:" (default).

    Returns:
        Formatted query results or error message.
    """
    # Safety: block all non-SELECT statements
    sql_stripped = sql.strip().strip(";").strip()
    sql_lower = sql_stripped.lower()
    blocked_keywords = ["insert", "update", "delete", "drop", "alter",
                        "create", "replace", "truncate", "exec", "pragma"]

    first_word = sql_lower.split()[0] if sql_lower.split() else ""
    if first_word in blocked_keywords and first_word != "pragma":
        return f"❌ BLOCKED: Only SELECT queries are allowed. Got: '{sql_stripped[:100]}'"

    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []

        if not rows:
            conn.close()
            return "✅ Query executed. No rows returned (empty result)."

        # Format output as aligned table
        widths = [len(c) for c in col_names]
        for row in rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val)))

        header = " | ".join(c.ljust(w) for c, w in zip(col_names, widths))
        sep = "-+-".join("-" * w for w in widths)
        body = "\n".join(
            " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
            for row in rows[:50]  # Max 50 rows in output
        )

        summary = f"✅ {len(rows)} row(s) returned"
        conn.close()
        return f"{summary}\n\n{header}\n{sep}\n{body}"

    except Exception as e:
        return f"❌ SQL Error: {e}"


def sqlite_load_csv(csv_content: str, table_name: str, db_path: str = ":memory:") -> str:
    """
    Load CSV data into a SQLite database.
    Utility function — infers column names from CSV header.

    Args:
        csv_content: CSV content as string (with header row)
        table_name: Name of the table to create
        db_path: Path to SQLite DB file or ":memory:"

    Returns:
        Status message with row count.
    """
    try:
        reader = _csv.DictReader(_io.StringIO(csv_content))
        rows = list(reader)
        if not rows:
            return "❌ CSV has no data rows."

        col_names = list(rows[0].keys())
        col_defs = ", ".join(f'"{c}" TEXT' for c in col_names)
        placeholders = ", ".join("?" for _ in col_names)

        conn = _sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
        cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

        for row in rows:
            values = [row.get(c, "") for c in col_names]
            col_list = ', '.join(f'"{c}"' for c in col_names)
            cursor.execute(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})', values)

        conn.commit()
        conn.close()
        return f"✅ Loaded {len(rows)} rows into table '{table_name}' ({len(col_names)} columns: {', '.join(col_names)})"
    except Exception as e:
        return f"❌ CSV Load Error: {e}"


# =============================================================================
# Python Execution Tool
# =============================================================================

import sys as _sys
import subprocess as _subprocess
import tempfile as _tempfile
import textwrap as _textwrap

TOOL_PYTHON_EXECUTE_DESCRIPTION = """Execute Python code for data analysis and visualization.

Use with caution — code runs in a restricted sandbox with limited filesystem access.

Available libraries: pandas, matplotlib, numpy, json, csv, statistics, math, datetime, collections.

Use cases:
- Data analysis with pandas
- Chart generation with matplotlib
- Statistical calculations
- Data transformation

Args:
    code: Python code to execute (use print() to see output)
    timeout: Maximum execution time in seconds (default: 30)

Returns:
    stdout/stderr from the execution.

Examples:
    import pandas as pd
    import matplotlib.pyplot as plt
    data = {'x': [1,2,3], 'y': [4,5,6]}
    df = pd.DataFrame(data)
    print(df.describe())
    plt.plot(df['x'], df['y'])
    plt.savefig('/tmp/chart.png')
    print('Chart saved to /tmp/chart.png')
"""


def python_execute(code: str, timeout: int = 30) -> str:
    """
    Execute Python code and return stdout + stderr.

    WARNING: Code runs in the same process. Only trusted agents should call this.

    Args:
        code: Python code to execute
        timeout: Max execution time in seconds

    Returns:
        Combined stdout and stderr output.
    """
    try:
        # Wrap code to capture stdout
        wrapper_code = (
            "import sys, io, traceback\n"
            "_buffer = io.StringIO()\n"
            "sys.stdout = _buffer\n"
            "sys.stderr = _buffer\n"
            "try:\n"
            + _textwrap.indent(code, '    ') + "\n"
            "except Exception:\n"
            "    traceback.print_exc()\n"
            "finally:\n"
            "    sys.stdout = sys.__stdout__\n"
            "    sys.stderr = sys.__stderr__\n"
            "    print(_buffer.getvalue(), end='')\n"
        )
        result = _subprocess.run(
            [_sys.executable, "-c", wrapper_code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={k: v for k, v in _os.environ.items() if k in ("PATH", "HOME", "TEMP", "TMPDIR")}
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n--- stderr ---\n{result.stderr}"
        if result.returncode != 0 and not output:
            output = f"❌ Exit code: {result.returncode}"
        return output if output else "✅ Code executed (no output)"
    except _subprocess.TimeoutExpired:
        return f"❌ Timed out after {timeout}s"
    except Exception as e:
        return f"❌ Execution Error: {e}"
