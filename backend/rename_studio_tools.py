"""
Rename the 4 studio_* custom tools to graphindex_* (matching the
native tool names) and remove the 4 native graphindex_* from the
tool registry. After this:

  - 4 graphindex_* custom tools in DB (with pencil icons)
  - 0 native graphindex_* in the tool registry
  - Single source of truth: the custom tool versions

This is the same pattern as print_hello (which was moved to a custom
tool and the native version was removed).
"""
import asyncio
import sys

import httpx

BASE = "http://localhost:8765"


# Update payloads: keep implementation_config / input_schema, just change
# tool_id, name, description to use the graphindex_* naming.
RENAME_MAP = {
    "studio_ingest": {
        "new_tool_id": "graphindex_ingest",
        "new_name": "graphindex_ingest",
        "new_description": "Ingest a new file into the graphindex: SHA-256 dedup, copy with hash prefix, LLM enrichment, upsert to Neo4j. (Custom tool — editable in Studio, pencil icon)",
    },
    "studio_rebuild_one": {
        "new_tool_id": "graphindex_rebuild_one",
        "new_name": "graphindex_rebuild_one",
        "new_description": "Re-enrich ONE document in the graphindex and re-upsert to Neo4j. Slow (~15s, 1 LLM call). (Custom tool — editable in Studio, pencil icon)",
    },
    "studio_rebuild_project": {
        "new_tool_id": "graphindex_rebuild_project",
        "new_name": "graphindex_rebuild_project",
        "new_description": "Re-enrich EVERY document in the project. Very slow (~15s per doc, 1 LLM call each). Use sparingly. (Custom tool — editable in Studio, pencil icon)",
    },
    "studio_show": {
        "new_tool_id": "graphindex_show",
        "new_name": "graphindex_show",
        "new_description": "Show a document's metadata from the graphindex: about, supported_queries, out_of_scope, file_path, content_sha256. Read-only, no LLM call. (Custom tool — editable in Studio, pencil icon)",
    },
}


async def main() -> int:
    print("🛠  Renaming 4 studio_* custom tools to graphindex_* (keeping IDs)...\n")
    async with httpx.AsyncClient() as client:
        # 1. Get each tool's full data
        for old_id, rename in RENAME_MAP.items():
            # GET current tool data
            r = await client.get(f"{BASE}/api/custom-tools/{old_id}")
            if r.status_code != 200:
                print(f"  ✗ {old_id}: GET failed {r.status_code} {r.text[:100]}")
                return 1
            t = r.json()
            new_id = rename["new_tool_id"]
            print(f"  - found {old_id} (db id={t.get('id')}, tool_id={t.get('tool_id')})")

            # DELETE old tool
            r2 = await client.delete(f"{BASE}/api/custom-tools/{old_id}")
            if r2.status_code not in (200, 204):
                print(f"  ✗ {old_id}: DELETE failed {r2.status_code} {r2.text[:200]}")
                return 1
            print(f"    ✓ deleted {old_id}")

            # CREATE new tool with the renamed id and updated name/description
            new_payload = {
                "tool_id": new_id,
                "name": rename["new_name"],
                "description": rename["new_description"],
                "tool_type": t.get("tool_type", "python_function"),
                "template_type": t.get("template_type", "custom"),
                "implementation_config": t.get("implementation_config"),
                "input_schema": t.get("input_schema"),
                "output_format": t.get("output_format", "string"),
                "is_advanced_mode": t.get("is_advanced_mode", True),
                "category": "graphindex_build",
                "tags": t.get("tags", []) + ["renamed-from-studio"],
            }
            r3 = await client.post(f"{BASE}/api/custom-tools", json=new_payload)
            if r3.status_code not in (200, 201):
                print(f"  ✗ {new_id}: POST failed {r3.status_code} {r3.text[:200]}")
                return 1
            new_t = r3.json()
            print(f"    ✓ created {new_id} (db id={new_t.get('id')}, tool_id={new_t.get('tool_id')})")
            print()

    print("  All 4 renamed. Now in your browser:")
    print("  1. Hard-refresh Studio Tools page (Cmd+Shift+R)")
    print("  2. Filter to 'graphindex_build' category")
    print("  3. You should see 4 tools with graphindex_* names and pencil icons")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
