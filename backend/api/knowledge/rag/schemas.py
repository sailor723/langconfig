# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Pydantic schemas for the api.knowledge.rag package.

Split out of api/knowledge/rag.py; moved verbatim.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from models.core import DocumentType, IndexingStatus

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
