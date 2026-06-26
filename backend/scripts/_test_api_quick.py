"""Quick API test for multi-turn skills."""
import requests
import json

BASE = "http://127.0.0.1:8765"
AID = 47

# Start session
r = requests.post(BASE + "/api/chat/start", json={"agent_id": AID}, timeout=10)
sid = r.json()["session_id"]
print(f"Session: {sid[:12]}...\n")

# Turn 1: Ticket
r = requests.post(BASE + "/api/chat/message", json={"session_id": sid, "message": "Order #12345 is 3 weeks late! I want a refund!"}, timeout=180)
d = r.json()
print(f"Turn 1 tools: {[t['tool_name'] for t in d.get('tool_calls',[])]}")
resp = d.get("message", "")  # Pydantic model field is 'message', not 'response'
print(f"  priority={'priority' in resp.lower()}, category={'category' in resp.lower()}, sentiment={'sentiment' in resp.lower()}")
print(f"  {resp[:200]}\n")

# Turn 2: Code review
r = requests.post(BASE + "/api/chat/message", json={"session_id": sid, "message": 'Review: def login(p): return "SELECT * FROM users WHERE pass=\'"+p+"\'"'}, timeout=180)
d = r.json()
resp = d.get("message", "")
print(f"Turn 2 tools: {[t['tool_name'] for t in d.get('tool_calls',[])]}")
print(f"  sql injection={'sql injection' in resp.lower()}, security={'security' in resp.lower()}")
print(f"  {resp[:200]}\n")

# Turn 3: Data analysis
r = requests.post(BASE + "/api/chat/message", json={"session_id": sid, "message": "Can you analyze my monthly sales CSV?"}, timeout=180)
d = r.json()
resp = d.get("message", "")
print(f"Turn 3 tools: {[t['tool_name'] for t in d.get('tool_calls',[])]}")
print(f"  csv={'csv' in resp.lower()}, analysis={'analysis' in resp.lower()}")
print(f"  {resp[:200]}\n")
