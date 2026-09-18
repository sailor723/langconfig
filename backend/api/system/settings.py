# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Slim settings router (Phase 5 of docs/settings-refactor.md).

Only the endpoints that are NOT settings-document concerns remain here,
reimplemented over the DSH-style engine (`core/settings`) where applicable:

- ``GET/PUT /storage-mode``        → runtime switch, persisted in the ``storage`` namespace
- ``GET /setup-status`` / ``POST /setup-complete`` → ``onboarding`` namespace + engine keys
- ``POST /api-keys/test``          → key resolution from ``models.api_keys`` document + .env
- ``GET/POST/DELETE /models``, ``GET /embedding-models`` → the DB-driven model registry
- ``POST /workspace/validate``, ``GET /default-guardrails``, ``GET /browse-directories``
  → standalone utilities

The document CRUD surface lives in ``settings_documents.py`` (describe/mutate).
The legacy endpoints (``GET/PATCH /``, ``/reset``, ``/general``, ``/workspace``,
``/model-defaults``, ``/api-keys`` CRUD) were deleted in Phase 5 — their writes
now go through ``POST /api/settings/mutate``.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import logging
from pydantic import BaseModel

from config import settings as app_settings
from db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── Schemas ──────────────────────────────────────────────────────────────────
class APIKeyTestRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    completed: bool
    has_api_key: bool
    has_workspace: bool
    default_workspace_path: str


class WorkspaceValidateRequest(BaseModel):
    path: str


class WorkspaceValidateResponse(BaseModel):
    valid: bool
    resolved_path: Optional[str] = None
    exists: bool = False
    writable: bool = False
    error: Optional[str] = None


class StorageModeUpdate(BaseModel):
    mode: str


class CreateModelRequest(BaseModel):
    model_id: str
    display_name: str
    provider: str
    capabilities: Optional[dict] = {}


class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_directory: bool


class DirectoryListResponse(BaseModel):
    current_path: str
    parent_path: Optional[str]
    entries: list[DirectoryEntry]


# ── Provider test helpers ────────────────────────────────────────────────────
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

# Provider name → models.api_keys document field (matches ApiKeys schema).
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
            # Agnes only responds to STREAMING chat requests — drain the SSE
            # stream and verify the key by collecting the final answer.
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
            resp = httpx.get(
                "https://serpapi.com/search",
                params={"q": "test", "num": 1, "api_key": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                return {"success": True, "message": "✓ SerpAPI key is valid"}
            else:
                detail = resp.text[:200]
                return {"success": False, "message": f"✗ SerpAPI error: {detail}"}

        return {"success": False, "message": f"Unknown search provider: {provider}"}
    except Exception as e:
        error_msg = str(e).strip().replace("\n", " ")
        return {"success": False, "message": f"✗ Connection failed: {error_msg[:200]}"}


# ── Engine-backed key resolution (models.api_keys document, then .env) ───────
def _document_api_keys(db: Session) -> dict:
    """UI-set provider keys from the DSH-style models document (decrypted).

    Returns {} when the engine table is unavailable — callers fall back to .env.
    Read-only: never creates the table.
    """
    try:
        from core.settings import store
        return store.get_document(db, "models").get("api_keys") or {}
    except Exception:
        return {}


def _resolve_api_key(db: Session, provider: str) -> Optional[str]:
    """Resolve a provider's key for testing: the single models.api_keys
    document first, then .env (legacy settings.api_keys is no longer used)."""
    field = API_PROVIDER_KEY_FIELDS.get(provider)
    if field:
        key = _document_api_keys(db).get(field)
        if key:
            return key
    return _get_env_key_for_provider(provider)


@router.post("/api-keys/test")
async def test_api_key(req: APIKeyTestRequest, db: Session = Depends(get_db)):
    """Test a provider's API key connection. Uses the posted key, else the
    models document key, else .env."""
    key = req.api_key or _resolve_api_key(db, req.provider)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key found for '{req.provider}'. Set it in Settings → Models or in .env.",
        )

    base_url_field = API_PROVIDER_BASE_URL_FIELDS.get(req.provider)
    base_url = None
    if base_url_field:
        base_url = _document_api_keys(db).get(base_url_field)
    if not base_url:
        base_url = app_settings.AGNES_BASE_URL if req.provider == "agnes" else None
        if not base_url:
            base_url = _get_env_base_url_for_provider(req.provider)

    if req.provider in SEARCH_PROVIDERS:
        result = _test_search_connection(req.provider, key)
    else:
        result = _test_provider_connection(req.provider, key, base_url_extra=base_url)

    return {"success": result["success"], "message": result["message"]}


# ── Storage mode (runtime switch, persisted in the storage namespace) ────────
VALID_STORAGE_MODES = ("local", "db")


def _storage_mode_label(mode: str) -> str:
    """Human-readable backend label for the Settings UI."""
    return "PostgreSQL (BYTEA)" if mode == "db" else "Local disk"


def _persisted_storage_mode(db: Session) -> Optional[str]:
    """The storage.mode value the user explicitly set (document), else None."""
    try:
        from core.settings import store
        store.ensure_table(db)
        return store.get_document(db, "storage").get("mode")
    except Exception:
        return None


@router.get("/storage-mode")
async def get_storage_mode(db: Session = Depends(get_db)):
    """Current storage mode: persisted runtime override > .env/default."""
    persisted = _persisted_storage_mode(db)
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

    from core.settings import mutate
    mutate(db, "storage", [{"op": "set", "path": ["mode"], "value": mode}])

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


# ── Model registry (DB-driven models table) ──────────────────────────────────
@router.get("/models")
async def list_available_models(db: Session = Depends(get_db)):
    """List available AI models (cloud + validated local models) with full metadata"""
    from models.model import Model

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

    from models.local_model import LocalModel
    local_models = db.query(LocalModel).filter(
        LocalModel.is_validated == True,
        LocalModel.is_active == True
    ).all()

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


@router.get("/embedding-models")
async def get_embedding_models():
    """Get available embedding models (reads from .env config)."""
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
        # Single source of truth: OLLAMA_BASE_URL in .env. If unset, the
        # /api/tags fetch will fail and we fall through to the empty
        # list. No localhost literal.
        from config import settings as _settings
        base_url = (app_settings.ollama_base_url or _settings.ollama_base_url or "").rstrip("/")
        if not base_url:
            return []  # no Ollama configured — return empty list
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


# ── First-run setup (onboarding namespace) ───────────────────────────────────
def _default_workspace_path() -> str:
    """The workspace root the app would use with no user override (resolved)."""
    from pathlib import Path
    from core.settings import runtime_get
    backend_dir = Path(__file__).resolve().parent.parent.parent  # api/system -> backend
    configured = runtime_get("workspace", "base_dir") or "backend/outputs"
    p = Path(configured).expanduser()
    if not p.is_absolute():
        p = backend_dir.parent / p
    return str(p.resolve())


def _has_any_chat_api_key(db: Session) -> bool:
    """True when at least one chat provider has a usable key (document or .env)."""
    doc_keys = _document_api_keys(db)
    for provider in _active_providers(db):
        field = API_PROVIDER_KEY_FIELDS.get(provider)
        if field and doc_keys.get(field):
            return True
        if _get_env_key_for_provider(provider):
            return True
    return False


def _onboarding_state(db: Session) -> dict:
    """completed flag + key presence + workspace path from the engine."""
    from core.settings import resolve_value
    onboarding = resolve_value(db, "onboarding")
    workspace = resolve_value(db, "workspace")
    return {
        "completed": bool(onboarding.get("setup_complete")),
        "has_api_key": _has_any_chat_api_key(db),
        "has_workspace": bool((workspace.get("workspace_path") or "").strip()),
    }


@router.get("/setup-status", response_model=SetupStatusResponse)
async def get_setup_status(db: Session = Depends(get_db)):
    """First-run onboarding status.

    ``needs_setup`` is true until the user has completed the setup wizard AND
    configured at least one provider key AND chosen a workspace path.
    """
    state = _onboarding_state(db)
    return SetupStatusResponse(
        needs_setup=not state["completed"] and (not state["has_api_key"] or not state["has_workspace"]),
        completed=state["completed"],
        has_api_key=state["has_api_key"],
        has_workspace=state["has_workspace"],
        default_workspace_path=_default_workspace_path(),
    )


@router.post("/setup-complete")
async def complete_setup(db: Session = Depends(get_db)):
    """Mark the first-run setup as finished (wizard dismissed)."""
    from core.settings import mutate
    mutate(db, "onboarding", [{"op": "set", "path": ["setup_complete"], "value": True}])
    return {"ok": True, "needs_setup": False}


# ── Workspace path validation (utility) ──────────────────────────────────────
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


# ── Agent guardrails (static prompt) ─────────────────────────────────────────
class AgentGuardrailsResponse(BaseModel):
    guardrails: str
    description: str


@router.get("/default-guardrails", response_model=AgentGuardrailsResponse)
async def get_default_guardrails():
    """Get the default agent guardrails prompt."""
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


# ── Directory browser (utility) ──────────────────────────────────────────────
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
    """List subdirectories for the folder-browser UI (hidden/system dirs excluded)."""
    from pathlib import Path as PathLib
    import re

    if not path or path == "." or path == "~":
        path = str(PathLib.home())

    try:
        current = PathLib(path).resolve()

        if not current.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        if not current.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        parent_path = None
        if current.parent != current:
            parent_path = str(current.parent)

        entries = []
        try:
            for item in sorted(current.iterdir(), key=lambda x: x.name.lower()):
                if not item.is_dir():
                    continue
                if item.name.startswith('.'):
                    continue
                if item.name in HIDDEN_DIRS:
                    continue
                if re.match(r'^[A-Za-z]:\\(Windows|Program Files)', str(item), re.IGNORECASE):
                    continue
                entries.append(DirectoryEntry(
                    name=item.name,
                    path=str(item),
                    is_directory=True
                ))
        except PermissionError:
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
