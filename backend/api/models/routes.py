"""
API endpoint for direct model invocation (Playground).

Allows the frontend to call model.invoke() without creating an agent.
Supports all model types: DeepSeek, OpenAI, Anthropic, Google, and local models.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from config import settings
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])


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


def _create_llm_for_playground(model_name: str, temperature: float, max_tokens: Optional[int]):
    """
    Create an LLM instance for the playground.
    Mirrors the provider logic from AgentFactory._create_llm().
    """
    streaming = False  # Non-streaming for simplicity

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

    # DeepSeek Models
    if db_provider == "deepseek" or model_name.startswith("deepseek"):
        if not settings.DEEPSEEK_API_KEY:
            raise HTTPException(status_code=400, detail="DEEPSEEK_API_KEY not configured")
        return init_chat_model(
            model=model_name,
            model_provider="deepseek",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.DEEPSEEK_API_KEY,
            streaming=streaming,
        )

    # Local Models
    if model_name.startswith("local-") or any(
        model_name.startswith(f"{p}-") for p in ["ollama", "lmstudio", "vllm", "litellm"]
    ):
        from services.local_model_service import LocalModelService
        local_config = LocalModelService.get_local_model_config(model_name)
        if not local_config:
            raise HTTPException(
                status_code=400,
                detail=f"Local model '{model_name}' not found. Configure it in Settings > Local Models."
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

    # Agnes AI (OpenAI-compatible with custom base_url)
    if db_provider == "agnes" or model_name.startswith("agnes"):
        api_key = settings.AGNES_API_KEY
        base_url = settings.AGNES_BASE_URL or "https://apihub.agnes-ai.com/v1"
        if not api_key:
            raise HTTPException(status_code=400, detail="AGNES_API_KEY not configured")
        return ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

    # Standard Providers via init_chat_model
    if db_provider == "openai" or model_name.startswith("gpt"):
        provider = "openai"
        api_key = settings.OPENAI_API_KEY
        base_url = getattr(settings, "OPENAI_API_BASE", None)
    elif db_provider == "anthropic" or model_name.startswith("claude"):
        provider = "anthropic"
        api_key = settings.ANTHROPIC_API_KEY
        base_url = None
    elif db_provider == "google" or model_name.startswith("gemini"):
        provider = "google_genai"
        api_key = settings.GOOGLE_API_KEY or settings.GEMINI_API_KEY
        base_url = None
    else:
        # Fallback: try DB provider as OpenAI-compatible
        if db_provider:
            from db.database import SessionLocal
            from models.model import Model
            pdb = SessionLocal()
            try:
                model_row = pdb.query(Model).filter(
                    Model.model_id == model_name
                ).first()
                provider = "openai"
                api_key = getattr(settings, f"{db_provider.upper()}_API_KEY", None)
                base_url = getattr(settings, f"{db_provider.upper()}_BASE_URL", None)
            finally:
                pdb.close()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model: {model_name}. Check available models in Settings."
            )

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key required for {model_name} (provider: {provider}). Add it in Settings > API Keys."
        )

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

    return init_chat_model(**init_kwargs)


@router.post("/invoke", response_model=ModelInvokeResponse)
async def model_invoke(request: ModelInvokeRequest):
    """
    Direct model invocation — no agent, no tools.

    Equivalent to:
        model = ChatOpenAI(model=...)
        response = model.invoke([HumanMessage(content="...")])

    Use this from the Playground UI to test any configured model.
    """
    try:
        llm = _create_llm_for_playground(request.model, request.temperature, request.max_tokens)

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
            model=request.model,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Model invoke failed for {request.model}: {e}")
        raise HTTPException(status_code=500, detail=str(e))