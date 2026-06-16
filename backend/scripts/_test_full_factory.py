"""Test AgentFactory.create_agent FULL flow (including constraints wrapping)."""
import asyncio, json
from core.agents.factory import AgentFactory
from db.database import engine
from sqlalchemy import text

async def test():
    with engine.connect() as c:
        r = c.execute(text("SELECT config FROM deep_agent_templates WHERE id = 40")).fetchone()
    cfg = dict(r[0]) or {}
    
    print(f"Model: {cfg.get('model')}")
    print(f"Native tools: {cfg.get('native_tools')}")
    print(f"Custom tools: {cfg.get('custom_tools')}")
    print(f"use_deepagents: {cfg.get('use_deepagents')}")
    
    # Call the full AgentFactory.create_agent path
    agent_instance, tools, callbacks = await AgentFactory.create_agent(
        agent_config=cfg,
        project_id=0,
        task_id=0,
        context="",
        mcp_manager=None,
        vector_store=None
    )
    
    print(f"\nAgent type: {type(agent_instance).__name__}")
    print(f"Tools loaded: {[t.name if hasattr(t, 'name') else str(t) for t in tools]}")
    
    # Invoke
    from langchain_core.messages import HumanMessage
    result = await agent_instance.ainvoke(
        {"messages": [HumanMessage(content="sqrt(6501)? call calculator tool")]}
    )
    
    print(f"\n--- Results ---")
    for m in result["messages"]:
        role = m.type
        content = str(m.content)[:100] if m.content else ""
        tcs = getattr(m, "tool_calls", [])
        if tcs:
            for tc in tcs:
                print(f"  [{role}] ✅ {tc['name']}({json.dumps(tc['args'])})")
        elif "tool_result" in str(type(m).__name__).lower():
            print(f"  [{role}] result: {content[:60]}")
        else:
            print(f"  [{role}] {content[:80]}")

asyncio.run(test())
