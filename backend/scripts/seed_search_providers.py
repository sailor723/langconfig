"""
Seed the `search_providers` table with 6 default web/encyclopedia search backends.

Run once after creating the `search_providers` table:
    cd backend && .venv/bin/python3 scripts/seed_search_providers.py

This is idempotent: it uses INSERT ... ON CONFLICT DO UPDATE to keep the table
in sync with the canonical list below.

Storage:
  - Metadata (display_name, description, capabilities, ...) → `search_providers` table
  - API keys (if required) → `settings.api_keys` JSONB column (encrypted via Fernet)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text
from db.database import SessionLocal, engine
from models.search_provider import SearchProvider


# Canonical list — single source of truth for search providers in the app
SEARCH_PROVIDERS = [
    {
        "id": "tavily",
        "display_name": "Tavily AI Search",
        "description": "AI-optimized search with relevance scoring, content extraction, and answer generation. Best for RAG + research agents.",
        "category": "web",
        "requires_api_key": True,
        "api_key_field": "tavily_api_key",
        "key_url": "https://app.tavily.com/home",
        "capabilities": ["web", "news", "academic", "answer_generation", "content_extraction"],
        "pricing": {"free_tier": "1000 queries/month", "paid": "$0.005/query (pay-as-you-go)"},
        "docs_url": "https://docs.tavily.com",
        "icon_color": "#f97316",
        "sort_order": 10,
    },
    {
        "id": "duckduckgo",
        "display_name": "DuckDuckGo",
        "description": "Free web search with no API key required. Privacy-focused, good for general queries without setup.",
        "category": "web",
        "requires_api_key": False,
        "api_key_field": None,
        "key_url": None,
        "capabilities": ["web", "instant_answer", "images", "videos", "news"],
        "pricing": {"free": "Yes — unlimited", "rate_limit": "No documented limit, but throttle recommended"},
        "docs_url": "https://duckduckgo.com/api",
        "icon_color": "#de5833",
        "sort_order": 20,
    },
    {
        "id": "wikipedia",
        "display_name": "Wikipedia",
        "description": "Free encyclopedia lookup via the MediaWiki API. No API key required. Best for factual lookups and concept explanations.",
        "category": "encyclopedia",
        "requires_api_key": False,
        "api_key_field": None,
        "key_url": None,
        "capabilities": ["encyclopedia", "summary", "full_text", "categories"],
        "pricing": {"free": "Yes — unlimited"},
        "docs_url": "https://www.mediawiki.org/wiki/API:Main_page",
        "icon_color": "#a3a3a3",
        "sort_order": 30,
    },
    {
        "id": "exa",
        "display_name": "Exa (Semantic Search)",
        "description": "Neural search engine for finding pages by meaning rather than keywords. Great for research and discovery.",
        "category": "semantic",
        "requires_api_key": True,
        "api_key_field": "exa_api_key",
        "key_url": "https://dashboard.exa.ai/api-keys",
        "capabilities": ["semantic", "similarity", "neural_search", "research"],
        "pricing": {"free_tier": "1000 queries/month", "paid": "$5/1k queries"},
        "docs_url": "https://docs.exa.ai",
        "icon_color": "#8b5cf6",
        "sort_order": 40,
    },
    {
        "id": "brave",
        "display_name": "Brave Search",
        "description": "Independent web search with privacy focus. Clean results, no tracking. Used by Brave browser.",
        "category": "web",
        "requires_api_key": True,
        "api_key_field": "brave_api_key",
        "key_url": "https://brave.com/search/api/",
        "capabilities": ["web", "news", "images", "videos", "local"],
        "pricing": {"free_tier": "2000 queries/month", "paid": "$3-9 CPM"},
        "docs_url": "https://brave.com/search/api/docs",
        "icon_color": "#fb542b",
        "sort_order": 50,
    },
    {
        "id": "serpapi",
        "display_name": "SerpAPI",
        "description": "Real-time Google, Bing, Yahoo, and other search engine results via API. Returns structured data.",
        "category": "web",
        "requires_api_key": True,
        "api_key_field": "serpapi_api_key",
        "key_url": "https://serpapi.com/manage-api-key",
        "capabilities": ["google", "bing", "yahoo", "shopping", "images", "news", "maps"],
        "pricing": {"free_tier": "100 searches/month", "paid": "$50/mo for 5000"},
        "docs_url": "https://serpapi.com/search-api",
        "icon_color": "#3b82f6",
        "sort_order": 60,
    },
]


def seed():
    # Auto-create the table if it doesn't exist yet (using SQLAlchemy metadata)
    from db.database import Base
    Base.metadata.create_all(bind=engine, tables=[SearchProvider.__table__])

    db = SessionLocal()
    try:
        for provider in SEARCH_PROVIDERS:
            existing = db.query(SearchProvider).filter_by(id=provider["id"]).first()
            if existing:
                # Update all fields
                for key, value in provider.items():
                    setattr(existing, key, value)
                print(f"  ↻ Updated: {provider['id']} ({provider['display_name']})")
            else:
                db.add(SearchProvider(**provider))
                print(f"  ✓ Inserted: {provider['id']} ({provider['display_name']})")
        db.commit()
        count = db.query(SearchProvider).count()
        print(f"\nTotal search providers: {count}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()