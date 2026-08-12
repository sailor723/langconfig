"""
DEPRECATED: model configuration moved to PostgreSQL (Phase 5 refactoring, commit ade43ad).

This file is intentionally empty and kept as a placeholder to avoid breaking legacy imports
that may still reference `from constants.models import ...`.

Current model management design (deliberate, post-Phase 5):
  - MODELS    → PostgreSQL `models` table, seeded by scripts/seeds/seed_models.py
                (23 cloud models: DeepSeek, GLM, MiniMax, Claude, GPT, Gemini, etc.)
                Query path: backend/core/agents/factory.py:_create_llm()
                Editable via UI / API.

  - API KEYS  → .env file only (12-factor app pattern).
                Read by backend/config.py:Settings (pydantic-settings).
                Encrypted DB storage was removed in Phase 5 — restart-pickup is fine
                for solo dev and container deploys.

  - DEFAULT_MODEL → hardcoded in backend/core/agents/factory.py:55 as
                    "claude-haiku-4-5-20251015" (was deepseek-chat pre-Phase 5).

Rationale:
  - Models in DB: non-engineers can add model aliases without .env editing.
  - Keys in .env: simpler, no encryption attack surface, 12-factor compliant.
  - No DB→.env fallback chain needed.

See:
  - models/model.py (SQLAlchemy Model)
  - scripts/seeds/seed_models.py (seeding)
  - core/agents/factory.py:_create_llm() (DB-driven routing)
  - config.py:Settings (.env-driven keys)
  - learning/phase1/README.md (Phase 1 design intent)
"""