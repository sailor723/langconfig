"""
Create chat_pdf custom tools via API.
Run: uv run python create_pdf_tools.py
"""
import httpx
import json
import asyncio

BASE = "http://localhost:8765"

LOAD_PDF_CODE = '''import os
import re
from pypdf import PdfReader

def load_pdf_for_chat(pdf_path: str, session_id: str) -> str:
    """Load a PDF file, extract all text, and store it in KV store for this session."""
    # 1. Extract text from PDF
    if not os.path.exists(pdf_path):
        return f"❌ PDF file not found: {pdf_path}"
    try:
        reader = PdfReader(pdf_path)
        num_pages = len(reader.pages)
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            t = page.extract_text()
            if t and t.strip():
                pages.append(f"--- Page {i}/{num_pages} ---\\n{t.strip()}")
        if not pages:
            return f"⚠️ No extractable text found in PDF ({num_pages} pages)."
        full_text = "\\n\\n".join(pages)
    except Exception as e:
        return f"❌ Failed to extract PDF text: {e}"

    # 2. Store in KV store (file-based)
    kv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".chat_pdf_kv")
    os.makedirs(kv_dir, exist_ok=True)
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
    with open(os.path.join(kv_dir, f"{safe_id}.txt"), "w", encoding="utf-8") as f:
        f.write(full_text)

    # 3. Return summary
    return (
        f"✅ PDF loaded successfully!\\n"
        f"   Pages: {num_pages}\n"
        f"   Chars: {len(full_text):,}\n"
        f"   Words: {len(full_text.split()):,}\n"
        f"\\n📄 Preview: {full_text[:200]}...\\n\\n"
        f"Call get_pdf_context('{session_id}') to retrieve the full text."
    )
'''

GET_PDF_CODE = '''import os
import re

def get_pdf_context(session_id: str, max_chars: int = 8000) -> str:
    """Retrieve the stored PDF text for this session."""
    kv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".chat_pdf_kv")
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
    file_path = os.path.join(kv_dir, f"{safe_id}.txt")

    if not os.path.exists(file_path):
        return "❌ No PDF found for this session. Call load_pdf_for_chat() first."

    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    if len(text) > max_chars:
        text = text[:max_chars] + "\\n\\n[...truncated at " + str(max_chars) + " chars]"

    return text
'''


async def create_tool(tool_id: str, name: str, desc: str, code: str, fn_name: str, args_schema: dict, input_schema: dict):
    async with httpx.AsyncClient() as client:
        payload = {
            "tool_id": tool_id,
            "name": name,
            "description": desc,
            "tool_type": "python_function",
            "implementation_config": {
                "function_name": fn_name,
                "code": code,
                "args_schema": args_schema
            },
            "input_schema": {
                "type": "object",
                "properties": {k: {"type": v["type"], "description": v["description"]} for k, v in input_schema.items()},
                "required": list(input_schema.keys())
            },
            "output_format": "string",
            "is_advanced_mode": True,
            "category": "pdf_chat",
            "tags": ["pdf", "chat", "kv-store"]
        }
        resp = await client.post(f"{BASE}/api/custom-tools", json=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            print(f"  ✓ Created '{tool_id}' (id={data.get('id', '?')})")
            return data
        else:
            print(f"  ✗ Failed to create '{tool_id}': {resp.status_code} {resp.text[:200]}")
            return None


async def main():
    print("Creating PDF chat tools...\n")

    # Tool 1: load_pdf
    t1 = await create_tool(
        tool_id="load_pdf",
        name="load_pdf_for_chat",
        desc="Load a PDF file, extract all text, and store it in KV store for chat. Call this first when a user uploads a PDF.",
        code=LOAD_PDF_CODE,
        fn_name="load_pdf_for_chat",
        args_schema={
            "pdf_path": {"type": "string", "description": "Path to the PDF file"},
            "session_id": {"type": "string", "description": "Chat session identifier (e.g., the current session_id)"}
        },
        input_schema={
            "pdf_path": {"type": "string", "description": "Path to the PDF file"},
            "session_id": {"type": "string", "description": "Chat session identifier"}
        }
    )

    # Tool 2: get_pdf
    t2 = await create_tool(
        tool_id="get_pdf",
        name="get_pdf_context",
        desc="Retrieve the full PDF text stored for a session. Call this when the user asks a question about the PDF they uploaded.",
        code=GET_PDF_CODE,
        fn_name="get_pdf_context",
        args_schema={
            "session_id": {"type": "string", "description": "Chat session identifier"},
            "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000)"}
        },
        input_schema={
            "session_id": {"type": "string", "description": "Chat session identifier"},
            "max_chars": {"type": "integer", "description": "Maximum characters to return"}
        }
    )

    print(f"\n--- Summary ---")
    if t1:
        print(f"  ✓ load_pdf: ready")
    if t2:
        print(f"  ✓ get_pdf: ready")
    if t1 and t2:
        print(f"\n✅ Both tools created! Go to Agent Builder → create/edit an agent →")
        print(f"   add 'load_pdf' and 'get_pdf' to custom_tools list → Save → Chat")
        print(f"   Upload a PDF in chat, then ask questions about it.")


if __name__ == "__main__":
    asyncio.run(main())
