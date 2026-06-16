"""Test model.bind_tools with tool_choice='any' to force tool calling."""
import asyncio
from core.agents.factory import AgentFactory
from db.database import engine
from sqlalchemy import text
from langchain.agents import create_agent

async def test():
    with engine.connect() as c:
        r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[0]) or {}
    
    # Create LLM
    llm = await AgentFactory._create_llm(model_name=cfg["model"], temperature=0, max_tokens=30000, config={"streaming": False})
    
    # Load tools
    tools = await AgentFactory._load_native_tools(cfg.get("native_tools", []))
    print(f"Tools: {[t.name for t in tools]}")
    
    # Bind tools with tool_choice="any"
    bound_model = llm.bind_tools(tools, tool_choice="any")
    
    # Create agent
    agent = create_agent(model=bound_model, tools=tools, system_prompt=cfg.get("system_prompt",""))
    print(f"Agent created with tool_choice='any'")
    
    # Invoke
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "sqrt(6501)?"}]})
    
    for m in result["messages"]:
        role = m.type
        content = str(m.content)[:100] if m.content else ""
        tcs = getattr(m, "tool_calls", [])
        if tcs:
            for tc in tcs:
                print(f"  [{role}] ✅ {tc['name']}({tc['args']})")
        elif "tool_result" in str(type(m).__name__).lower():
            print(f"  [{role}] result: {content[:60]}")
        else:
            print(f"  [{role}] {content[:80]}")

asyncio.run(test())
