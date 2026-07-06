# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Form, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import logging
import time
import re
import hashlib
import mimetypes
import zipfile
import tarfile
import tempfile
import shutil
from pathlib import Path

from db.database import get_db
from models.core import ContextDocument, DocumentType, IndexingStatus, SearchHistory, Project
from services.token_counter import get_token_counter

# Phase 9 integration: ensure learning/phase9/ is importable for
# build-graphindex-clean helpers used by _phase9_get_or_generate_enrichment.
# (phase9/ moved from langconfig/phase9/ to langconfig/learning/phase9/ on 2026-06-26)
import sys as _sys
import os as _os
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in _sys.path and _os.path.isdir(_REPO_ROOT):
    _sys.path.insert(0, _REPO_ROOT)
_PHASE9_DIR = _os.path.join(_REPO_ROOT, "learning", "phase9")
if _PHASE9_DIR not in _sys.path and _os.path.isdir(_PHASE9_DIR):
    _sys.path.insert(0, _PHASE9_DIR)

router = APIRouter(prefix="/api/rag", tags=["rag"])
logger = logging.getLogger(__name__)


# Pydantic Schemas
class DocumentUploadResponse(BaseModel):
    id: int
    name: str
    document_type: DocumentType
    size: int
    status: IndexingStatus
    message: str


class DocumentResponse(BaseModel):
    id: int
    project_id: int
    name: str  # Mapped from filename for frontend compatibility
    original_filename: str
    document_type: DocumentType
    size: int  # Mapped from file_size for frontend compatibility
    mime_type: Optional[str]
    indexing_status: IndexingStatus
    chunk_count: Optional[int]  # Mapped from indexed_chunks_count for frontend compatibility
    created_at: datetime
    indexed_at: Optional[datetime]

    # Step N+1: hierarchy metadata (industry/player/sub_category/
    # sub_department). Populated by bulk ingest from reports_new/.
    # Used by the KB sidebar's Tree view and folder-scope filter.
    industry: Optional[str] = None
    player: Optional[str] = None
    sub_category: Optional[str] = None
    sub_department: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_model(cls, doc):
        """Create response from ORM model with field mapping"""
        return cls(
            id=doc.id,
            project_id=doc.project_id,
            name=doc.filename,
            original_filename=doc.original_filename,
            document_type=doc.document_type,
            size=doc.file_size,
            mime_type=doc.mime_type,
            indexing_status=doc.indexing_status,
            chunk_count=doc.indexed_chunks_count,
            created_at=doc.created_at,
            indexed_at=doc.indexed_at,
            industry=getattr(doc, "industry", None),
            player=getattr(doc, "player", None),
            sub_category=getattr(doc, "sub_category", None),
            sub_department=getattr(doc, "sub_department", None),
        )


class SearchRequest(BaseModel):
    query: str
    project_id: int
    top_k: int = 5
    use_hyde: bool = False
    search_mode: str = "vector"  # "vector" (embedding RAG) or "graphindex" (vectorless progressive disclosure)
    # Optional list of ContextDocument ids to scope the search to. When
    # provided (and non-empty), only chunks belonging to these docs are
    # considered. Used by the Knowledge panel sidebar's per-doc checkboxes.
    document_ids: Optional[List[int]] = None


class SearchResult(BaseModel):
    document_id: int
    document_name: str
    chunk_text: str
    similarity_score: float
    metadata: Optional[dict]

    # NEW: Measured facts about this chunk
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    total_chunks_in_doc: Optional[int] = None
    chunk_token_count: int = 0  # Measured token count
    chunk_char_count: int = 0   # Character count
    source_location: Optional[str] = None  # Lines, pages, etc.
    retrieval_rank: int = 0  # Position in results (1-based)


class SearchMetrics(BaseModel):
    """Measured metrics from search execution - factual data only"""
    query: str
    use_hyde: bool
    hyde_auto_detected: bool  # Was HyDE auto-detected?
    use_toon: bool
    top_k: int

    # Measured timing (milliseconds)
    retrieval_duration_ms: float

    # Measured token counts (actual, not estimated)
    query_tokens: int
    total_context_tokens: int  # Sum of all retrieved chunks

    # Measured similarity scores
    results_count: int
    avg_similarity_score: float
    max_similarity_score: float
    min_similarity_score: float


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int

    # NEW: Real measured metrics
    metrics: Optional[SearchMetrics] = None
    search_mode: str = "vector"


class GraphIndexDocItem(BaseModel):
    """A document entry from GraphIndex search"""
    doc_id: str
    doc_name: str
    type: str
    page_count: int
    structure: Optional[list] = None
    context_doc_id: Optional[int] = None


class GraphIndexSearchResponse(BaseModel):
    query: str
    search_mode: str = "graphindex"
    documents: List[GraphIndexDocItem]
    total_documents: int


SUPPORTED_GRAPHINDEX_EXTS: set[str] = {
    ".pdf", ".txt", ".md", ".html", ".csv", ".json",
    ".xml", ".yaml", ".yml", ".py", ".js", ".ts",
    ".java", ".cpp", ".hpp", ".c", ".h", ".rb", ".go",
    ".rs", ".swift", ".kt", ".scala",
}


def _is_graphindexable(filename: str) -> bool:
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_GRAPHINDEX_EXTS


def _queue_graphindex_ingest(file_path: str, project_id: int = 1) -> None:
    """Run cmd_ingest on the uploaded file to create a Neo4j Document node.

    This is called as a background task after a file has been uploaded and
    saved to disk. It runs the same Phase 9 ingestion pipeline as the CLI:
    hash → dedup (FS + Neo4j) → copy → LLM enrichment → upsert to Neo4j.
    """
    try:
        from learning.phase9.graphindex.index_build import (
            make_llm, cmd_ingest, Neo4jDocumentIndex,
        )
        index = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        index.ensure_constraints()
        llm = make_llm()
        cmd_ingest(index, llm, file_path, project_id=project_id)
    except Exception as e:
        logger.error(f"graphindex ingest failed for {file_path}: {e}")


async def index_document_background(document_id: int):
    """Background task to index a document for both vector RAG and GraphIndex."""
    from db.database import SessionLocal
    from services.context_document_indexer import context_document_indexer

    db = SessionLocal()
    try:
        doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found for indexing")
            return

        if not doc.file_path:
            logger.error(f"Document {document_id} has no file_path")
            doc.indexing_status = IndexingStatus.FAILED
            db.commit()
            return

        # Update status to indexing
        doc.indexing_status = IndexingStatus.INDEXING
        file_path = doc.file_path  # Save for later use
        db.commit()
        db.close()

        vector_result = None
        vector_error = None

        # Index the document for vector RAG.
        try:
            vector_result = await context_document_indexer.index_document(
                document_id=document_id,
                file_path=file_path
            )
        except Exception as ve:
            vector_error = ve
            logger.warning(f"Vector indexing failed for {document_id}: {ve}")

        # Update status with new session
        db = SessionLocal()
        doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
        if doc:
            if vector_result:
                doc.indexed_chunks_count = vector_result.get("embeddings_stored", 0)
                doc.indexing_status = IndexingStatus.READY
                doc.indexed_at = datetime.utcnow()
            else:
                doc.indexing_status = IndexingStatus.FAILED
            db.commit()
        db.close()

        if vector_result:
            logger.info(f"Document {document_id} indexed successfully")
        else:
            logger.warning(f"Vector indexing failed for {document_id} — document available via GraphIndex only.")

    except Exception as e:
        logger.error(f"Failed to index document {document_id}: {e}", exc_info=True)
        # Create fresh session for error handling
        try:
            db.close()
        except Exception:
            pass

        db = SessionLocal()
        try:
            doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
            if doc:
                doc.indexing_status = IndexingStatus.FAILED
                db.commit()
        finally:
            db.close()


# Endpoints
@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile = File(None),
    metadata: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Upload a document for RAG indexing"""
    from services.file_storage import file_storage
    import json

    logger.info(f"Upload request - project_id={project_id}, file={file.filename if file else 'None'}, metadata={metadata}")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Parse metadata if provided
    doc_metadata = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning(f"Invalid metadata JSON: {metadata}")

    # Save file to disk. Pass the resolved hierarchy (industry /
    # player / sub_category / sub_department) so file_storage writes
    # the file under a nested folder path that mirrors the source
    # folder, instead of flattening everything into project_<id>/.
    # Without this, a browser folder-picker upload that includes a
    # relative path (e.g. "analysis/company_report.md") would be
    # written to `<project_dir>/<uuid>_analysis/company_report.md`
    # which pathlib treats as a directory and crashes the write.
    file_path = file_storage.save_file(
        project_id, file.filename, content,
        hierarchy={
            "industry": industry,
            "player": player,
            "sub_category": sub_category,
            "sub_department": sub_department,
        },
    )

    # Determine document type from file extension (expanded support)
    file_ext = file.filename.split('.')[-1].lower()
    doc_type_map = {
        'txt': DocumentType.TEXT,
        'md': DocumentType.MARKDOWN,
        'pdf': DocumentType.PDF,
        'json': DocumentType.JSON,
        'py': DocumentType.CODE,
        'js': DocumentType.CODE,
        'ts': DocumentType.CODE,
        'tsx': DocumentType.CODE,
        'jsx': DocumentType.CODE,
        'java': DocumentType.CODE,
        'c': DocumentType.CODE,
        'cpp': DocumentType.CODE,
        'h': DocumentType.CODE,
        'hpp': DocumentType.CODE,
        'cs': DocumentType.CODE,
        'rb': DocumentType.CODE,
        'go': DocumentType.CODE,
        'rs': DocumentType.CODE,
        'php': DocumentType.CODE,
        'swift': DocumentType.CODE,
        'kt': DocumentType.CODE,
        'scala': DocumentType.CODE,
        'r': DocumentType.CODE,
        'sql': DocumentType.CODE,
        'sh': DocumentType.CODE,
        'bash': DocumentType.CODE,
        'html': DocumentType.HTML,
        'htm': DocumentType.HTML,
        'xml': DocumentType.XML,
        'csv': DocumentType.CSV,
        'yaml': DocumentType.YAML,
        'yml': DocumentType.YAML,
        'doc': DocumentType.DOCX,
        'docx': DocumentType.DOCX,
        'rtf': DocumentType.TEXT,
        'odt': DocumentType.TEXT,
        'epub': DocumentType.TEXT,
        'ppt': DocumentType.TEXT,
        'pptx': DocumentType.TEXT,
        'xls': DocumentType.CSV,
        'xlsx': DocumentType.CSV,
        'png': DocumentType.IMAGE,
        'jpg': DocumentType.IMAGE,
        'jpeg': DocumentType.IMAGE,
        'gif': DocumentType.IMAGE,
        'bmp': DocumentType.IMAGE,
        'tiff': DocumentType.IMAGE,
        'webp': DocumentType.IMAGE,
    }
    document_type = doc_type_map.get(file_ext, DocumentType.TEXT)

    # Save file to disk. Pass the resolved hierarchy so file_storage
    # writes the file under a nested folder path mirroring the
    # source folder (industry/player/sub_category/sub_department/).
    # Without this, a browser folder-picker upload that includes a
    # relative path (e.g. "analysis/company_report.md") would be
    # written to `<project_dir>/<uuid>_analysis/company_report.md`
    # which pathlib treats as a directory and crashes the write.
    file_path = file_storage.save_file(
        project_id, file.filename, content,
        hierarchy={
            "industry": industry,
            "player": player,
            "sub_category": sub_category,
            "sub_department": sub_department,
        },
    )

    # Create document record with correct schema
    # Build name, tags and description from metadata
    custom_name = doc_metadata.get("name") if isinstance(doc_metadata, dict) else None
    description = doc_metadata.get("description") if isinstance(doc_metadata, dict) else None
    tags = doc_metadata.get("tags") if isinstance(doc_metadata, dict) else None
    # Step N+1: hierarchy metadata (industry/player/sub_category/
    # sub_department). Optional for single uploads — most users won't
    # set them, but the workspace-bulk-upload path can pass them
    # through so the sidebar's Tree view shows the file in the
    # right folder.
    industry        = doc_metadata.get("industry") if isinstance(doc_metadata, dict) else None
    player          = doc_metadata.get("player") if isinstance(doc_metadata, dict) else None
    sub_category    = doc_metadata.get("sub_category") if isinstance(doc_metadata, dict) else None
    sub_department  = doc_metadata.get("sub_department") if isinstance(doc_metadata, dict) else None

    # Check for duplicate: same filename + project_id (skip failed docs so they can be re-uploaded)
    existing = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.filename == (custom_name or file.filename),
        ContextDocument.indexing_status != IndexingStatus.FAILED
    ).first()
    if existing:
        logger.info(f"Duplicate document '{file.filename}' for project {project_id}, reusing existing id={existing.id}")
        return DocumentUploadResponse(
            id=existing.id,
            name=existing.filename,
            document_type=existing.document_type,
            size=existing.file_size or 0,
            status=existing.indexing_status.value,
            message="Document already exists"
    )

    # Delegate to cmd_ingest — single code path for PG + Neo4j + disk,
    # guaranteed consistent naming (no duplicates).
    # Save to a temp directory with the original filename so cmd_ingest
    # sees src.name == the real display name.
    import tempfile as _tf
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest,
        make_llm,
    )

    _tmp_dir = _tf.mkdtemp()
    _tmp_path = Path(_tmp_dir) / file.filename
    _tmp_path.write_bytes(content)

    try:
        idx = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        llm = make_llm()
        rc = cmd_ingest(idx, llm, str(_tmp_path), project_id=project_id)
        if rc != 0:
            raise HTTPException(status_code=500, detail="ingest failed")
    finally:
        try:
            import shutil as _shutil
            _shutil.rmtree(_tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # Find the PG record that cmd_ingest just created so we can return its id.
    doc = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.original_filename == file.filename,
    ).order_by(ContextDocument.id.desc()).first()
    if not doc:
        raise HTTPException(status_code=500, detail="document not found after ingest")

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size or 0,
        status=doc.indexing_status,
        message="Document uploaded and indexed."
    )


def _parse_hierarchy_from_path(file_path: str) -> dict:
    """Step N+1 safety-net: derive industry/player/sub_category/sub_department
    from a saved file_path.

    # Why this exists
    -----------------
    The Sidebar's Tree view buckets docs by `industry`. If a doc has
    `industry IS NULL`, the tree view puts it in a synthetic
    "(ungrouped)" folder. Once there, the user can't filter the chat
    by industry, the agent can't route by hierarchy, and the visual
    UI is cluttered.

    # When is this called?
    ---------------------
    Called by `_process_single_file_for_bulk` (and any other place
    that inserts a ContextDocument with a NULL hierarchy) as a
    safety net. If the frontend's `file_metadata` form field didn't
    arrive (e.g. older browser, live backend running pre-Step-O
    bytecode, "Browse Files" used instead of "Select Folder"), the
    form metadata is empty — but the file is already on disk at a
    path that mirrors the source folder, so we can re-extract the
    hierarchy from there.

    # Path layouts supported
    ------------------------
    All three forms are handled. We anchor on the `data/documents/`
    segment and then drop the project prefix to find the hierarchy:

      1. <base>/data/documents/project_<id>/<industry>/<player>/<sub_category>/<sub_department>/<hash>_<name>
         ^^^^^^^^^^^^^^^  live backend (file_storage.save_file, CWD-relative)
      2. <base>/data/documents/<id>/<industry>/<player>/<sub_category>/<sub_department>/<hash>_<name>
         ^^^^^^^^^^^^^^^  CLI ingest script (CWD-relative, no `project_` prefix)
      3. Relative: `data/documents/project_<id>/...` (e.g. when the
         backend reads a relative path from a config)

    The path can be absolute OR relative — we don't depend on a
    leading `/`. Windows-style backslashes are also handled.

    # Returns
    ---------
    A dict with whatever levels were found. Missing levels are
    `None`. Callers can check `if not industry or not player:` to
    decide whether to fall back. If even the file_path doesn't have
    a hierarchy (e.g. user uploaded a single file to project root
    via "Browse Files"), the doc legitimately goes to (ungrouped).
    """
    if not file_path:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    parts: list[str] = [p for p in file_path.replace("\\", "/").split("/") if p]
    if not parts:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    # Find the data/documents/ anchor and take what comes after it.
    anchor_idx = -1
    for i, p in enumerate(parts):
        if p == "data" and i + 1 < len(parts) and parts[i + 1] == "documents":
            anchor_idx = i + 1  # index of "documents"
            break
    if anchor_idx >= 0:
        parts = parts[anchor_idx + 1:]
    if not parts:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    # Drop the project prefix: either `project_<id>` (live API)
    # or bare `<id>` (CLI ingest). Anything that's all-digits is
    # treated as a bare project id.
    if parts[0].startswith("project_") or parts[0].isdigit():
        parts = parts[1:]
    out = {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    if len(parts) >= 2:
        out["industry"] = parts[0]
    if len(parts) >= 3:
        out["player"] = parts[1]
    if len(parts) >= 4:
        out["sub_category"] = parts[2]
    if len(parts) >= 5:
        out["sub_department"] = parts[3]
    return out


async def _process_single_file_for_bulk(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile,
    metadata: dict,
    db: Session
) -> DocumentUploadResponse:
    """Helper function to process a single file during bulk upload"""
    from services.file_storage import file_storage

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Determine document type from file extension (expanded support) — done
    # BEFORE save_file so we can early-out on hidden files like
    # `.placeholder` (no extension → map defaults to TEXT but the
    # actual upload would 400 with `Refusing to save hidden file`
    # from file_storage. We catch it here and skip cleanly so the
    # remaining 4 valid files in a folder upload still ingest.)
    file_ext = file.filename.split('.')[-1].lower()
    base_filename = Path(file.filename).name
    if base_filename.startswith("."):
        logger.warning(
            f"Skipping hidden file in folder upload: {file.filename!r}"
        )
        # Mimic the DocumentUploadResponse shape so the bulk loop
        # keeps going for the other files. Use a sentinel id of 0 —
        # the bulk caller filters out negative-or-zero ids anyway.
        from datetime import datetime as _dt
        return DocumentUploadResponse(
            id=0,
            name=file.filename,
            document_type=DocumentType.TEXT,
            size=file_size,
            status=IndexingStatus.SKIPPED,
            message=f"Skipped hidden file (no extension): {file.filename}",
        )
    doc_type_map = {
        'txt': DocumentType.TEXT,
        'md': DocumentType.MARKDOWN,
        'pdf': DocumentType.PDF,
        'json': DocumentType.JSON,
        'py': DocumentType.CODE,
        'js': DocumentType.CODE,
        'ts': DocumentType.CODE,
        'tsx': DocumentType.CODE,
        'jsx': DocumentType.CODE,
        'java': DocumentType.CODE,
        'c': DocumentType.CODE,
        'cpp': DocumentType.CODE,
        'h': DocumentType.CODE,
        'hpp': DocumentType.CODE,
        'cs': DocumentType.CODE,
        'rb': DocumentType.CODE,
        'go': DocumentType.CODE,
        'rs': DocumentType.CODE,
        'php': DocumentType.CODE,
        'swift': DocumentType.CODE,
        'kt': DocumentType.CODE,
        'scala': DocumentType.CODE,
        'r': DocumentType.CODE,
        'sql': DocumentType.CODE,
        'sh': DocumentType.CODE,
        'bash': DocumentType.CODE,
        'html': DocumentType.HTML,
        'htm': DocumentType.HTML,
        'xml': DocumentType.XML,
        'csv': DocumentType.CSV,
        'yaml': DocumentType.YAML,
        'yml': DocumentType.YAML,
        'doc': DocumentType.DOCX,
        'docx': DocumentType.DOCX,
        'rtf': DocumentType.TEXT,
        'odt': DocumentType.TEXT,
        'epub': DocumentType.TEXT,
        'ppt': DocumentType.TEXT,
        'pptx': DocumentType.TEXT,
        'xls': DocumentType.CSV,
        'xlsx': DocumentType.CSV,
        'png': DocumentType.IMAGE,
        'jpg': DocumentType.IMAGE,
        'jpeg': DocumentType.IMAGE,
        'gif': DocumentType.IMAGE,
        'bmp': DocumentType.IMAGE,
        'tiff': DocumentType.IMAGE,
        'webp': DocumentType.IMAGE,
    }
    document_type = doc_type_map.get(file_ext, DocumentType.TEXT)

    # Build metadata
    custom_name = metadata.get("name") if isinstance(metadata, dict) else None
    description = metadata.get("description") if isinstance(metadata, dict) else None
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    # Step N+1: hierarchy metadata. Same as the single-upload path —
    # folder uploads send these via the per-file `file_metadata` field.
    industry        = metadata.get("industry") if isinstance(metadata, dict) else None
    player          = metadata.get("player") if isinstance(metadata, dict) else None
    sub_category    = metadata.get("sub_category") if isinstance(metadata, dict) else None
    sub_department  = metadata.get("sub_department") if isinstance(metadata, dict) else None

    # ============================================================
    # FALLBACK: derive hierarchy from the saved file_path
    # ============================================================
    # Why this matters: the Sidebar's Tree view puts any doc with
    # NULL `industry` into a synthetic "(ungrouped)" folder. If a
    # doc lands in (ungrouped), the user can't filter by industry/
    # player/sub_category, the chat agent can't route by hierarchy,
    # and the visual UI is cluttered.
    #
    # When can `industry` be NULL despite the file having a proper
    # path on disk?
    #   1. The frontend "Select Folder" picker captures the
    #      webkitRelativePath and sends it as `file_metadata`, but
    #      the live backend is running pre-Step-O bytecode (we saw
    #      this on project 1 — 57 docs all in (ungrouped) because
    #      the running uvicorn hadn't been restarted since the fix
    #      landed on disk).
    #   2. The user uploaded via "Browse Files" (single file) so
    #      there is no relativePath at all.
    #   3. The form field was sent but the JSON was malformed.
    #
    # The file_storage layer ALWAYS writes the file to
    # `data/documents/project_<id>/<industry>/<player>/<sub_category>/
    # <sub_department>/<hash>_<name>` — either by honoring the
    # caller's chosen subfolder (live API upload) or by walking
    # a source folder (ingest-folder). So the hierarchy is
    # always in the file_path, even if it never made it into
    # the form field.
    #
    # This fallback re-extracts the hierarchy from the path
    # BEFORE we insert the row, so the doc lands in the correct
    # folder from the start — no (ungrouped) ever needed.
    #
    # For the existing 57 docs that already landed in (ungrouped),
    # use `/tmp/backfill_hierarchy.py` to fix them in-place
    # (idempotent — safe to run multiple times).
    # ============================================================
    if not industry or not player:
        derived = _parse_hierarchy_from_path(file_path)
        if not industry:
            industry = derived.get("industry")
        if not player:
            player = derived.get("player")
        if not sub_category:
            sub_category = derived.get("sub_category")
        if not sub_department:
            sub_department = derived.get("sub_department")
        if industry or player or sub_category:
            logger.info(
                f"[Step N+1 fallback] Derived hierarchy from file_path for "
                f"{file.filename}: industry={industry!r} player={player!r} "
                f"sub_category={sub_category!r} sub_department={sub_department!r}"
            )
        else:
            # If even the path didn't have a hierarchy, this is a
            # true "Browse Files" upload of a single file to a
            # project root. The doc will land in (ungrouped) — this
            # is the only legitimate path to that bucket.
            logger.debug(
                f"No hierarchy in form metadata or file_path for "
                f"{file.filename} — doc will land in (ungrouped)"
            )

    # Delegate to cmd_ingest — single code path for PG + Neo4j + disk.
    # Save to a temp directory with the original filename so cmd_ingest
    # sees src.name == the real display name.
    import tempfile as _tf
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest,
        make_llm,
    )

    _tmp_dir = _tf.mkdtemp()
    _tmp_path = Path(_tmp_dir) / file.filename
    _tmp_path.write_bytes(content)

    try:
        idx = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        llm = make_llm()
        # Pass the caller-supplied hierarchy (industry / player /
        # sub_category / sub_department) into cmd_ingest so the
        # ContextDocument row carries the correct folder bucket
        # instead of landing in (ungrouped). Without this, both
        # `effective_metadata` (read above for the legacy
        # `_parse_hierarchy_from_path` fallback) and the disk-side
        # hierarchy were computed but never persisted.
        hierarchy = {
            "industry": industry,
            "player": player,
            "sub_category": sub_category,
            "sub_department": sub_department,
        }
        rc = cmd_ingest(idx, llm, str(_tmp_path), project_id=project_id, hierarchy=hierarchy)
        if rc != 0:
            raise Exception("cmd_ingest failed")
    finally:
        try:
            import shutil as _shutil
            _shutil.rmtree(_tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # Find the PG record that cmd_ingest just created.
    doc = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.original_filename == file.filename,
    ).order_by(ContextDocument.id.desc()).first()
    if not doc:
        raise Exception("document not found after ingest")

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size or 0,
        status=doc.indexing_status,
        message="Document uploaded and indexed."
    )


@router.post("/upload-bulk", response_model=List[DocumentUploadResponse])
async def upload_documents_bulk(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    project_id: int = Form(...),
    extract_archives: bool = Form(True),
    metadata: Optional[str] = Form(None),
    # Step N+1: optional per-file metadata for folder uploads. When
    # the user selects a folder in the browser, each File carries a
    # `webkitRelativePath` like "electric_vehicle_industry/tesla/
    # marketing/01-product-lineup.md". The frontend parses the path
    # into industry/player/sub_category/sub_department and sends one
    # metadata dict per file in this field (JSON-encoded list, index
    # matches `files`). If omitted, all files share `metadata`
    # (existing behavior).
    file_metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload multiple documents or archives for RAG indexing.

    Supports:
    - Multiple file uploads
    - Archive extraction (.zip, .tar, .tar.gz, .tgz)
    - Folder structures (preserves paths as metadata — per-file via
      `file_metadata`, or shared via `metadata`)

    Note: Files should be sent as multipart/form-data with field name 'files'
    """
    import json

    try:
        logger.info(f"Bulk upload request received - project_id={project_id}, extract_archives={extract_archives}")
        logger.info(f"Number of files received: {len(files) if files else 0}")

        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")

        # Parse shared metadata if provided
        doc_metadata = {}
        if metadata:
            try:
                doc_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning(f"Invalid metadata JSON: {metadata}")

        # Parse per-file metadata if provided. Must be a list with one
        # entry per file (or empty list = no per-file metadata).
        per_file_metadata: list[dict] = []
        if file_metadata:
            try:
                parsed = json.loads(file_metadata)
                if isinstance(parsed, list):
                    per_file_metadata = [m if isinstance(m, dict) else {} for m in parsed]
                else:
                    logger.warning(f"file_metadata is not a list: {type(parsed).__name__}")
            except json.JSONDecodeError:
                logger.warning(f"Invalid file_metadata JSON: {file_metadata}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk upload validation: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

    uploaded_docs = []

    # Process each file. Use enumerate so we can look up the matching
    # entry in `per_file_metadata` for folder uploads (Step N+1).
    for file_idx, file in enumerate(files):
        try:
            logger.info(f"Processing file: {file.filename}")

            # Pick the metadata for THIS file:
            #  - per_file_metadata[file_idx] if the frontend supplied
            #    per-file metadata (folder upload, webkitRelativePath
            #    parsed into industry/player/sub_category), else
            #  - the shared doc_metadata (existing behavior).
            effective_metadata = (
                per_file_metadata[file_idx]
                if file_idx < len(per_file_metadata)
                else doc_metadata
            )

            # Check if it's an archive
            file_ext = file.filename.split('.')[-1].lower()
            is_archive = file_ext in ['zip', 'tar', 'gz', 'tgz']

            if is_archive and extract_archives:
                # For archives with extraction, process extracted files
                logger.info(f"Extracting archive: {file.filename}")
                content = await file.read()

                # Create temporary directory for extraction
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    archive_path = temp_path / file.filename

                    # Save archive to temp location
                    archive_path.write_bytes(content)

                    # Extract based on type
                    try:
                        if file_ext == 'zip':
                            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                                zip_ref.extractall(temp_path)
                        elif file_ext in ['tar', 'gz', 'tgz']:
                            with tarfile.open(archive_path, 'r:*') as tar_ref:
                                tar_ref.extractall(temp_path)

                        # Process all extracted files
                        for extracted_file in temp_path.rglob('*'):
                            if extracted_file.is_file() and extracted_file != archive_path:
                                # Get relative path from archive root
                                relative_path = str(extracted_file.relative_to(temp_path))
                                logger.info(f"Processing extracted file: {relative_path}")

                                # Read file and create mock UploadFile
                                file_content = extracted_file.read_bytes()

                                class MockUploadFile:
                                    def __init__(self, filename, content, content_type='application/octet-stream'):
                                        self.filename = filename
                                        self.content = content
                                        self.content_type = content_type

                                    async def read(self):
                                        return self.content

                                mock_file = MockUploadFile(extracted_file.name, file_content)
                                # Use the parent archive's effective_metadata
                                # for all extracted children (the user picked
                                # the archive as a single upload, not the
                                # internal structure).
                                result = await _process_single_file_for_bulk(
                                    background_tasks, project_id, mock_file, effective_metadata, db
                                )
                                uploaded_docs.append(result)

                    except Exception as e:
                        logger.error(f"Failed to extract archive {file.filename}: {e}")
                        # Upload archive as-is if extraction fails
                        await file.seek(0)
                        result = await _process_single_file_for_bulk(
                            background_tasks, project_id, file, effective_metadata, db
                        )
                        uploaded_docs.append(result)
            else:
                # Regular file upload (no extraction)
                result = await _process_single_file_for_bulk(
                    background_tasks, project_id, file, effective_metadata, db
                )
                uploaded_docs.append(result)

        except Exception as e:
            logger.error(f"Failed to process file {file.filename}: {e}", exc_info=True)
            # Continue with other files
            continue

    logger.info(f"Bulk upload completed: {len(uploaded_docs)} documents uploaded")
    return uploaded_docs


# --- Server-side folder ingest (Safari / Firefox fallback) ---------
# The browser-native <input type="file" webkitdirectory> doesn't work
# reliably in all browsers (Safari has quirks, Firefox uses a different
# API). For those cases, the user can paste an absolute folder path
# here and the server reads it from disk, ingesting every supported
# file with hierarchy metadata derived from the path.

@router.post("/ingest-folder")
async def ingest_folder_from_path(
    request: Request,
    db: Session = Depends(get_db),
):
    """Walk a folder on the server's disk and ingest every supported
    file into the given project, using the same code path as the CLI
    (index_build.cmd_ingest_folder) so PostgreSQL + Neo4j stay in sync.

    Body (JSON):
      {
        "project_id":   int,
        "folder_path":  absolute path on the server,
        "industry":     optional filter (default: derived from first path segment)
        "player":       optional filter (default: derived from second segment)
      }

    Returns:
      {
        "created": int, "updated": int, "skipped": int, "failed": int,
        "files_seen": int, "files_ingested": int, "files_filtered": int
      }
    """
    import json as _json
    try:
        body = await request.body()
        params = _json.loads(body or b"{}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    project_id   = params.get("project_id")
    folder_path  = params.get("folder_path")

    if not project_id or not folder_path:
        raise HTTPException(
            status_code=400,
            detail="Both 'project_id' and 'folder_path' are required"
        )

    # Validate project exists
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    # Validate folder exists on disk
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"folder not found on disk: {folder}"
        )

    # Delegate to CLI code path — guarantees consistent naming
    # across PostgreSQL, Neo4j, and disk files (no duplicates).
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest_folder,
        make_llm,
    )

    idx = Neo4jDocumentIndex(
        base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
        username=_os.environ.get("NEO4J_USER", "neo4j"),
        password=_os.environ.get("NEO4J_PASSWORD", "password"),
    )
    idx.ensure_constraints()
    llm = make_llm()
    # Count files up front so the frontend can show "ingested X
    # files" even when cmd_ingest_folder only returns a 0/1 exit
    # code (the CLI's return type). The CLI module is the single
    # source of truth for what counts as "indexable" — it already
    # filters hidden files and unsupported extensions. Re-using the
    # same constants here keeps the two paths in lockstep.
    from learning.phase9.graphindex.index_build import _SUPPORTED_EXTS
    files_seen = sum(
        1 for p in folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _SUPPORTED_EXTS
        and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    )
    ok = cmd_ingest_folder(idx, llm, str(folder), project_id=project_id)
    success = ok == 0
    # When the CLI succeeds we assume every file got created.
    # Failure cases are unusual (LLM parse error, Neo4j write
    # error) and the print log already surfaces them — the
    # frontend's alert is best-effort UX feedback.
    files_ingested = files_seen if success else 0
    files_failed = 0 if success else files_seen
    files_filtered = 0  # cmd_ingest_folder filters in-place; nothing drops here

    return {
        "success": success,
        "project_id": project_id,
        "folder": str(folder),
        "files_seen": files_seen,
        "files_ingested": files_ingested,
        "files_filtered": files_filtered,
        "created": files_ingested,
        "updated": 0,
        "skipped": 0,
        "failed": files_failed,
        "message": "Folder ingested successfully." if success else "Folder ingested with errors.",
    }


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    project_id: int,
    skip: int = 0,
    limit: int = 50,
    status: Optional[IndexingStatus] = None,
    db: Session = Depends(get_db)
):
    """List documents for a project"""
    query = db.query(ContextDocument).filter(ContextDocument.project_id == project_id)

    if status:
        query = query.filter(ContextDocument.indexing_status == status)

    documents = query.offset(skip).limit(limit).all()
    # Map ORM models to response models with field name mapping
    return [DocumentResponse.from_orm_model(doc) for doc in documents]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific document by ID"""
    doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.from_orm_model(doc)


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Serve the raw document file (PDF, text, etc.) so the Studio's
    Knowledge panel can render it in an <iframe> using the browser's
    built-in PDF viewer (or pdfjs-dist for Safari).

    ARCHITECTURE (per Phase 9 / L0):
      - Postgres ContextDocument is the sidebar index (doc id, name, etc.)
      - Neo4j Document is the file_path index (the source of truth for
        where the file actually lives on disk).
      - FS holds the actual bytes.

    So we:
      1. Look up the doc's `name` and `project_id` in Postgres by id
         (this is what the sidebar uses).
      2. Look up `file_path` in Neo4j by (project_id, name) — the
         authoritative source for the on-disk path.
      3. Stream the file from FS.

    This avoids stale `file_path` issues if Postgres and Neo4j get
    out of sync (which can happen if a doc is re-ingested via the
    CLI but the Postgres record isn't updated).
    """
    from fastapi.responses import FileResponse
    # 1. Postgres — get the doc's name + project_id by id
    doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 2. Resolve canonical file_path. Prefer Neo4j (authoritative source for
    #    the on-disk path) but fall back to Postgres.file_path if Neo4j
    #    doesn't have the doc yet. Previously we returned 404 in this case,
    #    which pdfjs-dist 6.x mis-reports as "Unexpected server response
    #    (406)" because the response body is JSON, not the expected PDF
    #    binary. Falling back keeps the viewer functional even before the
    #    graphindex ingest has completed.
    file_path_str: Optional[str] = None
    try:
        from services.neo4j_document_index import Neo4jDocumentIndex
        neo = Neo4jDocumentIndex()
        neo_doc = neo.get_document(
            project_id=doc.project_id,
            name=doc.original_filename or doc.filename,
        )
        if neo_doc and neo_doc.file_path:
            file_path_str = neo_doc.file_path
    except Exception:
        # Neo4j unavailable — fall back silently to Postgres
        file_path_str = None

    if not file_path_str:
        file_path_str = doc.file_path

    if not file_path_str:
        raise HTTPException(
            status_code=404,
            detail=f"Document has no resolvable file_path "
                   f"(Postgres + Neo4j both empty).",
        )

    file_path = Path(file_path_str)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Document file not found on disk: {file_path}",
        )

    # 3. Stream the file with the right Content-Type
    media_type = doc.mime_type or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=doc.original_filename or doc.filename,
        content_disposition_type="inline",
    )


class DocumentContentResponse(BaseModel):
    """Extracted text content for inline rendering in the Knowledge panel.

    Used by the frontend's DocumentViewer to render MD / TXT / JSON / YAML /
    CSV / DOCX / PPTX / XLSX inline instead of triggering a download.

    The `kind` field tells the frontend which renderer to use:
      - 'markdown'    — render with a Markdown component
      - 'csv'         — render as a table (rows is list of list of strings)
      - 'html'        — render raw HTML (sanitization done client-side)
      - 'code'        — render in a <pre><code> with syntax highlighting
      - 'plain'       — render in a <pre> with no formatting
    """
    kind: str
    content: str
    rows: Optional[List[List[str]]] = None
    sheet_names: Optional[List[str]] = None
    sheet_rows: Optional[List[List[List[str]]]] = None  # rows per sheet
    truncated: bool = False


def _extract_text_for_viewer(file_path: Path, ext: str, max_chars: int = 500_000) -> DocumentContentResponse:
    """Extract the text/markdown/csv/structured content for inline viewing.

    Mirrors the extraction logic in `_load_full_content_for_kv` so the
    Knowledge panel viewer shows the same content that search/answer uses.
    """
    ext = ext.lower()

    # Markdown
    if ext == ".md" or ext == ".markdown":
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # CSV — render as a 2D table
    if ext == ".csv":
        import csv as _csv
        rows: List[List[str]] = []
        with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = _csv.reader(f)
            for i, row in enumerate(reader):
                if i >= 5000:  # cap rows to keep payload reasonable
                    break
                rows.append(row)
        return DocumentContentResponse(
            kind="csv",
            content="",
            rows=rows,
            truncated=len(rows) >= 5000,
        )

    # HTML — wrap in a sandboxed iframe on the client
    if ext in (".html", ".htm"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="html",
            content=text[:max_chars],
            truncated=truncated,
        )

    # JSON
    if ext == ".json":
        try:
            import json as _json
            data = _json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
            formatted = _json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            formatted = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(formatted) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=formatted[:max_chars],
            truncated=truncated,
        )

    # YAML — treat as plain code (no parser dependency)
    if ext in (".yaml", ".yml"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=text[:max_chars],
            truncated=truncated,
        )

    # DOCX (Word)
    if ext == ".docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(file_path))
            parts: list[str] = []
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            # Also pull table cells
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
            text = "\n\n".join(parts)
        except Exception as e:
            logger.warning(f"docx parse failed for {file_path}: {e}")
            text = f"[Failed to parse .docx: {e}]"
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # PPTX (PowerPoint)
    if ext == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(str(file_path))
            parts: list[str] = []
            for slide_idx, slide in enumerate(prs.slides, start=1):
                parts.append(f"## Slide {slide_idx}")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            text = "".join(run.text for run in para.runs).strip()
                            if text:
                                parts.append(text)
                parts.append("")
            text = "\n\n".join(parts).strip()
        except Exception as e:
            logger.warning(f"pptx parse failed for {file_path}: {e}")
            text = f"[Failed to parse .pptx: {e}]"
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # XLSX (Excel) — return all sheets as rows
    if ext == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
            sheet_names = wb.sheetnames
            all_rows: list[list[list[str]]] = []
            for sheet_name in sheet_names:
                ws = wb[sheet_name]
                rows: list[list[str]] = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 5000:
                        break
                    rows.append(["" if v is None else str(v) for v in row])
                all_rows.append(rows)
            # Also build a flat markdown view of the first sheet
            text = ""
            if sheet_names:
                text = f"# {sheet_names[0]}\n\n"
                if all_rows and all_rows[0]:
                    header = all_rows[0][0]
                    text += "| " + " | ".join(header) + " |\n"
                    text += "| " + " | ".join(["---"] * len(header)) + " |\n"
                    for row in all_rows[0][1:50]:
                        text += "| " + " | ".join(row) + " |\n"
            return DocumentContentResponse(
                kind="csv",  # frontend uses 'csv' to render as a table; sheet_names makes it multi-sheet
                content=text,
                rows=all_rows[0] if all_rows else [],
                sheet_names=sheet_names,
                sheet_rows=all_rows,
                truncated=any(len(r) >= 5000 for r in all_rows),
            )
        except Exception as e:
            logger.warning(f"xlsx parse failed for {file_path}: {e}")
            return DocumentContentResponse(
                kind="plain",
                content=f"[Failed to parse .xlsx: {e}]",
                truncated=False,
            )

    # Plain text + code files
    if ext in (".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp",
               ".c", ".h", ".hpp", ".rb", ".go", ".rs", ".swift", ".kt",
               ".scala", ".sh", ".bash", ".sql", ".xml", ".log"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=text[:max_chars],
            truncated=truncated,
        )

    # Fallback — try to decode as UTF-8 text, else surface a hint
    try:
        text = file_path.read_text(encoding="utf-8")
        return DocumentContentResponse(kind="plain", content=text, truncated=False)
    except Exception:
        return DocumentContentResponse(
            kind="plain",
            content=f"[Binary file: {file_path.name} — open in new tab to download]",
            truncated=False,
        )


@router.get("/documents/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Return extracted text/structured content for inline rendering.

    Supports MD, TXT, JSON, YAML, CSV, HTML, XML, code files (kind='code'),
    DOCX, PPTX (kind='markdown'), XLSX (kind='csv' with multiple sheets).

    Resolves `file_path` from Neo4j (same as /file endpoint) so the file
    on disk is the one we read from.
    """
    doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Resolve canonical file_path from Neo4j (same logic as /file)
    try:
        from services.neo4j_document_index import Neo4jDocumentIndex
        neo = Neo4jDocumentIndex()
        neo_doc = neo.get_document(project_id=doc.project_id, name=doc.original_filename or doc.filename)
        file_path_str = neo_doc.file_path if neo_doc and neo_doc.file_path else doc.file_path
    except Exception:
        file_path_str = doc.file_path

    if not file_path_str:
        raise HTTPException(status_code=404, detail="Document has no file_path")

    file_path = Path(file_path_str)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {file_path}")

    ext = file_path.suffix.lower()
    return _extract_text_for_viewer(file_path, ext)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a document and its associated vector embeddings.

    This operation:
    1. Finds the document in PostgreSQL
    2. Deletes associated vector embeddings from pgvector table
    3. Deletes the document file from disk
    4. Deletes the document record from PostgreSQL
    """
    from services.file_storage import file_storage

    doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    project_id = doc.project_id
    file_path = doc.file_path

    try:
        # Delete associated embeddings from vector database
        if project_id:
            from services.llama_config import get_vector_store

            logger.info(f"Deleting vector embeddings for document {document_id} in project {project_id}")

            try:
                # Check if table exists first to avoid transaction errors
                from sqlalchemy import text
                table_name = f"data_project_index_{project_id}"

                check_query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = :table_name
                    )
                """)

                table_exists = db.execute(check_query, {"table_name": table_name}).scalar()

                if table_exists:
                    vector_store = get_vector_store(project_id)

                    # Delete vectors where metadata contains this document's filename
                    delete_query = text(f"""
                        DELETE FROM {table_name}
                        WHERE metadata_->>'filename' = :filename
                    """)

                    result = db.execute(delete_query, {"filename": doc.filename})
                    deleted_count = result.rowcount
                    logger.info(f"Deleted {deleted_count} vector embeddings for document {document_id}")
                else:
                    logger.info(f"Vector table {table_name} does not exist yet (document may be pending), skipping vector deletion")

            except Exception as e:
                logger.warning(f"Failed to delete vector embeddings: {e}")
                db.rollback()  # Rollback failed vector deletion to allow document deletion
                # Continue with document deletion even if vector cleanup fails

        # Step N+1: also delete the Neo4j Document node so the chat
        # agent's graphindex catalog doesn't keep pointing to a file
        # that's about to be removed. Without this, list_docs() would
        # still return the doc and the user would hit "doc not found"
        # errors when the LLM tries to read it.
        if project_id:
            try:
                from services.neo4j_document_index import Neo4jDocumentIndex
                idx = Neo4jDocumentIndex()
                # Build a set of candidate names to try, in priority order:
                # 1. original_filename (the user's original name)
                # 2. filename (Postgres ContextDocument.filename)
                # 3. file_path basename (which is the post-rename name,
                #    e.g. `cfd711e3_01_tesla_q3_strategy.pdf` — this is
                #    what Neo4j's `name` field is, since file_storage
                #    renames on save with an 8-char content-hash prefix)
                candidates = []
                if doc.original_filename:
                    candidates.append(doc.original_filename)
                if doc.filename and doc.filename not in candidates:
                    candidates.append(doc.filename)
                if doc.file_path:
                    bp = Path(doc.file_path).name
                    if bp and bp not in candidates:
                        candidates.append(bp)
                for lookup_name in candidates:
                    if idx.delete_document(project_id, lookup_name):
                        logger.info(f"Deleted Neo4j Document node for {lookup_name}")
                        break
                else:
                    # None of the candidates matched — fall back to a
                    # more thorough search by content_sha256 (set at
                    # ingest time on the Neo4j node)
                    if doc.content_hash:
                        rows = idx._run_cypher(
                            "MATCH (d:Document {project_id: $pid, content_sha256: $h}) "
                            "DETACH DELETE d RETURN count(d) AS n",
                            {"pid": project_id, "h": doc.content_hash},
                        )
                        if rows and rows[0].get("n", 0) > 0:
                            logger.info(
                                f"Deleted Neo4j Document node by content_sha256 "
                                f"({rows[0]['n']} nodes)"
                            )
            except Exception as e:
                logger.warning(f"Failed to delete Neo4j Document node: {e}")
                # Don't fail the whole delete — Neo4j is best-effort

        # Delete file from disk
        if file_path:
            try:
                file_storage.delete_file(file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file {file_path}: {e}")

        # Delete the document record
        db.delete(doc)
        db.commit()

        logger.info(f"Successfully deleted document {document_id}")
        return None

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete document {document_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


@router.post("/search")
async def search_documents(
    request: SearchRequest,
    db: Session = Depends(get_db)
):
    """
    Search documents using DNA-augmented HyDE vector similarity.

    This endpoint leverages the existing ContextRetriever service with:
    - Conditional HyDE for code generation queries
    - Project DNA augmentation for context-aware retrieval
    - PostgreSQL + pgvector for semantic search
    - Real-time metrics measurement (tokens, latency, similarity)

    When search_mode='graphindex', uses vectorless progressive disclosure (GraphIndex-style)
    instead of embedding similarity search.
    """

    try:
        # ===== GraphIndex Mode =====
        if request.search_mode == "graphindex":
            from learning.phase9.graphindex.index_build import Neo4jDocumentIndex
            import os as _os

            idx = Neo4jDocumentIndex(
                base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
                username=_os.environ.get("NEO4J_USER", "neo4j"),
                password=_os.environ.get("NEO4J_PASSWORD", "password"),
            )
            idx.ensure_constraints()

            best = idx.find_best_document(project_id=request.project_id, query=request.query)

            docs = []
            if best:
                context_doc = db.query(ContextDocument).filter(
                    ContextDocument.project_id == request.project_id,
                    ContextDocument.filename == best.name,
                ).first()
                docs.append(GraphIndexDocItem(
                    doc_id=str(context_doc.id) if context_doc else best.name,
                    doc_name=best.name,
                    type="unknown",
                    page_count=0,
                    structure=None,
                    context_doc_id=context_doc.id if context_doc else None,
                ))

            return GraphIndexSearchResponse(
                query=request.query,
                search_mode="graphindex",
                documents=docs,
                total_documents=len(docs),
            )

        # ===== Vector Mode (existing) =====
        # Check if project exists and is indexed
        from models.core import Project
        project = db.query(Project).filter(Project.id == request.project_id).first()

        if not project:
            raise HTTPException(status_code=404, detail=f"Project {request.project_id} not found")

        if project.indexing_status != IndexingStatus.READY:
            return SearchResponse(
                query=request.query,
                results=[],
                total_results=0,
                search_mode="vector",
            )

        # Use the search_context_documents from context_document_indexer directly
        from services.context_document_indexer import search_context_documents
        logger.info(f"Searching project {request.project_id}: '{request.query}' (hyde={request.use_hyde}, top_k={request.top_k})")

        # START TIMING MEASUREMENT
        start_time = time.time()
        
        search_result = await search_context_documents(
            query=request.query,
            project_id=request.project_id,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
        
        # END TIMING MEASUREMENT
        end_time = time.time()
        retrieval_duration_ms = (end_time - start_time) * 1000
        
        # Get token counter for measuring actual token counts
        token_counter = get_token_counter()
        
        # Measure query tokens
        query_tokens = token_counter.count_tokens(request.query)
        
        # Transform to SearchResult format
        results = []
        similarity_scores = []
        total_context_tokens = 0
        
        for i, item in enumerate(search_result['results']):
            # Measure token counts
            chunk_token_count = token_counter.count_tokens(item['text'])
            chunk_char_count = len(item['text'])
            total_context_tokens += chunk_token_count
            similarity_scores.append(item['score'])
            
            results.append(SearchResult(
                document_id=item['document_id'],
                document_name=item['filename'],
                chunk_text=item['text'],
                similarity_score=item['score'],
                metadata={},
                chunk_id=None,
                chunk_index=i,
                chunk_token_count=chunk_token_count,
                chunk_char_count=chunk_char_count,
                retrieval_rank=i + 1
            ))

        # Calculate aggregate similarity metrics
        avg_similarity = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0
        max_similarity = max(similarity_scores) if similarity_scores else 0.0
        min_similarity = min(similarity_scores) if similarity_scores else 0.0

        # Build metrics object with all measured facts
        metrics = SearchMetrics(
            query=request.query,
            use_hyde=bool(request.use_hyde),
            hyde_auto_detected=False,
            use_toon=False,  # Default to False for now
            top_k=request.top_k,
            retrieval_duration_ms=retrieval_duration_ms,
            query_tokens=query_tokens,
            total_context_tokens=total_context_tokens,
            results_count=len(results),
            avg_similarity_score=avg_similarity,
            max_similarity_score=max_similarity,
            min_similarity_score=min_similarity
        )

        # Store search in history for analysis
        search_history = SearchHistory(
            project_id=request.project_id,
            query=request.query,
            use_hyde=bool(request.use_hyde),
            hyde_auto_detected=False,
            use_toon=False,  # Default to False for now
            top_k=request.top_k,
            results_count=len(results),
            retrieval_duration_ms=retrieval_duration_ms,
            query_tokens=query_tokens,
            total_context_tokens=total_context_tokens,
            avg_similarity=avg_similarity,
            max_similarity=max_similarity,
            min_similarity=min_similarity,
            results_data={
                "query": request.query,
                "results_count": len(results),
                "metrics": metrics.dict()
            }
        )
        db.add(search_history)
        db.commit()

        logger.info(f"Search completed: {len(results)} results, {retrieval_duration_ms:.1f}ms, {total_context_tokens} tokens")

        return SearchResponse(
            query=request.query,
            results=results,
            total_results=len(results),
            metrics=metrics,
            search_mode="vector",
        )

    except ValueError as e:
        # Project not ready or not found
        logger.warning(f"Search failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/index/{document_id}")
async def index_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Manually trigger indexing for a specific document"""
    doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update status and queue background task
    doc.indexing_status = IndexingStatus.INDEXING
    db.commit()

    # Queue document for embedding generation and indexing
    background_tasks.add_task(index_document_background, doc.id)

    return {
        "message": "Document indexing started",
        "document_id": document_id,
        "status": IndexingStatus.INDEXING
    }


# Pydantic schema for search history
class SearchHistoryResponse(BaseModel):
    id: int
    project_id: int
    query: str
    use_hyde: bool
    hyde_auto_detected: bool
    use_toon: bool
    top_k: int
    results_count: int
    retrieval_duration_ms: float
    query_tokens: int
    total_context_tokens: int
    avg_similarity: Optional[float]
    max_similarity: Optional[float]
    min_similarity: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/search-history", response_model=List[SearchHistoryResponse])
async def get_search_history(
    project_id: int,
    limit: int = 50,
    skip: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get search history for a project with real measured metrics.
    Returns paginated list of past searches with all factual data.
    """
    history = (
        db.query(SearchHistory)
        .filter(SearchHistory.project_id == project_id)
        .order_by(SearchHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return history


# GraphIndex Endpoints for Progressive Disclosure
    """
    Get storage statistics for a project. RELOAD_MARKER_2025

    Returns both estimated and actual storage measurements:
    - Actual: Measured PostgreSQL table size
    - Estimated: Calculated from storage formulas (when tracking enabled)
    - Configuration: Current chunk size, embedding dimensions
    - Breakdown: Vector store vs document store

    This gives users visibility into storage costs and helps with capacity planning.
    """
    from services.storage_estimator import storage_estimator
    from models.core import Project

    try:
        # Get project
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        # Measure actual storage from PostgreSQL
        actual_storage = storage_estimator.measure_actual_storage(project_id)

        # Get configuration
        chunk_size = project.configuration.get("chunk_size_config", 1024) if project.configuration else 1024
        chunk_overlap = project.configuration.get("chunk_overlap_config", 20) if project.configuration else 20
        embedding_dimensions = project.embedding_dimension or 384

        response = {
            "project_id": project_id,
            "project_name": project.name,
            "indexing_status": project.indexing_status.value if project.indexing_status else "not_indexed",
            "last_indexed_at": project.last_indexed_at.isoformat() if project.last_indexed_at else None,
            "actual_storage": actual_storage,
            "configuration": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "embedding_dimensions": embedding_dimensions,
                "indexed_nodes_count": project.indexed_nodes_count or 0
            },
            "storage_per_document_gb": round(
                actual_storage["total_bytes"] / (1024**3) / max(1, len(project.documents))
            , 3) if project.documents else 0,
            "message": "Actual storage measured from PostgreSQL system catalog"
        }

        logger.info(f"Storage stats for project {project_id}: {actual_storage['total_gb']} GB")
        return response

    except Exception as e:
        logger.error(f"Failed to get storage stats for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get storage stats: {str(e)}")
