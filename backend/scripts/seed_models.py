"""
Seed the unified `models` table with all cloud models from hardcoded sources.

Run once after creating the `models` table:
    cd backend && .venv/bin/python3 scripts/seed_models.py

This script:
1. Drops and recreates cloud entries in the `models` table
2. Also copies data from `local_models` table (if any local models exist)
3. Sets `source='local'` for local models

After this, all model config is in PostgreSQL — no hardcoded enum needed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.database import SessionLocal, engine
from models.model import Model
from sqlalchemy import text


CLOUD_MODELS = [
    # OpenAI - GPT-5 Series
    {"model_id": "gpt-5.1", "display_name": "GPT-5.1", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 256000}},
    {"model_id": "gpt-4o", "display_name": "GPT-4o", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 128000}},
    {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 128000}},

    # DeepSeek
    {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 64000}},
    {"model_id": "deepseek-reasoner", "display_name": "DeepSeek Reasoner", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": False, "structured_output": False, "max_context": 64000}},

    # Anthropic - Claude 4.5
    {"model_id": "claude-opus-4-5", "display_name": "Claude Opus 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-opus-4-5-20250514", "display_name": "Claude Opus 4.5 (May 2025)", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-sonnet-4-5-20250514", "display_name": "Claude Sonnet 4.5 (May 2025)", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-sonnet-4-5-20250929", "display_name": "Claude Sonnet 4.5 (Sep 2025)", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},
    {"model_id": "claude-haiku-4-5-20251015", "display_name": "Claude Haiku 4.5 (Oct 2025)", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 200000}},

    # Google - Gemini 3 / 2.5 Series
    {"model_id": "gemini-3-pro-preview", "display_name": "Gemini 3 Pro (Preview)", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1048576}},
    {"model_id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1048576}},
    {"model_id": "gemini-2.5-flash-lite", "display_name": "Gemini 2.5 Flash Lite", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1048576}},
    {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1048576}},

    # GLM (Zhipu AI)
    {"model_id": "glm-4", "display_name": "GLM-4", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "max_context": 128000}},
    {"model_id": "glm-4v", "display_name": "GLM-4V (Vision)", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "max_context": 128000}},
    {"model_id": "glm-4-flash", "display_name": "GLM-4 Flash", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "max_context": 128000}},

    # MiniMax
    {"model_id": "minimax-t1", "display_name": "MiniMax T1", "provider": "minimax",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "max_context": 128000}},
    {"model_id": "minimax-m3", "display_name": "MiniMax M3", "provider": "minimax",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "max_context": 128000}},

    # Agnes AI
    {"model_id": "agnes-2.0-flash", "display_name": "Agnes 2.0 Flash", "provider": "agnes",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1000000}},
    {"model_id": "agnes-2.0-flash-free", "display_name": "Agnes 2.0 Flash (Free)", "provider": "agnes",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "max_context": 1000000}},
]


def seed():
    # ── Ensure table exists ──────────────────────────────────────────
    Model.metadata.create_all(bind=engine, checkfirst=True)
    print("📦 Ensured `models` table exists")

    db = SessionLocal()
    try:
        # 1. Delete existing cloud entries (re-seed fresh)
        deleted_cloud = db.query(Model).filter(Model.source == 'cloud').delete()
        print(f"🗑️  Deleted {deleted_cloud} existing cloud model entries")

        # 2. Insert all cloud models
        for m in CLOUD_MODELS:
            model = Model(
                model_id=m["model_id"],
                display_name=m["display_name"],
                provider=m["provider"],
                source="cloud",
                capabilities=m["capabilities"],
                is_active=True,
            )
            db.add(model)

        db.commit()
        cloud_count = db.query(Model).filter(Model.source == 'cloud').count()
        print(f"✅ Seeded {cloud_count} cloud models")

        # 3. Copy local models from local_models table (if table exists)
        try:
            local_models = db.execute(text(
                "SELECT id, name, display_name, provider, base_url, "
                "model_name, api_key, is_validated, capabilities, "
                "usage_count, is_active, tags, created_at "
                "FROM local_models"
            )).fetchall()

            if local_models:
                existing_ids = {m.model_id for m in db.query(Model.model_id).filter(Model.source == 'local').all()}
                imported = 0
                for lm in local_models:
                    local_id = f"local-{lm.name}"
                    if local_id not in existing_ids:
                        model = Model(
                            model_id=local_id,
                            display_name=lm.display_name,
                            provider=lm.provider,
                            source="local",
                            capabilities=lm.capabilities or {},
                            is_active=lm.is_active,
                            base_url=lm.base_url,
                            api_model_name=lm.model_name,
                            api_key=lm.api_key,
                            is_validated=lm.is_validated,
                            usage_count=lm.usage_count or 0,
                            tags=lm.tags or [],
                        )
                        db.add(model)
                        imported += 1

                if imported:
                    db.commit()
                    print(f"✅ Imported {imported} local models from local_models table")
                else:
                    print(f"ℹ️  Found {len(local_models)} local models in local_models table (all already imported)")
            else:
                print(f"ℹ️  No local models found in local_models table")
        except Exception as e:
            db.rollback()
            print(f"ℹ️  No local models table or data: {e}")

        # 4. Summary
        total = db.query(Model).count()
        by_source = {}
        for row in db.query(Model.source).all():
            by_source[row[0]] = by_source.get(row[0], 0) + 1

        print(f"\n📊 Summary: {total} total models in `models` table")
        for source, count in sorted(by_source.items()):
            print(f"   {source}: {count}")

    finally:
        db.close()

    # Show models grouped by provider
    db = SessionLocal()
    try:
        models = db.query(Model).order_by(Model.provider, Model.model_id).all()
        print(f"\n📋 All models:")
        current_provider = None
        for m in models:
            if m.provider != current_provider:
                current_provider = m.provider
                print(f"\n  {current_provider}:")
            active = "✓" if m.is_active else "✗"
            print(f"    {active} {m.model_id:35s} | {m.display_name:30s} | {m.source}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
