"""Test: does the AgentFactory create_agent actually work with tools?"""
import asyncio, json, sys
from core.agents.factory import AgentFactory
from db.database import engine
from sqlalchemy import text
from langchain.agents import create_agent

async def test():
    # Get config
    with engine.connect() as c:
        r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[0]) if r[0] else {}
    print(f"Model: {cfg.get('model')}")
    print(f"Native tools: {cfg.get('native_tools')}")
    
    # Create LLM the SAME way AgentFactory does
    llm = await AgentFactory._create_llm(
        model_name=cfg["model"],
        temperature=0,
        max_tokens=30000,
        config={"streaming": False}
    )
    print(f"LLM: {type(llm).__name__}")
    
    # Load tools the SAME way AgentFactory does
    tools = await AgentFactory._load_native_tools(cfg.get("native_tools", []))
    print(f"Tools: {[t.name for t in tools]}")
    
    # Create system prompt the SAME way AgentFactory does
    base_prompt = cfg.get("system_prompt", "")
    context = ""
    enable_memory = False
    system_prompt_str = AgentFactory._construct_system_prompt_string(
        base_prompt, context, enable_memory, tools=tools
    )
    print(f"\n=== System Prompt ===")
    print(system_prompt_str[:500])
    print("...")
    
    # Create agent
    agent = create_agent(model=llm, tools=tools, system_prompt=system_prompt_str)
    print(f"\nAgent created: {type(agent).__name__}")
    
    # Invoke
    print("\n--- Invoking agent ---")
    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": "what is sqrt(6501)? Use calculator tool."}]
    })
    
    msgs = result["messages"]
    for m in msgs:
        role = m.type
        content = str(m.content)[:100] if m.content else ""
        tcs = getattr(m, "tool_calls", [])
        if tcs:
            for tc in tcs:
                print(f"  [{role}] ✅ TOOL: {tc['name']}({json.dumps(tc['args'])})")
        elif "tool_result" in str(type(m).__name__).lower():
            print(f"  [{role}] tool_result: {content[:60]}")
        else:
            print(f"  [{role}] {content[:80]}")

asyncio.run(test())
