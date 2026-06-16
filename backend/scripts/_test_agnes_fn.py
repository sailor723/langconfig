"""Test if agnes-2.0-flash supports function calling directly via OpenAI SDK."""
import json
from services.encryption import encryption_service
from db.database import engine
from sqlalchemy import text
from openai import OpenAI

# Get agnes key from DB
with engine.connect() as c:
    r = c.execute(text("SELECT api_keys FROM settings ORDER BY id LIMIT 1")).fetchone()
keys = r[0] or {}
encrypted_key = keys.get("agnes")
encrypted_url = keys.get("agnes_base_url")
api_key = encryption_service.decrypt(encrypted_key) if encrypted_key else None
base_url = encryption_service.decrypt(encrypted_url) if encrypted_url else "https://apihub.agnes-ai.com/v1"

print(f"Base URL: {base_url}")
print(f"API Key present: {api_key is not None}")

if not api_key:
    print("❌ No Agnes API key")
    exit(1)

client = OpenAI(api_key=api_key, base_url=base_url)

# Test with tools
tools = [{
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a math expression",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression"}
            },
            "required": ["expression"]
        }
    }
}]

print("\n📤 Sending request with tools definition...")
r = client.chat.completions.create(
    model="agnes-2.0-flash",
    messages=[
        {"role": "system", "content": "Use calculator tool for math."},
        {"role": "user", "content": "what is sqrt(6501)?"}
    ],
    tools=tools,
    tool_choice="auto",
    max_tokens=500,
)

msg = r.choices[0].message
print(f"\nResponse role: {msg.role}")
print(f"Content: {msg.content[:200] if msg.content else '(none)'}")
print(f"Tool calls: {msg.tool_calls}")

if msg.tool_calls:
    for tc in msg.tool_calls:
        print(f"\n✅ TOOL CALLED: {tc.function.name}({tc.function.arguments})")
else:
    print("\n❌ No tool calls - model refused to use tools")
