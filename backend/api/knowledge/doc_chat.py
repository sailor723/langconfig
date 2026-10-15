"""
Simplified Document Chat — folder-based context, no RAG, no Neo4j.

Takes a selected folder path, reads all supported files from that folder
on disk, builds a system prompt with all file contents as inline context,
and streams the LLM response directly.

Flow:
  1. User selects a knowledge base and a folder in it (e.g. "industry/player/sub_category")
  2. Frontend sends POST /api/doc-chat with {knowledge, folder_path, messages, model}
  3. Backend scans that folder through `documents_dir(knowledge)` — the same resolver the upload
     endpoints write through, so the two ends cannot address different copies
  4. Builds system prompt with all document text as context
  5. Streams LLM response with citations [Source: filename.ext]
  6. Conversation history stored in-memory by conversation_id

A knowledge base is named by its folder name, exactly as it is on disk. There is no project id:
knowledge is not scoped to a project, it is a folder with a catalog beside it.

This replaces the previous graphindex_chat / Neo4j-based approach.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.settings import runtime_get
from services.agent_utils import resolve_model
from services.kb_discovery import documents_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/doc-chat", tags=["doc-chat"])

# What counts as a document is defined ONCE, in the ingest core, and imported here. Doc chat kept
# its own copy of these sets, which is how the read side and the write side could drift apart —
# `ingest-folder` ended up with a text-only list that silently skipped PDFs while chat read them.
from services.kv_ingest import PDF_EXTENSIONS, TEXT_EXTENSIONS  # noqa: E402

# FileStorage.save_file prefixes on-disk filenames with an 8-hex uuid to
# avoid collisions (e.g. "b37a8720_industry_analysis_report.md"). Strip it
# when naming documents in the prompt so citations show the clean name.
_HASH_PREFIX_RE = re.compile(r"^[0-9a-f]{8}_")


def _display_doc_name(filename: str) -> str:
    """Human-friendly document name — removes the 8-hex uuid collision prefix."""
    return _HASH_PREFIX_RE.sub("", filename)

# Max chars to feed into LLM context
MAX_CONTEXT_CHARS = 500_000  # 500K chars — fits comfortably in most model context windows
MAX_FILES = 100

# In-memory conversation store (simple dict, not persisted)
conversation_memory: Dict[str, List[Dict[str, Any]]] = {}


# ── Pydantic models ──────────────────────────────────────────────────────

class DocChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class DocChatRequest(BaseModel):
    messages: List[DocChatMessage] = Field(
        ..., description="Chat messages (last one is the current user query)"
    )
    folder_path: str = Field(
        "", description="Folder inside the knowledge base, e.g. 'electric_vehicle_industry/tesla'"
    )
    knowledge: str = Field(
        ..., min_length=1,
        description="Knowledge base folder name, as it appears under the knowledge root",
    )
    model: Optional[str] = Field(
        None, description="Model name (e.g. 'deepseek-chat', 'gpt-4o'). Defaults to system default."
    )
    conversation_id: Optional[str] = Field(
        None, description="Existing conversation id for multi-turn. Omit to start new."
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(
        None, ge=1, le=1_000_000,
        description="Maximum output tokens. Defaults to the model's own default.",
    )
    max_context_chars: int = Field(
        MAX_CONTEXT_CHARS, ge=10_000, le=1_000_000,
        description="Max characters of document text to include in context",
    )


# ── File scanning ────────────────────────────────────────────────────────

def _extract_text(file_path: Path, max_chars: int = 100_000) -> Optional[str]:
    """Extract text content from a supported file type."""
    suffix = file_path.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to read text file {file_path}: {e}")
            return None

    if suffix in PDF_EXTENSIONS:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(file_path))
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text[:max_chars]
        except ImportError:
            logger.warning("PyMuPDF (fitz) not available, skipping PDF")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract PDF text from {file_path}: {e}")
            return None

    return None


def resolve_kb_folder(knowledge: str, folder_path: str = "") -> Optional[Path]:
    """The directory a knowledge base — or a folder inside it — actually is.

    Both ends of the pipeline resolve through here, which is the point: uploads are written under
    `documents_dir(knowledge)` and doc chat reads under it, so "upload a document, then ask about
    it" is one directory rather than two path expressions that have to be kept in agreement. They
    previously were two, and disagreed.

    Returns None when the result would leave the knowledge base: `folder_path` comes from the
    client, and `..` in it must not read the rest of the disk.
    """
    root = documents_dir(knowledge).resolve()
    target = (root / folder_path).resolve() if folder_path else root
    try:
        target.relative_to(root)
    except ValueError:
        logger.warning(f"Refusing folder_path outside the knowledge base: {folder_path!r}")
        return None
    return target


def _scan_folder_sync(knowledge: str, folder_path: str = "",
                      max_files: int = MAX_FILES) -> List[Dict[str, Any]]:
    """Scan a folder for supported files and return their text content.

    Args:
        knowledge: Knowledge base folder name, resolved by `documents_dir()`.
        folder_path: Folder inside it, e.g. "industry/player".
        max_files: Max files to scan (sorted by size desc, capped by MAX_CONTEXT_CHARS).

    Returns:
        List of {name, path, content, size} dicts.
    """
    base = resolve_kb_folder(knowledge, folder_path)
    if base is None or not base.is_dir():
        logger.warning(f"Folder not found: {knowledge}/{folder_path}")
        return []

    files: List[Dict[str, Any]] = []
    for fp in sorted(base.rglob("*")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        suffix = fp.suffix.lower()
        if suffix not in TEXT_EXTENSIONS and suffix not in PDF_EXTENSIONS:
            continue

        try:
            text = _extract_text(fp)
            if text is None:
                continue
            files.append({
                "name": fp.name,
                "display_name": _display_doc_name(fp.name),
                "path": str(fp.relative_to(base)),
                "content": text,
                "size": len(text),
            })
        except Exception as e:
            logger.warning(f"Error scanning {fp}: {e}")

    # Sort by size descending (most informative first)
    files.sort(key=lambda f: f["size"], reverse=True)

    result = []
    total_chars = 0

    for f in files[:max_files]:
        if total_chars + f["size"] > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 2000:
                f["content"] = f["content"][:remaining] + "\n\n...[truncated]"
                result.append(f)
            break
        result.append(f)
        total_chars += f["size"]

    return result


# ── LLM helpers ──────────────────────────────────────────────────────────

async def _resolve_llm(request: DocChatRequest):
    """Create the chat model for a doc-chat request.

    Routes through the app's shared model resolution (services.agent_utils)
    so Doc Chat honors the same LLM settings as everywhere else: DB-stored
    API keys, local Ollama models served with the 128K context window, etc.
    """
    model_name = request.model or runtime_get("models", "default_model") or "deepseek-chat"
    return await resolve_model(
        model_name,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        config={"streaming": True},
    )


# ── Streaming endpoint ───────────────────────────────────────────────────

@router.post("")
async def doc_chat(request: DocChatRequest):
    """SSE-streamed chat with documents from a selected folder as context.

    Scans the folder for supported files, builds a system prompt with all
    document contents inline, streams the LLM response with
    `[Source: filename.ext]` citations, and stores conversation history
    in-memory keyed by conversation_id.
    """
    try:
        conversation_id = request.conversation_id or f"doc_conv_{int(time.time() * 1000)}"

        # Scan folder for documents
        md_files = await asyncio.to_thread(
            _scan_folder_sync,
            request.knowledge,
            request.folder_path,
            MAX_FILES,
        )

        if not md_files:
            no_files_msg = (
                f"No supported documents found in '{request.knowledge}"
                f"{'/' + request.folder_path if request.folder_path else ''}'.\n\n"
                f"Please upload documents to that folder first via the Knowledge panel."
            )
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'token', 'content': no_files_msg})}\n\n"
                      f"data: {json.dumps({'type': 'done', 'usage': {'input_tokens': 0, 'output_tokens': 0, 'latency_s': 0}})}\n\n"]),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Conversation-ID": conversation_id,
                },
            )

        # Build document context
        doc_parts = []
        total_chars = 0
        max_context = min(request.max_context_chars, MAX_CONTEXT_CHARS)
        for f in md_files:
            # Use the cleaned name so citations show the original document
            # name instead of the uuid-prefixed on-disk filename.
            header = f"\n--- File: {f.get('display_name', f['path'])} ---\n"
            entry = header + f["content"]
            if total_chars + len(entry) > max_context:
                remaining = max_context - total_chars
                if remaining > 2000:
                    entry = header + f["content"][:remaining] + "\n\n...[truncated]"
                    doc_parts.append(entry)
                    total_chars += len(entry)
                break
            doc_parts.append(entry)
            total_chars += len(entry)

        doc_context = "\n".join(doc_parts)
        file_count = len(md_files)

        system_prompt = (
            f"You are a document-grounded Q&A assistant. Answer the user's question "
            f"using ONLY the documents provided below.\n\n"
            f"## Selected Folder: {request.folder_path}\n"
            f"## Number of Documents Loaded: {file_count}\n"
            f"## Total Characters of Context: {total_chars}\n\n"
            f"## DOCUMENTS (this is your ONLY source of truth):\n"
            f"{doc_context}\n\n"
            f"## RULES:\n"
            f"1. Begin your reply with exactly: `**[Documents loaded: {file_count} files, {total_chars} chars]**`\n"
            f"2. Answer ONLY using facts, numbers, and statements from the documents above.\n"
            f"3. For every claim, cite the source file: `[Source: filename.ext]`\n"
            f"4. If the documents do not contain the answer, respond with: "
            f"\"The loaded documents do not contain information about [topic].\"\n"
            f"5. NEVER use your own knowledge, NEVER make up information."
        )

        # Build messages for LLM
        messages_for_llm = [("system", system_prompt)]

        # Restore conversation history if available
        if conversation_id in conversation_memory and conversation_memory[conversation_id]:
            for msg in conversation_memory[conversation_id]:
                messages_for_llm.append((msg["role"], msg["content"]))
            # Only append the last user message from request if not already in history
            if request.messages:
                last_msg = request.messages[-1]
                if not messages_for_llm or messages_for_llm[-1] != (last_msg.role, last_msg.content):
                    messages_for_llm.append((last_msg.role, last_msg.content))
        else:
            for msg in request.messages:
                messages_for_llm.append((msg.role, msg.content))

        user_message = request.messages[-1].content if request.messages else ""
        assistant_response = ""
        llm = await _resolve_llm(request)

        async def event_generator() -> AsyncGenerator[str, None]:
            nonlocal assistant_response

            # Emit start event with conversation_id
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id, 'folder_path': request.folder_path, 'file_count': file_count, 'total_chars': total_chars})}\n\n"

            t0 = time.time()

            # Stream the LLM response
            try:
                async for chunk in llm.astream(messages_for_llm):
                    if hasattr(chunk, "content") and chunk.content:
                        assistant_response += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
            except Exception as e:
                logger.exception(f"LLM streaming error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

            elapsed = time.time() - t0

            # Store in conversation memory
            if conversation_id not in conversation_memory:
                conversation_memory[conversation_id] = []
            conversation_memory[conversation_id].append({
                "role": "user", "content": user_message, "timestamp": time.time(),
            })
            conversation_memory[conversation_id].append({
                "role": "assistant", "content": assistant_response, "timestamp": time.time(),
            })

            # Emit done event with usage info
            yield f"data: {json.dumps({'type': 'done', 'usage': {'input_tokens': 0, 'output_tokens': 0, 'latency_s': elapsed, 'file_count': file_count, 'total_chars': total_chars}})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Conversation-ID": conversation_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"doc_chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Folder listing endpoint ─────────────────────────────────────────────

@router.get("/folders")
async def list_doc_chat_folders(knowledge: str):
    """List every folder inside a knowledge base that holds supported files.

    Used by the frontend scope selector. `knowledge` is the knowledge base's folder name, the same
    handle the upload endpoints take, and the scan goes through `documents_dir()` — so this lists
    the folders documents were actually uploaded into, not a parallel copy of them.

    Scans the filesystem so it works even when documents have no hierarchy metadata in the catalog.
    """
    base = resolve_kb_folder(knowledge)
    if base is None or not base.is_dir():
        return {"folders": [], "total": 0, "knowledge": knowledge}

    folders: set[str] = set()
    SUPPORTED = TEXT_EXTENSIONS | PDF_EXTENSIONS

    # Walk all subdirectories looking for supported files
    for fp in sorted(base.rglob("*")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        if fp.suffix.lower() not in SUPPORTED:
            continue
        rel = fp.relative_to(base)
        parent = str(rel.parent)
        # Skip the root: files sitting directly in the knowledge base are the "" scope, which the
        # caller already has and does not need listed.
        if parent != ".":
            folders.add(parent)

    sorted_folders = sorted(folders)
    return {"folders": sorted_folders, "total": len(sorted_folders), "knowledge": knowledge}


# ── Source-code endpoint ────────────────────────────────────────────────

@router.get("/code")
async def get_doc_chat_code():
    """Return the source of this doc-chat module.

    Powers the "View code" action in the Doc Chat panel so users can inspect
    exactly how the folder-scoped Q&A pipeline is implemented.
    """
    try:
        code = Path(__file__).read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read source: {e}")
    return {"file": "doc_chat.py", "code": code}


# ── History endpoints ────────────────────────────────────────────────────

@router.get("/history/{conversation_id}")
async def get_doc_chat_history(conversation_id: str):
    """Get conversation history for a doc chat session."""
    if conversation_id not in conversation_memory:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conversation_id,
        "messages": conversation_memory[conversation_id],
        "message_count": len(conversation_memory[conversation_id]),
    }


@router.get("/conversations")
async def list_doc_chat_conversations():
    """List all doc chat conversations."""
    doc_convs = {
        cid: msgs for cid, msgs in conversation_memory.items()
        if cid.startswith("doc_conv_")
    }
    return {
        "conversations": [
            {
                "conversation_id": cid,
                "message_count": len(msgs),
                "last_updated": msgs[-1]["timestamp"] if msgs else None,
            }
            for cid, msgs in doc_convs.items()
        ],
        "total": len(doc_convs),
    }
