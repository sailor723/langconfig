"""
Search Providers API — list, get, set API key, test connection.

Endpoints:
  GET  /api/search-providers/                      → list all providers (with key status)
  GET  /api/search-providers/{provider_id}         → get one provider
  POST /api/search-providers/{provider_id}/key     → set/update API key (encrypted)
  DELETE /api/search-providers/{provider_id}/key   → remove API key
  POST /api/search-providers/{provider_id}/test    → test the key works

Storage (SINGLE api-key table):
  - Metadata → `search_providers` table
  - API keys → the ``models`` settings document's ``api_keys`` field
    (core/settings — the one table every API key lives in; secrets encrypted
    at rest). The legacy ``settings.api_keys`` JSONB column was migrated into
    it and is no longer read or written.
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import SessionLocal
from models.search_provider import SearchProvider

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
    """Look up a search provider's API key from the SINGLE api-key table:
    the ``models`` settings document's ``api_keys`` field (core/settings).

    This is the one canonical location for every API key (LLM + search).
    The legacy ``settings.api_keys`` JSONB column is no longer read or
    written (migrated to the models document); see docs/settings-refactor.md.
    """
    if not api_key_field:
        return None
    try:
        from core.settings import get_document
        doc = get_document(db, "models")
        return (doc.get("api_keys") or {}).get(api_key_field)
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

    Persists to the SINGLE api-key table: the ``models`` settings document's
    ``api_keys`` field (core/settings — secrets encrypted at rest). The legacy
    ``settings.api_keys`` JSONB column is no longer written.
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

    try:
        from core.settings import mutate
        doc, _rev = mutate(
            db,
            "models",
            [{"op": "set", "path": ["api_keys", p.api_key_field], "value": payload.api_key.strip()}],
        )
    except Exception as exc:  # noqa: BLE001 — surface a clear error to the UI
        raise HTTPException(status_code=500, detail=f"Failed to store API key: {exc}") from exc

    return {
        "status": "saved",
        "provider_id": provider_id,
        "api_key_field": p.api_key_field,
        "masked_key": _mask_key(payload.api_key.strip()),
    }


@router.delete("/{provider_id}/key")
def delete_search_provider_key(provider_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Remove the API key for a search provider (from the models doc)."""
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")
    if not p.api_key_field:
        raise HTTPException(status_code=400, detail="Provider has no api_key_field")

    try:
        from core.settings import mutate
        doc, _rev = mutate(
            db,
            "models",
            [{"op": "unset", "path": ["api_keys", p.api_key_field]}],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to remove API key: {exc}") from exc

    return {"status": "deleted", "provider_id": provider_id}


def _live_test_tavily(key: str) -> str:
    import httpx
    r = httpx.post("https://api.tavily.com/search",
                   json={"query": "test", "max_results": 1, "api_key": key}, timeout=15)
    if r.status_code == 200:
        return "Tavily reachable — API key is valid"
    raise Exception(f"Tavily HTTP {r.status_code}: {r.text[:100]}")

def _live_test_duckduckgo() -> str:
    import httpx, re
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": "test"},
                   headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', r.text)
    return f"DuckDuckGo reachable — {len(snippets)} result(s)"

def _live_test_wikipedia() -> str:
    import httpx
    r = httpx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Python",
                   headers={"User-Agent": "LangConfig/1.0"}, timeout=15)
    if r.status_code == 200:
        return f"Wikipedia reachable — found \"{r.json().get('title','')}\""
    return f"Wikipedia HTTP {r.status_code}"

def _live_test_exa(key: str) -> str:
    import httpx
    r = httpx.post("https://api.exa.ai/search",
                   json={"query": "test", "numResults": 1},
                   headers={"x-api-key": key, "Content-Type": "application/json"}, timeout=15)
    if r.status_code == 200:
        return "Exa API key is valid"
    raise Exception(f"Exa HTTP {r.status_code}: {r.text[:100]}")

def _live_test_brave(key: str) -> str:
    import httpx
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                   params={"q": "test", "count": 1},
                   headers={"Accept": "application/json", "X-Subscription-Token": key}, timeout=15)
    if r.status_code == 200:
        return "Brave API key is valid"
    raise Exception(f"Brave HTTP {r.status_code}: {r.text[:100]}")

def _live_test_serpapi(key: str) -> str:
    import httpx
    r = httpx.get("https://serpapi.com/search",
                   params={"q": "test", "api_key": key, "engine": "google", "num": 1}, timeout=15)
    if r.status_code == 200:
        return "SerpAPI key is valid"
    raise Exception(f"SerpAPI HTTP {r.status_code}: {r.text[:100]}")

_LIVE_TESTS = {
    "tavily":     _live_test_tavily,
    "duckduckgo": lambda _: _live_test_duckduckgo(),
    "wikipedia":  lambda _: _live_test_wikipedia(),
    "exa":        _live_test_exa,
    "brave":      _live_test_brave,
    "serpapi":    _live_test_serpapi,
}

@router.post("/{provider_id}/test")
def test_search_provider(provider_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Test the search provider with a live API call.

    For keyless providers (DDG, Wikipedia), does a quick live HTTP fetch.
    For keyed providers, makes a minimal API call to validate the stored key.
    """
    p = db.query(SearchProvider).filter_by(id=provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Search provider '{provider_id}' not found")

    key = None
    if p.requires_api_key:
        key = _get_decrypted_key(p.api_key_field, db) if p.api_key_field else None
        if not key:
            return {"success": False, "provider_id": provider_id, "message": f"API key not set for {p.display_name}"}

    tester = _LIVE_TESTS.get(provider_id)
    if not tester:
        return {"success": False, "provider_id": provider_id, "message": f"No live test for '{provider_id}'"}

    import time
    start = time.time()
    try:
        msg = tester(key)  # All lambdas accept key arg (keyless ones ignore it)
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {"success": True, "provider_id": provider_id, "display_name": p.display_name, "message": msg, "execution_time_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {"success": False, "provider_id": provider_id, "display_name": p.display_name, "message": str(e), "execution_time_ms": elapsed_ms}