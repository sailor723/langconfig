"""
Chat with PDF — simple KV store approach for DeepSeek Chat.

How it works:
1. User uploads a PDF via the chat UI
2. Agent calls load_pdf_for_chat() → extracts all text → stores in KV store
3. When user asks about the PDF, agent calls get_pdf_context() → gets full text → answers

No vector DB, no embeddings. Just full text extraction + LLM reasoning.

KV Store: Uses a simple JSON file (no Redis needed). Stored at:
  {workspace_dir}/chat_pdf_kv/{session_id}.txt
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# PDF Text Extraction
# ---------------------------------------------------------------------------

def _extract_pdf_text(file_path: str) -> str:
    """
    Extract all text from a PDF file using pypdf.

    Args:
        file_path: Absolute or relative path to the PDF file

    Returns:
        Extracted text as a single string, pages separated by page breaks.
    """
    from pypdf import PdfReader

    if not os.path.exists(file_path):
        return f"❌ PDF file not found: {file_path}"

    try:
        reader = PdfReader(file_path)
        num_pages = len(reader.pages)

        pages_text = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(f"--- Page {i}/{num_pages} ---\n{text.strip()}")

        if not pages_text:
            return f"⚠️ No extractable text found in PDF ({num_pages} pages). It may be a scanned document (image-only PDF)."

        full_text = "\n\n".join(pages_text)
        return full_text

    except Exception as e:
        return f"❌ Failed to extract PDF text: {e}"


# ---------------------------------------------------------------------------
# KV Store — file-based, no external dependencies
# ---------------------------------------------------------------------------

def _get_kv_dir() -> str:
    """Get or create the KV store directory."""
    # Use a well-known location: alongside the app data
    kv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".chat_pdf_kv")
    os.makedirs(kv_dir, exist_ok=True)
    return kv_dir


def _store_text(session_id: str, text: str) -> None:
    """
    Store PDF text in KV store.

    Args:
        session_id: Unique session identifier (use chat session_id)
        text: Full extracted PDF text
    """
    kv_dir = _get_kv_dir()
    # Sanitize session_id for filename safety
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
    file_path = os.path.join(kv_dir, f"{safe_id}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)


def _retrieve_text(session_id: str) -> Optional[str]:
    """
    Retrieve PDF text from KV store.

    Args:
        session_id: Session identifier used when storing

    Returns:
        Stored PDF text, or None if not found.
    """
    kv_dir = _get_kv_dir()
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
    file_path = os.path.join(kv_dir, f"{safe_id}.txt")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return None


# ---------------------------------------------------------------------------
# Tools — These are the functions the agent calls
# ---------------------------------------------------------------------------

def load_pdf_for_chat(pdf_path: str, session_id: str) -> str:
    """
    Load a PDF file, extract all text, and store it in the KV store for this session.

    Call this when the user uploads a PDF and wants to chat about its contents.
    The PDF text is stored by session_id — subsequent calls to get_pdf_context()
    with the same session_id will return it.

    Args:
        pdf_path: Path to the PDF file (use the workspace path from file uploads)
        session_id: Chat session identifier (from the current conversation context)

    Returns:
        Summary of what was loaded (page count, char count, preview).
    """
    # 1. Extract text
    full_text = _extract_pdf_text(pdf_path)

    if full_text.startswith("❌") or full_text.startswith("⚠️"):
        return full_text  # Return error as-is

    # 2. Store in KV
    _store_text(session_id, full_text)

    # 3. Return summary
    char_count = len(full_text)
    word_count = len(full_text.split())
    page_count = full_text.count("--- Page ")
    preview = full_text[:300]

    return (
        f"✅ PDF loaded successfully for session '{session_id}'!\n"
        f"   • Pages: {page_count}\n"
        f"   • Characters: {char_count:,}\n"
        f"   • Words: {word_count:,}\n"
        f"\n"
        f"📄 Preview:\n{preview}\n...\n\n"
        f"You can now answer questions about this document. "
        f"Call get_pdf_context() with session_id='{session_id}' to retrieve the full text."
    )


def get_pdf_context(session_id: str, max_chars: int = 8000) -> str:
    """
    Retrieve the full PDF text stored for this session.

    Call this when the user asks a question about the PDF they uploaded.
    Returns the entire document text (up to max_chars characters) so the LLM
    can reference it when answering.

    Args:
        session_id: Chat session identifier (same as used in load_pdf_for_chat)
        max_chars: Maximum characters to return (DeepSeek context limit ~8K is fine)

    Returns:
        The PDF text, or a message if no PDF has been loaded for this session.
    """
    text = _retrieve_text(session_id)

    if text is None:
        return (
            f"No PDF content found for session '{session_id}'. "
            f"Please call load_pdf_for_chat() first with the PDF file path."
        )

    if len(text) > max_chars:
        text = text[:max_chars]
        text += f"\n\n[...truncated at {max_chars} characters. The document is longer.]"

    return text
