# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared agent utilities for LangConfig.

Consolidates model resolution, config validation, and tool loading logic
that is shared between AgentFactory and DeepAgentFactory.

This eliminates the duplication between the two factories while keeping
each factory focused on its own agent-creation pipeline.
"""

import logging
from typing import Dict, Any, List, Optional, Sequence
from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langchain_core.language_models import BaseLanguageModel, BaseChatModel
from langchain.chat_models import init_chat_model
from config import settings, get_api_key_from_db

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Default Configuration Constants
DEFAULT_MODEL = "claude-haiku-4-5-20251015"
DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 1_000_000

# Validation Bounds Constants
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 1_000_000

# Supported Models Registry (for validation) — loaded from DB models table
# Fallback kept for bootstrapping if DB is not available
_SUPPORTED_MODELS_FALLBACK = {
    "gpt-5.1", "gpt-4o", "gpt-4o-mini",
    "deepseek-chat", "deepseek-reasoner",
    "claude-opus-4-5", "claude-opus-4-5-20250514",
    "claude-sonnet-4-5", "claude-sonnet-4-5-20250514", "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5", "claude-haiku-4-5-20251015",
    "gemini-3-pro-preview", "gemini-2.5-flash",
}


def get_supported_models() -> set:
    """Load supported model IDs from the `models` DB table. Falls back to hardcoded set."""
    try:
        from db.database import SessionLocal
        from models.model import Model
        db = SessionLocal()
        try:
            models = db.query(Model.model_id).filter(Model.is_active == True).all()
            if models:
                return {m[0] for m in models}
        finally:
            db.close()
    except Exception:
        pass
    return _SUPPORTED_MODELS_FALLBACK


SUPPORTED_MODELS = _SUPPORTED_MODELS_FALLBACK


# =============================================================================
# Config Validation
# =============================================================================

def validate_agent_config(agent_config: Dict[str, Any]) -> List[str]:
    """
    Comprehensive validation of agent configuration.

    Validates:
    - Required fields
    - Parameter bounds (temperature, tokens)
    - Model compatibility
    - Tool configurations
    - Middleware compatibility
    - Mutual exclusions

    Returns:
        List of error/warning messages (empty if valid)
    """
    errors = []

    # 1. Check required fields
    if not agent_config.get("model"):
        errors.append("model is required")

    # 2. Validate temperature bounds
    temperature = agent_config.get("temperature", DEFAULT_TEMPERATURE)
    if not isinstance(temperature, (int, float)):
        errors.append(f"temperature must be a number, got {type(temperature).__name__}")
    elif not (MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE):
        errors.append(f"temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}, got {temperature}")

    # 3. Validate max_tokens bounds
    max_tokens = agent_config.get("max_tokens", DEFAULT_MAX_TOKENS)
    if not isinstance(max_tokens, int):
        errors.append(f"max_tokens must be an integer, got {type(max_tokens).__name__}")
    elif not (MIN_MAX_TOKENS <= max_tokens <= MAX_MAX_TOKENS):
        errors.append(f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}, got {max_tokens}")

    # 4. Validate model name (warn if not in registry, don't fail)
    model_name = agent_config.get("model", DEFAULT_MODEL)
    supported = get_supported_models()
    if model_name and model_name not in supported:
        logger.warning(f"Model '{model_name}' not in supported registry. Supported: {sorted(supported)}")

    # 5. Check mutual exclusivity: structured output + tools
    has_tools = (
        agent_config.get("native_tools") or
        agent_config.get("mcp_tools") or
        agent_config.get("cli_tools") or
        agent_config.get("custom_tools")
    )
    if agent_config.get("enable_structured_output") and has_tools:
        errors.append("Cannot use structured output with tools (mutually exclusive)")

    # 6. Validate tool configurations (if tool IDs are strings)
    for tool_field in ["native_tools", "cli_tools", "custom_tools", "mcp_tools"]:
        tools_list = agent_config.get(tool_field, [])
        if tools_list and not isinstance(tools_list, list):
            errors.append(f"{tool_field} must be a list, got {type(tools_list).__name__}")
        elif tools_list:
            for tool in tools_list:
                if not isinstance(tool, str):
                    errors.append(f"{tool_field} must contain strings, found {type(tool).__name__}")
                    break

    # 7. Validate interrupt node names (if provided as lists)
    for interrupt_field in ["interrupt_before", "interrupt_after"]:
        interrupt_val = agent_config.get(interrupt_field)
        if interrupt_val and isinstance(interrupt_val, list):
            valid_nodes = {"agent", "tools"}
            for node in interrupt_val:
                if node not in valid_nodes:
                    logger.warning(f"{interrupt_field} contains unknown node '{node}'. Valid nodes: {valid_nodes}")

    # 8. Validate middleware configuration
    middleware = agent_config.get("middleware", [])
    if middleware and not isinstance(middleware, list):
        errors.append(f"middleware must be a list, got {type(middleware).__name__}")

    # 9. Validate fallback models
    fallback_models = agent_config.get("fallback_models", [])
    if fallback_models and not isinstance(fallback_models, list):
        errors.append(f"fallback_models must be a list, got {type(fallback_models).__name__}")
    elif fallback_models:
        for fallback in fallback_models:
            if not isinstance(fallback, str):
                errors.append(f"fallback_models must contain strings, found {type(fallback).__name__}")
                break

    return errors


# =============================================================================
# LLM Creation
# =============================================================================

def local_model_extra_body(local_config) -> Optional[Dict[str, Any]]:
    """Extra request body for local OpenAI-compatible chat calls.

    Qwen3-series models served by Ollama enable a long "thinking" phase by
    default; those reasoning tokens can stall clients and even exceed the
    request timeout before the first real answer token arrives. Passing
    `think: false` skips that phase entirely. Non-reasoning models (e.g.
    gemma4) ignore the flag harmlessly, so this only fires for the family
    that actually supports the toggle.

    Args:
        local_config: LocalModelConfig for the model being created.

    Returns:
        Extra body dict, or None when no override applies.
    """
    if getattr(local_config, "provider", "") != "ollama":
        return None
    name = (getattr(local_config, "model_name", "") or "").lower()
    if name.startswith("qwen3") or name.startswith("qwq"):
        return {"think": False}
    return None


def is_ollama_reasoning_model(local_config) -> bool:
    """Whether an Ollama model supports (and should keep) its thinking phase.

    Qwen3/QwQ-family models serve reasoning natively; keeping it ON lets the
    chain-of-thought be captured into `additional_kwargs["reasoning_content"]`
    and shown in the UI. Other Ollama models don't support thinking, so the
    flag is left off (Ollama ignores it harmlessly either way).
    """
    if getattr(local_config, "provider", "") != "ollama":
        return False
    name = (getattr(local_config, "model_name", "") or "").lower()
    return name.startswith("qwen3") or name.startswith("qwq")


# Token budget reserved for a reasoning model's chain-of-thought so the final
# answer is not starved out by the thinking phase.
REASONING_HEADROOM_TOKENS = 8192

# Minimum context window served to Ollama models (128K). Reasoning models eat
# a large share of it during thinking, so the context must be sized generously.
OLLAMA_CONTEXT_TOKENS = 131072


def ollama_num_predict(max_tokens: Optional[int], reasoning: bool) -> Optional[int]:
    """Map a max_tokens budget to Ollama `num_predict`.

    With reasoning enabled the chain-of-thought counts against the output
    budget; without headroom a small `max_tokens` is fully consumed by
    thinking and the final answer comes back empty. The result is capped at
    the Ollama context window (`num_ctx`), which also bounds output.

    Args:
        max_tokens: Requested output token cap (None = model default).
        reasoning: Whether thinking mode is enabled for this model.

    Returns:
        Ollama num_predict value (None keeps the model default).
    """
    if max_tokens is None:
        return None
    budget = max_tokens + (REASONING_HEADROOM_TOKENS if reasoning else 0)
    return min(budget, OLLAMA_CONTEXT_TOKENS)


def normalize_ollama_base_url(base_url: Optional[str]) -> str:
    """Strip any path (typically `/v1`) from a local endpoint URL.

    The DB stores OpenAI-compatible URLs (`http://localhost:11434/v1`), but
    ChatOllama speaks the native `/api/chat` protocol on the host root, so the
    trailing path must be dropped or every request would hit a 404.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base_url or "")
    if not parts.scheme:
        return base_url or ""
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def build_local_chat_model(
    local_config,
    temperature: float,
    max_tokens: Optional[int],
    streaming: bool = True,
) -> BaseChatModel:
    """Create a chat model for a locally-hosted model.

    Ollama models are built with ChatOllama (native `/api/chat`) because the
    OpenAI-compatible `/v1` shim used by ChatOpenAI drops `reasoning_content`
    — the model's thinking output. ChatOllama preserves it (when `reasoning`
    is enabled) in `additional_kwargs["reasoning_content"]`. Other local
    providers (LM Studio, vLLM, ...) keep the OpenAI-compatible client.

    Args:
        local_config: LocalModelConfig for the model being created.
        temperature: Generation temperature.
        max_tokens: Maximum tokens to generate (maps to Ollama `num_predict`).
        streaming: Request streaming mode (OpenAI-compatible providers only).

    Returns:
        Configured chat model instance.
    """
    if getattr(local_config, "provider", "") == "ollama":
        from langchain_ollama import ChatOllama

        reasoning = is_ollama_reasoning_model(local_config)
        return ChatOllama(
            model=local_config.model_name,
            base_url=normalize_ollama_base_url(local_config.base_url),
            temperature=temperature,
            num_ctx=OLLAMA_CONTEXT_TOKENS,
            num_predict=ollama_num_predict(max_tokens, reasoning),
            reasoning=reasoning,
            client_kwargs={"timeout": local_config.timeout},
        )

    return ChatOpenAI(
        model=local_config.model_name,
        base_url=local_config.base_url,
        api_key=local_config.api_key or "not-needed",
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=local_config.timeout,
        extra_body=local_model_extra_body(local_config),
    )


async def resolve_model(
    model_name: str,
    temperature: float,
    max_tokens: Optional[int],
    config: Dict[str, Any]
) -> BaseChatModel:
    """
    Create an LLM instance based on model name using init_chat_model.

    Supports:
    - OpenAI (GPT-5, GPT-4.5, o1, etc.)
    - Anthropic (Claude 4.x, Claude 3.7, etc.)
    - Google (Gemini 2.0, Gemini 3, etc.)
    - DeepSeek (OpenAI-compatible via ChatOpenAI)
    - Local models (Ollama, LM Studio, vLLM, etc.)

    Args:
        model_name: Model identifier (e.g., "gpt-5-turbo", "claude-4-sonnet", "deepseek-chat")
        temperature: Generation temperature (0.0-2.0)
        max_tokens: Maximum tokens to generate
        config: Full agent config (for provider-specific params)

    Returns:
        Configured BaseChatModel instance

    Raises:
        ValueError: If the model's API key is not configured
    """
    logger.debug(f"Initializing LLM instance for model: {model_name}")
    streaming = config.get("streaming", True)

    # --- Look up provider from models DB table (single source of truth) ---
    db_provider = None
    try:
        from db.database import SessionLocal
        from models.model import Model
        db = SessionLocal()
        try:
            model_row = db.query(Model).filter(
                Model.model_id == model_name,
                Model.is_active == True
            ).first()
            if model_row and model_row.source == 'cloud':
                db_provider = model_row.provider
        finally:
            db.close()
    except Exception:
        pass

    # --- DeepSeek Models ---
    if db_provider == "deepseek" or model_name.startswith("deepseek"):
        if not get_api_key_from_db("deepseek_api_key"):
            raise ValueError(f"DEEPSEEK_API_KEY is required for model {model_name}")

        return init_chat_model(
            model=model_name,
            model_provider="deepseek",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=get_api_key_from_db("deepseek_api_key"),
            streaming=streaming,
        )

    # --- Local Models (Ollama, LM Studio, vLLM, etc.) ---
    if model_name.startswith("local-") or any(
        model_name.startswith(f"{p}-") for p in ["ollama", "lmstudio", "vllm", "litellm"]
    ):
        from services.local_model_service import LocalModelService
        local_config = LocalModelService.get_local_model_config(model_name)
        if not local_config:
            raise ValueError(
                f"Local model '{model_name}' not found or not validated. "
                "Configure it in Settings > Local Models and test the connection."
            )
        logger.info(f"✓ Creating local model: {local_config.model_name} via {local_config.provider} at {local_config.base_url}")
        return build_local_chat_model(
            local_config,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

    # --- Standard Providers via init_chat_model ---
    if db_provider == "openai" or model_name.startswith("gpt"):
        provider = "openai"
        api_key = get_api_key_from_db("openai_api_key")
        base_url = getattr(settings, 'OPENAI_API_BASE', None)
    elif db_provider == "anthropic" or model_name.startswith("claude"):
        provider = "anthropic"
        api_key = get_api_key_from_db("anthropic_api_key")
        base_url = None
    elif db_provider == "google" or model_name.startswith("gemini"):
        provider = "google_genai"
        api_key = get_api_key_from_db("google_api_key") or get_api_key_from_db("gemini_api_key")
        base_url = None
    elif db_provider == "agnes" or model_name.startswith("agnes"):
        provider = "openai"
        api_key = get_api_key_from_db("agnes_api_key")
        base_url = settings.AGNES_BASE_URL
    elif db_provider == "minimax" or model_name.startswith("minimax"):
        provider = "openai"
        api_key = get_api_key_from_db("minimax_api_key")
        base_url = settings.MINIMAX_API_BASE
    elif db_provider == "kimi" or model_name.startswith("kimi"):
        provider = "openai"
        api_key = get_api_key_from_db("kimi_api_key") or get_api_key_from_db("minimax_api_key")
        base_url = getattr(settings, 'KIMI_API_BASE', None) or "https://api.moonshot.cn/v1"
    elif db_provider == "qwen" or model_name.startswith("qwen"):
        provider = "openai"
        api_key = get_api_key_from_db("qwen_api_key")
        base_url = getattr(settings, 'QWEN_API_BASE', None) or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif db_provider == "glm" or model_name.startswith("glm"):
        provider = "openai"
        api_key = get_api_key_from_db("glm_api_key")
        base_url = getattr(settings, 'GLM_API_BASE', None) or "https://open.bigmodel.cn/api/paas/v4"
    else:
        logger.warning(f"Unknown model '{model_name}', defaulting to OpenAI-compatible.")
        provider = "openai"
        api_key = get_api_key_from_db("openai_api_key")
        base_url = getattr(settings, 'OPENAI_API_BASE', None)

    if not api_key:
        raise ValueError(f"API key is required for model {model_name} (provider: {provider})")

    init_kwargs = {
        "model": model_name,
        "model_provider": provider,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": api_key,
        "streaming": streaming,
    }
    if base_url:
        init_kwargs["base_url"] = base_url

    if provider == "google_genai":
        init_kwargs["convert_system_message_to_human"] = True

    logger.debug(f"init_chat_model kwargs: model={model_name}, provider={provider}, ...")
    return init_chat_model(**init_kwargs)


async def create_llm_with_fallbacks(
    primary_model: str,
    fallback_models: Sequence[str],
    temperature: float,
    max_tokens: Optional[int],
    config: Dict[str, Any]
) -> BaseLanguageModel:
    """
    Creates the primary LLM and configures fallbacks if provided.

    Args:
        primary_model: Primary model identifier
        fallback_models: List of fallback model identifiers
        temperature: Generation temperature
        max_tokens: Maximum tokens to generate
        config: Full agent configuration

    Returns:
        Configured LLM instance with fallbacks

    Raises:
        ValueError: If primary and all fallback models fail to initialize
    """
    attempted_models = []
    errors = []

    # Try primary model
    try:
        logger.info(f"Attempting to create primary model: {primary_model}")
        primary_llm = await resolve_model(primary_model, temperature, max_tokens, config)
        attempted_models.append(primary_model)
        logger.info(f"✓ Primary model '{primary_model}' initialized successfully")
    except Exception as e:
        error_msg = f"Primary model '{primary_model}' failed: {str(e)}"
        logger.error(error_msg)
        errors.append(error_msg)
        primary_llm = None

    # If no fallback models provided, fail if primary failed
    if not fallback_models:
        if primary_llm is None:
            raise ValueError(
                f"Failed to initialize primary model '{primary_model}'. "
                f"Error: {errors[0]}"
            )
        return primary_llm

    # Try fallback models
    fallbacks = []
    for fb_model in fallback_models:
        try:
            logger.info(f"Attempting fallback model: {fb_model}")
            fb_llm = await resolve_model(fb_model, temperature, max_tokens, config)
            fallbacks.append(fb_llm)
            attempted_models.append(fb_model)
            logger.info(f"✓ Fallback model '{fb_model}' initialized successfully")
        except Exception as e:
            error_msg = f"Fallback model '{fb_model}' failed: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)

    # If primary succeeded, apply fallbacks and return
    if primary_llm is not None:
        if fallbacks:
            logger.info(f"✓ Configured {len(fallbacks)} fallback(s) for primary model '{primary_model}'")
            return primary_llm.with_fallbacks(fallbacks)
        else:
            logger.warning(f"Primary model succeeded but no fallbacks available")
            return primary_llm

    # Primary failed — use first successful fallback as primary
    if fallbacks:
        logger.warning(
            f"Primary model '{primary_model}' failed, using first successful fallback '{fallback_models[0]}' as primary"
        )
        primary_llm = fallbacks[0]
        additional_fallbacks = fallbacks[1:]
        if additional_fallbacks:
            return primary_llm.with_fallbacks(additional_fallbacks)
        return primary_llm

    # All models failed
    raise ValueError(
        f"Failed to initialize any LLM. Attempted models: {attempted_models}. "
        f"Errors: {'; '.join(errors)}"
    )


# =============================================================================
# Tool Loading (shared between AgentFactory and DeepAgentFactory)
# =============================================================================

SIMPLE_MEMORY_TOOL_NAMES = {"memory_store", "memory_recall", "enable_memory"}


def parse_memory_tools(native_tool_names: List[str]) -> tuple:
    """
    Separate memory tool names from regular native tool names.

    Returns:
        Tuple of (regular_tool_names, memory_tool_names)
    """
    memory_tools = [t for t in native_tool_names if t in SIMPLE_MEMORY_TOOL_NAMES]
    regular_tools = [t for t in native_tool_names if t not in SIMPLE_MEMORY_TOOL_NAMES]
    return regular_tools, memory_tools


async def load_agent_tools(
    native_tool_names: List[str],
    cli_tool_names: List[str],
    custom_tool_ids: List[str],
    workspace_context: Optional[Dict[str, Any]] = None,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
) -> List[BaseTool]:
    """
    Load tools from config, handling memory tool routing automatically.

    Memory tools are intercepted and routed to the PostgreSQL-backed SimpleMemory
    system rather than loaded as native tools.

    Args:
        native_tool_names: List of native tool names
        cli_tool_names: List of CLI tool names
        custom_tool_ids: List of custom tool IDs
        workspace_context: Optional workspace context for file-writing tools
        project_id: Project ID for memory
        task_id: Task ID for memory

    Returns:
        List of loaded BaseTool instances
    """
    from core.agents.tool_loader import ToolLoader
    tools: List[BaseTool] = []

    # Separate memory tools from regular native tools
    reg_tools, mem_tools = parse_memory_tools(native_tool_names)
    if mem_tools:
        logger.info(
            f"Detected memory tools in native_tools: {mem_tools}. "
            f"Routing to SimpleMemory (text-based + PostgreSQL)."
        )

    # Load regular native tools
    if reg_tools:
        loaded = await ToolLoader.load_native(reg_tools, workspace_context=workspace_context)
        tools.extend(loaded)
        logger.info(f"Loaded {len(loaded)} native tools: {reg_tools}")

    # Load CLI tools
    if cli_tool_names:
        loaded = await ToolLoader.load_cli(cli_tool_names)
        tools.extend(loaded)
        logger.info(f"Loaded {len(loaded)} CLI tools: {cli_tool_names}")

    # Load custom tools
    if custom_tool_ids:
        loaded = await ToolLoader.load_custom(custom_tool_ids, project_id)
        tools.extend(loaded)
        logger.info(f"Loaded {len(loaded)} custom tools: {[t.name for t in loaded]}")

    # Load memory tools (PostgreSQL-backed) if requested
    if mem_tools and project_id is not None and task_id is not None:
        try:
            from core.agents.memory import get_or_create_memory
            from db.database import AsyncSessionLocal
            db_session = AsyncSessionLocal()
            memory_system = get_or_create_memory(
                project_id=project_id,
                agent_id=f"task_{task_id}",
                db_session=db_session,
            )
            memory_tools = memory_system.create_memory_tools()
            tools.extend(memory_tools)
            logger.info(f"✓ Loaded {len(memory_tools)} memory tools (PG-backed, {memory_system.memory_count} cached)")
        except Exception as e:
            logger.error(f"Failed to add memory tools: {e}. Proceeding without them.")

    return tools
