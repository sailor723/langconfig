# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Document CRUD/content endpoints for the api.knowledge.rag package.

Split out of api/knowledge/rag.py; moved verbatim. Registered on the
prefix-less sub-router included by the package __init__ under /api/rag.
"""
import mimetypes
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.core import ContextDocument, IndexingStatus

from .helpers import _extract_text_for_viewer
from .schemas import DocumentContentResponse, DocumentResponse
from .shared import logger

router = APIRouter(tags=["rag"])

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
