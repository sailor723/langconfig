"""
API endpoint for direct model invocation (Playground).

Allows the frontend to call model.invoke() without creating an agent.
Supports all model types: DeepSeek, OpenAI, Anthropic, Google, and local models.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from db.database import get_db
from models.model import Model
from models.settings import Settings as SettingsModel
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])

OPENAI_COMPATIBLE_PROVIDER_BASE_URLS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimax.chat/v1",
}


class ModelInvokeRequest(BaseModel):
    model: str = Field(..., description="Model identifier (e.g., deepseek-chat, gpt-4o, claude-sonnet-4-5)")
    message: str = Field(..., description="User message to send to the model")
    system_prompt: Optional[str] = Field(None, description="Optional system prompt")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Temperature for generation")
    max_tokens: Optional[int] = Field(None, ge=1, le=500000, description="Max tokens to generate")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Nucleus sampling — only consider tokens with top_p cumulative probability")
    frequency_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0, description="Penalize tokens by their frequency so far")
    presence_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0, description="Penalize tokens that already appeared")
    stop: Optional[list] = Field(None, description="Stop sequences (list of strings)")
    json_mode: bool = Field(False, description="Force JSON output (structured_output)")
    tools: bool = Field(False, description="Enable tool/function calling for this turn")
    stream: bool = Field(False, description="Stream the response (NDJSON chunks)")
    tool_names: Optional[list[str]] = Field(None, description="List of demo tool names to bind (e.g. ['get_weather', 'get_current_time']). Defaults to all if not specified.")
    image_url: Optional[str] = Field(None, description="URL of an image to include for multimodal (vision) testing.")


class ToolCallLog(BaseModel):
    """One tool invocation trace entry returned in ModelInvokeResponse."""
    name: str
    arguments: dict
    result: str


class ModelInvokeResponse(BaseModel):
    content: str
    usage: Optional[dict] = None
    model: str
    tool_calls: Optional[list[ToolCallLog]] = None


def _get_settings_row(db: Session) -> SettingsModel:
    """Read the single runtime settings row from PostgreSQL."""
    settings_row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    if not settings_row:
        raise HTTPException(
            status_code=400,
            detail="Settings row not found. Configure Settings before invoking a model.",
        )
    return settings_row


def _resolve_model_name(model_name: Optional[str], db: Session) -> str:
    """Resolve the explicit model or the default model from .env."""
    if model_name:
        return model_name

    from config import settings as app_settings
    if app_settings.default_model:
        return app_settings.default_model

    raise HTTPException(
        status_code=400,
        detail="Default model is not configured in .env (DEFAULT_MODEL).",
    )


def _get_active_model_row(db: Session, model_name: str) -> Optional[Model]:
    """Fetch the active model record from the models table."""
    return (
        db.query(Model)
        .filter(
            Model.model_id == model_name,
            Model.is_active.is_(True),
        )
        .first()
    )


def _get_decrypted_setting_value(settings_row: SettingsModel, key_name: str) -> Optional[str]:
    """Get API key from .env (via app_settings) for a provider."""
    from config import settings as app_settings
    mapping: dict[str, Optional[str]] = {
        "openai": app_settings.openai_api_key,
        "anthropic": app_settings.anthropic_api_key,
        "google": app_settings.google_api_key,
        "cohere": None,
        "replicate": None,
        "deepseek": app_settings.deepseek_api_key,
        "glm": None,
        "minimax": app_settings.minimax_api_key,
        "tavily": app_settings.tavily_api_key,
        "serper": app_settings.serper_api_key,
        "agnes": app_settings.agnes_api_key,
        "agnes_base_url": app_settings.agnes_base_url,
    }
    return mapping.get(key_name)


def _create_openai_compatible_llm(
    model_name: str,
    temperature: float,
    max_tokens: Optional[int],
    api_key: str,
    base_url: str,
):
    """Create an OpenAI-compatible client for providers that expose custom base URLs."""
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=False,
    )


def _create_llm_for_playground(
    model_name: str,
    temperature: float,
    max_tokens: Optional[int],
    db: Session,
):
    """
    Create an LLM instance for the playground.
    Reads model metadata and provider credentials from PostgreSQL.
    """
    streaming = False  # Non-streaming for simplicity

    resolved_model_name = _resolve_model_name(model_name, db)
    settings_row = _get_settings_row(db)
    model_row = _get_active_model_row(db, resolved_model_name)

    if resolved_model_name.startswith("local-") or (
        model_row and model_row.source == "local"
    ) or any(
        resolved_model_name.startswith(f"{provider}-")
        for provider in ["ollama", "lmstudio", "vllm", "litellm"]
    ):
        from services.local_model_service import LocalModelService

        local_config = LocalModelService.get_local_model_config(resolved_model_name)
        if not local_config:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Local model '{resolved_model_name}' not found. "
                    "Configure it in Settings > Local Models."
                ),
            )
        return ChatOpenAI(
            model=local_config.model_name,
            base_url=local_config.base_url,
            api_key=local_config.api_key or "not-needed",
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            timeout=local_config.timeout,
        )

    if not model_row:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {resolved_model_name}. Check available models in Settings.",
        )

    provider = model_row.provider
    api_key = _get_decrypted_setting_value(settings_row, provider)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"API key required for {resolved_model_name} (provider: {provider}). "
                "Add it in Settings > API Keys."
            ),
        )

    if provider == "deepseek":
        return init_chat_model(
            model=resolved_model_name,
            model_provider="deepseek",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            streaming=streaming,
        )

    if provider == "agnes":
        base_url = _get_decrypted_setting_value(settings_row, "agnes_base_url") or model_row.base_url
        if not base_url:
            raise HTTPException(
                status_code=400,
                detail="Agnes base URL must be configured in .env (AGNES_BASE_URL).",
            )
        return _create_openai_compatible_llm(
            model_name=resolved_model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
        )

    if provider in OPENAI_COMPATIBLE_PROVIDER_BASE_URLS:
        return _create_openai_compatible_llm(
            model_name=resolved_model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=OPENAI_COMPATIBLE_PROVIDER_BASE_URLS[provider],
        )

    init_kwargs = {
        "model": resolved_model_name,
        "model_provider": "google_genai" if provider == "google" else provider,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": api_key,
        "streaming": streaming,
    }
    if provider == "google":
        init_kwargs["convert_system_message_to_human"] = True

    return init_chat_model(**init_kwargs)


# ════════════════════════════════════════════════════════════════════════
# Demo tool registry — used by the Playground when tools=true
# ════════════════════════════════════════════════════════════════════════

DEMO_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city. Returns temperature and conditions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name (e.g. 'Tokyo', 'San Francisco')"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "description": "Temperature unit"}
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date/time, optionally for a timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone (e.g. 'UTC', 'Asia/Tokyo'). Defaults to UTC."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web and return a list of relevant URLs and snippets. Use this for up-to-date information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "max_results": {"type": "integer", "description": "Max number of results to return (1-10)", "default": 3}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression. Supports + - * / ** ( ) and math functions like sqrt, sin, cos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression, e.g. 'sqrt(144) + 3*4'"}
                },
                "required": ["expression"],
            },
        },
    },
]


def _execute_demo_tool(name: str, args: dict) -> str:
    """Run a demo tool and return its output as a string."""
    try:
        if name == "get_weather":
            city = args.get("city", "unknown")
            unit = args.get("unit", "celsius")
            # Deterministic demo output (no real API call)
            mock = {
                "Tokyo":    (22, "Partly cloudy"),
                "London":   (15, "Light rain"),
                "New York": (18, "Sunny"),
                "San Francisco": (16, "Foggy"),
                "Paris":    (17, "Overcast"),
                "Beijing":  (24, "Hazy"),
                "Shanghai": (26, "Humid"),
                "Sydney":   (20, "Clear"),
            }
            for key, (t, cond) in mock.items():
                if key.lower() in city.lower():
                    t_disp = round(t * 9/5 + 32) if unit == "fahrenheit" else t
                    return f"Weather in {key}: {cond}, {t_disp}°{'F' if unit == 'fahrenheit' else 'C'}"
            # generic fallback
            t = 20
            t_disp = round(t * 9/5 + 32) if unit == "fahrenheit" else t
            return f"Weather in {city}: Clear, {t_disp}°{'F' if unit == 'fahrenheit' else 'C'} (mock data)"

        if name == "get_current_time":
            from datetime import datetime
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(args.get("timezone") or "UTC")
            except Exception:
                tz = None
            now = datetime.now(tz) if tz else datetime.utcnow()
            return f"Current time: {now.isoformat(timespec='seconds')} ({args.get('timezone') or 'UTC'})"

        if name == "search_web":
            q = args.get("query", "")
            n = min(int(args.get("max_results", 3) or 3), 10)
            # Deterministic mock results
            return (
                f"Search results for '{q}' (top {n}):\n"
                f"1. https://example.com/{q.replace(' ', '-')}-overview\n"
                f"   Snippet: Overview of {q} with key facts and references.\n"
                f"2. https://docs.example.com/{q.replace(' ', '-')}\n"
                f"   Snippet: Official documentation and latest updates on {q}.\n"
                f"3. https://blog.example.com/{q.replace(' ', '-')}-2026\n"
                f"   Snippet: 2026 trends and analysis on {q}.\n"
            )[:1500]

        if name == "calculate":
            expr = args.get("expression", "")
            import math
            safe_globals = {
                "__builtins__": {},
                "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log, "exp": math.exp, "pi": math.pi, "e": math.e,
                "abs": abs, "round": round, "pow": pow,
            }
            result = eval(expr, safe_globals)  # noqa: S307 — controlled input
            return f"{expr} = {result}"

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error: {type(e).__name__}: {e}"


@router.post("/invoke", response_model=ModelInvokeResponse)
async def model_invoke(request: ModelInvokeRequest, db: Session = Depends(get_db)):
    """
    Direct model invocation — no agent, no tools.

    Equivalent to:
        model = ChatOpenAI(model=...)
        response = model.invoke([HumanMessage(content="...")])

    Use this from the Playground UI to test any configured model.
    """
    try:
        resolved_model_name = _resolve_model_name(request.model, db)
        llm = _create_llm_for_playground(
            resolved_model_name,
            request.temperature,
            request.max_tokens,
            db,
        )

        # Apply optional sampling / penalty params if supported by provider
        if request.top_p is not None:
            try: llm.top_p = request.top_p
            except Exception: pass
        if request.frequency_penalty is not None:
            try: llm.frequency_penalty = request.frequency_penalty
            except Exception: pass
        if request.presence_penalty is not None:
            try: llm.presence_penalty = request.presence_penalty
            except Exception: pass
        if request.stop:
            try: llm.stop = request.stop
            except Exception: pass

        # JSON mode (structured output): instruct via system message for non-native providers
        messages = []
        sys_extra = ""
        if request.json_mode:
            sys_extra = "\n\nYou MUST respond with valid JSON only. No prose, no markdown code fences."
        if request.system_prompt:
            messages.append(SystemMessage(content=request.system_prompt + sys_extra))
        elif sys_extra:
            messages.append(SystemMessage(content=sys_extra.strip()))

        # Build user message — text-only OR multimodal (text + image_url)
        if request.image_url:
            try:
                user_msg = HumanMessage(
                    content=[
                        {"type": "text", "text": request.message or "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": request.image_url}},
                    ]
                )
            except Exception:
                user_msg = HumanMessage(content=request.message)
        else:
            user_msg = HumanMessage(content=request.message)
        messages.append(user_msg)

        # Bind demo tools if requested
        tool_call_log: list[ToolCallLog] = []
        if request.tools:
            try:
                from langchain_core.tools import tool as _tool_dec
                tools_to_bind = []
                names = request.tool_names or [s["function"]["name"] for s in DEMO_TOOL_SCHEMAS]

                from langchain_core.tools import StructuredTool

                def _make_tool(spec):
                    """Build a LangChain StructuredTool from a DEMO_TOOL_SCHEMAS entry (mock)."""
                    fname = spec["function"]["name"]
                    fdesc = spec["function"]["description"]
                    fparams = spec["function"]["parameters"]
                    props = fparams.get("properties", {})
                    required = fparams.get("required", [])

                    def _run(**kwargs):
                        return _execute_demo_tool(fname, kwargs)

                    return StructuredTool.from_function(
                        func=_run,
                        name=fname,
                        description=fdesc,
                        args_schema={
                            "type": "object",
                            "properties": props,
                            "required": required,
                        },
                    )

                for schema in DEMO_TOOL_SCHEMAS:
                    name = schema["function"]["name"]
                    if name not in names:
                        continue
                    tools_to_bind.append(_make_tool(schema))

                if tools_to_bind:
                    llm = llm.bind_tools(tools_to_bind)
                    logger.info(f"Bound {len(tools_to_bind)} tools: {[t.name for t in tools_to_bind]}")
            except Exception as e:
                logger.warning(f"Tool binding failed: {e}")

        # Tool-calling agent loop (max 3 turns)
        response = llm.invoke(messages)
        tool_turns = 0
        while request.tools and getattr(response, "tool_calls", None) and tool_turns < 3:
            from langchain_core.messages import ToolMessage
            messages.append(response)
            for tc in response.tool_calls:
                tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                tool_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                tool_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", f"call_{tool_turns}")
                tool_result = _execute_demo_tool(tool_name, tool_args or {})
                tool_call_log.append(ToolCallLog(name=tool_name, arguments=tool_args or {}, result=tool_result))
                messages.append(ToolMessage(content=tool_result, tool_call_id=tool_id))
            response = llm.invoke(messages)
            tool_turns += 1

        usage_meta = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage_meta = {
                "input_tokens": response.usage_metadata.get("input_tokens", 0),
                "output_tokens": response.usage_metadata.get("output_tokens", 0),
                "total_tokens": response.usage_metadata.get("total_tokens", 0),
            }

        return ModelInvokeResponse(
            content=response.content if isinstance(response.content, str) else str(response.content),
            usage=usage_meta,
            model=resolved_model_name,
            tool_calls=tool_call_log or None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Model invoke failed for {request.model}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
