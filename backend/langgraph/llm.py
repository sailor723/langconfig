"""Shared chat-model resolution for the code-defined LangGraph assistants.

The graph modules (sql_agent.py, sql_agent_hitl.py, ...) must stay runnable
both inside the FastAPI app and standalone (e.g. `python sql_agent.py`), so
the model is never hard-coded here:

1. `resolve_default_model()` picks the platform's *default* model — the one
   chosen in Settings > Model Cards > "Set Default" (persisted in the DB
   settings row), falling back to `.env` `DEFAULT_MODEL` and finally
   "deepseek-chat" so behaviour is unchanged when nothing is configured.
2. `build_chat_model()` constructs a chat model for that id. Inside the app
   it reuses the platform resolver (models registry + Settings > Local
   Models), so an Ollama default such as `local-ollama-gemma4` is served
   through its OpenAI-compatible endpoint; standalone it falls back to the
   `LOCAL_LLM_*` env config.
"""
import asyncio
import os
from typing import Any, Dict, Optional

from langchain.chat_models import init_chat_model

# Model ids routed to an OpenAI-compatible local endpoint
_LOCAL_PREFIXES = ("local-", "ollama-", "lmstudio-", "vllm-", "litellm-")


def _db_default_model() -> Optional[str]:
    """The model chosen in Settings > Model Cards ("Set Default").

    Returns None when the DB is unreachable (e.g. running standalone).
    """
    try:
        from db.database import SessionLocal
        from models.settings import Settings

        db = SessionLocal()
        try:
            row = db.query(Settings).filter(Settings.id == 1).first()
            if row:
                return row.default_model or row.primary_model
        finally:
            db.close()
    except Exception:
        pass
    return None


def resolve_default_model() -> str:
    """Default model id: DB settings -> .env DEFAULT_MODEL -> deepseek-chat."""
    return _db_default_model() or os.environ.get("DEFAULT_MODEL") or "deepseek-chat"


def build_chat_model(
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    **kwargs: Any,
):
    """Build a chat model for the configured default model id.

    Args:
        temperature: Generation temperature.
        max_tokens: Maximum tokens to generate.
        **kwargs: Extra init options (e.g. {"streaming": False}).
    """
    model_name = resolve_default_model()

    # Inside the FastAPI app: reuse the platform resolver, which maps the id
    # to a provider/endpoint (local models come from Settings > Local Models).
    try:
        from services.agent_utils import resolve_model

        config: Dict[str, Any] = {"streaming": True, **kwargs}
        return asyncio.run(resolve_model(model_name, temperature, max_tokens, config))
    except Exception:
        pass

    # Standalone fallback: point an Ollama client at the local endpoint
    # (default port), otherwise use the env-declared provider. ChatOllama
    # preserves the model's reasoning output; the OpenAI-compatible /v1 shim
    # would drop it.
    if model_name.startswith(_LOCAL_PREFIXES):
        from langchain_ollama import ChatOllama
        from services.agent_utils import (
            OLLAMA_CONTEXT_TOKENS,
            normalize_ollama_base_url,
            ollama_num_predict,
        )

        local_model = os.environ.get("LOCAL_LLM_MODEL") or model_name
        # Qwen3/QwQ-series models reason by default — keep thinking ON so the
        # chain-of-thought is captured and can be shown in the UI.
        reasoning = (local_model or "").lower().startswith(("qwen3", "qwq"))
        return ChatOllama(
            model=local_model,
            base_url=normalize_ollama_base_url(
                os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434/v1"
            ),
            temperature=temperature,
            num_ctx=OLLAMA_CONTEXT_TOKENS,
            num_predict=ollama_num_predict(max_tokens, reasoning),
            reasoning=reasoning,
            client_kwargs={"timeout": 600},
        )

    # Phase 5b: keys are wizard-only (settings documents, encrypted at rest).
    # get_api_key_from_db resolves .env first, then the models.api_keys document
    # — so a key entered in Settings works here without .env.
    from config import get_api_key_from_db
    api_key = get_api_key_from_db("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"

    return init_chat_model(
        model=model_name,
        model_provider=os.environ.get("DEFAULT_LLM_PROVIDER") or "deepseek",
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
    )
