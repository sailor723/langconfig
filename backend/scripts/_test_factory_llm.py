"""Test AgentFactory's LLM creation directly."""
import asyncio
from core.agents.factory import AgentFactory
from db.database import engine
from sqlalchemy import text

async def test():
    # Get agent 40 config
    with engine.connect() as c:
        r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = r[0] or {}
    
    print(f"Model: {cfg.get('model')}")
    print(f"Native tools: {cfg.get('native_tools')}")
    
    # Create LLM using the same method as AgentFactory
    llm = await AgentFactory._create_llm(
        model_name=cfg["model"],
        temperature=0,
        max_tokens=30000,
        config={"streaming": False}
    )
    print(f"\nLLM type: {type(llm).__name__}")
    
    # Load tools (math tools are now custom tools from DB)
    tools = await AgentFactory._load_custom_tools(
        ["math_sqrt", "math_add", "math_subtract", "math_multiply", "math_divide"],
        project_id=0
    )
    print(f"Loaded tools: {[t.name for t in tools]}")
    
    # Import create_agent
    from langchain.agents import create_agent
    
    agent = create_agent(llm, tools, system_prompt="Use math tools for calculations.")
    print(f"\nAgent created")
    
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "sqrt(6501)?"}]})
    msgs = result["messages"]
    for m in msgs:
        role = m.type
        content = str(m.content)[:100] if m.content else ""
        tcs = getattr(m, "tool_calls", [])
        if tcs:
            for tc in tcs:
                print(f"  [{role}] ✅ {tc['name']}({tc['args']})")
        else:
            print(f"  [{role}] {content}")
    
    print("\n✅ Done!")

asyncio.run(test())
