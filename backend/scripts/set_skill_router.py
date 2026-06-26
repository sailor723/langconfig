"""Set skill_router_model on ticker_classifer and test skill routing."""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate

db = SessionLocal()
a = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == "ticker_classifer").first()
if a:
    config = a.config
    config["skill_router_model"] = "deepseek:deepseek-chat"
    a.config = config
    db.commit()
    print(f"✅ Set skill_router_model=deepseek:deepseek-chat on {a.name}")
    print(f"   skills: {config.get('skills')}")
    print(f"   skill_router_model: {config.get('skill_router_model')}")
    print(f"   use_local_sandbox: {config.get('use_local_sandbox')}")
else:
    print("Agent not found")
db.close()
