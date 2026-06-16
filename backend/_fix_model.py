#!/usr/bin/env python3
"""Switch agent model to deepseek-chat."""
import json, urllib.request

HOST = "http://localhost:8765"
AGENT_ID = 45

body = json.dumps({"config": {"model": "deepseek-chat"}})
req = urllib.request.Request(
    f"{HOST}/api/deepagents/{AGENT_ID}",
    data=body.encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="PUT",
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Agent updated: {result['name']}")
print(f"Model: {result['config']['model']}")
print(f"Tools: {result['config']['custom_tools']}")
