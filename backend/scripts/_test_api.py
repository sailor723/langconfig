"""Test via server - create session then test."""
import requests, json

BASE = "http://127.0.0.1:8765"

# Step 1: Start session
print("1️⃣ Starting session...")
r = requests.post(f"{BASE}/api/chat/start", json={"agent_id": 40, "user_id": 1})
print(f"   Status: {r.status_code}")
data = r.json()
print(f"   Response: {json.dumps(data, indent=2)[:200]}")
sid = data.get("session_id", "")

if not sid:
    print("❌ No session ID")
    exit(1)

# Step 2: Send message
print(f"\n2️⃣ Sending message to session {sid}...")
r = requests.post(f"{BASE}/api/chat/message", json={
    "session_id": sid,
    "message": "calculate sqrt(6501) using the calculator tool",
    "user_id": 1
})
print(f"   Status: {r.status_code}")
data = r.json()
print(f"   Full response:")
print(json.dumps(data, indent=2)[:500])
print()

# Step 3: Check tool_calls
tc = data.get("tool_calls", [])
resp = data.get("response", "")
if tc:
    print(f"✅ Tool calls: {json.dumps(tc, indent=2)}")
else:
    print(f"❌ No tool calls. Response: {resp[:200]}")
