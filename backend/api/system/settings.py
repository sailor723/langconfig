# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from db.database import get_db
from models.settings import Settings as SettingsModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Pydantic Schemas
class APIKeyTestRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None


class APIKeySet(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None
    replicate_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    glm_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
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


# Helper functions for database access
def get_or_create_settings(db: Session) -> SettingsModel:
    """Get settings from database or create default row if it doesn't exist"""
    # Migrate: add theme column if missing
    try:
        from sqlalchemy import text as sa_text
        db.execute(sa_text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS theme VARCHAR DEFAULT 'langconfig'"))
        db.commit()
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
    "google": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "glm": "glm-4",
    "minimax": "minimax-m3",
    "agnes": "agnes-2.0-flash",
}

CHAT_PROVIDERS = ["openai", "anthropic", "google", "deepseek", "glm", "minimax", "agnes"]
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
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
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
            r = client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ok"}], max_tokens=5, timeout=15)
            _ = r.choices[0].message.content
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


# ── API Keys endpoints (now read from .env) ──


@router.get("/api-keys")
async def get_api_keys():
    """Get API key status (read from .env)."""
    providers = ["openai", "anthropic", "google", "cohere", "replicate", "deepseek", "glm", "minimax", "tavily", "serper", "agnes"]

    results = []
    for provider in providers:
        key = _get_env_key_for_provider(provider)
        results.append(
            APIKeyResponse(
                provider=provider,
                is_set=key is not None,
                masked_key=mask_api_key(key) if key else None,
                connected=None,
                connected_message=None,
            )
        )

    return results


@router.post("/api-keys")
async def set_api_keys():
    """API keys are managed via .env — this endpoint is no longer used."""
    return {"message": "API keys are configured in .env file. Edit .env directly or use Settings UI to see current status."}


@router.delete("/api-keys/{provider}")
async def delete_api_key(provider: str):
    """API keys are managed via .env — this endpoint is no longer used."""
    return {"message": f"API keys are configured in .env file. Remove the entry for '{provider}' from .env directly."}


@router.post("/api-keys/test")
async def test_api_key(req: APIKeyTestRequest):
    """Test a provider's API key connection. Reads key from .env."""
    key = req.api_key or _get_env_key_for_provider(req.provider)

    if not key:
        raise HTTPException(status_code=400, detail=f"No API key found for '{req.provider}'. Set it in .env file.")

    if req.provider in SEARCH_PROVIDERS:
        result = _test_search_connection(req.provider, key)
    else:
        base_url_extra = app_settings.AGNES_BASE_URL if req.provider == "agnes" else None
        result = _test_provider_connection(req.provider, key, base_url_extra)

    return {"success": result["success"], "message": result["message"]}


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


@router.post("/workspace", response_model=WorkspaceSettings)
async def update_workspace_settings(workspace: WorkspaceSettings, db: Session = Depends(get_db)):
    """Update workspace configuration"""
    settings = get_or_create_settings(db)

    if workspace.workspace_path is not None:
        settings.workspace_path = workspace.workspace_path
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


# Model Defaults Settings Endpoints (read from .env)
@router.get("/model-defaults", response_model=ModelDefaultsSettings)
async def get_model_defaults_settings():
    """Get model defaults configuration (from .env)."""
    fallback_list = [m.strip() for m in app_settings.fallback_models.split(",") if m.strip()] if app_settings.fallback_models else [app_settings.default_model]
    return ModelDefaultsSettings(
        primary_model=app_settings.default_model,
        fallback_models=fallback_list or [app_settings.default_model],
        temperature=app_settings.default_temperature,
        max_tokens=app_settings.max_tokens,
        top_p=app_settings.top_p,
        routing_strategy="balanced",
        daily_token_limit=0,
        monthly_token_limit=0,
        alert_threshold=80,
    )


@router.post("/model-defaults", response_model=ModelDefaultsSettings)
async def update_model_defaults_settings():
    """Model defaults are managed via .env."""
    fallback_list = [m.strip() for m in app_settings.fallback_models.split(",") if m.strip()] if app_settings.fallback_models else [app_settings.default_model]
    return ModelDefaultsSettings(
        primary_model=app_settings.default_model,
        fallback_models=fallback_list or [app_settings.default_model],
        temperature=app_settings.default_temperature,
        max_tokens=app_settings.max_tokens,
        top_p=app_settings.top_p,
        routing_strategy="balanced",
        daily_token_limit=0,
        monthly_token_limit=0,
        alert_threshold=80,
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
