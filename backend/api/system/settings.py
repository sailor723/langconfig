# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import logging
from pydantic import BaseModel

from db.database import get_db
from models.settings import Settings as SettingsModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Pydantic Schemas
class APIKeyTestRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None


class APIKeySet(BaseModel):
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    google_api_key: Optional[str] = None
    google_base_url: Optional[str] = None
    cohere_api_key: Optional[str] = None
    cohere_base_url: Optional[str] = None
    replicate_api_key: Optional[str] = None
    replicate_base_url: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_api_base: Optional[str] = None
    glm_api_key: Optional[str] = None
    glm_api_base: Optional[str] = None
    minimax_api_key: Optional[str] = None
    minimax_api_base: Optional[str] = None
    qwen_api_key: Optional[str] = None
    qwen_api_base: Optional[str] = None
    kimi_api_key: Optional[str] = None
    kimi_api_base: Optional[str] = None
    tavily_api_key: Optional[str] = None
    serper_api_key: Optional[str] = None
    agnes_api_key: Optional[str] = None
    agnes_base_url: Optional[str] = None


class APIKeyResponse(BaseModel):
    provider: str
    is_set: bool
    masked_key: Optional[str] = None
    connected: Optional[bool] = None
    connected_message: Optional[str] = None
    kind: str = "chat"  # "chat" | "search" — lets the UI group providers


class SettingsUpdate(BaseModel):
    default_model: Optional[str] = None
    default_temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    embedding_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    storage_path: Optional[str] = None


class SettingsResponse(BaseModel):
    default_model: str
    default_temperature: float
    max_tokens: int
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    storage_path: str


class GeneralSettings(BaseModel):
    app_name: Optional[str] = "LangConfig"
    language: Optional[str] = "en"
    auto_save: Optional[bool] = True
    auto_save_interval: Optional[int] = 300
    confirm_before_delete: Optional[bool] = True
    show_notifications: Optional[bool] = True
    check_updates: Optional[bool] = True
    telemetry: Optional[bool] = False
    log_level: Optional[str] = "info"
    theme: Optional[str] = "langconfig"


class LocalModelsSettings(BaseModel):
    provider: Optional[str] = "ollama"
    base_url: Optional[str] = "http://localhost:11434/v1"
    model_name: Optional[str] = "llama3.2:latest"
    api_key: Optional[str] = None


class WorkspaceSettings(BaseModel):
    workspace_path: Optional[str] = ""
    allow_read: Optional[bool] = True
    allow_write: Optional[bool] = True
    require_approval: Optional[bool] = True
    auto_detect_git: Optional[bool] = True
    backup_before_edit: Optional[bool] = True


class WorkspaceValidateRequest(BaseModel):
    path: str


class WorkspaceValidateResponse(BaseModel):
    valid: bool
    resolved_path: Optional[str] = None
    exists: bool = False
    writable: bool = False
    error: Optional[str] = None


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    completed: bool
    has_api_key: bool
    has_workspace: bool
    default_workspace_path: str


class ModelDefaultsSettings(BaseModel):
    primary_model: Optional[str] = "gpt-4o"
    fallback_models: Optional[list[str]] = ["claude-sonnet-4-5"]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    top_p: Optional[float] = 1.0
    routing_strategy: Optional[str] = "balanced"
    daily_token_limit: Optional[int] = 0
    monthly_token_limit: Optional[int] = 0
    alert_threshold: Optional[int] = 80


import os
import platform

# Platform-specific default storage paths
def get_default_storage_path() -> str:
    system = platform.system()
    if system == "Windows":
        return os.path.join(os.getenv("APPDATA", "."), "LangConfig", "documents")
    elif system == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/LangConfig/documents")
    else:  # Linux
        return os.path.expanduser("~/.local/share/langconfig/documents")


# Process-wide guard so the settings-table migration runs at most once.
# ALTER TABLE takes an ACCESS EXCLUSIVE lock; running it on every request could
# deadlock the server when concurrent calls contend for the same table lock.
_SETTINGS_MIGRATED = False


# Helper functions for database access
def get_or_create_settings(db: Session) -> SettingsModel:
    """Get settings from database or create default row if it doesn't exist"""
    global _SETTINGS_MIGRATED
    # Migrate: add theme column if missing — once per process, with a short
    # lock_timeout so it fails fast instead of hanging the event loop forever.
    if not _SETTINGS_MIGRATED:
        try:
            from sqlalchemy import text as sa_text
            db.execute(sa_text("SET LOCAL lock_timeout = '3s'"))
            db.execute(sa_text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS theme VARCHAR DEFAULT 'langconfig'"))
            db.commit()
            _SETTINGS_MIGRATED = True
        except Exception:
            db.rollback()
            pass

    settings = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    if not settings:
        settings = SettingsModel(
            id=1,
            api_keys={},
            storage_path=get_default_storage_path()
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def mask_api_key(key: str) -> str:
    """Mask API key for display"""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


from config import settings as app_settings

# Test models for each provider
PROVIDER_TEST_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "google": "gemini-3.1-flash-lite",
    "deepseek": "deepseek-chat",
    "glm": "glm-4",
    "minimax": "minimax-m3",
    "agnes": "agnes-2.0-flash",
}

CHAT_PROVIDERS = ["openai", "anthropic", "google", "deepseek", "glm", "minimax", "qwen", "kimi", "agnes"]
SEARCH_PROVIDERS = ["tavily", "serper"]
CONNECTION_STATUS_KEY = "_connection_status"


def _test_provider_connection(provider: str, api_key: str, base_url_extra: str | None = None) -> dict:
    """Test a provider's API key by making a real LLM call."""
    test_model = PROVIDER_TEST_MODELS.get(provider)
    if not test_model:
        return {"success": False, "message": f"Unknown provider: {provider}"}
    try:
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
            _ = r.choices[0].message.content
        elif provider == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(api_key=api_key)
            r = client.messages.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5)
            _ = r.content[0].text
        elif provider == "google":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            # gemini-3 models "think" first; give the test a generous timeout
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=30)
            _ = r.choices[0].message.content
        elif provider == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
            _ = r.choices[0].message.content
        elif provider == "glm":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
            _ = r.choices[0].message.content
        elif provider == "minimax":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.minimax.chat/v1")
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
            _ = r.choices[0].message.content
        elif provider == "agnes":
            from openai import OpenAI
            base_url = base_url_extra or "https://apihub.agnes-ai.com/v1"
            client = OpenAI(api_key=api_key, base_url=base_url)
            # Agnes only responds to STREAMING chat requests — non-streaming
            # calls hang with 0 bytes server-side. Drain the SSE stream and
            # verify the key by collecting the final answer.
            stream = client.chat.completions.create(
                model=test_model,
                messages=[{"role": "user", "content": "ok"}],
                timeout=20,
                stream=True,
            )
            content = ""
            for chunk in stream:
                for choice in chunk.choices or []:
                    if choice.delta and choice.delta.content:
                        content += choice.delta.content
                    if choice.finish_reason == "stop":
                        break
            _ = content or "<empty response>"
        else:
            return {"success": False, "message": f"Test not implemented for {provider}"}
        return {"success": True, "message": f"✓ Connected to {test_model}"}
    except Exception as e:
        error_msg = str(e).strip().replace("\n", " ")
        return {"success": False, "message": f"✗ Connection failed: {error_msg[:200]}"}


def _test_search_connection(provider: str, api_key: str) -> dict:
    """Test a search provider's API key by making a lightweight API call."""
    try:
        import httpx

        if provider == "tavily":
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": "test", "max_results": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                return {"success": True, "message": "✓ Tavily API key is valid"}
            else:
                detail = resp.json().get("error", resp.text)[:200]
                return {"success": False, "message": f"✗ Tavily error: {detail}"}

        elif provider == "serper":
            resp = httpx.post(
                "https://google.serper.dev/search",
                json={"q": "test", "num": 1},
                headers={"X-API-KEY": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                return {"success": True, "message": "✓ Serper API key is valid"}
            else:
                detail = resp.text[:200]
                return {"success": False, "message": f"✗ Serper error: {detail}"}

        return {"success": False, "message": f"Unknown search provider: {provider}"}
    except Exception as e:
        error_msg = str(e).strip().replace("\n", " ")
        return {"success": False, "message": f"✗ Connection failed: {error_msg[:200]}"}


# ── API Keys endpoints (env-first, DB fallback) ──


# Provider list derived from the active models table — falls back to the
# hardcoded CHAT_PROVIDERS list if the DB hasn't been seeded yet.
def _active_providers(db: Session) -> list[str]:
    """Distinct lower(provider) from `models` where is_active=true."""
    try:
        rows = db.execute(
            __import__("sqlalchemy").text(
                "SELECT DISTINCT lower(provider) FROM models WHERE is_active=true ORDER BY 1"
            )
        ).fetchall()
        if rows:
            return [r[0] for r in rows]
    except Exception:
        pass
    return list(CHAT_PROVIDERS)


@router.get("/api-keys")
async def get_api_keys(db: Session = Depends(get_db)):
    """Get API key status. Reads DB first (UI-set), then .env fallback.

    Provider list comes from the active `models` table so qwen/kimi and any
    newly seeded providers appear automatically.
    """
    chat_providers = _active_providers(db)
    # Always include search providers too
    providers = sorted(set(chat_providers) | set(SEARCH_PROVIDERS))

    db_keys = _db_api_keys(db)
    results = []
    for provider in providers:
        # DB-first (encrypted at rest) → .env fallback. A stored key that
        # can't be decrypted (encryption key rotated) is treated as unset.
        key = None
        field = API_PROVIDER_KEY_FIELDS.get(provider)
        if field:
            db_val = db_keys.get(field)
            if db_val:
                from services.encryption import encryption_service
                try:
                    key = encryption_service.decrypt(db_val)
                except Exception:
                    key = None
        if not key:
            key = _get_env_key_for_provider(provider)
        results.append(
            APIKeyResponse(
                provider=provider,
                is_set=key is not None,
                masked_key=mask_api_key(key) if key else None,
                connected=None,
                connected_message=None,
                kind="search" if provider in SEARCH_PROVIDERS else "chat",
            )
        )

    return results


@router.post("/api-keys")
async def set_api_keys(payload: APIKeySet, db: Session = Depends(get_db)):
    """Persist API keys to the DB settings row (runtime override), encrypted at rest.

    .env still takes precedence when both exist (see config.get_api_key_from_db).
    Keys are Fernet-encrypted before storage; reads decrypt transparently.
    Empty-string values are treated as removal requests.
    """
    from services.encryption import encryption_service
    settings = get_or_create_settings(db)
    keys = dict(settings.api_keys or {})
    updated, removed = [], []
    for field, value in payload.model_dump(exclude_none=True).items():
        if isinstance(value, str):
            value = value.strip()
            if value:
                keys[field] = encryption_service.encrypt(value)
                updated.append(field)
            elif field in keys:
                del keys[field]
                removed.append(field)
    settings.api_keys = keys
    db.commit()
    msg = f"Saved: {', '.join(updated) or 'none'}"
    if removed:
        msg += f"; Removed: {', '.join(removed)}"
    return {"updated": updated, "removed": removed, "message": msg}


@router.delete("/api-keys/{provider}")
async def delete_api_key(provider: str, db: Session = Depends(get_db)):
    """Remove a provider's DB-stored key. Keys set in .env must be removed there."""
    field = API_PROVIDER_KEY_FIELDS.get(provider)
    if not field:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    settings = get_or_create_settings(db)
    keys = dict(settings.api_keys or {})
    removed = keys.pop(field, None)
    settings.api_keys = keys
    db.commit()
    if removed is not None:
        return {"message": f"Removed {provider} API key from DB."}
    return {"message": f"No DB-stored key for {provider}. Note: keys set in .env must be edited in .env directly."}


@router.post("/api-keys/test")
async def test_api_key(req: APIKeyTestRequest, db: Session = Depends(get_db)):
    """Test a provider's API key connection. Uses the posted key, else DB, else .env.

    base_url follows the same DB-first precedence via API_PROVIDER_BASE_URL_FIELDS.
    """
    key = req.api_key or _resolve_api_key(db, req.provider)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key found for '{req.provider}'. Set it via the UI (⊕ Set Key) or in .env.",
        )

    # Base URL: DB override → posted → .env default
    base_url_field = API_PROVIDER_BASE_URL_FIELDS.get(req.provider)
    base_url = None
    if base_url_field:
        base_url = _db_api_keys(db).get(base_url_field)
        if base_url:
            from services.encryption import encryption_service
            base_url = encryption_service.decrypt(base_url)
    if not base_url:
        base_url = req.api_key and None  # posted-only flow doesn't carry base_url; .env default kicks in below
        base_url = app_settings.AGNES_BASE_URL if req.provider == "agnes" else base_url
        # For OpenAI-compat providers, the .env default is set via *_api_base fields
        if not base_url:
            base_url = _get_env_base_url_for_provider(req.provider)

    if req.provider in SEARCH_PROVIDERS:
        result = _test_search_connection(req.provider, key)
    else:
        result = _test_provider_connection(req.provider, key, base_url_extra=base_url)

    return {"success": result["success"], "message": result["message"]}


def _get_env_base_url_for_provider(provider: str) -> Optional[str]:
    """Default base URL for a provider from app_settings."""
    return {
        "openai": "https://api.openai.com/v1",
        "deepseek": app_settings.DEEPSEEK_API_BASE,
        "glm": app_settings.GLM_API_BASE or "https://open.bigmodel.cn/api/paas/v4/",
        "minimax": app_settings.MINIMAX_API_BASE,
        "qwen": app_settings.QWEN_API_BASE,
        "kimi": app_settings.KIMI_API_BASE,
        "anthropic": None,  # uses native Anthropic client
        "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "agnes": app_settings.AGNES_BASE_URL,
    }.get(provider)


def _get_env_key_for_provider(provider: str) -> Optional[str]:
    """Get API key from .env for a provider."""
    mapping = {
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
    }
    return mapping.get(provider)


# Provider name → settings.api_keys JSON field name (matches APIKeySet + get_api_key_from_db)
API_PROVIDER_KEY_FIELDS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google": "google_api_key",
    "cohere": "cohere_api_key",
    "replicate": "replicate_api_key",
    "deepseek": "deepseek_api_key",
    "glm": "glm_api_key",
    "minimax": "minimax_api_key",
    "qwen": "qwen_api_key",
    "kimi": "kimi_api_key",
    "tavily": "tavily_api_key",
    "serper": "serper_api_key",
    "agnes": "agnes_api_key",
}

# Provider → settings.api_keys JSON field name for base URLs. Most providers use
# "*_api_base" (matching .env + pydantic); the ones with explicit "_base_url"
# suffix are providers whose standard env var is named that way.
API_PROVIDER_BASE_URL_FIELDS = {
    "openai": "openai_base_url",
    "anthropic": "anthropic_base_url",
    "google": "google_base_url",
    "cohere": "cohere_base_url",
    "replicate": "replicate_base_url",
    "deepseek": "deepseek_api_base",
    "glm": "glm_api_base",
    "minimax": "minimax_api_base",
    "qwen": "qwen_api_base",
    "kimi": "kimi_api_base",
    "agnes": "agnes_base_url",
}


def _db_api_keys(db: Session) -> dict:
    """Return the API keys stored in the DB settings row (UI-set keys)."""
    try:
        row = get_or_create_settings(db)
        return dict(row.api_keys or {})
    except Exception:
        return {}


def _resolve_api_key(db: Session, provider: str) -> Optional[str]:
    """Resolve a provider's key for testing: DB-stored (UI-set) key first, then .env.

    The test endpoint validates what the user saved in the Settings UI, so the
    DB key takes priority here — the opposite of normal app resolution, where
    .env is canonical. Falls back to .env when no UI-set key exists.
    """
    field = API_PROVIDER_KEY_FIELDS.get(provider)
    db_key = _db_api_keys(db).get(field) if field else None
    if db_key:
        # DB keys are Fernet-encrypted at rest; decrypt for the test. decrypt()
        # returns the value unchanged if it was never encrypted (backward compat).
        from services.encryption import encryption_service
        return encryption_service.decrypt(db_key)
    return _get_env_key_for_provider(provider)


@router.get("/", response_model=SettingsResponse)
async def get_settings(db: Session = Depends(get_db)):
    """Get application settings"""
    settings = get_or_create_settings(db)
    return SettingsResponse(
        default_model=settings.default_model,
        default_temperature=settings.default_temperature,
        max_tokens=settings.max_tokens,
        embedding_model=settings.embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        storage_path=settings.storage_path or get_default_storage_path()
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(settings_update: SettingsUpdate, db: Session = Depends(get_db)):
    """Update application settings"""
    settings = get_or_create_settings(db)

    # Update only provided fields
    update_data = settings_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    db.commit()
    db.refresh(settings)

    return SettingsResponse(
        default_model=settings.default_model,
        default_temperature=settings.default_temperature,
        max_tokens=settings.max_tokens,
        embedding_model=settings.embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        storage_path=settings.storage_path or get_default_storage_path()
    )


@router.post("/reset")
async def reset_settings(db: Session = Depends(get_db)):
    """Reset settings to defaults"""
    settings = get_or_create_settings(db)

    settings.default_model = "gpt-4o"
    settings.default_temperature = 0.7
    settings.max_tokens = 4096
    settings.embedding_model = "text-embedding-3-small"
    settings.chunk_size = 1000
    settings.chunk_overlap = 200
    settings.storage_path = get_default_storage_path()

    db.commit()
    return {"message": "Settings reset to defaults"}


# ── Storage mode (docs/system-architecture.md §15, Phase 5) ──
# Runtime switch between 'local' (disk, default) and 'db' (Postgres BYTEA).
# The choice is persisted in the settings table so it survives restarts; on
# boot the lifespan applies the persisted value over the .env default.
VALID_STORAGE_MODES = ("local", "db")


class StorageModeUpdate(BaseModel):
    mode: str


def _storage_mode_label(mode: str) -> str:
    """Human-readable backend label for the Settings UI."""
    return "PostgreSQL (BYTEA)" if mode == "db" else "Local disk"


@router.get("/storage-mode")
async def get_storage_mode(db: Session = Depends(get_db)):
    """Current storage mode: persisted runtime override > .env/default."""
    row = get_or_create_settings(db)
    persisted = getattr(row, "storage_mode", None)
    mode = (persisted or app_settings.storage_mode or "local").lower()
    return {
        "mode": mode,
        "source": "db" if persisted else "env",
        "backend": _storage_mode_label(mode),
    }


@router.put("/storage-mode")
async def update_storage_mode(update: StorageModeUpdate, db: Session = Depends(get_db)):
    """Switch the storage backend at runtime and persist the choice."""
    from services.storage import reset_storage

    mode = update.mode.strip().lower()
    if mode not in VALID_STORAGE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid storage mode: {mode!r}. Choose 'local' or 'db'.",
        )

    row = get_or_create_settings(db)
    row.storage_mode = mode
    db.commit()

    # Take effect immediately: mutate the process-wide setting and drop the
    # cached backend so the next get_storage() builds the new one.
    app_settings.storage_mode = mode
    reset_storage()
    logger.info("Storage mode switched to '%s' (persisted)", mode)
    return {
        "mode": mode,
        "source": "db",
        "backend": _storage_mode_label(mode),
    }


@router.get("/models")
async def list_available_models(db: Session = Depends(get_db)):
    """List available AI models (cloud + validated local models) with full metadata"""
    from models.model import Model

    # All cloud models from the models table (single source of truth)
    cloud_models = db.query(Model).filter(
        Model.source == 'cloud',
        Model.is_active == True
    ).order_by(Model.provider, Model.model_id).all()

    cloud_model_list = []
    for m in cloud_models:
        cloud_model_list.append({
            "model_id": m.model_id,
            "display_name": m.display_name,
            "provider": m.provider,
            "capabilities": m.capabilities or {},
            "is_active": m.is_active,
        })

    # Local models (validated only)
    from models.local_model import LocalModel
    local_models = db.query(LocalModel).filter(
        LocalModel.is_validated == True,
        LocalModel.is_active == True
    ).all()

    # Local models
    local_model_list = []
    for model in local_models:
        model_id = f"local-{model.name}"
        local_model_list.append({
            "id": model.id,
            "name": model_id,
            "display_name": model.display_name,
            "provider": model.provider,
            "capabilities": model.capabilities,
            "is_validated": model.is_validated
        })

    return JSONResponse(
        content={
            "cloud_models": cloud_model_list,
            "local_models": local_model_list
        },
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@router.get("/embedding-models")
async def get_embedding_models():
    """Get available embedding models (reads from .env config)."""
    from config import settings as app_settings
    models = []

    # Cloud embedding models
    if app_settings.openai_api_key:
        models.extend([
            {"id": "text-embedding-3-large", "name": "text-embedding-3-large", "provider": "openai", "type": "cloud"},
            {"id": "text-embedding-3-small", "name": "text-embedding-3-small", "provider": "openai", "type": "cloud"},
            {"id": "text-embedding-ada-002", "name": "text-embedding-ada-002", "provider": "openai", "type": "cloud"},
        ])

    # Local embedding models from Ollama
    try:
        import httpx
        base_url = app_settings.ollama_base_url.rstrip("/") or "http://localhost:11434"
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            for tag in resp.json().get("models", []):
                name = tag.get("name", "")
                models.append({
                    "id": f"ollama-{name}",
                    "name": name,
                    "provider": "ollama",
                    "type": "local",
                })
    except Exception:
        pass  # Ollama not available

    return {"models": models}


class CreateModelRequest(BaseModel):
    model_id: str
    display_name: str
    provider: str
    capabilities: Optional[dict] = {}


@router.post("/models")
async def create_model(req: CreateModelRequest, db: Session = Depends(get_db)):
    """Add a new model to the database"""
    from models.model import Model

    existing = db.query(Model).filter(Model.model_id == req.model_id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Model '{req.model_id}' already exists")

    model = Model(
        model_id=req.model_id,
        display_name=req.display_name,
        provider=req.provider,
        source='cloud',
        capabilities=req.capabilities or {},
        is_active=True,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return {"message": f"Model '{req.model_id}' created", "model": model.to_dict()}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, db: Session = Depends(get_db)):
    """Delete a model from the database"""
    from models.model import Model

    model = db.query(Model).filter(Model.model_id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    db.delete(model)
    db.commit()
    return {"message": f"Model '{model_id}' deleted"}


# General Settings Endpoints
@router.get("/general", response_model=GeneralSettings)
async def get_general_settings(db: Session = Depends(get_db)):
    """Get general application settings"""
    settings = get_or_create_settings(db)
    return GeneralSettings(
        app_name=settings.app_name,
        language=settings.language or "en",
        auto_save=settings.auto_save,
        auto_save_interval=settings.auto_save_interval,
        confirm_before_delete=settings.confirm_before_delete,
        show_notifications=settings.show_notifications,
        check_updates=settings.check_updates,
        telemetry=settings.telemetry,
        log_level=settings.log_level,
        theme=getattr(settings, 'theme', 'langconfig')
    )


@router.post("/general", response_model=GeneralSettings)
async def update_general_settings(general_settings: GeneralSettings, db: Session = Depends(get_db)):
    """Update general application settings"""
    settings = get_or_create_settings(db)

    update_data = general_settings.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    db.commit()
    db.refresh(settings)

    return GeneralSettings(
        app_name=settings.app_name,
        language=settings.language or "en",
        auto_save=settings.auto_save,
        auto_save_interval=settings.auto_save_interval,
        confirm_before_delete=settings.confirm_before_delete,
        show_notifications=settings.show_notifications,
        check_updates=settings.check_updates,
        telemetry=settings.telemetry,
        log_level=settings.log_level,
        theme=getattr(settings, 'theme', 'langconfig')
    )


# Local Models Settings Endpoints (read from .env)
@router.get("/local-models", response_model=LocalModelsSettings)
async def get_local_models_settings():
    """Get local models configuration (from .env)."""
    return LocalModelsSettings(
        provider=app_settings.local_llm_provider,
        base_url=app_settings.local_llm_base_url,
        model_name=app_settings.local_llm_model,
        api_key=app_settings.local_llm_api_key,
    )


@router.post("/local-models", response_model=LocalModelsSettings)
async def update_local_models_settings():
    """Local model settings are managed via .env."""
    return LocalModelsSettings(
        provider=app_settings.local_llm_provider,
        base_url=app_settings.local_llm_base_url,
        model_name=app_settings.local_llm_model,
        api_key=app_settings.local_llm_api_key,
    )


# Workspace Settings Endpoints
@router.get("/workspace", response_model=WorkspaceSettings)
async def get_workspace_settings(db: Session = Depends(get_db)):
    """Get workspace configuration"""
    settings = get_or_create_settings(db)
    return WorkspaceSettings(
        workspace_path=settings.workspace_path,
        allow_read=settings.workspace_allow_read,
        allow_write=settings.workspace_allow_write,
        require_approval=settings.workspace_require_approval,
        auto_detect_git=settings.workspace_auto_detect_git,
        backup_before_edit=settings.workspace_backup_before_edit
    )


def _validate_workspace_path(path: str) -> WorkspaceValidateResponse:
    """Check a workspace path is usable: resolvable, exists (or creatable),
    and writable."""
    from pathlib import Path
    import os
    try:
        p = Path(path).expanduser().resolve()
    except Exception as e:
        return WorkspaceValidateResponse(valid=False, error=f"Invalid path: {e}")
    try:
        p.mkdir(parents=True, exist_ok=True)
        exists = p.is_dir()
        writable = os.access(p, os.W_OK)
        if not writable:
            return WorkspaceValidateResponse(
                valid=False, resolved_path=str(p), exists=exists,
                writable=False, error="Directory is not writable",
            )
        return WorkspaceValidateResponse(
            valid=True, resolved_path=str(p), exists=exists, writable=True,
        )
    except Exception as e:
        return WorkspaceValidateResponse(
            valid=False, resolved_path=str(p), exists=False,
            writable=False, error=str(e),
        )


@router.post("/workspace/validate", response_model=WorkspaceValidateResponse)
async def validate_workspace_path(payload: WorkspaceValidateRequest):
    """Validate a candidate workspace path without saving it."""
    return _validate_workspace_path(payload.path)


@router.post("/workspace", response_model=WorkspaceSettings)
async def update_workspace_settings(workspace: WorkspaceSettings, db: Session = Depends(get_db)):
    """Update workspace configuration"""
    from services.workspace_manager import reset_workspace_manager
    settings = get_or_create_settings(db)

    if workspace.workspace_path is not None:
        path = (workspace.workspace_path or "").strip()
        if path:
            check = _validate_workspace_path(path)
            if not check.valid:
                raise HTTPException(status_code=400, detail=check.error or "Invalid workspace path")
            settings.workspace_path = check.resolved_path
            # The workspace root changed — drop the cached manager so the new
            # path is used immediately.
            reset_workspace_manager()
        else:
            settings.workspace_path = ""
    if workspace.allow_read is not None:
        settings.workspace_allow_read = workspace.allow_read
    if workspace.allow_write is not None:
        settings.workspace_allow_write = workspace.allow_write
    if workspace.require_approval is not None:
        settings.workspace_require_approval = workspace.require_approval
    if workspace.auto_detect_git is not None:
        settings.workspace_auto_detect_git = workspace.auto_detect_git
    if workspace.backup_before_edit is not None:
        settings.workspace_backup_before_edit = workspace.backup_before_edit

    db.commit()
    db.refresh(settings)

    return WorkspaceSettings(
        workspace_path=settings.workspace_path,
        allow_read=settings.workspace_allow_read,
        allow_write=settings.workspace_allow_write,
        require_approval=settings.workspace_require_approval,
        auto_detect_git=settings.workspace_auto_detect_git,
        backup_before_edit=settings.workspace_backup_before_edit
    )


# First-run setup endpoints
def _default_workspace_path() -> str:
    """The workspace root the app would use with no user override (resolved)."""
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parent.parent.parent  # api/system -> backend
    from config import settings as cfg
    configured = getattr(cfg, "workspace_base_dir", None) or "backend/outputs"
    p = Path(configured).expanduser()
    if not p.is_absolute():
        p = backend_dir.parent / p
    return str(p.resolve())


def _has_any_chat_api_key(db: Session) -> bool:
    """True when at least one chat provider has a usable key (DB or .env).

    A stored DB key that can't be decrypted (e.g. the encryption key was
    rotated) counts as not-set — the user can re-enter it in the setup.
    """
    db_keys = _db_api_keys(db)
    from services.encryption import encryption_service
    for provider in _active_providers(db):
        field = API_PROVIDER_KEY_FIELDS.get(provider)
        if field:
            db_val = db_keys.get(field)
            if db_val:
                try:
                    if encryption_service.decrypt(db_val):
                        return True
                except Exception:
                    continue  # undecryptable stored key → treat as not set
        if _get_env_key_for_provider(provider):
            return True
    return False


@router.get("/setup-status", response_model=SetupStatusResponse)
async def get_setup_status(db: Session = Depends(get_db)):
    """First-run onboarding status.

    ``needs_setup`` is true until the user has completed the setup wizard AND
    configured at least one provider key AND chosen a workspace path.
    """
    settings = get_or_create_settings(db)
    completed = bool(getattr(settings, "setup_complete", False))
    has_api_key = _has_any_chat_api_key(db)
    has_workspace = bool((settings.workspace_path or "").strip())
    return SetupStatusResponse(
        needs_setup=not completed and (not has_api_key or not has_workspace),
        completed=completed,
        has_api_key=has_api_key,
        has_workspace=has_workspace,
        default_workspace_path=_default_workspace_path(),
    )


@router.post("/setup-complete")
async def complete_setup(db: Session = Depends(get_db)):
    """Mark the first-run setup as finished (wizard dismissed)."""
    settings = get_or_create_settings(db)
    settings.setup_complete = True
    db.commit()
    return {"ok": True, "needs_setup": False}


# Model Defaults Settings Endpoints (persisted in PostgreSQL)
@router.get("/model-defaults", response_model=ModelDefaultsSettings)
async def get_model_defaults_settings(db: Session = Depends(get_db)):
    """Get model defaults configuration from PostgreSQL settings."""
    settings = get_or_create_settings(db)
    primary_model = settings.default_model or settings.primary_model or app_settings.default_model
    fallback_models = settings.fallback_models
    if not fallback_models:
        fallback_models = (
            [m.strip() for m in app_settings.fallback_models.split(",") if m.strip()]
            if app_settings.fallback_models else [primary_model]
        )
    return ModelDefaultsSettings(
        primary_model=primary_model,
        fallback_models=fallback_models,
        temperature=settings.temperature if settings.temperature is not None else app_settings.default_temperature,
        max_tokens=settings.max_tokens_default if settings.max_tokens_default is not None else app_settings.max_tokens,
        top_p=settings.top_p if settings.top_p is not None else app_settings.top_p,
        routing_strategy=settings.routing_strategy or "balanced",
        daily_token_limit=settings.daily_token_limit or 0,
        monthly_token_limit=settings.monthly_token_limit or 0,
        alert_threshold=settings.alert_threshold if settings.alert_threshold is not None else 80,
    )


@router.post("/model-defaults", response_model=ModelDefaultsSettings)
async def update_model_defaults_settings(
    update: ModelDefaultsSettings,
    db: Session = Depends(get_db),
):
    """Persist model defaults in PostgreSQL."""
    settings = get_or_create_settings(db)
    update_data = update.model_dump(exclude_unset=True)

    if "primary_model" in update_data:
        settings.default_model = update_data["primary_model"]
        settings.primary_model = update_data["primary_model"]
    if "fallback_models" in update_data:
        settings.fallback_models = update_data["fallback_models"]
    if "temperature" in update_data:
        settings.temperature = update_data["temperature"]
    if "max_tokens" in update_data:
        settings.max_tokens_default = update_data["max_tokens"]
        settings.max_tokens = update_data["max_tokens"]
    if "top_p" in update_data:
        settings.top_p = update_data["top_p"]
    if "routing_strategy" in update_data:
        settings.routing_strategy = update_data["routing_strategy"]
    if "daily_token_limit" in update_data:
        settings.daily_token_limit = update_data["daily_token_limit"]
    if "monthly_token_limit" in update_data:
        settings.monthly_token_limit = update_data["monthly_token_limit"]
    if "alert_threshold" in update_data:
        settings.alert_threshold = update_data["alert_threshold"]

    db.commit()
    db.refresh(settings)

    fallback_models = settings.fallback_models or (
        [m.strip() for m in app_settings.fallback_models.split(",") if m.strip()]
        if app_settings.fallback_models else [settings.default_model or app_settings.default_model]
    )
    return ModelDefaultsSettings(
        primary_model=settings.default_model or settings.primary_model or app_settings.default_model,
        fallback_models=fallback_models,
        temperature=settings.temperature if settings.temperature is not None else app_settings.default_temperature,
        max_tokens=settings.max_tokens_default if settings.max_tokens_default is not None else app_settings.max_tokens,
        top_p=settings.top_p if settings.top_p is not None else app_settings.top_p,
        routing_strategy=settings.routing_strategy or "balanced",
        daily_token_limit=settings.daily_token_limit or 0,
        monthly_token_limit=settings.monthly_token_limit or 0,
        alert_threshold=settings.alert_threshold if settings.alert_threshold is not None else 80,
    )


# Agent Guardrails Endpoint
class AgentGuardrailsResponse(BaseModel):
    guardrails: str
    description: str


@router.get("/default-guardrails", response_model=AgentGuardrailsResponse)
async def get_default_guardrails():
    """
    Get the default agent guardrails prompt.

    This prompt is prepended to every agent's system prompt to enforce:
    1. Stopping criteria - prevents infinite loops and over-exploration
    2. Tool usage guidelines - ensures tools are called with correct parameters

    The agent's reasoning loop (Reason → Act → Observe) is handled internally
    by LangChain's create_agent(). These guardrails add production-safety rules.

    Can be customized per-agent via the 'guardrails' field in agent config.
    """
    from core.agents.factory import DEFAULT_AGENT_GUARDRAILS

    return AgentGuardrailsResponse(
        guardrails=DEFAULT_AGENT_GUARDRAILS,
        description=(
            "Agent Guardrails are production-safety rules prepended to every agent's prompt. "
            "They enforce: (1) Stopping criteria to prevent infinite loops, "
            "(2) Tool usage rules to ensure correct parameter usage. "
            "The reasoning loop is handled internally by LangChain - these add extra safety."
        )
    )


# =============================================================================
# Directory Browser Endpoint
# =============================================================================

class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_directory: bool


class DirectoryListResponse(BaseModel):
    current_path: str
    parent_path: Optional[str]
    entries: list[DirectoryEntry]


# Hidden and system directories to exclude
HIDDEN_DIRS = {
    '.git', '.svn', '.hg', '.bzr',
    '__pycache__', '.pytest_cache', '.mypy_cache',
    'node_modules', '.venv', 'venv', '.env',
    '$RECYCLE.BIN', 'System Volume Information',
    '.Trash', '.Spotlight-V100', '.fseventsd',
    'AppData', 'Application Data', 'Local Settings',
}


@router.get("/browse-directories", response_model=DirectoryListResponse)
async def browse_directories(path: str = "."):
    """
    List directories for folder browser UI.

    Returns subdirectories at the given path for navigation.
    Excludes hidden directories, system folders, and files.

    Args:
        path: Directory path to browse (defaults to user home)
    """
    from pathlib import Path as PathLib
    import re

    # Default to user home if path is "." or empty
    if not path or path == "." or path == "~":
        path = str(PathLib.home())

    try:
        current = PathLib(path).resolve()

        if not current.exists():
            raise HTTPException(status_code=404, detail="Directory not found")

        if not current.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        # Get parent path (None if at root)
        parent_path = None
        if current.parent != current:
            parent_path = str(current.parent)

        # List subdirectories
        entries = []
        try:
            for item in sorted(current.iterdir(), key=lambda x: x.name.lower()):
                # Skip files
                if not item.is_dir():
                    continue

                # Skip hidden directories (starting with .)
                if item.name.startswith('.'):
                    continue

                # Skip known hidden/system directories
                if item.name in HIDDEN_DIRS:
                    continue

                # Skip Windows system directories
                if re.match(r'^[A-Za-z]:\\(Windows|Program Files)', str(item), re.IGNORECASE):
                    continue

                entries.append(DirectoryEntry(
                    name=item.name,
                    path=str(item),
                    is_directory=True
                ))

        except PermissionError:
            # Return empty list if we can't read the directory
            pass

        return DirectoryListResponse(
            current_path=str(current),
            parent_path=parent_path,
            entries=entries
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error browsing directory: {str(e)}")
