# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
MCP Manager Service

Manages MCP (Model Context Protocol) server lifecycle, tool discovery, and invocation.
Handles communication with MCP servers running as subprocesses.

Features:
- Lazy loading: Servers initialized on-demand instead of at startup
- Health checks: Automatic retry with exponential backoff
- Capability caching: Pre-defined capabilities to avoid discovery timeouts
- Graceful degradation: System works even if some MCPs fail
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.mcp_tools import (
    MCPServerConfig,
    MCPToolInvocation,
    MCPToolResult,
    MCPToolCapability,
    BUILTIN_MCP_SERVERS,
)

# HTTP MCP transport (optional — only used when a server config requests
# transport="streamable_http"). Imported lazily inside start() so the stdio-only
# path doesn't pay the import cost.

logger = logging.getLogger(__name__)


# =============================================================================
# MCP Multimodal Content Parsing
# =============================================================================

def _parse_mcp_content_blocks(result: Any) -> Tuple[List[Dict], List[Dict], bool]:
    """
    Parse MCP tool result into content blocks and artifacts.

    MCP tools can return multimodal content (text, images, audio, files) in their responses.
    This function parses the standard MCP response format into structured content blocks.

    Args:
        result: Raw result from MCP tool invocation

    Returns:
        Tuple of (content_blocks, artifacts, has_multimodal)
        - content_blocks: List of parsed content blocks for LLM context
        - artifacts: List of content blocks for UI display only
        - has_multimodal: True if result contains non-text content
    """
    content_blocks: List[Dict] = []
    artifacts: List[Dict] = []
    has_multimodal = False

    if result is None:
        return content_blocks, artifacts, has_multimodal

    # Handle dict with standard MCP content format
    if isinstance(result, dict):
        # Standard MCP content array format: { "content": [...] }
        if "content" in result and isinstance(result["content"], list):
            for block in result["content"]:
                parsed = _parse_single_content_block(block)
                if parsed:
                    content_blocks.append(parsed)
                    if parsed.get("type") in ("image", "audio", "resource", "file"):
                        has_multimodal = True

        # Check for artifacts (content meant for UI display, not LLM)
        if "artifacts" in result and isinstance(result["artifacts"], list):
            for block in result["artifacts"]:
                parsed = _parse_single_content_block(block)
                if parsed:
                    artifacts.append(parsed)
                    if parsed.get("type") in ("image", "audio", "resource", "file"):
                        has_multimodal = True

        # If no content array but has other data, treat the whole dict as result
        if not content_blocks and "content" not in result:
            # Check for direct image/screenshot data (common in browser tools)
            if "screenshot" in result or "image" in result:
                image_data = result.get("screenshot") or result.get("image")
                if isinstance(image_data, str):
                    content_blocks.append({
                        "type": "image",
                        "data": image_data,
                        "mimeType": result.get("mimeType", "image/png"),
                        "alt_text": result.get("alt_text")
                    })
                    has_multimodal = True
            else:
                # Wrap as text if it's a plain result dict
                content_blocks.append({
                    "type": "text",
                    "text": json.dumps(result, indent=2)
                })

    # Handle list of content blocks directly
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                parsed = _parse_single_content_block(item)
                if parsed:
                    content_blocks.append(parsed)
                    if parsed.get("type") in ("image", "audio", "resource", "file"):
                        has_multimodal = True
            elif isinstance(item, str):
                content_blocks.append({"type": "text", "text": item})

    # Handle raw string result
    elif isinstance(result, str):
        content_blocks.append({"type": "text", "text": result})

    # Handle other primitives
    else:
        content_blocks.append({"type": "text", "text": str(result)})

    return content_blocks, artifacts, has_multimodal


def _parse_single_content_block(block: Dict) -> Optional[Dict]:
    """
    Parse a single MCP content block.

    Args:
        block: Raw content block dict from MCP response

    Returns:
        Parsed content block dict or None if invalid
    """
    if not isinstance(block, dict):
        return None

    block_type = block.get("type")

    if block_type == "text":
        text = block.get("text", "")
        if text:
            return {"type": "text", "text": text}

    elif block_type == "image":
        data = block.get("data", "")
        if data:
            return {
                "type": "image",
                "data": data,
                "mimeType": block.get("mimeType", "image/png"),
                "alt_text": block.get("alt_text")
            }

    elif block_type == "audio":
        data = block.get("data", "")
        if data:
            return {
                "type": "audio",
                "data": data,
                "mimeType": block.get("mimeType", "audio/wav"),
                "duration_seconds": block.get("duration_seconds")
            }

    elif block_type == "resource":
        uri = block.get("uri", "")
        if uri:
            return {
                "type": "resource",
                "uri": uri,
                "mimeType": block.get("mimeType"),
                "blob": block.get("blob"),
                "text": block.get("text")
            }

    elif block_type == "file":
        return {
            "type": "file",
            "name": block.get("name", "unnamed"),
            "mimeType": block.get("mimeType"),
            "data": block.get("data"),
            "text": block.get("text")
        }

    # If no recognized type, but has text content, treat as text
    elif "text" in block:
        return {"type": "text", "text": block["text"]}

    return None

# Capability cache to avoid slow/unreliable capability discovery
# This significantly speeds up startup and avoids timeout issues
CAPABILITY_CACHE: Dict[str, List[Dict[str, Any]]] = {
    "test-runner": [
        {"name": "run_pytest", "description": "Run Python tests using pytest", "category": "testing"},
        {"name": "run_jest", "description": "Run JavaScript/TypeScript tests using Jest", "category": "testing"},
        {"name": "run_tests_auto", "description": "Auto-detect test framework and run tests", "category": "testing"}
    ],
    "static-analyzer": [
        {"name": "run_pylint", "description": "Run pylint on Python code", "category": "linting"},
        {"name": "run_mypy", "description": "Run mypy type checker on Python code", "category": "linting"},
        {"name": "run_eslint", "description": "Run ESLint on JavaScript/TypeScript code", "category": "linting"},
        {"name": "run_tsc", "description": "Run TypeScript compiler type checking", "category": "linting"},
        {"name": "analyze_auto", "description": "Auto-detect language and run appropriate linters", "category": "linting"}
    ]
}


class MCPServer:
    """Represents a running MCP server instance"""
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        # HTTP transport handles (only populated when config.transport == "streamable_http")
        self._http_ctx = None            # async-context-manager from streamablehttp_client()
        self._http_session: Optional[Any] = None   # mcp.ClientSession
        self._http_read: Optional[Any] = None      # the inbound stream
        self.is_running = False
        self.capabilities: List[MCPToolCapability] = config.capabilities.copy()

    async def _start_streamable_http(self) -> bool:
        """Connect to an MCP server already running at `config.url` over HTTP.

        Uses the official `mcp` SDK's streamablehttp_client + ClientSession so
        we get a typed interface instead of raw JSON-RPC over stdin/stdout.
        The server is expected to be already running (LangConfig does not
        start it). On success, `self._http_session` is set; on failure we
        retry up to 3 times with exponential backoff.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = self.config.url
        if not url:
            logger.error(f"MCP server {self.config.server_id}: streamable_http requires `url`")
            return False

        # Inject credentials from auth service if any.
        headers: Dict[str, str] = {}
        # (no user_id / db here — streamable_http is a standalone server, no
        # per-request credential injection. The server reads its own env vars.)

        max_retries = 3
        retry_delay = 1.0
        last_err: Optional[str] = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"Retry {attempt}/{max_retries} for MCP server: {self.config.display_name}")
                else:
                    logger.info(f"Connecting to MCP server: {self.config.display_name} at {url}")

                self._http_ctx = streamablehttp_client(url=url, headers=headers or None)
                # Enter the context manager and keep both the streams and the
                # cleanup task alive for the lifetime of the server.
                self._http_read, self._http_write, _get_session_id = await self._http_ctx.__aenter__()
                self._http_session = ClientSession(self._http_read, self._http_write)
                await self._http_session.initialize()
                # Probe the server so we fail fast if it returns an error.
                await self._http_session.list_tools()
                self.is_running = True
                logger.info(f"✓ MCP server {self.config.server_id} connected (streamable_http at {url})")
                return True
            except Exception as e:
                last_err = str(e)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {self.config.server_id}: {e}")
                # Clean up partial state
                if self._http_session is not None:
                    try:
                        await self._http_session.close()
                    except Exception:
                        pass
                    self._http_session = None
                if self._http_ctx is not None:
                    try:
                        await self._http_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    self._http_ctx = None
                self._http_read = None
                self._http_write = None
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        logger.error(f"Failed to connect to MCP server {self.config.server_id} at {url}: {last_err}")
        return False

    async def start(self, use_cache: bool = True, user_id: Optional[int] = None, db: Optional[AsyncSession] = None) -> bool:
        """
        Start the MCP server process with health check and retry logic.

        Args:
            use_cache: Use cached capabilities instead of discovery (faster, more reliable)
            user_id: User ID for credential injection (optional)
            db: Database session for credential retrieval (optional)
        """
        if self.is_running:
            logger.warning(f"MCP server {self.config.server_id} is already running")
            return True

        # ── HTTP transport: connect to a server already running at `url`. ──
        # The user starts the server once (e.g. via uvx, docker compose, or a
        # daemon) and LangConfig just consumes it. We use the official `mcp`
        # SDK's streamablehttp_client + ClientSession to get a high-level
        # interface instead of the raw JSON-RPC over stdin/stdout that
        # stdio uses.
        if self.config.transport == "streamable_http":
            return await self._start_streamable_http()

        max_retries = 3
        retry_delay = 1.0  # Start with 1 second

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"Retry {attempt}/{max_retries} for MCP server: {self.config.display_name}")
                else:
                    logger.info(f"Starting MCP server: {self.config.display_name}")

                logger.debug(f"Command: {' '.join(self.config.command)}")

                # Inject credentials if user_id and db provided
                env_vars = self.config.env_vars.copy()
                if user_id and db:
                    from services.agent_auth_service import get_agent_auth_service, AccessType
                    auth_service = get_agent_auth_service()
                    env_vars = await auth_service.inject_mcp_credentials(
                        mcp_server_id=self.config.server_id,
                        user_id=user_id,
                        env_vars=env_vars,
                        db=db,
                        access_type=AccessType.DELEGATED
                    )

                # Start the MCP server as a subprocess
                self.process = await asyncio.create_subprocess_exec(
                    *self.config.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, **env_vars}
                )

                # Wait a bit to ensure it started successfully
                await asyncio.sleep(1)

                if self.process.returncode is not None:
                    stderr = await self.process.stderr.read()
                    raise RuntimeError(f"MCP server failed to start: {stderr.decode()}")

                # Health check: Try to communicate with the server
                if not await self._health_check():
                    raise RuntimeError("Health check failed")

                self.is_running = True
                logger.info(f"✓ MCP server {self.config.server_id} started successfully")

                # Load capabilities from cache or discover
                if use_cache and self.config.server_id in CAPABILITY_CACHE:
                    self._load_capabilities_from_cache()
                    logger.info(f"✓ Loaded {len(self.capabilities)} capabilities from cache")
                elif not self.capabilities:
                    await self._discover_capabilities()

                return True

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {self.config.server_id}: {e}")

                # Clean up failed attempt
                if self.process:
                    try:
                        if self.process.returncode is None:
                            self.process.kill()
                            await self.process.wait()
                    except:
                        pass
                    self.process = None

                # Last attempt failed
                if attempt == max_retries - 1:
                    logger.error(f"Failed to start MCP server {self.config.server_id} after {max_retries} attempts")
                    self.is_running = False
                    return False

                # Exponential backoff
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

        return False

    async def _health_check(self, timeout: float = 5.0) -> bool:
        """
        Perform a health check on the MCP server.
        Returns True if server is responsive, False otherwise.
        """
        try:
            # Simple ping to check if server is responsive
            request = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "ping",
                "params": {}
            }

            # Try to send a simple request
            await asyncio.wait_for(self._send_request_raw(request), timeout=timeout)
            return True

        except asyncio.TimeoutError:
            logger.warning(f"Health check timeout for {self.config.server_id}")
            return False
        except Exception as e:
            logger.debug(f"Health check failed for {self.config.server_id}: {e}")
            # Some servers may not support ping, so we'll consider them healthy
            return True

    def _load_capabilities_from_cache(self):
        """Load capabilities from the pre-defined cache"""
        cached = CAPABILITY_CACHE.get(self.config.server_id, [])
        self.capabilities = [
            MCPToolCapability(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema={},
                category=tool.get("category", "general")
            )
            for tool in cached
        ]
    
    async def stop(self):
        """Stop the MCP server process (or close HTTP session)"""
        if not self.is_running:
            return

        # HTTP transport: close the streamable-http client + session.
        if self._http_session is not None or self._http_ctx is not None:
            try:
                logger.info(f"Closing MCP HTTP session: {self.config.display_name}")
                if self._http_session is not None:
                    try:
                        await self._http_session.close()
                    except Exception as e:
                        logger.debug(f"session.close() error: {e}")
            except Exception as e:
                logger.warning(f"Error closing HTTP session for {self.config.server_id}: {e}")
            finally:
                self._http_session = None
            try:
                if self._http_ctx is not None:
                    await self._http_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"http_ctx.__aexit__ error: {e}")
            finally:
                self._http_ctx = None
                self._http_read = None
                self._http_write = None
                self.is_running = False
            return

        # stdio transport: terminate the subprocess.
        if not self.process:
            return
        try:
            logger.info(f"Stopping MCP server: {self.config.display_name}")

            # Check if process is still running before attempting to terminate
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"MCP server {self.config.server_id} did not stop gracefully, killing")
                    if self.process.returncode is None:  # Still running?
                        self.process.kill()
                        await self.process.wait()
        except ProcessLookupError:
            # Process already terminated, which is fine
            pass
        except Exception as e:
            logger.warning(f"Error stopping MCP server {self.config.server_id}: {e}")
        finally:
            self.is_running = False
            self.process = None
    
    async def _discover_capabilities(self):
        """Discover available tools from the MCP server"""
        try:
            # HTTP transport: use the high-level SDK call directly.
            if self._http_session is not None:
                logger.debug(f"Listing tools over HTTP from {self.config.server_id}")
                result = await self._http_session.list_tools()
                tools = result.tools
                self.capabilities = [
                    MCPToolCapability(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema or {},
                        category="discovered",
                    )
                    for tool in tools
                ]
                logger.info(f"Discovered {len(self.capabilities)} tools from {self.config.server_id} (HTTP)")
                return

            # stdio transport: give servers more time to initialize.
            await asyncio.sleep(1)
            logger.debug(f"Sending tools/list request to {self.config.server_id}")

            # Send initialization request to discover tools (longer timeout for large toolsets)
            response = await self._send_request({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }, timeout=60)  # 60 second timeout for tool discovery

            if response and "result" in response:
                tools = response["result"].get("tools", [])
                logger.debug(f"Raw response from {self.config.server_id}: {len(tools)} tools")

                self.capabilities = [
                    MCPToolCapability(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        category="discovered"
                    )
                    for tool in tools
                ]
                logger.info(f"Discovered {len(self.capabilities)} tools from {self.config.server_id}")
            else:
                logger.warning(f"No tools/list result from {self.config.server_id}, response: {response}")

        except Exception as e:
            logger.warning(f"Could not discover capabilities for {self.config.server_id}: {e}")
    
    async def _send_request_raw(self, request: Dict[str, Any], timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Send a raw JSON-RPC request to the MCP server (stdio only)."""
        # The HTTP transport path uses the high-level SDK session directly
        # (see _discover_capabilities / invoke_tool). If a caller hits this
        # method on an HTTP server, fall back to a clear error.
        if self.config.transport == "streamable_http" or self._http_session is not None:
            raise RuntimeError(
                f"MCP server {self.config.server_id}: _send_request_raw is stdio-only; "
                "use the HTTP session (invoke_tool / _discover_capabilities) instead."
            )
        if not self.process:
            raise RuntimeError(f"MCP server {self.config.server_id} process not available")

        try:
            # Write request
            request_json = json.dumps(request) + "\n"
            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()

            # Read response with timeout
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=timeout
            )

            if not response_line:
                raise RuntimeError("MCP server closed connection")

            response = json.loads(response_line.decode())
            return response

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from {self.config.server_id}")
            raise
        except Exception as e:
            logger.error(f"Error communicating with MCP server {self.config.server_id}: {e}")
            raise

    async def _send_request(self, request: Dict[str, Any], timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request to the MCP server"""
        if not self.is_running or not self.process:
            raise RuntimeError(f"MCP server {self.config.server_id} is not running")

        return await self._send_request_raw(request, timeout)
    
    async def invoke_tool(self, invocation: MCPToolInvocation) -> MCPToolResult:
        """Invoke a tool on this MCP server"""
        start_time = time.time()

        try:
            # HTTP transport: use the high-level SDK call directly.
            if self._http_session is not None:
                result = await self._http_session.call_tool(
                    invocation.tool_name, invocation.arguments or {}
                )
                execution_time = time.time() - start_time

                # Build a dict-shaped result the same way stdio's
                # jsonrpc response is shaped, so downstream `_parse_mcp_content_blocks`
                # works for both.
                content_dicts = []
                for block in (result.content or []):
                    item = {"type": getattr(block, "type", "text")}
                    if hasattr(block, "text"):
                        item["text"] = block.text
                    content_dicts.append(item)
                raw_result = {
                    "content": content_dicts,
                    "isError": bool(getattr(result, "isError", False)),
                }
                if result.isError:
                    err_text = ""
                    for item in content_dicts:
                        if item.get("text"):
                            err_text += item["text"]
                    return MCPToolResult(
                        success=False,
                        tool_name=invocation.tool_name,
                        error=err_text or "Unknown error",
                        execution_time=execution_time,
                    )

                content_blocks, artifacts, has_multimodal = _parse_mcp_content_blocks(raw_result)
                return MCPToolResult(
                    success=True,
                    tool_name=invocation.tool_name,
                    result=raw_result,
                    execution_time=execution_time,
                    metadata={
                        "server_id": self.config.server_id,
                        "server_type": self.config.server_type,
                    },
                    content_blocks=content_blocks,
                    artifacts=artifacts,
                    has_multimodal=has_multimodal,
                )

            # stdio transport: build a raw JSON-RPC request and send it.
            request = {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000),
                "method": "tools/call",
                "params": {
                    "name": invocation.tool_name,
                    "arguments": invocation.arguments
                }
            }

            response = await self._send_request(request, timeout=invocation.timeout)
            execution_time = time.time() - start_time

            if "error" in response:
                return MCPToolResult(
                    success=False,
                    tool_name=invocation.tool_name,
                    error=response["error"].get("message", "Unknown error"),
                    execution_time=execution_time
                )

            raw_result = response.get("result")

            # Parse multimodal content from MCP result
            content_blocks, artifacts, has_multimodal = _parse_mcp_content_blocks(raw_result)

            if has_multimodal:
                logger.info(f"Tool {invocation.tool_name} returned multimodal content: "
                           f"{len(content_blocks)} blocks, {len(artifacts)} artifacts")

            return MCPToolResult(
                success=True,
                tool_name=invocation.tool_name,
                result=raw_result,  # Keep raw for backwards compatibility
                execution_time=execution_time,
                metadata={
                    "server_id": self.config.server_id,
                    "server_type": self.config.server_type
                },
                content_blocks=content_blocks,
                artifacts=artifacts,
                has_multimodal=has_multimodal
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Tool invocation failed for {invocation.tool_name}: {e}")
            return MCPToolResult(
                success=False,
                tool_name=invocation.tool_name,
                error=str(e),
                execution_time=execution_time
            )


class MCPManager:
    """
    Manages multiple MCP servers and routes tool invocations.

    Features:
    - Lazy loading: Servers initialized on-demand, not at startup
    - Health checks: Automatic retry with exponential backoff
    - Graceful degradation: System works even if some MCPs fail
    - Routes tool invocations to appropriate servers
    """

    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self._initialized = False
        self._pending_servers: Dict[str, MCPServerConfig] = {}  # Servers not yet started
        self._failed_servers: Dict[str, str] = {}  # Servers that failed to start
        self._initialization_lock = asyncio.Lock()  # Prevent concurrent initialization

    async def initialize(self, lazy_load: bool = True):
        """
        Initialize the MCP manager.

        Args:
            lazy_load: If True, don't start servers immediately (start on first use)
                      If False, start all enabled servers now (old behavior)
        """
        if self._initialized:
            return

        logger.info("Initializing MCP Manager...")

        if lazy_load:
            # Just register servers, don't start them yet
            for server_id, config in BUILTIN_MCP_SERVERS.items():
                if config.enabled:
                    # Use config.server_id as the key (e.g., "web-search", "filesystem-local")
                    self._pending_servers[config.server_id] = config
                    logger.debug(f"Registered {config.server_id} ({config.display_name}) for lazy loading")

            logger.info(f"✓ MCP Manager initialized with {len(self._pending_servers)} servers (lazy loading)")
            logger.debug(f"Pending servers keys: {list(self._pending_servers.keys())}")
        else:
            # Old behavior: Start all servers immediately
            for server_id, config in BUILTIN_MCP_SERVERS.items():
                if config.enabled:
                    await self.add_server(config)

            logger.info(f"✓ MCP Manager initialized with {len(self.servers)} servers")

        self._initialized = True
    
    async def _ensure_server_started(self, server_id: str) -> bool:
        """
        Ensure a server is started (lazy loading).
        If server is pending, start it now. If already started, return True.

        Returns:
            True if server is running, False if it failed to start
        """
        # Already running
        if server_id in self.servers:
            return True

        # Already failed
        if server_id in self._failed_servers:
            logger.warning(f"Skipping {server_id} - previously failed: {self._failed_servers[server_id]}")
            return False

        # Not registered
        if server_id not in self._pending_servers:
            logger.error(f"MCP server {server_id} not found in registry")
            return False

        # Start the server (with lock to prevent concurrent initialization)
        async with self._initialization_lock:
            # Double-check after acquiring lock
            if server_id in self.servers:
                return True

            config = self._pending_servers[server_id]
            logger.info(f"Lazy loading MCP server: {config.display_name}")

            server = MCPServer(config)
            success = await server.start(use_cache=True)

            if success:
                self.servers[server_id] = server
                del self._pending_servers[server_id]
                logger.info(f"✓ Lazy loaded MCP server: {config.display_name}")
                return True
            else:
                self._failed_servers[server_id] = "Failed to start"
                logger.error(f"✗ Failed to lazy load MCP server: {config.display_name}")
                return False

    async def add_server(self, config: MCPServerConfig) -> bool:
        """Add and start a new MCP server"""
        if config.server_id in self.servers:
            logger.warning(f"MCP server {config.server_id} already exists")
            return False

        server = MCPServer(config)
        success = await server.start(use_cache=True)

        if success:
            self.servers[config.server_id] = server
            logger.info(f"Added MCP server: {config.display_name}")
        else:
            self._failed_servers[config.server_id] = "Failed to start"

        return success
    
    async def remove_server(self, server_id: str):
        """Stop and remove an MCP server"""
        if server_id in self.servers:
            await self.servers[server_id].stop()
            del self.servers[server_id]
            logger.info(f"Removed MCP server: {server_id}")
    
    async def shutdown(self):
        """Shutdown all MCP servers"""
        logger.info("Shutting down MCP Manager...")
        for server in self.servers.values():
            await server.stop()
        self.servers.clear()
        self._initialized = False
    
    def get_server(self, server_id: str) -> Optional[MCPServer]:
        """Get an MCP server by ID"""
        return self.servers.get(server_id)
    
    def list_servers(self) -> List[MCPServerConfig]:
        """List all registered MCP servers"""
        return [server.config for server in self.servers.values()]
    
    def list_capabilities(self, server_id: Optional[str] = None) -> List[MCPToolCapability]:
        """List available tools from all servers or a specific server"""
        if server_id:
            server = self.servers.get(server_id)
            return server.capabilities if server else []
        
        # Return all capabilities from all servers
        all_capabilities = []
        for server in self.servers.values():
            all_capabilities.extend(server.capabilities)
        return all_capabilities
    
    async def invoke_tool(self, invocation: MCPToolInvocation) -> MCPToolResult:
        """
        Invoke a tool on the specified MCP server.
        Uses lazy loading - starts the server if not already running.
        """
        # Lazy load the server if needed
        if invocation.server_id not in self.servers:
            success = await self._ensure_server_started(invocation.server_id)
            if not success:
                return MCPToolResult(
                    success=False,
                    tool_name=invocation.tool_name,
                    error=f"MCP server {invocation.server_id} failed to start",
                    execution_time=0.0
                )

        server = self.servers.get(invocation.server_id)

        if not server:
            return MCPToolResult(
                success=False,
                tool_name=invocation.tool_name,
                error=f"MCP server {invocation.server_id} not found",
                execution_time=0.0
            )

        if not server.is_running:
            return MCPToolResult(
                success=False,
                tool_name=invocation.tool_name,
                error=f"MCP server {invocation.server_id} is not running",
                execution_time=0.0
            )

        return await server.invoke_tool(invocation)


# =============================================================================
# Global MCP Manager Singleton
# =============================================================================
# This is the ONLY place where the MCP manager singleton should be defined.
# All other modules should import get_mcp_manager from this file.

_mcp_manager: Optional[MCPManager] = None


async def get_mcp_manager() -> MCPManager:
    """
    Get the global MCP manager instance (singleton pattern).

    The MCP manager is initialized once at application startup with lazy_load=True,
    meaning MCP servers are registered but not started until first use.

    This ensures:
    - Single source of truth for MCP server state
    - All tool loading code uses the same manager instance
    - Lazy loading works consistently across workflows

    Returns:
        The global MCPManager instance
    """
    global _mcp_manager

    logger = logging.getLogger(__name__)
    logger.debug(f"get_mcp_manager() called - _mcp_manager is None: {_mcp_manager is None}")

    if _mcp_manager is None:
        logger.info("Creating NEW MCP Manager instance (first initialization)")
        _mcp_manager = MCPManager()
        # CRITICAL: Use lazy_load=True to register servers without starting them
        # Servers will start on-demand when tools are first requested
        await _mcp_manager.initialize(lazy_load=True)
    else:
        logger.debug(f"Returning existing MCP Manager instance (initialized={_mcp_manager._initialized})")

    return _mcp_manager


def get_mcp_manager_sync() -> MCPManager:
    """Get the MCP manager synchronously (for FastAPI dependencies)"""
    global _mcp_manager
    
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
        # Note: Will need to call initialize() separately in async context
    
    return _mcp_manager
