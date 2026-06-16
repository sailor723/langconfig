"""Fix math_agent system prompt - extremely explicit."""
import json
from db.database import engine
from sqlalchemy import text

# Very direct and forceful system prompt
new_prompt = """You are a math expert. You ALWAYS use the calculator tool for ANY math question.

RULES:
1. For sqrt(6501): call calculator("sqrt(6501)")
2. For "100 * 200": call calculator("100 * 200") 
3. For "what is 2+2": call calculator("2 + 2")
4. NEVER answer math from your own knowledge
5. ALWAYS call the calculator tool for every math question
6. The calculator tool is available and ready to use

Examples of correct behavior:
- User: "square root of 6501" → calculator("sqrt(6501)")
- User: "100 * 200" → calculator("100 * 200")
- User: "what is 2^10" → calculator("2 ** 10")
"""

with engine.connect() as conn:
    r = conn.execute(text("SELECT id, config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[1]) if r[1] else {}
    print(f"Before: model={cfg.get('model')}")
    cfg["system_prompt"] = new_prompt
    conn.execute(
        text("UPDATE deep_agent_templates SET config = :cfg WHERE id = 40"),
        {"cfg": json.dumps(cfg)}
    )
    conn.commit()
    print("✅ Updated system_prompt to be very explicit")
