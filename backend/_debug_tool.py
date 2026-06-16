#!/usr/bin/env python3
"""Check tool config in DB directly."""
from db.database import SessionLocal
from models.custom_tool import CustomTool
import json

db = SessionLocal()
tool = db.query(CustomTool).filter(CustomTool.tool_id == "get_pdf").first()
if tool:
    print("=== input_schema ===")
    print(json.dumps(tool.input_schema, indent=2))
    print()
    print("=== implementation_config ===")
    print(json.dumps(tool.implementation_config, indent=2))
    print()
    print("=== args_schema in impl ===")
    print(json.dumps(tool.implementation_config.get("args_schema", "NOT PRESENT"), indent=2))
else:
    print("Tool not found")
db.close()
