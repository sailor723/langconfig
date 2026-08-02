"""Add python_execute native tool to agent 162 (Presentation Generator)."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from dotenv import load_dotenv

load_dotenv(os.path.join("..", ".env"))

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate

db = SessionLocal()
try:
    row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 162).first()
    if not row:
        print("AGENT 162 NOT FOUND")
        sys.exit(1)

    cfg = copy.deepcopy(row.config)
    tools = cfg.get("native_tools") or []
    if "python_execute" in tools:
        print("python_execute already in native_tools:", tools)
    else:
        tools = tools + ["python_execute"]
        cfg["native_tools"] = tools
        # JSON columns require reassignment, not in-place mutation
        row.config = cfg
        db.commit()
        print("UPDATED native_tools:", tools)
finally:
    db.close()
