"""Test if tool result actually reaches the LLM."""
import requests, json

BASE = "http://localhost:8765"

# Start session
r = requests.post(f"{BASE}/api/chat/start", json={"agent_id": 40}, timeout=10)
sid = r.json().get("session_id")
print(f"Session: {sid}")

# Ask something the model CANNOT know - like a fake calculation
# sqrt(123456789) = 11111.111... - model might "know" this
# But what about: 827364 * 192847 ?
r2 = requests.post(f"{BASE}/api/chat/message/stream", 
    json={"session_id": sid, "message": "what is 827364 * 192847 ? use math_multiply"},
    stream=True, timeout=120)

tool_seen = False
tool_output = None
final_answer = ""
for line in r2.iter_lines(decode_unicode=True):
    if not line: continue
    if line.startswith("data: "):
        data = json.loads(line[6:])
        if data.get("type") == "tool_start":
            tool_seen = True
            print(f"TOOL_START: {data['tool_name']} args={data.get('data',{}).get('input',{})}")
        elif data.get("type") == "tool_end":
            out = data.get("data", {}).get("output", None)
            tool_output = out
            print(f"TOOL_END: output={out}")
        elif data.get("type") == "chunk":
            final_answer += data.get("content", "")
            print(data.get("content", ""), end="", flush=True)

print(f"\n\nTool was called: {tool_seen}")
print(f"Tool output from event: {tool_output}")
print(f"Final answer: {final_answer[:150]}")
# Ground truth
print(f"Ground truth: {827364 * 192847}")
