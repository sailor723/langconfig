"""Test multi-turn skill delegation via chat API."""
import requests, json, time, sys

BASE = "http://127.0.0.1:8765"
AID = 47

# Start session
r = requests.post(f"{BASE}/api/chat/start", json={"agent_id": AID}, timeout=10)
sid = r.json()["session_id"]
print(f"Session: {sid[:12]}...\n")

def send(msg, turn):
    t0 = time.time()
    r = requests.post(f"{BASE}/api/chat/message", json={"session_id": sid, "message": msg}, timeout=180)
    t = time.time() - t0
    data = r.json()
    tools = data.get("tool_calls", [])
    resp = data.get("response", "")[:300]
    tokens = data.get("metrics", {}).get("total_tokens", "?")
    print(f"--- Turn {turn} ({t:.1f}s, {tokens} tok) ---")
    for tc in tools:
        sn = tc.get("skill_name", "")
        name = tc["tool_name"]
        print(f"  TOOL: {name}" + (f" [{sn}]" if sn else ""))
    # Check if response is skill-driven
    keywords = {"priority":"ticket","category":"ticket","sql injection":"code","csv":"data","revenue":"data"}
    detected = [f"{kw}({skill})" for kw, skill in keywords.items() if kw.lower() in resp.lower()]
    if detected:
        print(f"  ✅ {', '.join(detected)}")
    else:
        print(f"  ⚠️  {resp[:200]}")
    print()

send("Order #12345 is 3 weeks late! I want a refund!", 1)
send('Review: def login(p): return "SELECT * FROM users WHERE pass=\'"+p+"\'"', 2)
send("Can you analyze my monthly sales CSV?", 3)
