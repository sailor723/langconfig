#!/usr/bin/env python3
"""
Phase 9 / Step 2.6 — semantic LLM-based doc routing.

Builds a one-shot catalog from Neo4j (each doc's routing metadata),
then asks an LLM to pick the best document for a query.

This is progressive disclosure: the catalog is the small "what exists"
view, and only the chosen doc's full content is loaded afterward.

Per rules.md:
  - No truncation, no chunking, no embeddings.
  - MiniMax M3 via init_chat_model.
  - Standalone script (no FastAPI / live Neo4j / DB).

Usage:
  # Route a single query
  python phase9/route_semantic.py --query "苏格拉底思想"

  # Compare string-matching vs LLM routing
  python phase9/route_semantic.py --query "..." --compare

  # Pretty-print the catalog
  python phase9/route_semantic.py --show-catalog
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# .env resolution (works as script AND in REPL)
try:
    _env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    choose_best_document_match,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
import fitz  # noqa: E402  (PyMuPDF for PDF text extraction)

# --- SESSION_START (runtime state — must stay in code, not .env) ------------
SESSION_START = time.time()


def fetch_catalog(idx: Neo4jDocumentIndex, project_id: int,
                  doc_scope: str = "all") -> List[Dict[str, Any]]:
    """Pull docs (all or scoped) as routing metadata rows.

    If *doc_scope* is ``"all"`` (the default), returns ALL docs in the project.
    Otherwise it's treated as a JSON array of doc names to scope to.
    """
    if doc_scope == "all":
        cypher = """
MATCH (d:Document {project_id: $pid})
RETURN d.name AS name,
       d.context_doc_id AS cid,
       d.file_path AS fp,
       COALESCE(d.what_this_document_is_about, d.content_preview, '') AS about,
       COALESCE(d.supported_queries, d.search_terms, []) AS supports
ORDER BY d.name
"""
        return idx._run_cypher(cypher, {"pid": project_id})

    # Scoped: filter by doc names (use CONTAINS to handle invisible Unicode chars)
    scope_list: List[str] = json.loads(doc_scope) if isinstance(doc_scope, str) else doc_scope
    # Build a CONTAINS filter for each scope name
    contains_filters = " OR ".join(f"d.name CONTAINS $s{i}" for i in range(len(scope_list)))
    params = {"pid": project_id, "scope_list": scope_list}
    for i, name in enumerate(scope_list):
        params[f"s{i}"] = name
    cypher = f"""
MATCH (d:Document {{project_id: $pid}})
WHERE {contains_filters}
RETURN d.name AS name,
       d.context_doc_id AS cid,
       d.file_path AS fp,
       COALESCE(d.what_this_document_is_about, d.content_preview, '') AS about,
       COALESCE(d.supported_queries, d.search_terms, []) AS supports
ORDER BY d.name
"""
    return idx._run_cypher(cypher, params)


# --- Multi-doc load + combined answer ---------------------------------------

# Per-doc char limits. Primary gets more because it's the main source;
# supporting docs are reference material so we cap them tighter.
# Bumped from 30K/15K → 200K/80K → 10M/10M (effectively no cap).
# MiniMax M3 supports 1M-token context, so the old caps forced the
# LLM to take a second turn to read the rest of long docs. The 10M
# here is just a safety net to prevent OOM on truly gigantic files
# (a 5000-page manual would still hit this). For normal documents
# (10-K, contracts, reports) the full text is loaded in one call.
_PRIMARY_MAX_CHARS = int(os.getenv("GRAPHINDEX_PRIMARY_MAX_CHARS", "10000000"))
_SUPPORTING_MAX_CHARS = int(os.getenv("GRAPHINDEX_SUPPORTING_MAX_CHARS", "10000000"))

# Cache file_path lookups so we don't hit Neo4j per doc.
# Key is (project_id, name) so docs with the same name from
# different projects don't collide. Without this, looking up
# "foo.pdf" in project 1 (which doesn't have it) would cache
# the empty path, and the same lookup in project 8 would
# return the stale empty path instead of the real file_path.
_FILE_PATH_CACHE: Dict[tuple, str] = {}


def _read_doc_text(file_path: str, max_chars: int) -> str:
    """Read PDF / MD / TXT up to max_chars. Returns "" if file is missing."""
    if not file_path or not Path(file_path).exists():
        return ""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        out: List[str] = []
        total = 0
        for i in range(len(doc)):
            if total >= max_chars:
                out.append(f"\n... [truncated after page {i+1}/{len(doc)}]")
                break
            page_text = doc[i].get_text("text").strip()
            if page_text:
                chunk = f"--- Page {i+1}/{len(doc)} ---\n{page_text}"
                out.append(chunk)
                total += len(chunk)
        doc.close()
        return "\n\n".join(out)
    # Plain text fallback
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars]


def _file_path_for(index: Neo4jDocumentIndex, project_id: int, name: str) -> str:
    """Look up file_path from Neo4j, with in-memory cache.
    Cache key is (project_id, name) so the same name from different
    projects is cached separately (see _FILE_PATH_CACHE docstring)."""
    key = (project_id, name)
    if key in _FILE_PATH_CACHE:
        return _FILE_PATH_CACHE[key]
    node = index.get_document(project_id=project_id, name=name)
    path = node.file_path if node else ""
    _FILE_PATH_CACHE[key] = path
    return path


def load_doc_context(
    index: Neo4jDocumentIndex,
    project_id: int,
    doc_names: List[str],
    reasons: Optional[Dict[str, str]] = None,
) -> str:
    """Concatenate matched docs into a single human-readable string.

    Reads full text for each document, ordered by relevance (best first).
    First doc is marked PRIMARY, rest are SUPPORTING with their reason.
    """
    parts: List[str] = []
    for i, name in enumerate(doc_names, start=1):
        path = _file_path_for(index, project_id, name)
        max_chars = _PRIMARY_MAX_CHARS if i == 1 else _SUPPORTING_MAX_CHARS
        text = _read_doc_text(path, max_chars)
        label = "PRIMARY" if i == 1 else "SUPPORTING"
        reason = (reasons or {}).get(name, "")
        reason_line = f"\n[Reason: {reason}]" if reason else ""
        parts.append(
            f"=== Document {i} ({label}): {name} ==={reason_line}\n{text}"
            if text else
            f"=== Document {i} ({label}): {name} ==={reason_line}\n(no extractable text)"
        )
    return "\n\n".join(parts)


ANSWER_SYSTEM_TEMPLATE = """You are a document-grounded analyst. Answer the user's question using the provided documents.

Rules:
1. Use ONLY the supplied documents. If the answer is not present, say so.
2. Cite document + page for every claim, e.g. "(Document 1, page 3)".
3. If multiple documents are listed, weave them together — note where they
   agree, disagree, or complement each other.
4. If supporting documents are included for context, mention when a supporting
   doc adds information that the primary doesn't have.
"""


def answer_from_docs(
    query: str,
    combined_context: str,
    llm: BaseChatModel,
) -> tuple[str, int]:
    """Run the final synthesis LLM call over the combined context. Returns
    (answer, cache_read_tokens). The combined_context is part of the user
    message, so it changes per query — no cache hit here."""
    resp = llm.invoke([
        SystemMessage(content=ANSWER_SYSTEM_TEMPLATE),
        HumanMessage(content=(
            f"Question:\n{query}\n\n"
            f"--- Documents ---\n\n{combined_context}"
        )),
    ])
    answer = resp.content if isinstance(resp.content, str) else str(resp.content)
    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return answer, cache_read


