# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Search/indexing endpoints for the api.knowledge.rag package.

Split out of api/knowledge/rag.py; moved verbatim. Registered on the
prefix-less sub-router included by the package __init__ under /api/rag.
"""
import time
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.core import (ContextDocument, IndexingStatus, Project,
                         SearchHistory)
from services.token_counter import get_token_counter

from .helpers import index_document_background
from .schemas import (GraphIndexDocItem, GraphIndexSearchResponse,
                      SearchHistoryResponse, SearchMetrics, SearchRequest,
                      SearchResponse, SearchResult)
from .shared import logger

# Single source of truth for Neo4j HTTP connection config — read
# from the project-root .env via the centralized connection module.
from langgraph.connection import (
    NEO4J_HTTP_URL,
    NEO4J_HTTP_USER,
    NEO4J_HTTP_PASSWORD,
)


router = APIRouter(tags=["rag"])

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
                base_url=_NEO4J_HTTP_URL,
                username=_NEO4J_HTTP_USER,
                password=_NEO4J_HTTP_PASSWORD,
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
