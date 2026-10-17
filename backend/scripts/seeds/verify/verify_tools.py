# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Verify if image_generation tool is assigned to agents.

Ad-hoc diagnostic (no pass/fail): prints which agents carry the tool.

    cd backend && .venv/bin/python scripts/seeds/verify/verify_tools.py
"""
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND  # noqa: E402  (also puts backend/ on sys.path)

from db.database import SessionLocal  # noqa: E402
from models.workflow import WorkflowProfile
import json

db = SessionLocal()

workflow = db.query(WorkflowProfile).filter(WorkflowProfile.id == 24).first()

if workflow:
    print(f"=== WORKFLOW: {workflow.name} ===\n")
    config = workflow.configuration
    nodes = config.get('nodes', [])

    for node in nodes:
        node_id = node.get('id')
        node_type = node.get('type')
        node_config = node.get('config', {})

        # Get custom tools
        custom_tools = node_config.get('custom_tools', [])
        mcp_tools = node_config.get('mcp_tools', [])

        print(f"Node ID: {node_id}")
        # Remove emojis/non-ASCII from type for display
        safe_type = ''.join(c for c in node_type if ord(c) < 128) if node_type else 'unknown'
        print(f"  Type: {safe_type[:50]}")
        print(f"  MCP Tools: {mcp_tools}")
        print(f"  Custom Tools: {custom_tools}")

        if 'image_generation' in custom_tools:
            print(f"  >>> IMAGE_GENERATION TOOL FOUND! <<<")
        else:
            print(f"  X No image_generation tool")
        print()
else:
    print("Workflow 24 not found")

db.close()
