"""Check session for tool calls."""
import json
from db.database import engine
from sqlalchemy import text

with engine.connect() as c:
    # Check the latest session for agent 40
    s = c.execute(text("""
        SELECT session_id, messages, tool_calls FROM chat_sessions 
        WHERE agent_id = 40 ORDER BY updated_at DESC LIMIT 1
    """)).fetchone()
    
    if s:
        print(f"Session: {s[0]}")
        msgs = s[1] or []
        tc = s[2] or []
        print(f"Messages: {len(msgs)}")
        print(f"Tool calls: {tc}")
        
        for i, m in enumerate(msgs):
            role = m.get("role", "?")
            content = m.get("content", "")
            tcs = m.get("tool_calls", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        print(f"  msg[{i}] TOOL_USE: {block.get('name')}({json.dumps(block.get('input',{}))})")
                    elif isinstance(block, dict) and block.get("type") == "tool_result":
                        print(f"  msg[{i}] TOOL_RESULT: {str(block.get('content',''))[:80]}")
                    elif isinstance(block, dict):
                        txt = block.get("text", "")
                        if txt:
                            print(f"  msg[{i}] {str(txt)[:100]}")
            else:
                if tcs:
                    fn = tcs[0].get("function", {})
                    print(f"  msg[{i}] TOOL_CALL: {fn.get('name')}({str(fn.get('arguments',''))[:60]})")
                elif content:
                    print(f"  msg[{i}] {str(content)[:150]}")
    else:
        print("No sessions found for agent 40")
