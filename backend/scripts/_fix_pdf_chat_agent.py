#!/usr/bin/env python3
"""Fix pdf_chat agent (id=45): tell agent project_id=1."""
import json
import urllib.request

req = urllib.request.Request("http://localhost:8765/api/deepagents/45")
resp = urllib.request.urlopen(req)
agent = json.loads(resp.read())

NEW_PROMPT = (
    "CRITICAL: You MUST call graphindex_search(query, project_id=1) before saying you cannot answer.\n\n"
    "RULES:\n"
    "1. When user asks about any topic, report, or document -> IMMEDIATELY call graphindex_search(query, project_id=1)\n"
    "2. If graphindex_search returns results -> call graphindex_load(context_doc_id) to read full content\n"
    "3. Answer based on the content you loaded\n"
    "4. Only if graphindex_search returns ZERO results -> tell the user you couldn't find it\n\n"
    "You have the tools: graphindex_search(query, project_id), graphindex_load(context_doc_id)\n"
    "ALWAYS use them first. NEVER say you don't have access without searching.\n"
    "IMPORTANT: ALWAYS pass project_id=1 when calling graphindex_search."
)

old_config = agent["config"]
old_config["system_prompt"] = NEW_PROMPT

body = json.dumps({"config": old_config, "lock_version": agent["lock_version"]})
req = urllib.request.Request(
    "http://localhost:8765/api/deepagents/45",
    data=body.encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="PUT",
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"✅ Agent updated: {result['name']}")
print(f"   Prompt: {result['config']['system_prompt'][:60]}...")
