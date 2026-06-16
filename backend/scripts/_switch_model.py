"""Switch math_agent to deepseek-chat for tool calling test."""
import json
from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    r = conn.execute(text("SELECT id, config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[1]) if r[1] else {}
    print(f"Before: model={cfg.get('model')}")
    cfg["model"] = "deepseek-chat"
    conn.execute(
        text("UPDATE deep_agent_templates SET config = :cfg WHERE id = 40"),
        {"cfg": json.dumps(cfg)}
    )
    conn.commit()
    print("✅ math_agent now uses deepseek-chat")
