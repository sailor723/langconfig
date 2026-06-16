"""Fix: set use_deepagents=False, use math custom tools from DB, update prompt."""
import json
from db.database import engine
from sqlalchemy import text

new_prompt = """You are a math expert. You ALWAYS use the math tools for ALL calculations. Never answer math questions from your own knowledge alone. When someone asks a math question, call the appropriate math tool.

Available tools:
- math_sqrt(x): Calculate square root of x
- math_add(a, b): Add two numbers
- math_subtract(a, b): Subtract b from a
- math_multiply(a, b): Multiply two numbers
- math_divide(a, b): Divide a by b

Examples:
- "what is sqrt(6501)" → math_sqrt(x=6501)
- "100 * 200" → math_multiply(a=100, b=200)
- "what is the square root of 6501?" → math_sqrt(x=6501)

CRITICAL: Always use math tools. Never do math yourself."""

with engine.connect() as conn:
    r = conn.execute(text("SELECT id, config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[1]) if r[1] else {}
    print(f"Before: use_deepagents={cfg.get('use_deepagents')}, native_tools={cfg.get('native_tools')}, custom_tools={cfg.get('custom_tools')}")

    # Set use_deepagents=False (use standard AgentFactory, same as notebook)
    cfg["use_deepagents"] = False
    
    # Remove calculator from native_tools (now a custom tool)
    native = cfg.get("native_tools", [])
    cfg["native_tools"] = [t for t in native if t != "calculator"]
    
    # Use math custom tools from DB instead
    cfg["custom_tools"] = ["math_sqrt", "math_add", "math_subtract", "math_multiply", "math_divide"]
    
    # Update prompt
    cfg["system_prompt"] = new_prompt

    conn.execute(
        text("UPDATE deep_agent_templates SET config = :cfg WHERE id = 40"),
        {"cfg": json.dumps(cfg)}
    )
    conn.commit()

    v = conn.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    vcfg = v[0] or {}
    print(f"After:  use_deepagents={vcfg.get('use_deepagents')}, native_tools={vcfg.get('native_tools')}, custom_tools={vcfg.get('custom_tools')}")
    print("✅ math_agent now uses custom math tools from DB (same as notebook pattern)")
