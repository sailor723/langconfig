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
    {"model_id": "gpt-5.5", "display_name": "GPT-5.5", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 128000,
                      "input_price": 5.00, "output_price": 30.00, "speed_tps": 80,
                      "thinking": True, "open_source": False, "release": "2026-03"}},
    {"model_id": "gpt-5.1", "display_name": "GPT-5.1", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 128000,
                      "input_price": 2.50, "output_price": 15.00, "speed_tps": 70,
                      "thinking": True, "open_source": False, "release": "2025-08"}},
    {"model_id": "gpt-4.1", "display_name": "GPT-4.1", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 32000,
                      "input_price": 2.00, "output_price": 8.00, "speed_tps": 60,
                      "thinking": False, "open_source": False, "release": "2025-04",
                      "strength": "Coding, long-context"}},
    {"model_id": "gpt-4o", "display_name": "GPT-4o", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True,
                      "max_context": 128000, "max_output": 16000,
                      "input_price": 2.50, "output_price": 10.00, "speed_tps": 55,
                      "thinking": False, "open_source": False, "release": "2024-05",
                      "strength": "Multimodal, voice"}},
    {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 128000, "max_output": 16000,
                      "input_price": 0.15, "output_price": 0.60, "speed_tps": 90,
                      "thinking": False, "open_source": False, "release": "2024-07",
                      "strength": "Fast, cheap"}},
    {"model_id": "o3", "display_name": "OpenAI o3", "provider": "openai",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True,
                      "max_context": 200000, "max_output": 100000,
                      "input_price": 2.00, "output_price": 8.00, "speed_tps": 30,
                      "thinking": True, "open_source": False, "release": "2025-12",
                      "strength": "Reasoning, math, science"}},

    # DeepSeek (current production models)
    {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat (V3.2)", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True,
                      "max_context": 128000, "max_output": 8192,
                      "input_price": 0.27, "output_price": 1.10, "speed_tps": 65,
                      "thinking": False, "open_source": True, "license": "DeepSeek",
                      "release": "2025-09", "strength": "Current production, fast, cheap"}},
    {"model_id": "deepseek-reasoner", "display_name": "DeepSeek Reasoner (R1)", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": False, "structured_output": False,
                      "max_context": 128000, "max_output": 32000,
                      "input_price": 0.55, "output_price": 2.19, "speed_tps": 35,
                      "thinking": True, "open_source": True, "license": "MIT",
                      "release": "2025-01", "strength": "Reasoning, math, science"}},
    # DeepSeek V4 Series (April 2026 — preview)
    {"model_id": "deepseek-v4-pro", "display_name": "DeepSeek V4 Pro", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True,
                      "max_context": 1000000, "max_output": 384000,
                      "input_price": 1.74, "output_price": 3.48, "speed_tps": 40,
                      "thinking": True, "open_source": True, "license": "MIT",
                      "release": "2026-04",
                      "strength": "Frontier MoE, hybrid attention",
                      "params_total": "1.6T", "params_active": "49B",
                      "architecture": "Hybrid CSA+HCA"}},
    {"model_id": "deepseek-v4-flash", "display_name": "DeepSeek V4 Flash", "provider": "deepseek",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 384000,
                      "input_price": 0.14, "output_price": 0.28, "speed_tps": 83,
                      "thinking": True, "open_source": True, "license": "MIT",
                      "release": "2026-04",
                      "strength": "Fast, cheap, agents",
                      "params_total": "284B", "params_active": "13B",
                      "architecture": "Hybrid CSA+HCA"}},

    # Anthropic - Claude 4.x
    {"model_id": "claude-opus-4-8", "display_name": "Claude Opus 4.8", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 128000,
                      "input_price": 5.00, "output_price": 25.00, "speed_tps": 35,
                      "thinking": True, "open_source": False, "release": "2026-02",
                      "strength": "Agentic, complex reasoning"}},
    {"model_id": "claude-opus-4-5", "display_name": "Claude Opus 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 200000, "max_output": 128000,
                      "input_price": 5.00, "output_price": 25.00, "speed_tps": 30,
                      "thinking": True, "open_source": False, "release": "2025-11",
                      "strength": "Complex reasoning"}},
    {"model_id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 64000,
                      "input_price": 3.00, "output_price": 15.00, "speed_tps": 65,
                      "thinking": True, "open_source": False, "release": "2026-04",
                      "strength": "Best speed/intelligence balance"}},
    {"model_id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 200000, "max_output": 64000,
                      "input_price": 3.00, "output_price": 15.00, "speed_tps": 60,
                      "thinking": True, "open_source": False, "release": "2025-09",
                      "strength": "Coding, daily tasks"}},
    {"model_id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 200000, "max_output": 64000,
                      "input_price": 1.00, "output_price": 5.00, "speed_tps": 110,
                      "thinking": False, "open_source": False, "release": "2025-10",
                      "strength": "Fast, low-cost"}},
    {"model_id": "claude-haiku-4-5-20251015", "display_name": "Claude Haiku 4.5 (Oct 2025)", "provider": "anthropic",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 200000, "max_output": 64000,
                      "input_price": 1.00, "output_price": 5.00, "speed_tps": 110,
                      "thinking": False, "open_source": False, "release": "2025-10",
                      "strength": "Fast, low-cost"}},

    # Google - Gemini 3 / 2.5 Series
    {"model_id": "gemini-3.1-pro-preview", "display_name": "Gemini 3.1 Pro (Preview)", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True, "video": True,
                      "max_context": 1048576, "max_output": 65536,
                      "input_price": 2.00, "output_price": 12.00, "speed_tps": 60,
                      "thinking": True, "open_source": False, "release": "2026-05",
                      "strength": "Frontier reasoning, video, audio"}},
    {"model_id": "gemini-3-flash-preview", "display_name": "Gemini 3 Flash (Preview)", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True, "video": True,
                      "max_context": 200000, "max_output": 65536,
                      "input_price": 0.50, "output_price": 3.00, "speed_tps": 120,
                      "thinking": True, "open_source": False, "release": "2026-03",
                      "strength": "Fast, default"}},
    {"model_id": "gemini-2.5-pro", "display_name": "Gemini 2.5 Pro", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True, "video": True,
                      "max_context": 1048576, "max_output": 65536,
                      "input_price": 1.25, "output_price": 10.00, "speed_tps": 45,
                      "thinking": True, "open_source": False, "release": "2025-06",
                      "strength": "Reasoning, video understanding"}},
    {"model_id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True, "video": True,
                      "max_context": 1048576, "max_output": 65536,
                      "input_price": 0.30, "output_price": 2.50, "speed_tps": 100,
                      "thinking": True, "open_source": False, "release": "2025-06",
                      "strength": "Best price-performance"}},
    {"model_id": "gemini-2.5-flash-lite", "display_name": "Gemini 2.5 Flash Lite", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1048576, "max_output": 65536,
                      "input_price": 0.10, "output_price": 0.40, "speed_tps": 150,
                      "thinking": False, "open_source": False, "release": "2025-07",
                      "strength": "Cheapest, high volume"}},
    {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "provider": "google",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1048576, "max_output": 8192,
                      "input_price": 0.10, "output_price": 0.40, "speed_tps": 130,
                      "thinking": False, "open_source": False, "release": "2024-12",
                      "strength": "Legacy fast"}},
    {"model_id": "gemma-4", "display_name": "Gemma 4 (Open)", "provider": "google",
     "capabilities": {"streaming": True, "tools": False, "structured_output": False,
                      "max_context": 32000, "max_output": 8192,
                      "input_price": 0.0, "output_price": 0.0, "speed_tps": 90,
                      "thinking": False, "open_source": True, "license": "Gemma",
                      "release": "2025-09", "strength": "Research, on-device"}},

    # GLM (Zhipu AI) - 5.1 series
    {"model_id": "glm-5.1", "display_name": "GLM 5.1", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 200000, "max_output": 32000,
                      "input_price": 1.00, "output_price": 4.00, "speed_tps": 65,
                      "thinking": True, "open_source": False, "release": "2026-04",
                      "strength": "Frontier Chinese, coding"}},
    {"model_id": "glm-4.5", "display_name": "GLM 4.5", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 128000, "max_output": 32000,
                      "input_price": 0.50, "output_price": 2.00, "speed_tps": 70,
                      "thinking": True, "open_source": True, "license": "MIT",
                      "release": "2025-07", "strength": "Open MoE"}},
    {"model_id": "glm-4v", "display_name": "GLM-4V (Vision)", "provider": "glm",
     "capabilities": {"streaming": True, "tools": True, "structured_output": False, "vision": True,
                      "max_context": 128000, "max_output": 8192,
                      "input_price": 0.20, "output_price": 0.80, "speed_tps": 80,
                      "thinking": False, "open_source": False, "release": "2024-12"}},

    # MiniMax - M3 series
    {"model_id": "minimax-m3", "display_name": "MiniMax M3", "provider": "minimax",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "audio": True, "video": True,
                      "max_context": 1000000, "max_output": 64000,
                      "input_price": 0.30, "output_price": 1.20, "speed_tps": 80,
                      "thinking": True, "open_source": False, "release": "2026-03",
                      "strength": "Long-context multimodal"}},
    {"model_id": "minimax-m2.7", "display_name": "MiniMax M2.7", "provider": "minimax",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 256000, "max_output": 32000,
                      "input_price": 0.20, "output_price": 1.00, "speed_tps": 90,
                      "thinking": True, "open_source": False, "release": "2026-01",
                      "strength": "Multimodal, agents"}},

    # Qwen (Alibaba)
    {"model_id": "qwen3.5-plus", "display_name": "Qwen 3.5 Plus", "provider": "qwen",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 32000,
                      "input_price": 0.40, "output_price": 2.40, "speed_tps": 70,
                      "thinking": True, "open_source": False, "release": "2026-03",
                      "strength": "Multilingual, coding"}},
    {"model_id": "qwen3.6-plus", "display_name": "Qwen 3.6 Plus", "provider": "qwen",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True, "vision": True,
                      "max_context": 1000000, "max_output": 32000,
                      "input_price": 0.50, "output_price": 2.50, "speed_tps": 75,
                      "thinking": True, "open_source": False, "release": "2026-05",
                      "strength": "Latest Qwen, multimodal"}},

    # Kimi (Moonshot)
    {"model_id": "kimi-k2.6", "display_name": "Kimi K2.6", "provider": "kimi",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True,
                      "max_context": 262144, "max_output": 32000,
                      "input_price": 0.95, "output_price": 4.00, "speed_tps": 55,
                      "thinking": True, "open_source": False, "release": "2026-04",
                      "strength": "Long-doc, Chinese"}},

    # Agnes AI
    {"model_id": "agnes-2.0-flash", "display_name": "Agnes 2.0 Flash", "provider": "agnes",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True,
                      "max_context": 1000000, "max_output": 32000,
                      "input_price": 0.50, "output_price": 2.00, "speed_tps": 70,
                      "thinking": False, "open_source": False, "release": "2026-03",
                      "strength": "OpenAI-compatible hub"}},
    {"model_id": "agnes-2.0-flash-free", "display_name": "Agnes 2.0 Flash (Free)", "provider": "agnes",
     "capabilities": {"streaming": True, "tools": True, "structured_output": True,
                      "max_context": 1000000, "max_output": 32000,
                      "input_price": 0.0, "output_price": 0.0, "speed_tps": 60,
                      "thinking": False, "open_source": False, "release": "2026-03",
                      "strength": "Free tier"}},
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
