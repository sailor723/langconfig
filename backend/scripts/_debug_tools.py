"""Debug: check math custom tools and agent config."""
import json
from db.database import engine
from sqlalchemy import text

with engine.connect() as c:
    # Check the custom tools table
    tools = c.execute(text("SELECT tool_id, name, tool_type, input_schema, description FROM custom_tools WHERE tool_id LIKE 'math_%' ORDER BY tool_id")).fetchall()
    print("=== CUSTOM TOOLS ===")
    for t in tools:
        print(f"  tool_id={t[0]:20s}  name={t[1]:15s}  type={t[2]:10s}  input={json.dumps(t[3]):80s}  desc={t[4][:60]}")

    print()
    
    # Check agent 40 config
    r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = r[0] or {}
    print("=== AGENT 40 CONFIG ===")
    print(f"  use_deepagents: {cfg.get('use_deepagents')}")
    print(f"  custom_tools: {cfg.get('custom_tools')}")
    print(f"  native_tools: {cfg.get('native_tools')}")
    print(f"  system_prompt: {str(cfg.get('system_prompt', ''))[:200]}")
