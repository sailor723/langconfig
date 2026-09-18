# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""RAG document endpoints (uploads, documents, search).

Split out of api/knowledge/rag.py. The package __init__ is the sole
aggregator: it owns the "/api/rag" prefixed router and includes each
sub-module's router. Sub-modules import only from siblings (never from
this __init__), so include_router cannot silently drop routes.
"""
import logging
import os as _os
import sys as _sys

# Phase 9 integration: ensure learning/phase9/ is on sys.path so the
# lazy graphindex imports inside endpoint bodies resolve correctly.
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in _sys.path and _os.path.isdir(_REPO_ROOT):
    _sys.path.insert(0, _REPO_ROOT)
_PHASE9_DIR = _os.path.join(_REPO_ROOT, "learning", "phase9")
if _PHASE9_DIR not in _sys.path and _os.path.isdir(_PHASE9_DIR):
    _sys.path.insert(0, _PHASE9_DIR)

from fastapi import APIRouter

logger = logging.getLogger("api.knowledge.rag")

from . import documents, helpers, search, uploads
from .documents import (delete_document, get_document, get_document_content,
                        get_document_file, list_documents)
from .helpers import (SUPPORTED_GRAPHINDEX_EXTS, _extract_text_for_viewer,
                      _is_graphindexable, _queue_graphindex_ingest,
                      index_document_background)
from .schemas import (DocumentContentResponse, DocumentResponse,
                      DocumentUploadResponse, GraphIndexDocItem,
                      GraphIndexSearchResponse, SearchHistoryResponse,
                      SearchMetrics, SearchRequest, SearchResponse, SearchResult)
from .search import get_search_history, index_document, search_documents
from .uploads import (_parse_hierarchy_from_path, _process_single_file_for_bulk,
                      ingest_folder_from_path, upload_document,
                      upload_documents_bulk)

# Sole router aggregator: carries the /api/rag prefix; sub-module routers
# are prefix-less so the prefix does not stack.
router = APIRouter(prefix="/api/rag", tags=["rag"])
router.include_router(uploads.router)
router.include_router(documents.router)
router.include_router(search.router)

__all__ = [
    "router",
    "logger",
    # schemas
    "DocumentUploadResponse", "DocumentResponse", "SearchRequest",
    "SearchResult", "SearchMetrics", "SearchResponse", "GraphIndexDocItem",
    "GraphIndexSearchResponse", "DocumentContentResponse",
    "SearchHistoryResponse",
    # constants + helpers
    "SUPPORTED_GRAPHINDEX_EXTS", "_is_graphindexable", "_queue_graphindex_ingest",
    "index_document_background", "_extract_text_for_viewer",
    # upload endpoints
    "upload_document", "_parse_hierarchy_from_path", "_process_single_file_for_bulk",
    "upload_documents_bulk", "ingest_folder_from_path",
    # document endpoints
    "list_documents", "get_document", "get_document_file",
    "get_document_content", "delete_document",
    # search endpoints
    "search_documents", "index_document", "get_search_history",
]
