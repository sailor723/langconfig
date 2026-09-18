"""Test streaming endpoint for multi-turn skills."""
import requests
import json

BASE = "http://127.0.0.1:8765"

# Start session
r = requests.post(BASE + "/api/chat/start", json={"agent_id": 47}, timeout=10)
sid = r.json()["session_id"]
print(f"Session: {sid[:12]}...")

messages = [
    "Order #12345 is 3 weeks late! I want a refund!",
    "Review: def login(p): return \"SELECT * FROM users WHERE pass='\"+p+\"'\"",
    "Can you analyze my monthly sales CSV?",
]

for i, msg in enumerate(messages):
    print(f"\n=== Streaming Turn {i+1} ===")
    r = requests.post(
        BASE + "/api/chat/message/stream",
        json={"session_id": sid, "message": msg},
        stream=True,
        timeout=300,
    )

    full_text = ""
    tool_count = 0
    error_msg = None
    complete = False

    for line in r.iter_lines():
        if line:
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data = json.loads(line[6:])
                t = data.get("type")
                if t == "chunk":
                    full_text += data.get("content", "")
                elif t == "tool_start":
                    tool_count += 1
                elif t == "complete":
                    complete = True
                    break
                elif t == "error":
                    error_msg = data.get("message")

    print(f"  Tools used: {tool_count}")
    if error_msg:
        print(f"  ERROR: {error_msg}")
    else:
        print(f"  Response length: {len(full_text)}")
        print(f"  Preview: {full_text[:200]}")
        if i == 0:
            print(f"  priority={'priority' in full_text.lower()}")
        elif i == 1:
            print(f"  sql injection={'sql injection' in full_text.lower()}")
        elif i == 2:
            print(f"  csv={'csv' in full_text.lower()}")

print("\n=== Done ===")
