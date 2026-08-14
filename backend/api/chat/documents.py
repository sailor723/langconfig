# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Chat session document endpoints (upload / list / download / delete).

Split out of api/chat/routes.py. Registered on a prefix-less router included
by the parent (routes.py) under the "/api/chat" prefix.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from db.database import get_db
from models.core import DocumentType, IndexingStatus
from models.deep_agent import ChatSession, DeepAgentTemplate, SessionDocument
from services.document_type import resolve_document_type

from .schemas import SessionDocumentResponse

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])


def _resolve_agent_workspace(session, db, ws_mgr):
    """Resolve the agent workspace root from the DB.

    Priority: the agent's user-defined ``workspace_path`` (persisted in
    deep_agent_templates) → the default ``outputs/agents/agent_{id}/``
    convention.
    """
    if session.agent_id:
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == session.agent_id
        ).first()
        if agent is not None:
            return ws_mgr.resolve_agent_workspace(agent)
    return ws_mgr.get_agent_workspace(session.agent_id)


async def index_session_document_background(document_id: int, agent_id: int):
    """
    Background task to index a session document with embeddings.
    Similar to index_document_background but session-scoped.
    """
    from db.database import SessionLocal
    from services.context_document_indexer import context_document_indexer

    db = SessionLocal()
    try:
        doc = db.query(SessionDocument).filter(SessionDocument.id == document_id).first()
        if not doc:
            logger.error(f"Session document {document_id} not found for indexing")
            return

        if not doc.file_path:
            logger.error(f"Session document {document_id} has no file_path")
            doc.indexing_status = IndexingStatus.FAILED
            db.commit()
            return

        # Update status to indexing
        doc.indexing_status = IndexingStatus.INDEXING
        file_path = doc.file_path
        session_id = doc.session_id
        db.commit()
        db.close()

        # Get agent and project info for metadata
        db = SessionLocal()
        session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not session:
            logger.error(f"Chat session {session_id} not found")
            return

        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if not agent:
            logger.error(f"Agent {agent_id} not found")
            return

        project_id = agent.project_id if hasattr(agent, 'project_id') else None
        db.close()

        # Index the document with session-specific metadata
        result = await context_document_indexer.index_document(
            document_id=document_id,
            file_path=file_path,
        )

        # Update status to ready
        db = SessionLocal()
        doc = db.query(SessionDocument).filter(SessionDocument.id == document_id).first()
        if doc:
            doc.indexing_status = IndexingStatus.READY
            doc.indexed_at = datetime.utcnow()
            doc.indexed_chunks_count = result.get("embeddings_stored", 0)
            db.commit()
        db.close()

        logger.info(f"Session document {document_id} indexed successfully")

    except Exception as e:
        logger.error(f"Failed to index session document {document_id}: {e}", exc_info=True)
        # Create fresh session for error handling
        try:
            db.close()
        except:
            pass

        db = SessionLocal()
        try:
            doc = db.query(SessionDocument).filter(SessionDocument.id == document_id).first()
            if doc:
                doc.indexing_status = IndexingStatus.FAILED
                db.commit()
        finally:
            db.close()


def _extract_file_text(content: bytes, filename: str, max_chars: int = 1_000_000) -> str:
    """Extract text from various file types (PDF, DOCX, PPTX, MD, TXT, etc.)."""
    import io
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ""

    try:
        # --- Plain text files ---
        if ext in ('txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'jsx',
                    'yaml', 'yml', 'xml', 'html', 'htm', 'css', 'scss',
                    'sql', 'sh', 'bash', 'rb', 'go', 'rs', 'java',
                    'c', 'cpp', 'h', 'hpp', 'rtf', 'tex', 'toml',
                    'ini', 'cfg', 'conf', 'log'):
            text = content.decode('utf-8', errors='replace')
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[...truncated]"
            return text

        # --- CSV ---
        if ext == 'csv':
            import csv
            text = content.decode('utf-8', errors='replace')
            reader = csv.reader(io.StringIO(text))
            rows = []
            for i, row in enumerate(reader):
                rows.append(' | '.join(row))
                if i >= 2000:  # limit rows
                    rows.append('... (truncated)')
                    break
            result = '\n'.join(rows)
            if len(result) > max_chars:
                result = result[:max_chars] + "\n\n[...truncated]"
            return result

        # --- PDF ---
        if ext == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for i, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                if text and text.strip():
                    pages.append(f"--- Page {i}/{len(reader.pages)} ---\n{text.strip()}")
            if pages:
                full_text = "\n\n".join(pages)
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars] + "\n\n[...truncated]"
                return full_text
            return "[Empty PDF]"

        # --- DOCX ---
        if ext == 'docx':
            from docx import Document
            doc = Document(io.BytesIO(content))
            paragraphs = []
            for p in doc.paragraphs:
                if p.text.strip():
                    paragraphs.append(p.text.strip())
            text = '\n'.join(paragraphs)
            # Also extract tables
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    text += '\n' + ' | '.join(cells)
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[...truncated]"
            return text if text.strip() else "[Empty DOCX]"

        # --- PPTX ---
        if ext == 'pptx':
            from pptx import Presentation
            prs = Presentation(io.BytesIO(content))
            slides_text = []
            for i, slide in enumerate(prs.slides, start=1):
                slide_lines = [f"--- Slide {i}/{len(prs.slides)} ---"]
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            if para.text.strip():
                                slide_lines.append(para.text.strip())
                    if shape.has_table:
                        for row in shape.table.rows:
                            cells = [cell.text.strip() for cell in row.cells]
                            slide_lines.append(' | '.join(cells))
                slides_text.append('\n'.join(slide_lines))
            text = '\n\n'.join(slides_text)
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[...truncated]"
            return text if text.strip() else "[Empty PPTX]"

        return f"[Unsupported file type: .{ext}]"

    except Exception as e:
        logger.warning(f"Failed to extract text from {filename}: {e}")
        return f"[Text extraction failed: {e}]"


async def _index_to_graphindex_for_chat(
    project_id: int,
    file_content: bytes,
    filename: str,
    file_path: str,
    file_size: int,
    mime_type: str,
    file_text: str,
):
    """
    Background: Index a chat-uploaded file into GraphIndex (Neo4j).

    Deduplicates by SHA256 content hash first, then filename as fallback.
    If the exact same content already exists in the project, reuses it.
    Otherwise creates a new ContextDocument and syncs to Neo4j.
    """
    import logging
    import hashlib
    logger = logging.getLogger(__name__)
    try:
        from db.database import SessionLocal
        from models.core import ContextDocument, DocumentType, IndexingStatus
        from services.file_storage import file_storage

        logger.info(
            f"[phase9] chat upload starting: filename={filename!r}, "
            f"project_id={project_id}, file_size={file_size} bytes"
        )

        content_hash = hashlib.sha256(file_content).hexdigest()

        db = SessionLocal()
        try:
            # Dedup: check by content hash first (precise)
            existing = db.query(ContextDocument).filter(
                ContextDocument.project_id == project_id,
                ContextDocument.content_hash == content_hash,
                ContextDocument.indexing_status != IndexingStatus.FAILED,
            ).first()

            # Fallback: check by filename (user may re-upload same name, different content)
            if not existing:
                existing = db.query(ContextDocument).filter(
                    ContextDocument.project_id == project_id,
                    ContextDocument.filename == filename,
                    ContextDocument.indexing_status != IndexingStatus.FAILED,
                ).first()

            if existing:
                # Update hash if it was missing (backfill for old docs)
                if not existing.content_hash:
                    existing.content_hash = content_hash

                logger.info(f"Dedup ({'hash' if existing.content_hash == content_hash else 'filename'}): "
                           f"reusing ContextDocument {existing.id} for {filename}")
                # Re-index if not already indexing
                if existing.indexing_status != IndexingStatus.INDEXING:
                    existing.indexing_status = IndexingStatus.NOT_INDEXED
                    db.commit()
                    from api.knowledge.rag import index_document_background
                    await index_document_background(existing.id)
                    logger.info(f"Re-indexed existing doc {existing.id}: {filename}")
                else:
                    db.commit()
                return

            # Save file to project storage
            project_file_path = file_storage.save_file(project_id, filename, file_content)

            doc = ContextDocument(
                project_id=project_id,
                filename=filename,
                original_filename=filename,
                file_path=project_file_path,
                file_size=file_size,
                mime_type=mime_type,
                content_hash=content_hash,
                document_type=DocumentType.PDF if filename.lower().endswith('.pdf') else DocumentType.TEXT,
                indexing_status=IndexingStatus.INDEXING,
                description=f"Uploaded via chat: {filename}",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # Trigger full indexing (GraphIndex + vector).
            # The knowledge-panel path inside this will call
            # _phase9_get_or_generate_enrichment and populate
            # about / supports / out_of_scope / few_shot on the Neo4j node,
            # so chat-uploaded docs become routable.
            from api.knowledge.rag import index_document_background
            await index_document_background(doc.id)

            logger.info(
                f"[phase9] chat upload indexed: doc_id={doc.id}, "
                f"filename={filename!r} (now routable in Neo4j)"
            )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to index chat-uploaded file to GraphIndex: {e}")


@router.post("/{session_id}/upload", response_model=SessionDocumentResponse)
async def upload_file_to_session(
    session_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    project_id: Optional[int] = Query(None, description="Project ID for GraphIndex indexing"),
    db: Session = Depends(get_db)
):
    """
    Upload a single file to a chat session for agent context.
    """
    result = await _process_single_chat_upload(session_id, file, background_tasks, project_id, db)
    return result


@router.post("/{session_id}/upload-multiple", response_model=List[SessionDocumentResponse])
async def upload_multiple_files_to_session(
    session_id: str,
    files: List[UploadFile] = File(..., description="Multiple files to upload"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    project_id: Optional[int] = Query(None, description="Project ID for GraphIndex indexing"),
    db: Session = Depends(get_db)
):
    """
    Upload multiple files to a chat session at once. Each file is extracted,
    injected as a separate context message, and optionally indexed to GraphIndex.
    """
    results = []
    for file in files:
        try:
            result = await _process_single_chat_upload(session_id, file, background_tasks, project_id, db)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to upload {file.filename} in batch: {e}")
            # Continue with other files
    return results


async def _process_single_chat_upload(
    session_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    project_id: Optional[int],
    db: Session,
) -> SessionDocumentResponse:
    """Process a single file upload for chat: save, extract, inject as context message."""
    from services.file_storage import file_storage

    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    content = await file.read()
    file_size = len(content)

    # Save file to session-scoped storage
    file_path = file_storage.save_file(f"chat_sessions/{session_id}", file.filename, content)

    # Copy to sandbox workspace for agent access. Per-agent workspace root
    # keeps uploads + generated files under one directory (the agent's
    # user-defined workspace_path when set, else outputs/agents/agent_{id}/),
    # so the Files panel lists everything from a single root.
    sandbox_exts = ('.csv', '.pdf', '.docx', '.pptx', '.md', '.txt', '.json', '.py', '.js', '.ts', '.tsx', '.jsx')
    safe_name = Path(file.filename).name  # basename only — block path-traversal writes
    if file.filename.lower().endswith(sandbox_exts):
        try:
            from services.workspace_manager import get_workspace_manager
            ws_mgr = get_workspace_manager()
            sandbox_path = _resolve_agent_workspace(session, db, ws_mgr) / safe_name
            sandbox_path.write_bytes(content)
            logger.info(f"File copied to agent workspace: {sandbox_path}")
            # If uploaded CSV, auto-generate companion .skill.md from the data.
            if file.filename.lower().endswith('.csv'):
                try:
                    from services.data_skill_generator import generate_data_skill
                    _skill_path = generate_data_skill(
                        str(sandbox_path), str(sandbox_path.parent)
                    )
                    if _skill_path:
                        logger.info(f"Generated companion .skill.md: {_skill_path}")
                except Exception as _gen_e:
                    logger.warning(f"Failed to generate data skill: {_gen_e}")
        except Exception as e:
            logger.warning(f"Failed to copy {file.filename} to sandbox: {e}")

    # Detect document type
    file_ext = file.filename.split('.')[-1].lower()
    document_type = resolve_document_type(file.filename)

    # Create SessionDocument record
    doc = SessionDocument(
        session_id=session_id,
        filename=file.filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        document_type=document_type,
        indexing_status=IndexingStatus.NOT_INDEXED,
        message_index=len(session.messages) if session.messages else 0
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Extract text and inject as session message
    extractable_exts = {'.pdf', '.md', '.txt', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.csv',
                        '.docx', '.pptx', '.yaml', '.yml', '.xml', '.html', '.htm', '.css', '.scss',
                        '.sql', '.sh', '.bash', '.rb', '.go', '.rs', '.java', '.c', '.cpp', '.h', '.hpp',
                        '.rtf', '.tex', '.toml', '.ini', '.cfg', '.conf', '.log'}
    if file_ext.startswith('.'):
        ext_with_dot = file_ext
    else:
        ext_with_dot = f".{file_ext}"

    if ext_with_dot in extractable_exts:
        doc.indexing_status = IndexingStatus.READY
        db.commit()

        file_text = _extract_file_text(content, file.filename)
        label = file_ext.upper()
        session.messages.append({
            "role": "assistant",
            "content": f"[{label} Content: \"{file.filename}\"]\n\n{file_text}",
            "timestamp": datetime.utcnow().isoformat(),
            "banked": False
        })
        flag_modified(session, "messages")
        db.commit()

        # If project_id provided, index to GraphIndex asynchronously
        if project_id and file_ext in ('pdf', 'md', 'txt'):
            import asyncio
            asyncio.create_task(
                _index_to_graphindex_for_chat(
                    project_id=project_id,
                    file_content=content,
                    filename=file.filename,
                    file_path=file_path,
                    file_size=file_size,
                    mime_type=file.content_type,
                    file_text=file_text,
                )
            )
    else:
        background_tasks.add_task(index_session_document_background, doc.id, session.agent_id)

    return SessionDocumentResponse(
        id=doc.id,
        session_id=doc.session_id,
        filename=doc.filename,
        original_filename=doc.original_filename,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        document_type=doc.document_type.value,
        indexing_status=doc.indexing_status.value,
        uploaded_at=doc.uploaded_at,
        message_index=doc.message_index,
        indexed_chunks_count=doc.indexed_chunks_count,
    )


@router.get("/{session_id}/documents", response_model=List[SessionDocumentResponse])
async def list_session_documents(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get all documents uploaded to this chat session."""
    # Verify session exists
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    docs = db.query(SessionDocument).filter(
        SessionDocument.session_id == session_id
    ).order_by(SessionDocument.uploaded_at.desc()).all()

    return [
        SessionDocumentResponse(
            id=doc.id,
            session_id=doc.session_id,
            filename=doc.filename,
            original_filename=doc.original_filename,
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            document_type=doc.document_type.value,
            indexing_status=doc.indexing_status.value,
            uploaded_at=doc.uploaded_at,
            message_index=doc.message_index,
            indexed_chunks_count=doc.indexed_chunks_count
        )
        for doc in docs
    ]


@router.get("/{session_id}/generated-files")
async def list_session_generated_files(
    session_id: str,
    db: Session = Depends(get_db)
):
    """List files the agent generated during this chat session.

    Primary source: the per-agent workspace (outputs/agents/agent_{id}/),
    where all of the agent's files — uploads and generated output — now
    live. Legacy roots (standalone chat workspace + default) are scanned
    for sessions created before this workspace layout existed.
    """
    from datetime import datetime
    from pathlib import Path

    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from services.workspace_manager import get_workspace_manager

    workspace_mgr = get_workspace_manager()
    seen = set()
    generated = []

    def add_file(path: Path):
        """Record a file into the result set (dedup by resolved path)."""
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        stat = path.stat()
        size_human = (
            f"{stat.st_size / 1024:.1f} KB" if stat.st_size >= 1024
            else f"{stat.st_size} B"
        )
        generated.append({
            "filename": path.name,
            "path": str(path.resolve().relative_to(workspace_mgr.base_dir)),
            "size_bytes": stat.st_size,
            "size_human": size_human,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    # ── Primary root: the agent's own workspace. No time-window heuristic
    #    needed — every file here belongs to this agent (uploads are copied
    #    in on upload, generated files land here via the sandbox root).
    if session.agent_id:
        agent_workspace = _resolve_agent_workspace(session, db, workspace_mgr)
        if agent_workspace.is_dir():
            for p in sorted(agent_workspace.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    add_file(p)

    # ── Legacy roots: sessions that ran before per-agent workspaces wrote
    #    to standalone/workflow_None/task_0 or default/. Resolve write-tool
    #    calls against them, plus a time-window fallback for non-write tools.
    try:
        chat_workspace_dir = workspace_mgr.get_task_workspace(None, None, 0)
    except Exception:
        chat_workspace_dir = None
    default_dir = workspace_mgr.base_dir / "default"
    legacy_roots = [r for r in (chat_workspace_dir, default_dir) if r is not None]

    write_tools = {"write_file", "file_write", "vfs_write_file", "write"}
    for tool_call in session.tool_calls or []:
        tool_name = tool_call.get("tool_name", "") or ""
        if tool_name not in write_tools:
            continue
        arguments = tool_call.get("arguments") or {}
        if not isinstance(arguments, dict):
            continue
        file_arg = arguments.get("file_path") or arguments.get("path") or ""
        if not isinstance(file_arg, str) or not file_arg.strip():
            continue

        # Resolve the written path inside any legacy root; the first root
        # that actually contains the file wins.
        file_path = Path(file_arg)
        for root in legacy_roots:
            candidate = file_path if file_path.is_absolute() else root / file_path
            candidate = candidate.resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                add_file(candidate)
                break

    if session.created_at and session.updated_at:
        from datetime import timedelta, timezone

        window_start = session.created_at - timedelta(minutes=2)
        window_end = session.updated_at + timedelta(minutes=2)
        for root in legacy_roots:
            try:
                for p in root.rglob("*"):
                    if not p.is_file() or "__pycache__" in p.parts:
                        continue
                    try:
                        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                    except OSError:
                        continue
                    if not (window_start <= mtime <= window_end):
                        continue
                    add_file(p)
            except OSError:
                continue

    generated.sort(key=lambda f: f.get("modified_at") or "", reverse=True)
    return {"files": generated, "total_files": len(generated)}


@router.get("/{session_id}/documents/{document_id}/download")
async def download_session_document(
    session_id: str,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Download a file uploaded to a chat session."""
    from pathlib import Path

    doc = db.query(SessionDocument).filter(
        SessionDocument.id == document_id,
        SessionDocument.session_id == session_id
    ).first()

    if not doc or not doc.file_path:
        raise HTTPException(status_code=404, detail="Document not found")

    # Defense-in-depth: only serve files inside the storage root, never an
    # arbitrary path stored in the DB.
    from services.file_storage import file_storage
    try:
        Path(doc.file_path).resolve().relative_to(file_storage.base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document path")

    if not Path(doc.file_path).is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=doc.file_path,
        filename=doc.original_filename or doc.filename,
        media_type=doc.mime_type or "application/octet-stream"
    )


@router.delete("/{session_id}/documents/{document_id}", status_code=204)
async def delete_session_document(
    session_id: str,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Delete a document from the session."""
    from services.file_storage import file_storage

    doc = db.query(SessionDocument).filter(
        SessionDocument.id == document_id,
        SessionDocument.session_id == session_id
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file from disk
    if doc.file_path:
        try:
            file_storage.delete_file(doc.file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {doc.file_path}: {e}")

    # TODO: Delete vector embeddings from vector store
    # This would require querying the vector store with session_id and document_id metadata

    db.delete(doc)
    db.commit()

    return None
