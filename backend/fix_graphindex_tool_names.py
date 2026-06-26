"""
Fix naming consistency in the 4 graphindex_* custom tools.

Currently:
  tool_id: graphindex_ingest
  function_name (in DB): studio_ingest    <-- inconsistent
  def in code: def studio_ingest(...)     <-- inconsistent

Target:
  tool_id: graphindex_ingest
  function_name: graphindex_ingest
  def in code: def graphindex_ingest(...)

The factory uses function_name to look up the function in the exec'd code,
so as long as function_name and the def agree, it works. But for
cleanliness, both should match the tool_id.
"""
import asyncio
import re
import sys

import httpx

BASE = "http://localhost:8765"

TOOL_IDS = ["graphindex_ingest", "graphindex_rebuild_one",
            "graphindex_rebuild_project", "graphindex_show"]


async def fix_one(client: httpx.AsyncClient, tool_id: str) -> dict:
    # GET current
    r = await client.get(f"{BASE}/api/custom-tools/{tool_id}")
    if r.status_code != 200:
        return {"ok": False, "tool_id": tool_id, "error": f"GET {r.status_code} {r.text[:100]}"}
    t = r.json()
    impl = t.get("implementation_config", {})
    old_fn = impl.get("function_name", "")
    old_code = impl.get("code", "")

    # Update the function_name
    impl["function_name"] = tool_id

    # Update the def in the code
    new_code = re.sub(
        rf"\bdef\s+{re.escape(old_fn)}\s*\(",
        f"def {tool_id}(",
        old_code,
        count=1,
    )

    # PUT update
    payload = {
        "name": t.get("name"),
        "description": t.get("description"),
        "tool_type": t.get("tool_type"),
        "template_type": t.get("template_type"),
        "implementation_config": {**impl, "code": new_code},
        "input_schema": t.get("input_schema"),
        "output_format": t.get("output_format"),
        "is_advanced_mode": t.get("is_advanced_mode"),
        "category": t.get("category"),
        "tags": t.get("tags"),
    }
    r2 = await client.put(f"{BASE}/api/custom-tools/{tool_id}", json=payload)
    if r2.status_code not in (200, 201):
        return {"ok": False, "tool_id": tool_id, "error": f"PUT {r2.status_code} {r2.text[:300]}"}

    # Verify with a fresh GET
    r3 = await client.get(f"{BASE}/api/custom-tools/{tool_id}")
    if r3.status_code != 200:
        return {"ok": False, "tool_id": tool_id, "error": f"verify GET {r3.status_code}"}
    t2 = r3.json()
    new_fn = t2.get("implementation_config", {}).get("function_name")
    new_code = t2.get("implementation_config", {}).get("code", "")
    new_code_first_line = new_code.split("\n", 1)[0].strip()
    return {
        "ok": True,
        "tool_id": tool_id,
        "old_fn": old_fn,
        "new_fn": new_fn,
        "new_code_first_line": new_code_first_line,
    }


async def main() -> int:
    print("🛠  Fixing function_name consistency in 4 graphindex_* custom tools...\n")
    async with httpx.AsyncClient() as client:
        for tool_id in TOOL_IDS:
            result = await fix_one(client, tool_id)
            if result["ok"]:
                print(f"  ✓ {result['tool_id']:30s} {result['old_fn']:20s} -> {result['new_fn']:20s}")
                print(f"    code: {result['new_code_first_line'][:60]}")
            else:
                print(f"  ✗ {result['tool_id']:30s} {result['error']}")
                return 1

    print()
    print("  All 4 tools updated. Now tool_id, function_name, and def all match.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
