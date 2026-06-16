"""Check current math_agent config."""
import json
from db.database import engine
from sqlalchemy import text
with engine.connect() as c:
    r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = r[0] or {}
    print("=== System Prompt ===")
    print(cfg.get("system_prompt",""))
    print()
    print("=== use_deepagents ===")
    print(cfg.get("use_deepagents"))
    print()
    print("=== native_tools ===")
    print(cfg.get("native_tools"))
    print()
    print("=== custom_tools ===")
    print(cfg.get("custom_tools"))
