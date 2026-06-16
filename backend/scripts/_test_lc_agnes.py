"""Test langchain tool binding with agnes."""
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    import math
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    allowed.update({"abs": abs, "round": round, "int": int, "float": float, "pow": pow})
    try:
        code = compile(expression.strip(), "<string>", "eval")
        for name in code.co_names:
            if name not in allowed:
                return f"Error: '{name}' not allowed"
        return str(eval(code, {"__builtins__": {}}, allowed))
    except Exception as e:
        return f"Error: {e}"

from services.encryption import encryption_service
from db.database import engine
from sqlalchemy import text

# Get agnes key
with engine.connect() as c:
    r = c.execute(text("SELECT api_keys FROM settings ORDER BY id LIMIT 1")).fetchone()
keys = r[0] or {}
ak = encryption_service.decrypt(keys.get("agnes"))
bu = encryption_service.decrypt(keys.get("agnes_base_url")) or "https://apihub.agnes-ai.com/v1"

print(f"Creating model with agnes-2.0-flash via {bu}")
model = init_chat_model(
    model="agnes-2.0-flash",
    model_provider="openai",
    api_key=ak,
    base_url=bu,
    temperature=0,
)

# Bind tools and invoke
tools = [calculator]
model_with_tools = model.bind_tools(tools)

print("Invoking model with tools...")
r = model_with_tools.invoke([{"role": "user", "content": "what is sqrt(6501)? call calculator tool"}])
print(f"\nRole: {r.type}")
print(f"Content: {str(r.content)[:200]}")
print(f"Tool calls: {r.tool_calls}")
if r.tool_calls:
    for tc in r.tool_calls:
        print(f"  ✅ {tc['name']}({tc['args']})")
else:
    print("❌ No tool calls from LangChain model!")
