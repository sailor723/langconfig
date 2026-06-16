"""Test math_agent with native calculator tool."""
import requests, json

BASE = "http://127.0.0.1:8765"

# Start session
r = requests.post(f"{BASE}/api/chat/start", json={"agent_id": 40})
sid = r.json().get("session_id", "")
print(f"Session: {sid}")

# Ask sqrt
r = requests.post(f"{BASE}/api/chat/message", json={
    "session_id": sid,
    "message": "Use the calculator tool to calculate the square root of 6501"
})
data = r.json()
resp = data.get("response", "")
print(f"\n📝 Response: {resp[:300]}")
print(f"\n🔧 Tool calls: {json.dumps(data.get('tool_calls', []), indent=2)[:500]}")

msgs = data.get("all_messages", [])
if msgs:
    print(f"\n📋 Messages:")
    for m in msgs[-6:]:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            c = json.dumps(content)[:100]
        else:
            c = str(content)[:100]
        tcs = m.get("tool_calls", [])
        if tcs:
            fn = tcs[0].get("function", {})
            print(f"  [{role}] TOOL: {fn.get('name','?')}({str(fn.get('arguments',''))[:50]})")
        elif "tool_result" in c:
            print(f"  [{role}] tool_result")
        else:
            print(f"  [{role}] {c}")
