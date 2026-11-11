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
from .shared import load_session_for_caller
from models.core import DocumentType, IndexingStatus
from models.deep_agent import ChatSession, DeepAgentTemplate, SessionDocument
from services.calendar_ics import parse_ics
from services.document_type import resolve_document_type

from .schemas import SessionDocumentResponse

logger = logging.getLogger(__name__)
# No prefix here: this router is included into routes.router, which already
# carries the "/api/chat" prefix (FastAPI would otherwise stack prefixes).
router = APIRouter(tags=["chat"])

# Workspace top-level folders that the platform stages on every run, so their
# contents are not something the agent "generated". `skills/` holds one directory
# per enabled skill (a SKILL.md plus support files), and listing it buried the
# user's own output: measured on a coding-agent session, 246 of the 249 rows in
# `GET /{session_id}/generated-files` were staged skill files and the report the
# user asked for was the third row. The Files panel is the only place a
# non-technical user sees what an agent produced, so it must not be a mirror of
# the skill library.
#
# `large_tool_results/` is the spill directory the runtime writes when one tool
# result is too big for the transcript (a 128 KB spreadsheet dump became
# `large_tool_results/call_00_ET_…`, a file with no extension, no readable name
# and nothing the user can do with it, sitting between their upload and their
# report).
EXCLUDED_WORKSPACE_FOLDERS = frozenset({"skills", "large_tool_results"})


def _is_excluded_workspace_path(rel_parts) -> bool:
    """True when a workspace-relative path lives under a platform-staged folder.

    ``rel_parts`` is the sequence of path components *below* its scan root, so the
    last component (the file itself) is not considered — a user's own file named
    ``skills-report.md`` stays visible, while everything under ``skills/`` goes.
    """
    return any(part in EXCLUDED_WORKSPACE_FOLDERS for part in rel_parts[:-1])


def _resolve_agent_workspace(session, db, ws_mgr):
    """Resolve the agent workspace root from the DB, scoped to the vault.

    Priority: the agent's user-defined ``workspace_path`` (persisted in
    deep_agent_templates) → vault-scoped default
    ``outputs/{vault_key}/agents/agent_{id}/`` (vault_key = the
    project's user-visible ``number``, else its ``id``) → legacy
    ``outputs/agents/agent_{id}/``.
    """
    if session.agent_id:
        agent = db.query(DeepAgentTemplate).filter(
            DeepAgentTemplate.id == session.agent_id
        ).first()
        if agent is not None:
            project_id = getattr(session, "project_id", None)
            return ws_mgr.resolve_agent_workspace(
                agent, project_id,
                vault_key=ws_mgr.project_vault_key(db, project_id) or None,
                agent_key=ws_mgr.agent_vault_key(db, agent),
            )
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
    db: Session = Depends(get_db),
    outline: bool = Query(False, description="put the document's outline, not its full text, into the conversation"),
):
    """
    Upload a single file to a chat session for agent context.
    """
    result = await _process_single_chat_upload(session_id, file, background_tasks, project_id, db, outline=outline)
    return result


@router.post("/{session_id}/upload-multiple", response_model=List[SessionDocumentResponse])
async def upload_multiple_files_to_session(
    session_id: str,
    files: List[UploadFile] = File(..., description="Multiple files to upload"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    project_id: Optional[int] = Query(None, description="Project ID for GraphIndex indexing"),
    db: Session = Depends(get_db),
    outline: bool = Query(False, description="put the document's outline, not its full text, into the conversation"),
):
    """
    Upload multiple files to a chat session at once. Each file is extracted,
    injected as a separate context message, and optionally indexed to GraphIndex.
    """
    results = []
    for file in files:
        try:
            result = await _process_single_chat_upload(session_id, file, background_tasks, project_id, db, outline=outline)
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
    outline: bool = False,
) -> SessionDocumentResponse:
    """Process a single file upload for chat: save, extract, inject as context message."""
    from services.file_storage import file_storage

    session = load_session_for_caller(db, session_id)

    content = await file.read()
    file_size = len(content)

    # Save file to session-scoped storage
    file_path = file_storage.save_file(f"chat_sessions/{session_id}", file.filename, content)

    # Copy to sandbox workspace for agent access. Uploads land in the agent
    # workspace's dedicated upload subfolder (AGENT_UPLOADS_DIR), kept
    # separate from agent-generated files (generated/) and the instruction docs
    # (AGENTS.md / CLAUDE.md at the root). The agent's filesystem tools are
    # scoped to the workspace root, so it can still read uploads.
    sandbox_exts = (
        '.csv', '.pdf', '.docx', '.pptx', '.md', '.txt', '.json', '.py',
        '.js', '.ts', '.tsx', '.jsx',
        # Spreadsheets: a workbook is a data source like a CSV, so it has to reach
        # the agent workspace too — otherwise the upload lands in project storage
        # and read_any_file (which reads .xlsx sheet by sheet) cannot see it.
        '.xlsx', '.xlsm', '.xls',
        # Images: copied into the agent workspace upload/ folder so the
        # read_image (OCR) tool and vision models (deepseek-flash) can
        # reach them through the workspace sandbox. Without this an image
        # upload was saved to project storage and then unreachable by the
        # agent — the one file type whose whole point is being read.
        '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff',
    )
    safe_name = Path(file.filename).name  # basename only — block path-traversal writes
    if file.filename.lower().endswith(sandbox_exts):
        try:
            from services.workspace_manager import get_workspace_manager, AGENT_UPLOADS_DIR
            ws_mgr = get_workspace_manager()
            uploads_dir = _resolve_agent_workspace(session, db, ws_mgr) / AGENT_UPLOADS_DIR
            uploads_dir.mkdir(parents=True, exist_ok=True)
            sandbox_path = uploads_dir / safe_name
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

    if document_type == DocumentType.IMAGE:
        # Images have no extractable text layer; embedding them would fail (the
        # vector indexer is text-only). Leave them NOT_INDEXED and let the agent
        # read them through read_image / a vision model instead.
        doc.indexing_status = IndexingStatus.NOT_INDEXED
        db.commit()
    elif ext_with_dot in extractable_exts:
        doc.indexing_status = IndexingStatus.READY
        db.commit()

        # NO embedding on upload (deliberate, 2026-11-04).
        #
        # The text below is appended to the conversation, and that is what makes
        # "upload a file, then ask about it" work — the model reads the text, it
        # does not need a vector index. The old extra step (embed the whole file
        # into the uploader's collection for `rag_search`) is gone because of what
        # it cost: one 4 MB CSV became a SINGLE ollama request that ran 4 min 20 s,
        # and since the embedding server serves one request at a time, every other
        # account's search queued behind that upload for four minutes. The instance
        # looked down; it was behind one file.
        #
        # Anything that still wants vectors can go through the Knowledge activity
        # (`POST /api/rag/upload`), which embeds in bounded batches and is an
        # explicit action rather than a side effect of attaching a file.
        file_text = _extract_file_text(content, file.filename)
        label = file_ext.upper()
        # `outline=true` — the conversation gets the document's SHAPE, not its 40 KB of text, and the
        # file itself is in the agent's `upload/` folder where `read_any_file` can open the part it needs.
        # Measured: a build whose session carried two full documents as context ran >6 minutes inside one
        # model call with no tool call at all; the same comparison, handed an outline plus the paths,
        # answered in 12 s. Full text in the context is right for "read this and answer"; it is wrong for
        # "compare this against what we already built".
        if outline:
            head = "\n".join(file_text.splitlines()[:40])
            msg = {
                "role": "assistant",
                "content": (f"[{label} OUTLINE: \"{file.filename}\"] {len(file_text):,} chars of text; the "
                            f"whole file is at `upload/{file.filename}` (read it with read_any_file when you "
                            f"need a passage).\n\n{head}"
                            + ("\n… [outline truncated]" if len(file_text.splitlines()) > 40 else "")),
                "timestamp": datetime.utcnow().isoformat(),
                "banked": False,
            }
            # Assign a NEW list: `flag_modified` on a JSON column whose attribute was not loaded raises
            # "Can't flag attribute 'messages' modified; it's not present in the object state" (measured
            # as a 500 on the first outline upload). A new list is dirty by construction.
            session.messages = list(session.messages or []) + [msg]
            db.commit()
            file_text = file_text[:2000]     # the indexer still gets a bounded slice
        else:
            session.messages = list(session.messages or []) + [{
                "role": "assistant",
                "content": f"[{label} Content: \"{file.filename}\"]\n\n{file_text}",
                "timestamp": datetime.utcnow().isoformat(),
                "banked": False
            }]
        # NO flag_modified here: a JSON column that was just refreshed by a commit rejects it
        # ("Can't flag attribute 'messages' modified; it's not present in the object state" — measured
        # as a 500 on the first outline upload, because the outline branch commits before this line).
        # Assigning a NEW list marks the attribute dirty by construction, in both branches.
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
        # No text layer to embed — and indexing could not have worked anyway:
        # index_session_document_background hands a SESSION document id to
        # context_document_indexer.index_document(), which looks it up with
        # db.get(ContextDocument, id). Two different tables, so every upload
        # that landed here (images, .xlsx, .db, …) logged
        # "Context document N not found" while the file itself was saved fine.
        # Record the status instead of scheduling a task that cannot succeed;
        # such files stay reachable to the agent through the workspace copy.
        doc.indexing_status = IndexingStatus.NOT_INDEXED
        db.commit()
        logger.info(
            f"Uploaded {file.filename!r} ({document_type.value}) has no text layer: "
            f"kept NOT_INDEXED, available to the agent in the workspace upload/ folder"
        )

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
    session = load_session_for_caller(db, session_id)

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

    Platform-staged folders (``EXCLUDED_WORKSPACE_FOLDERS``) are never
    listed: the skill library is an installation, not an output.
    """
    from datetime import datetime
    from pathlib import Path

    session = load_session_for_caller(db, session_id)

    from services.workspace_manager import get_workspace_manager

    workspace_mgr = get_workspace_manager()
    seen = set()
    generated = []

    def _collect_file_info(path: Path, workspace_root: Optional[Path] = None) -> Optional[dict]:
        """Build the file-info dict for a path (None if already seen)."""
        key = str(path.resolve())
        if key in seen:
            return None
        seen.add(key)
        stat = path.stat()
        size_human = (
            f"{stat.st_size / 1024:.1f} KB" if stat.st_size >= 1024
            else f"{stat.st_size} B"
        )
        info = {
            "filename": path.name,
            "path": str(path.resolve().relative_to(workspace_mgr.user_base())),
            "size_bytes": stat.st_size,
            "size_human": size_human,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
        # An HTML deliverable is meant to be opened, and the Files panel is where a person looks.
        # `path` above is relative to the PERSON's tree; this route wants it relative to the agent
        # workspace, so compute and hand back a ready-made URL instead of making the client guess.
        if workspace_root is not None and path.suffix.lower() in (".html", ".htm"):
            try:
                rel = path.resolve().relative_to(workspace_root.resolve())
                info["open_url"] = (f"/api/chat/{session.session_id}/workspace/file"
                                    f"?path={rel.as_posix()}")
            except ValueError:
                pass
        return info

    def add_file(path: Path, folder: Optional[str] = None):
        """Record a file into the result set (dedup by resolved path)."""
        _file = _collect_file_info(path)
        if _file is not None:
            if folder:
                _file["folder"] = folder
            generated.append(_file)

    # ── Primary root: the agent's own workspace. No time-window heuristic
    #    needed — every file here belongs to this agent. Instruction docs
    #    (AGENTS.md / CLAUDE.md) are not generated output, so they are
    #    excluded, and so is the staged skill library (`skills/`, see
    #    EXCLUDED_WORKSPACE_FOLDERS). Each file is tagged with its top-level
    #    workspace folder (generated/ · upload/ · other/) so the UI can render
    #    a cascading (nested) view instead of one flat list.
    if session.agent_id:
        agent_workspace = _resolve_agent_workspace(session, db, workspace_mgr)
        if agent_workspace.is_dir():
            for p in sorted(agent_workspace.rglob("*")):
                if not p.is_file() or "__pycache__" in p.parts:
                    continue
                if p.name in ("AGENTS.md", "CLAUDE.md", ".gitkeep"):
                    continue
                rel = p.relative_to(agent_workspace)
                if _is_excluded_workspace_path(rel.parts):
                    continue
                # Top-level folder of the workspace (relative path first part,
                # falling back to the workspace root itself).
                folder = rel.parts[0] if len(rel.parts) > 1 else "workspace"
                _file = _collect_file_info(p, agent_workspace)
                if _file is not None:
                    _file["folder"] = folder
                    generated.append(_file)

    # ── Legacy roots: sessions that ran before per-agent workspaces wrote
    #    to standalone/workflow_None/task_0 or default/. Resolve write-tool
    #    calls against them, plus a time-window fallback for non-write tools.
    try:
        chat_workspace_dir = workspace_mgr.get_task_workspace(None, None, 0)
    except Exception:
        chat_workspace_dir = None
    default_dir = workspace_mgr.user_base() / "default"
    legacy_roots = [r for r in (chat_workspace_dir, default_dir) if r is not None]

    write_tools = {"write_file", "file_write", "write"}
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
                rel = candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if _is_excluded_workspace_path(rel.parts):
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
                        rel = p.relative_to(root)
                    except ValueError:
                        continue
                    if _is_excluded_workspace_path(rel.parts):
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


@router.get("/{session_id}/workspace/file")
async def get_session_workspace_file(
    session_id: str,
    path: str = Query(..., description="workspace-relative path, e.g. generated/x_dashboard.html"),
    db: Session = Depends(get_db),
):
    """Serve one file from this conversation's agent workspace, inline.

    Why a route instead of letting the client open `file://`: a page served over http cannot
    navigate to file:// (every browser blocks it), so a generated dashboard had to be found on
    disk by hand. This serves it with `content-disposition: inline`, which is what lets the UI
    open a dashboard in a tab the moment it is generated.

    Containment is explicit: the resolved path must sit inside the agent workspace for THIS
    conversation, so `../..` cannot reach another account's tree.
    """
    from services.workspace_manager import get_workspace_manager

    session = load_session_for_caller(db, session_id)
    if not session.agent_id:
        raise HTTPException(status_code=400, detail="This conversation has no agent workspace")
    root = _resolve_agent_workspace(session, db, get_workspace_manager())

    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path is outside the agent workspace")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=str(candidate), media_type=_guess_media(candidate.name),
                        headers={"Content-Disposition": f'inline; filename="{candidate.name}"',
                                 # a regenerated dashboard must not come back from cache
                                 "Cache-Control": "no-store"})


def _guess_media(name: str) -> str:
    low = name.lower()
    if low.endswith(".html") or low.endswith(".htm"):
        return "text/html; charset=utf-8"
    if low.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if low.endswith(".csv"):
        return "text/csv; charset=utf-8"
    if low.endswith(".json"):
        return "application/json"
    if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return f"image/{low.rsplit('.', 1)[-1].replace('jpg', 'jpeg')}"
    if low.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


@router.get("/{session_id}/dashboards")
async def list_session_dashboards(session_id: str, db: Session = Depends(get_db)):
    """Dashboards generated in this conversation, newest first — what the UI auto-opens.

    Kept separate from `generated-files` on purpose: that list is for a person browsing, this
    one is for the client's "did a new dashboard just appear?" check, so it is small and says
    exactly how to open each entry.
    """
    from services.workspace_manager import get_workspace_manager

    session = load_session_for_caller(db, session_id)
    if not session.agent_id:
        return {"dashboards": []}
    root = _resolve_agent_workspace(session, db, get_workspace_manager())
    if not root.is_dir():
        return {"dashboards": []}

    found = []
    for path in root.rglob("*dashboard*.html"):
        if not path.is_file():
            continue
        # Platform-staged skill copies live here; they are not this conversation's dashboards
        # (same rule the Files panel uses — 246 of 249 rows were staged skill files once).
        if EXCLUDED_WORKSPACE_FOLDERS.intersection(path.relative_to(root).parts[:-1]):
            continue
        try:
            rel = path.relative_to(root)
            stat = path.stat()
        except (ValueError, OSError):
            continue
        found.append({
            "name": path.name,
            "path": str(rel),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "url": f"/api/chat/{session_id}/workspace/file?path={rel.as_posix()}",
        })
    found.sort(key=lambda f: f["modified_at"], reverse=True)
    return {"dashboards": found}


@router.post("/{session_id}/workspace/clear")
async def clear_session_workspace(session_id: str, db: Session = Depends(get_db)):
    """Empty the agent workspace this conversation runs in.

    The Files panel is the only place a non-technical user can see what an agent
    has produced, so it is also where they should be able to start over — a
    workspace full of test uploads is otherwise cleared by hand on the server.

    What is removed: the contents of `upload/`, `generated/`, `other/` and
    `skills/` (all user-visible data). What is kept: the directory skeleton and
    the agent's own instruction docs (AGENTS.md / CLAUDE.md) — those are
    configuration, and the chat path rewrites them on the next run anyway.
    """
    from services.workspace_manager import get_workspace_manager

    session = load_session_for_caller(db, session_id)
    workspace_mgr = get_workspace_manager()

    if not session.agent_id:
        raise HTTPException(status_code=400, detail="This conversation has no agent workspace")

    root = _resolve_agent_workspace(session, db, workspace_mgr)

    # Candidate workspaces for this agent: the resolved one plus the legacy default.
    # A vault-bound conversation resolves to the vault workspace, but files uploaded
    # from an earlier unbound conversation of the same agent sit in
    # outputs/<user>/agents/agent_<id>/ — clearing only one made "empty" look broken.
    roots = [root]
    try:
        legacy = workspace_mgr.user_base() / "agents" / f"agent_{session.agent_id}"
        if legacy.resolve() != root.resolve():
            roots.append(legacy)
    except Exception:
        pass
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        return {"status": "ok", "removed_files": 0, "workspace": str(root), "note": "workspace did not exist"}

    # The Files panel's "Uploaded" list is built from `session_documents`, not from
    # the directory: deleting the bytes alone left the panel still listing the file
    # (and the agent still believing it exists). Clear the rows with the files.
    from models.deep_agent import SessionDocument as _SessionDocument

    doc_rows = db.query(_SessionDocument).filter(_SessionDocument.session_id == session_id).all()
    removed_docs = 0
    for doc in doc_rows:
        for candidate in (doc.file_path, doc.filename):
            if not candidate:
                continue
            try:
                from pathlib import Path as _P

                p_ = _P(candidate)
                if p_.is_file() and (root in p_.parents or p_.parent == root):
                    p_.unlink(missing_ok=True)
            except Exception:
                pass
        db.delete(doc)
        removed_docs += 1
    if removed_docs:
        db.commit()

    keep_names = {"AGENTS.md", "CLAUDE.md", ".gitkeep"}
    removed, kept = 0, []
    for root in roots:
      for entry in sorted(root.iterdir()):
        if entry.name in keep_names:
            kept.append(entry.name)
            continue
        if entry.is_dir():
            for child in sorted(entry.rglob("*"), reverse=True):
                if child.is_file():
                    removed += 1
                    child.unlink(missing_ok=True)
            # leave the skeleton directories in place
            if entry.name in ("upload", "generated", "other", "skills"):
                (entry / ".gitkeep").touch()
            else:
                import shutil

                shutil.rmtree(entry, ignore_errors=True)
        else:
            removed += 1
            entry.unlink(missing_ok=True)

    logger.info(f"Workspace cleared for session {session_id}: {removed} file(s) in {root}")
    return {
        "status": "ok",
        "removed_files": removed,
        "removed_documents": removed_docs,
        "workspace": str(root),
        "kept": kept,
    }


@router.get("/{session_id}/calendar")
async def get_session_calendar(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Calendar events read out of the ``.ics`` files in the agent workspace.

    Read-only on purpose: the agent already writes the files (``calendar_expert``
    in the training build), so rendering them keeps a single source of truth —
    no second event store that the agent would need a new tool to reach.

    A file that yields no VEVENT is reported in ``unparsed_files`` rather than
    silently dropped, and an event without a TZID comes back with
    ``timezone: null`` so the UI can show the literal time instead of inventing
    a local one.
    """
    from services.workspace_manager import get_workspace_manager

    MAX_ICS_FILES = 200

    session = load_session_for_caller(db, session_id)
    workspace_mgr = get_workspace_manager()

    events: List[dict] = []
    unparsed: List[str] = []
    scanned = 0
    workspace_rel: Optional[str] = None

    root = _resolve_agent_workspace(session, db, workspace_mgr) if session.agent_id else None
    if root is not None and root.is_dir():
        try:
            workspace_rel = str(root.resolve().relative_to(workspace_mgr.user_base()))
        except ValueError:
            workspace_rel = str(root)

        for path in sorted(root.rglob("*.ics")):
            if scanned >= MAX_ICS_FILES:
                break
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            scanned += 1
            try:
                rel = str(path.resolve().relative_to(root.resolve()))
            except ValueError:
                rel = path.name
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                unparsed.append(rel)
                continue
            try:
                stat = path.stat()
                modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                modified_at = None
            parsed = parse_ics(raw, fallback_title=path.stem)
            if not parsed:
                unparsed.append(rel)
                continue
            for event in parsed:
                event["file"] = rel
                event["modified_at"] = modified_at
                events.append(event)

    events.sort(key=lambda e: (e.get("start") or "", e.get("title") or ""))
    return {
        "events": events,
        "files_scanned": scanned,
        "unparsed_files": unparsed,
        "workspace": workspace_rel,
    }


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
