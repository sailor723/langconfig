#!/usr/bin/env python3
"""Fix pdf_chat agent (id=45): update prompt with auto-summary instructions."""
import json
import urllib.request

# First, get current agent to find lock_version
req = urllib.request.Request("http://localhost:8765/api/deepagents/45")
resp = urllib.request.urlopen(req)
agent = json.loads(resp.read())
print(f"Current: {agent['name']}, lock_version={agent['lock_version']}")

NEW_PROMPT = (
    "You are a PDF Chat Assistant. You help users understand and analyze documents "
    "that they upload or reference.\n\n"
    "When a user uploads a document, two messages appear in the conversation:\n"
    "  1. The full document content: `[PDF Content: \"filename.pdf\"]`\n"
    "  2. A request: \"A new document \\\"filename.pdf\\\" has been uploaded. Please read it and provide a briefing.\"\n\n"
    "Your workflow:\n"
    "1. Read the document content directly from the conversation — no tools needed\n"
    "2. IMMEDIATELY provide a thorough briefing of the uploaded document: "
    "summarize its content, key sections, main topics, structure, and any notable details\n"
    "3. Answer any follow-up questions based on the document text\n"
    "4. If you need to search project documents that were NOT uploaded in this chat, "
    "use graphindex_search(query) to find them\n"
    "5. Use graphindex_load(context_doc_id) to get full content of a document found "
    "via graphindex_search\n\n"
    "The session_id is available in your configuration context."
)

old_config = agent["config"]
old_config["system_prompt"] = NEW_PROMPT
old_config["custom_tools"] = []
old_config["native_tools"] = ["graphindex_search", "graphindex_load"]

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
cfg = result["config"]
print(f'  custom_tools: {cfg.get("custom_tools", [])}')
print(f'  native_tools: {cfg.get("native_tools", [])}')
