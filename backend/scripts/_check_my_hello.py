"""Check if my_hello tool exists in DB."""
from db.database import SessionLocal
from models.custom_tool import CustomTool

db = SessionLocal()
tool = db.query(CustomTool).filter(CustomTool.tool_id == "my_hello").first()
if tool:
    print(f"✅ Found my_hello!")
    print(f"  name: {tool.name}")
    print(f"  type: {tool.tool_type}")
    print(f"  description: {tool.description[:80]}")
    print(f"  fn_name: {tool.implementation_config.get('function_name')}")
    code = tool.implementation_config.get("code", "")
    print(f"  code:\n{code[:200]}")
else:
    print("❌ my_hello NOT found in custom_tools table")
    all_tools = db.query(CustomTool).all()
    if all_tools:
        print(f"\nAll custom tools ({len(all_tools)}):")
        for t in all_tools:
            print(f"  - {t.tool_id}: {t.name}")
    else:
        print("No custom tools in DB at all")
db.close()
