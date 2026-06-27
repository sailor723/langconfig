# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Form
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
from pathlib import Path

from db.database import get_db
from models.core import ContextDocument, DocumentType, IndexingStatus, SearchHistory
from services.token_counter import get_token_counter

# Phase 9 integration: ensure learning/phase9/ is importable for
# build-graphindex-clean helpers used by _phase9_get_or_generate_enrichment.
# (phase9/ moved from langconfig/phase9/ to langconfig/learning/phase9/ on 2026-06-26)
import sys as _sys
import os as _os
_PHASE9_DIR = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "learning", "phase9")
)
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
        )


class SearchRequest(BaseModel):
    query: str
    project_id: int
    top_k: int = 5
    use_hyde: bool = False
    search_mode: str = "vector"  # "vector" (embedding RAG) or "graphindex" (vectorless progressive disclosure)


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


class GraphIndexPage(BaseModel):
    page: int
    content: str


class GraphIndexFullDocumentResponse(BaseModel):
    doc_id: str
    doc_name: str
    type: str
    page_count: int
    structure: list
    pages: List[GraphIndexPage]


class GraphIndexStructureResponse(BaseModel):
    doc_id: str
    doc_name: str
    type: str
    page_count: int
    structure: list


class GraphIndexAnswerRequest(BaseModel):
    query: str
    project_id: int
    context_doc_id: Optional[int] = None
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096


class GraphIndexAnswerResponse(BaseModel):
    query: str
    search_mode: str = "graphindex"
    context_doc_id: int
    doc_id: str
    doc_name: str
    model: str
    answer: str
    pages_loaded: int
    content_chars: int


def _build_graphindex_query_terms(query: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    if not normalized:
        return []

    terms: List[str] = [normalized]
    terms.extend([token for token in normalized.split(" ") if token])

    if " " not in normalized and len(normalized) > 1:
        for i in range(len(normalized) - 1):
            terms.append(normalized[i:i + 2])

    return list(dict.fromkeys(terms))


def _score_graphindex_document(query: str, meta: dict, context_doc: ContextDocument) -> float:
    normalized_query = query.strip().lower()
    query_terms = _build_graphindex_query_terms(query)
    score = 0.0

    searchable_terms = meta.get("search_terms", [])
    content_preview = (meta.get("content_preview") or "").lower()
    filename = (meta.get("doc_name") or "").lower()
    description = (context_doc.description or "").lower()
    tags = context_doc.tags or []

    for token in query_terms:
        if len(token) < 2:
            continue
        if len(normalized_query) > 8 and len(token) < 4:
            continue

        if token in filename:
            score += 3.0
        if description and token in description:
            score += 2.0
        if content_preview and token in content_preview:
            score += 2.0
        for tag in tags:
            if token in str(tag).lower():
                score += 2.5
        for searchable in searchable_terms:
            if token in searchable:
                score += 1.0

    return score


def _resolve_graphindex_target_document(
    request: "GraphIndexAnswerRequest",
    db: Session,
    client
) -> tuple[ContextDocument, dict]:
    """Find the target document for a GraphIndex answer request."""
    if request.context_doc_id is not None:
        context_doc = (
            db.query(ContextDocument)
            .filter(
                ContextDocument.id == request.context_doc_id,
                ContextDocument.project_id == request.project_id,
            )
            .first()
        )
        if not context_doc:
            raise HTTPException(status_code=404, detail="Document not found in project")
        meta: dict = {}
        if context_doc.doc_index_id:
            meta = client.get_document(context_doc.doc_index_id) or {}
            if isinstance(meta, dict) and "error" in meta:
                meta = {}
        return context_doc, meta

    neo4j_context_doc = _try_resolve_graphindex_target_document_via_neo4j(
        project_id=request.project_id,
        query=request.query,
        db=db,
        client=client,
    )
    if neo4j_context_doc is not None:
        meta: dict = {}
        if neo4j_context_doc.doc_index_id:
            meta = client.get_document(neo4j_context_doc.doc_index_id) or {}
            if isinstance(meta, dict) and "error" in meta:
                meta = {}
        return neo4j_context_doc, meta

    project_docs = (
        db.query(ContextDocument)
        .filter(
            ContextDocument.project_id == request.project_id,
            ContextDocument.doc_index_id.isnot(None),
        )
        .all()
    )
    if not project_docs:
        raise HTTPException(status_code=404, detail="No GraphIndex documents found for project")

    project_doc_map = {doc.doc_index_id: doc for doc in project_docs}
    best_match: Optional[tuple[float, ContextDocument, dict]] = None
    for doc_id, meta in client.list_all().items():
        context_doc = project_doc_map.get(doc_id)
        if not context_doc:
            continue
        score = _score_graphindex_document(request.query, meta, context_doc)
        if score <= 0:
            continue
        if best_match is None or score > best_match[0]:
            best_match = (score, context_doc, meta)

    if best_match is None:
        raise HTTPException(status_code=404, detail="No matching GraphIndex document found")

    return best_match[1], best_match[2]


def _get_neo4j_document_index():
    import os

    from services.neo4j_document_index import Neo4jDocumentIndex

    base_url = os.environ.get("NEO4J_URL", "http://localhost:7474")
    username = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    return Neo4jDocumentIndex(
        base_url=base_url,
        username=username,
        password=password,
        database=database,
    )


def _try_resolve_graphindex_target_document_via_neo4j(
    project_id: int,
    query: str,
    db: Session,
    client,
) -> Optional[ContextDocument]:
    try:
        index = _get_neo4j_document_index()
        index.ensure_constraints()
        match = index.find_best_document(project_id=project_id, query=query)
        if not match or not match.context_doc_id:
            return None
    except Exception:
        return None

    context_doc = (
        db.query(ContextDocument)
        .filter(
            ContextDocument.project_id == project_id,
            ContextDocument.id == match.context_doc_id,
        )
        .first()
    )
    if not context_doc:
        return None

    if match.doc_index_id and not context_doc.doc_index_id:
        context_doc.doc_index_id = match.doc_index_id
    if match.file_path and context_doc.file_path != match.file_path:
        context_doc.file_path = match.file_path
    return context_doc


def _infer_graphindex_type_from_filename(filename: str) -> str:
    lowered = (filename or "").lower().strip()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".md"):
        return "md"
    return "text"


def _try_graphindex_search_via_neo4j(
    project_id: int,
    query: str,
    top_k: int,
    client,
) -> Optional[GraphIndexSearchResponse]:
    try:
        index = _get_neo4j_document_index()
        index.ensure_constraints()
        match = index.find_best_document(project_id=project_id, query=query)
        if not match:
            return None
    except Exception:
        return None

    structure = []
    if match.doc_index_id:
        try:
            structure_value = client.get_document_structure(match.doc_index_id)
            if isinstance(structure_value, list):
                structure = structure_value[:20]
        except Exception:
            structure = []

    doc_id = match.doc_index_id or f"context:{match.context_doc_id}"
    doc_name = match.doc_name or match.name
    doc_type = _infer_graphindex_type_from_filename(match.name)
    page_count = int(match.page_count or 0)

    logger.info(f"[PAGEINDEX_DEBUG] context_doc_id={match.context_doc_id!r}, type={type(match.context_doc_id).__name__}")

    return GraphIndexSearchResponse(
        query=query,
        search_mode="graphindex",
        documents=[
            GraphIndexDocItem(
                doc_id=doc_id,
                doc_name=doc_name,
                type=doc_type,
                page_count=page_count,
                structure=structure,
                context_doc_id=match.context_doc_id,
            )
        ][: max(1, int(top_k or 1))],
        total_documents=1,
    )


def _phase9_get_or_generate_enrichment(
    context_doc: "ContextDocument",
    index,
    graphindex_meta: dict,
):
    """Phase 9 enrichment provider for knowledge-panel uploads.

    Strategy:
      1. If a Neo4j Document node with this name already exists and has a
         populated `what_this_document_is_about`, reuse its enrichment
         (preserves Phase 9 build-side ingests and --rebuild-one results).
      2. Otherwise, run a single LLM call via phase9/graphindex_build_python
         to generate about / supports / out_of_scope / few_shot.

    Returns:
        Neo4jDocumentEnrichment (possibly empty fields if LLM fails).
    """
    from services.neo4j_document_index import Neo4jDocumentEnrichment

    existing = None
    try:
        existing = index.get_document(
            project_id=context_doc.project_id, name=context_doc.filename
        )
    except Exception:
        existing = None

    if existing and existing.what_this_document_is_about:
        logger.info(
            f"[phase9] reusing existing enrichment for {context_doc.filename!r} "
            f"(about={existing.what_this_document_is_about[:60]!r}...)"
        )
        return Neo4jDocumentEnrichment(
            what_this_document_is_about=existing.what_this_document_is_about,
            supported_queries=list(existing.supported_queries or []),
            out_of_scope=list(existing.out_of_scope or []),
            few_shot=[{"query": s.get("query", ""), "answer_hint": s.get("answer_hint", "")}
                      for s in (existing.few_shot or []) if isinstance(s, dict)],
        )

    # No existing enrichment — generate via Phase 9 LLM call.
    try:
        from graphindex_build_python import enrich_document, make_llm
        llm = make_llm()
        enrichment = enrich_document(index, llm, context_doc.file_path)
        logger.info(
            f"[phase9] generated fresh enrichment for {context_doc.filename!r}: "
            f"about={enrichment.what_this_document_is_about[:60]!r}..."
        )
        return enrichment
    except Exception as e:
        logger.warning(
            f"[phase9] enrichment generation failed for {context_doc.filename!r}: {e}. "
            f"Falling back to empty enrichment."
        )
        return Neo4jDocumentEnrichment()


def _try_sync_context_document_to_neo4j(context_doc: ContextDocument, client) -> None:
    if not context_doc.project_id:
        return
    if not context_doc.file_path:
        return

    try:
        index = _get_neo4j_document_index()
        index.ensure_constraints()
    except Exception:
        return

    graphindex_meta: dict = {}
    if context_doc.doc_index_id:
        try:
            meta = client.get_document(context_doc.doc_index_id) or {}
            if isinstance(meta, dict) and "error" not in meta:
                graphindex_meta = meta
        except Exception:
            graphindex_meta = {}

    try:
        from services.neo4j_document_index import build_document_node_properties

        # Phase 9 enrichment: if the Neo4j node already has fields populated
        # (e.g. via phase9/graphindex_build_python.py --ingest), preserve them.
        # Otherwise generate fresh enrichment via LLM. This replaces the legacy
        # `enrichment=None` which left Neo4j nodes with empty about / supports /
        # out_of_scope and broke routing for knowledge-panel uploads.
        enrichment_obj = _phase9_get_or_generate_enrichment(
            context_doc=context_doc,
            index=index,
            graphindex_meta=graphindex_meta,
        )

        properties = build_document_node_properties(
            project_id=context_doc.project_id,
            context_doc_id=context_doc.id,
            doc_index_id=context_doc.doc_index_id,
            name=context_doc.filename,
            file_path=context_doc.file_path,
            description=context_doc.description or "",
            tags=list(context_doc.tags or []),
            graphindex_meta=graphindex_meta,
            enrichment=enrichment_obj,
        )
        index.upsert_document(
            project_id=context_doc.project_id,
            name=context_doc.filename,
            file_path=context_doc.file_path,
            properties=properties,
        )
    except Exception:
        return


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
        doc_index_id = None

        # Index to DocIndex (GraphIndex-style vectorless index) first so GraphIndex
        # remains available even if vector embedding generation fails later.
        try:
            from services.doc_index_service import DocIndexClient
            import os
            doc_index_base = os.environ.get(
                "DOC_INDEX_BASE",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "outputs")
            )
            # Use default workspace
            client = DocIndexClient(doc_index_base)
            doc_index_id = client.index(file_path)
            logger.info(f"Document {document_id} also indexed to DocIndex (GraphIndex mode) with doc_index_id {doc_index_id}")
        except Exception as pi_e:
            logger.warning(f"DocIndex indexing failed for {document_id}: {pi_e}")

        # Index the document for vector RAG separately.
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
            if doc_index_id:
                doc.doc_index_id = doc_index_id
            if vector_result:
                doc.indexed_chunks_count = vector_result.get("embeddings_stored", 0)
            if doc_index_id or vector_result:
                doc.indexing_status = IndexingStatus.READY
                doc.indexed_at = datetime.utcnow()
            else:
                doc.indexing_status = IndexingStatus.FAILED
            db.commit()
            if doc.indexing_status == IndexingStatus.READY:
                try:
                    client = _get_doc_index_client()
                    _try_sync_context_document_to_neo4j(doc, client)
                except Exception:
                    pass
        db.close()

        if vector_error and doc_index_id:
            logger.info(f"Document {document_id} indexed for GraphIndex; vector indexing failed but document remains usable.")
        elif vector_result or doc_index_id:
            logger.info(f"Document {document_id} indexed successfully")
        else:
            raise RuntimeError("Both GraphIndex and vector indexing failed")

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

    # Save file to disk
    file_path = file_storage.save_file(project_id, file.filename, content)

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

    # Create document record with correct schema
    # Build name, tags and description from metadata
    custom_name = doc_metadata.get("name") if isinstance(doc_metadata, dict) else None
    description = doc_metadata.get("description") if isinstance(doc_metadata, dict) else None
    tags = doc_metadata.get("tags") if isinstance(doc_metadata, dict) else None

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
            status=existing.indexing_status.value,
            message="Document already exists"
        )

    doc = ContextDocument(
        project_id=project_id,
        filename=custom_name or file.filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        document_type=document_type,
        indexing_status=IndexingStatus.NOT_INDEXED,
        content_hash=hashlib.sha256(content).hexdigest(),
        description=description,
        tags=tags or []
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Queue document for embedding generation and indexing
    background_tasks.add_task(index_document_background, doc.id)

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size,
        status=doc.indexing_status,
        message="Document uploaded successfully. Indexing queued."
    )


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

    # Save file to disk
    file_path = file_storage.save_file(project_id, file.filename, content)

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

    # Build metadata
    custom_name = metadata.get("name") if isinstance(metadata, dict) else None
    description = metadata.get("description") if isinstance(metadata, dict) else None
    tags = metadata.get("tags") if isinstance(metadata, dict) else None

    # Create document record
    doc = ContextDocument(
        project_id=project_id,
        filename=custom_name or file.filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        document_type=document_type,
        indexing_status=IndexingStatus.NOT_INDEXED,
        content_hash=hashlib.sha256(content).hexdigest(),
        description=description,
        tags=tags or []
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Queue for indexing
    background_tasks.add_task(index_document_background, doc.id)

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size,
        status=doc.indexing_status,
        message="Document uploaded successfully. Indexing queued."
    )


@router.post("/upload-bulk", response_model=List[DocumentUploadResponse])
async def upload_documents_bulk(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    project_id: int = Form(...),
    extract_archives: bool = Form(True),
    metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload multiple documents or archives for RAG indexing.

    Supports:
    - Multiple file uploads
    - Archive extraction (.zip, .tar, .tar.gz, .tgz)
    - Folder structures (preserves paths as metadata)

    Note: Files should be sent as multipart/form-data with field name 'files'
    """
    import json

    try:
        logger.info(f"Bulk upload request received - project_id={project_id}, extract_archives={extract_archives}")
        logger.info(f"Number of files received: {len(files) if files else 0}")

        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")

        # Parse metadata if provided
        doc_metadata = {}
        if metadata:
            try:
                doc_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning(f"Invalid metadata JSON: {metadata}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk upload validation: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

    uploaded_docs = []

    # Process each file
    for file in files:
        try:
            logger.info(f"Processing file: {file.filename}")

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
                                result = await _process_single_file_for_bulk(
                                    background_tasks, project_id, mock_file, doc_metadata, db
                                )
                                uploaded_docs.append(result)

                    except Exception as e:
                        logger.error(f"Failed to extract archive {file.filename}: {e}")
                        # Upload archive as-is if extraction fails
                        await file.seek(0)
                        result = await _process_single_file_for_bulk(
                            background_tasks, project_id, file, doc_metadata, db
                        )
                        uploaded_docs.append(result)
            else:
                # Regular file upload (no extraction)
                result = await _process_single_file_for_bulk(
                    background_tasks, project_id, file, doc_metadata, db
                )
                uploaded_docs.append(result)

        except Exception as e:
            logger.error(f"Failed to process file {file.filename}: {e}", exc_info=True)
            # Continue with other files
            continue

    logger.info(f"Bulk upload completed: {len(uploaded_docs)} documents uploaded")
    return uploaded_docs


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

    # 2. Neo4j — get the canonical file_path by (project_id, name)
    from services.neo4j_document_index import Neo4jDocumentIndex
    neo = Neo4jDocumentIndex()
    neo_doc = neo.get_document(project_id=doc.project_id, name=doc.original_filename or doc.filename)
    if not neo_doc or not neo_doc.file_path:
        raise HTTPException(
            status_code=404,
            detail=f"Document not indexed in GraphIndex (Neo4j). "
                   f"Ingest it via the Studio or run cmd_ingest in phase9.",
        )

    file_path = Path(neo_doc.file_path)
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
            from services.doc_index_service import DocIndexClient
            import os

            # DEBUG: log the incoming request
            logger.info(f"[DEBUG] GraphIndex search request: query={request.query!r}, project_id={request.project_id}, top_k={request.top_k}")

            # Use the base outputs directory as DocIndex workspace
            # (DocIndexClient appends /doc_index internally)
            doc_index_base = os.environ.get(
                "DOC_INDEX_BASE",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "outputs")
            )
            client = DocIndexClient(doc_index_base)

            neo4j_result = _try_graphindex_search_via_neo4j(
                project_id=request.project_id,
                query=request.query,
                top_k=request.top_k,
                client=client,
            )
            if neo4j_result is not None:
                return neo4j_result
            
            # Get all doc_index_ids for the current project (with description and tags)
            project_docs = db.query(ContextDocument).filter(
                ContextDocument.project_id == request.project_id,
                ContextDocument.doc_index_id.isnot(None)
            ).all()
            # Create a map from doc_index_id to ContextDocument (for description and tags)
            project_doc_map = {doc.doc_index_id: doc for doc in project_docs}
            
            scored_documents = []
            for doc_id, meta in client.list_all().items():
                # Only include documents from the current project
                if doc_id not in project_doc_map:
                    continue
                    
                structure = client.get_document_structure(doc_id)
                context_doc = project_doc_map[doc_id]
                score = _score_graphindex_document(request.query, meta, context_doc)

                if score > 0:
                    scored_documents.append((-score, doc_id, meta, structure))  # Negative for ascending sort
            
            # Sort by score descending and take top N
            scored_documents.sort()
            top_docs = []
            for _, doc_id, meta, structure in scored_documents[:request.top_k]:
                    context_doc = project_doc_map.get(doc_id)
                    top_docs.append(GraphIndexDocItem(
                    doc_id=doc_id,
                    doc_name=meta.get("doc_name", "Unknown"),
                    type=meta.get("type", "unknown"),
                    page_count=meta.get("page_count", 0),
                    structure=structure[:20] if isinstance(structure, list) else [],  # Limit structure output
                    context_doc_id=context_doc.id if context_doc else None,
                ))

            return GraphIndexSearchResponse(
                query=request.query,
                search_mode="graphindex",
                documents=top_docs,
                total_documents=len(top_docs),
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
            top_k=request.top_k
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
def _get_doc_index_client():
    """Helper to get DocIndexClient instance"""
    import os
    from services.doc_index_service import DocIndexClient
    doc_index_base = os.environ.get(
        "DOC_INDEX_BASE",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "outputs")
    )
    return DocIndexClient(doc_index_base)


def _get_doc_index_id_from_context_id(context_doc_id: int, db: Session) -> str:
    """Helper to get DocIndex ID from ContextDocument ID"""
    doc = db.query(ContextDocument).filter(ContextDocument.id == context_doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.doc_index_id:
        raise HTTPException(status_code=404, detail="Document not indexed in GraphIndex")
    return doc.doc_index_id


def _load_full_content_for_kv(context_doc: ContextDocument, client) -> tuple[str, str, int, str]:
    from pathlib import Path

    if context_doc.doc_index_id:
        full_doc = client.get_full_content(context_doc.doc_index_id)
        if isinstance(full_doc, dict) and "error" not in full_doc:
            pages = full_doc.get("pages", [])
            full_content = "\n\n".join(
                f"[Page {page.get('page', '?')}]\n{page.get('content', '')}"
                for page in pages
                if page.get("content")
            )
            if full_content.strip():
                doc_id = str(full_doc.get("id") or context_doc.doc_index_id)
                doc_name = str(full_doc.get("doc_name") or context_doc.filename)
                return doc_id, doc_name, len(pages), full_content

    file_path = (context_doc.file_path or "").strip()
    if not file_path:
        raise HTTPException(status_code=400, detail="Document has no file_path and no GraphIndex content")

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".html", ".xml"}:
        full_content = path.read_text(encoding="utf-8", errors="ignore")
        if not full_content.strip():
            raise HTTPException(status_code=400, detail="Document file has no readable text content")
        return f"context:{context_doc.id}", context_doc.filename, 0, full_content

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_texts: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                page_texts.append(f"[Page {idx}]\n{text}")
        full_content = "\n\n".join(page_texts)
        if not full_content.strip():
            raise HTTPException(status_code=400, detail="PDF has no extractable text content")
        return f"context:{context_doc.id}", context_doc.filename, len(reader.pages), full_content

    data = path.read_bytes()
    try:
        full_content = data.decode("utf-8", errors="ignore")
    except Exception:
        full_content = ""
    if not full_content.strip():
        raise HTTPException(status_code=400, detail="Document file has no extractable text content")
    return f"context:{context_doc.id}", context_doc.filename, 0, full_content


@router.get("/documents/{context_doc_id}/graphindex/structure", response_model=GraphIndexStructureResponse)
async def get_document_structure(
    context_doc_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the Table of Contents structure of a document using ContextDocument ID.
    Part of the progressive disclosure workflow.
    """
    doc_index_id = _get_doc_index_id_from_context_id(context_doc_id, db)
    client = _get_doc_index_client()
    
    doc_info = client.get_document(doc_index_id)
    structure = client.get_document_structure(doc_index_id)
    
    if "error" in doc_info:
        raise HTTPException(status_code=404, detail=doc_info["error"])
    
    # Map 'id' to 'doc_id' for the schema
    doc_info_copy = doc_info.copy()
    doc_info_copy["doc_id"] = doc_info_copy.pop("id")
    
    return GraphIndexStructureResponse(
        **doc_info_copy,
        structure=structure
    )


@router.get("/documents/{context_doc_id}/graphindex/full", response_model=GraphIndexFullDocumentResponse)
async def get_document_full_content(
    context_doc_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the full content of a document (all pages) using ContextDocument ID.
    Use this once the right document is selected via progressive disclosure.
    """
    doc_index_id = _get_doc_index_id_from_context_id(context_doc_id, db)
    client = _get_doc_index_client()
    
    full_doc = client.get_full_content(doc_index_id)
    if "error" in full_doc:
        raise HTTPException(status_code=404, detail=full_doc["error"])
    
    # Map 'id' to 'doc_id' for the schema
    full_doc_copy = full_doc.copy()
    full_doc_copy["doc_id"] = full_doc_copy.pop("id")
    
    return GraphIndexFullDocumentResponse(**full_doc_copy)


class DocumentPreviewResponse(BaseModel):
    """Document preview data"""
    doc_id: str
    context_doc_id: int
    doc_name: str
    type: str
    page_count: int
    content_preview: str
    has_more: bool
    total_chars: int


@router.get("/documents/{context_doc_id}/preview", response_model=DocumentPreviewResponse)
async def preview_document(
    context_doc_id: int,
    max_chars: int = 2000,
    db: Session = Depends(get_db)
):
    """
    Get a preview of a document (first N chars of content + metadata).
    """
    from models.core import ContextDocument
    doc = db.query(ContextDocument).filter(ContextDocument.id == context_doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    client = _get_doc_index_client()
    doc_id_str, doc_name, page_count, full_content = _load_full_content_for_kv(doc, client)
    preview = full_content[:max_chars]
    has_more = len(full_content) > max_chars

    return DocumentPreviewResponse(
        doc_id=doc_id_str,
        context_doc_id=context_doc_id,
        doc_name=doc_name,
        type=doc.document_type.value if hasattr(doc.document_type, 'value') else str(doc.document_type),
        page_count=page_count,
        content_preview=preview,
        has_more=has_more,
        total_chars=len(full_content),
    )

@router.post("/graphindex/answer", response_model=GraphIndexAnswerResponse)
async def answer_with_graphindex(
    request: GraphIndexAnswerRequest,
    db: Session = Depends(get_db)
):
    """
    Answer a query using the full content of a selected or auto-matched GraphIndex document.

    This is the KV-style flow:
    - key: selected/found document
    - value: full document content
    """
    from api.models.routes import _create_llm_for_playground, _resolve_model_name

    client = _get_doc_index_client()
    context_doc, _ = _resolve_graphindex_target_document(request, db, client)
    doc_id, doc_name, pages_loaded, full_content = _load_full_content_for_kv(context_doc, client)

    # Read default and fallback models from PostgreSQL settings (no hardcoded model names)
    from models.settings import Settings as SettingsModel
    settings_row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    db_fallback_models: list = (settings_row.fallback_models or []) if settings_row else []
    models_to_try = ([request.model] if request.model else [])
    if not models_to_try:
        # No explicit model requested: use DB default first, then DB fallbacks
        default = _resolve_model_name(None, db)
        models_to_try = [default] + db_fallback_models
    else:
        # Explicit model requested: try it, then DB fallbacks
        models_to_try = models_to_try + db_fallback_models

    model_name = None
    llm = None
    last_error = None
    for mname in models_to_try:
        try:
            model_name = _resolve_model_name(mname, db)
            llm = _create_llm_for_playground(
                model_name=model_name,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                db=db,
            )
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Model {mname} failed: {e}")
            continue
    if llm is None:
        raise HTTPException(status_code=400, detail=str(last_error or "No working model available"))

    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = (
        "You answer questions using one selected document only.\n"
        "Treat the document as a key-value source where the key is the document identity "
        "and the value is the full document content loaded below.\n"
        "Do not use outside knowledge. If the answer is not in the document, say so clearly."
    )
    user_prompt = (
        f"Document key: {context_doc.filename}\n"
        f"Document description: {context_doc.description or 'N/A'}\n"
        f"User query: {request.query}\n\n"
        f"Full document value:\n{full_content}"
    )
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])

    return GraphIndexAnswerResponse(
        query=request.query,
        context_doc_id=context_doc.id,
        doc_id=doc_id,
        doc_name=doc_name,
        model=model_name,
        answer=response.content if isinstance(response.content, str) else str(response.content),
        pages_loaded=pages_loaded,
        content_chars=len(full_content),
    )


@router.get("/documents/{context_doc_id}/graphindex/pages/{pages}", response_model=List[GraphIndexPage])
async def get_document_pages(
    context_doc_id: int,
    pages: str,
    db: Session = Depends(get_db)
):
    """
    Get specific pages of a document using ContextDocument ID.
    Pages format: '5-7', '3,8', or '12' (1-indexed).
    """
    doc_index_id = _get_doc_index_id_from_context_id(context_doc_id, db)
    client = _get_doc_index_client()
    
    page_content = client.get_page_content(doc_index_id, pages)
    if page_content and len(page_content) > 0 and "error" in page_content[0]:
        raise HTTPException(status_code=404, detail=page_content[0]["error"])
    
    return page_content


@router.get("/projects/{project_id}/storage-stats")
async def get_project_storage_stats(
    project_id: int,
    db: Session = Depends(get_db)
):
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
