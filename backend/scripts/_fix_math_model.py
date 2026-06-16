"""Switch math_agent to deepseek-chat to verify tool calling works."""
import json
from db.database import engine
from sqlalchemy import text

new_prompt = """You are a math expert. You ALWAYS use the calculator tool for ALL calculations. Never answer math questions from your own knowledge alone. When someone asks a math question, call calculator() with the expression.

Examples:
- "what is sqrt(6501)" → calculator("sqrt(6501)")
- "100 * 200" → calculator("100 * 200")

CRITICAL: Always call the calculator tool. Never do math yourself."""

with engine.connect() as conn:
    r = conn.execute(text("SELECT id, config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[1]) if r[1] else {}
    print(f"Before: model={cfg.get('model')}, native_tools={cfg.get('native_tools')}")

    cfg["model"] = "deepseek-chat"
    cfg["system_prompt"] = new_prompt

    conn.execute(
        text("UPDATE deep_agent_templates SET config = :cfg WHERE id = 40"),
        {"cfg": json.dumps(cfg)}
    )
    conn.commit()

    v = conn.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    vcfg = v[0] or {}
    print(f"After:  model={vcfg.get('model')}")
    print("✅ math_agent now uses deepseek-chat")
