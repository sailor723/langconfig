"""
SearchProvider — config for web/encode search backends (Tavily, Wikipedia, DDG, etc.).

Mirrors the `models` table pattern (Phase 5): all search provider metadata in DB,
API keys stored encrypted in `settings.api_keys` JSONB column.

Seed data: backend/scripts/seeds/in/seed_search_providers.py
"""
from sqlalchemy import Column, String, Boolean, Integer, JSON, Text
from db.database import Base


class SearchProvider(Base):
    __tablename__ = "search_providers"

    id = Column(String, primary_key=True)              # e.g. "tavily", "wikipedia"
    display_name = Column(String, nullable=False)      # "Tavily AI Search"
    description = Column(Text, nullable=True)          # one-line description for UI
    category = Column(String, default="web")            # "web" | "academic" | "news" | "semantic"
    requires_api_key = Column(Boolean, default=True)
    api_key_field = Column(String, nullable=True)      # e.g. "tavily_api_key" → settings.api_keys[...]
    key_url = Column(String, nullable=True)            # where to get the key
    capabilities = Column(JSON, default=list)          # ["web", "news", "academic", "images"]
    pricing = Column(JSON, default=dict)               # {"free_tier": "1000/mo", "paid": "$0.001/query"}
    docs_url = Column(String, nullable=True)
    icon_color = Column(String, default="#3b82f6")      # tailwind-like hex for UI accent
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=100)          # for UI ordering