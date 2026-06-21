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


class ModelInvokeResponse(BaseModel):
    content: str
    usage: Optional[dict] = None
    model: str


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
        "minimax": None,
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

        messages = []
        if request.system_prompt:
            messages.append(SystemMessage(content=request.system_prompt))
        messages.append(HumanMessage(content=request.message))

        response = llm.invoke(messages)

        usage_meta = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage_meta = {
                "input_tokens": response.usage_metadata.get("input_tokens", 0),
                "output_tokens": response.usage_metadata.get("output_tokens", 0),
                "total_tokens": response.usage_metadata.get("total_tokens", 0),
            }

        return ModelInvokeResponse(
            content=response.content,
            usage=usage_meta,
            model=resolved_model_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Model invoke failed for {request.model}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
