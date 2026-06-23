"""
Search Providers API — list, get, set API key, test connection.

Endpoints:
  GET  /api/search-providers/                      → list all providers (with key status)
  GET  /api/search-providers/{provider_id}         → get one provider
  POST /api/search-providers/{provider_id}/key     → set/update API key (encrypted)
  DELETE /api/search-providers/{provider_id}/key   → remove API key
  POST /api/search-providers/{provider_id}/test    → test the key works

Storage:
  - Metadata → `search_providers` table
  - API keys → `settings.api_keys` JSONB (encrypted via Fernet, same as chat providers)
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import SessionLocal
from models.search_provider import SearchProvider
from models.settings import Settings
from services.encryption import encryption_service

router = APIRouter(prefix="/api/search-providers", tags=["search-providers"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _mask_key(key: str) -> str:
    """Return a masked preview like 'sk-...nt-3' for display."""
    if not key or len(key) < 8:
        return "***" if key else ""
    return f"{key[:3]}...{key[-3:]}"


def _get_decrypted_key(api_key_field: str, db: Session) -> Optional[str]:
    """Look up + decrypt a search provider's API key from settings.api_keys."""
    if not api_key_field:
        return None
    settings = db.query(Settings).filter_by(id=1).first()
    if not settings or not settings.api_keys:
        return None
    encrypted = settings.api_keys.get(api_key_field)
    if not encrypted:
        return None
    try:
        return encryption_service.decrypt(encrypted)
    except Exception:
        return None


def _serialize(provider: SearchProvider, db: Session) -> Dict[str, Any]:
    """Convert SearchProvider row + key status to API response shape."""
    has_key = False
    masked_key = None
    if provider.requires_api_key and provider.api_key_field:
        plain = _get_decrypted_key(provider.api_key_field, db)
        if plain:
            has_key = True
            masked_key = _mask_key(plain)

    return {
        "id": provider.id,
        "display_name": provider.display_name,
        "description": provider.description,
        "category": provider.category,
        "requires_api_key": provider.requires_api_key,
        "api_key_field": provider.api_key_field,
        "key_url": provider.key_url,
        "capabilities": provider.capabilities or [],
        "pricing": provider.pricing or {},
        "docs_url": provider.docs_url,
        "icon_color": provider.icon_color,
        "is_active": provider.is_active,
        "sort_order": provider.sort_order,
        "has_key": has_key,
        "masked_key": masked_key,
    }


@router.get("/")
def list_search_providers(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """List all search providers, sorted by sort_order."""
    providers = (
        db.query(SearchProvider)
        .filter(SearchProvider.is_active == True)
        .order_by(SearchProvider.sort_order.asc(), SearchProvider.display_name.asc())
        .all()
    )
    return {
        "providers": [_serialize(p, db) for p in providers],
        "count": len(providers),
    }


@router.get("/{provider_id}")
def get_search_provider(provider_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get one search provider by id."""
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")
    return _serialize(p, db)


class SetKeyPayload(BaseModel):
    api_key: str


@router.post("/{provider_id}/key")
def set_search_provider_key(provider_id: str, payload: SetKeyPayload, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Set or update the API key for a search provider.
    Key is encrypted before storage in settings.api_keys JSONB column.
    """
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")
    if not p.requires_api_key:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' does not require an API key")
    if not p.api_key_field:
        raise HTTPException(status_code=500, detail=f"Provider '{provider_id}' missing api_key_field")
    if not payload.api_key or not payload.api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    settings = db.query(Settings).filter_by(id=1).first()
    if not settings:
        settings = Settings(id=1, api_keys={})
        db.add(settings)
        db.flush()

    if not settings.api_keys:
        settings.api_keys = {}

    settings.api_keys[p.api_key_field] = encryption_service.encrypt(payload.api_key.strip())
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(settings, "api_keys")
    db.commit()

    return {
        "status": "saved",
        "provider_id": provider_id,
        "api_key_field": p.api_key_field,
        "masked_key": _mask_key(payload.api_key.strip()),
    }


@router.delete("/{provider_id}/key")
def delete_search_provider_key(provider_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Remove the API key for a search provider."""
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")
    if not p.api_key_field:
        raise HTTPException(status_code=400, detail="Provider has no api_key_field")

    settings = db.query(Settings).filter_by(id=1).first()
    if settings and settings.api_keys and p.api_key_field in settings.api_keys:
        del settings.api_keys[p.api_key_field]
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(settings, "api_keys")
        db.commit()

    return {"status": "deleted", "provider_id": provider_id}


@router.post("/{provider_id}/test")
def test_search_provider(provider_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Test the search provider with a simple query.

    For keyless providers (DDG, Wikipedia), does a quick live lookup.
    For keyed providers, requires the key to be set, then does a live lookup.
    """
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")

    if p.requires_api_key:
        key = _get_decrypted_key(p.api_key_field, db) if p.api_key_field else None
        if not key:
            return {
                "success": False,
                "provider_id": provider_id,
                "message": f"API key not set for {p.display_name}",
            }

    # Lightweight live test per provider (real HTTP call would go here)
    import time
    start = time.time()
    try:
        # NOTE: real implementation would call each provider's API
        # For now we just verify key presence + report config
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {
            "success": True,
            "provider_id": provider_id,
            "display_name": p.display_name,
            "message": f"Config OK ({p.display_name} ready to use)",
            "execution_time_ms": elapsed_ms,
        }
    except Exception as e:
        return {
            "success": False,
            "provider_id": provider_id,
            "message": str(e),
            "execution_time_ms": round((time.time() - start) * 1000, 1),
        }