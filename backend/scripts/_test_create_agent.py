"""Test: does create_agent (langchain.agents) work with tools + agnes?"""
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.tools import tool
from services.encryption import encryption_service
from db.database import engine
from sqlalchemy import text

@tool
def calculator(expression: str) -> str:
    """Evaluate math expression."""
    import math
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    allowed.update({"abs": abs, "round": round, "int": int, "float": float, "pow": pow})
    try:
        code = compile(expression.strip(), "<string>", "eval")
        for n in code.co_names:
            if n not in allowed: return f"Error: '{n}' not allowed"
        return str(eval(code, {"__builtins__": {}}, allowed))
    except Exception as e:
        return f"Error: {e}"

with engine.connect() as c:
    r = c.execute(text("SELECT api_keys FROM settings ORDER BY id LIMIT 1")).fetchone()
keys = r[0] or {}
ak = encryption_service.decrypt(keys.get("agnes"))
bu = encryption_service.decrypt(keys.get("agnes_base_url")) or "https://apihub.agnes-ai.com/v1"

model = init_chat_model(model="agnes-2.0-flash", model_provider="openai", api_key=ak, base_url=bu, temperature=0)

agent = create_agent(model, [calculator], system_prompt="You ALWAYS use calculator tool for math.")
print("Agent created")

r = agent.invoke({"messages": [{"role": "user", "content": "what is sqrt(6501)? use calculator"}]})
msgs = r["messages"]
for m in msgs:
    role = m.type
    content = str(m.content)[:100] if m.content else ""
    tcs = getattr(m, "tool_calls", [])
    if tcs:
        for tc in tcs:
            print(f"  [{role}] ✅ TOOL: {tc['name']}({tc['args']})")
    elif "tool_result" in m.__class__.__name__:
        print(f"  [{role}] tool_result: {content[:80]}")
    else:
        print(f"  [{role}] {content}")
