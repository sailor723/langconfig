#!/usr/bin/env python3
"""Test DeepSeek + graphindex_search via streaming endpoint."""
import urllib.request, json, time, sys

# Create session
req = urllib.request.Request(
    "http://localhost:8765/api/chat/start",
    data=json.dumps({"agent_id": 45}).encode(),
    headers={"Content-Type": "application/json"},
)
resp = json.loads(urllib.request.urlopen(req).read())
sid = resp["session_id"]
print(f"Session: {sid}")

time.sleep(2)

# Send Nike query via streaming endpoint
data = json.dumps({"session_id": sid, "message": "Search project documents for Nike 10-K financial report and summarize it"}).encode()
req = urllib.request.Request(
    "http://localhost:8765/api/chat/message/stream",
    data=data,
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=120)
    body = resp.read().decode()
    print(f"\nResponse ({len(body)} chars):")
    print(body[:1000])
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode()[:300])
except Exception as e:
    print(f"Error: {e}")
