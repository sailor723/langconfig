"""
Register print_hello as a custom tool (so it gets a pencil icon in the UI).

Pattern: same as create_pdf_tools.py — POST to /api/custom-tools with
tool_type="python_function" and inline Python code.

After this:
  - print_hello appears in the Tools page with a pencil icon
  - Click pencil → modal opens showing the Python code
  - Edit + save → updates the DB record
"""
import asyncio
import json
import sys

import httpx

BASE = "http://localhost:8765"

PRINT_HELLO_CODE = '''def print_hello(message: str = "hello") -> str:
    """Demo tool: returns a greeting.

    Args:
        message: The greeting to return (default: "hello").

    Returns:
        A friendly greeting string.
    """
    return f"👋 {message} from print_hello tool!"
'''


async def main() -> int:
    payload = {
        "tool_id": "print_hello",
        "name": "Print Hello (Custom)",
        "description": "Demo tool: returns a greeting. Used to test the Studio tool-node flow. (Registered as custom tool to get pencil icon)",
        "tool_type": "python_function",
        "implementation_config": {
            "function_name": "print_hello",
            "code": PRINT_HELLO_CODE,
            "args_schema": {
                "message": {
                    "type": "string",
                    "description": "The greeting to return (default: 'hello')",
                    "default": "hello",
                },
            },
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The greeting to return (default: 'hello')",
                    "default": "hello",
                },
            },
            "required": [],
        },
        "output_format": "string",
        "is_advanced_mode": True,
        "category": "demo",
        "tags": ["demo", "hello", "studio-test"],
    }

    print(f"🛠  Registering custom tool: {payload['tool_id']}")
    print(f"   tool_type: {payload['tool_type']}")
    print(f"   function:  {payload['implementation_config']['function_name']}")
    print()

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE}/api/custom-tools", json=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            print(f"  ✓ Created (id={data.get('id', '?')}, tool_id={data.get('tool_id', '?')})")
            print()
            print("  Now in your browser:")
            print("  1. Hard refresh the Tools page (Cmd+Shift+R / Ctrl+Shift+R)")
            print("  2. The 'Print Hello (Custom)' card should have a pencil icon ✏️")
            print("  3. Click the pencil → modal opens with the Python code")
            print("  4. Edit + Save → updates the DB record")
            return 0
        else:
            print(f"  ✗ Failed: {resp.status_code} {resp.text[:300]}")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
