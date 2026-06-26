#!/usr/bin/env python3
"""
Phase 9 / Step A1 — LangChain tool wrappers around Neo4j catalog + filesystem reads.

These tools are consumed by the query_agent.py DeepAgent (router / loader /
answerer subagents). The same primitives also exist as plain functions in
route_semantic.py — those power the legacy llm.invoke() code path; this
file is the LangChain-tool version for the deepagent code path.

Per rules.md: tools are stateful only via Neo4j + filesystem, no in-memory
state. Safe to call from multiple subagents concurrently.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

# Repo + backend path resolution (works in script and REPL)
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))

from langchain_core.tools import tool  # noqa: E402

from services.neo4j_document_index import Neo4jDocumentIndex  # noqa: E402

# Reuse the catalog + file reader logic from route_semantic to keep
# one source of truth for "how to read a doc" and "how to format catalog".
from route_semantic import (  # noqa: E402
    fetch_catalog as _fetch_catalog,
    format_catalog as _format_catalog,
    _file_path_for as _file_path_for,
    _read_doc_text as _read_doc_text,
    SUPPORTING_MAX_CHARS,
    PRIMARY_MAX_CHARS,
)

# --- Module-level singletons (lazy init, reused across subagent calls) ---

_IDX: Optional[Neo4jDocumentIndex] = None
_PROJECT_ID = 1


def _idx() -> Neo4jDocumentIndex:
    global _IDX
    if _IDX is None:
        _IDX = Neo4jDocumentIndex(
            base_url=os.getenv("NEO4J_URL", "http://localhost:7474"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
        )
    return _IDX


# --- Tool 1: fetch_catalog_tool -------------------------------------------

@tool
def fetch_catalog_tool(project_id: int = 1,
                       limit_chars: int = 200_000) -> str:
    """Fetch the document catalog (names + about + supported_queries +
    out_of_scope + nested exclude metadata) for a project, formatted as
    a human-readable string the LLM can read directly.

    Args:
        project_id: Neo4j project id (default 1).
        limit_chars: Truncate the formatted catalog at this many chars.

    Returns:
        Formatted catalog text. Returns "NO_DOCS" if the project has none.
    """
    idx = _idx()
    rows = _fetch_catalog(idx, project_id)
    if not rows:
        return "NO_DOCS"
    text = _format_catalog(rows)
    if len(text) > limit_chars:
        text = text[:limit_chars] + f"\n... [truncated at {limit_chars:,} chars]"
    return text


# --- Tool 2: read_doc_tool ------------------------------------------------

@tool
def read_doc_tool(name: str, max_chars: int = 30_000) -> str:
    """Read a single document's content from filesystem (PDF / MD / TXT).

    Use max_chars=30000 for primary docs and max_chars=15000 for supporting
    docs to control context size.

    Args:
        name: Exact document name (e.g. "nke-10k-2023.pdf").
        max_chars: Hard cap on returned characters.

    Returns:
        The document text with --- Page N --- markers, or an error string
        if the file is missing.
    """
    idx = _idx()
    path = _file_path_for(idx, _PROJECT_ID, name)
    if not path:
        return f"ERROR: doc {name!r} has no file_path in Neo4j"
    text = _read_doc_text(path, max_chars)
    if not text:
        return f"ERROR: no extractable text from {name!r}"
    return text


# --- Tool 3: list_docs_tool ----------------------------------------------

@tool
def list_docs_tool(project_id: int = 1) -> List[str]:
    """List all document names in a project. Cheap to call.

    Args:
        project_id: Neo4j project id (default 1).

    Returns:
        List of document names.
    """
    idx = _idx()
    rows = _fetch_catalog(idx, project_id)
    return [r["name"] for r in rows]


# --- Tool 4: load_multi_doc_tool -----------------------------------------

@tool
def load_multi_doc_tool(primary: str,
                         supporting: Optional[List[str]] = None) -> str:
    """Load primary + supporting documents into a single context string.

    Use this when you need to combine several documents before asking the
    LLM to synthesize an answer. Caps: primary=30K chars, each
    supporting=15K chars.

    Args:
        primary: Exact name of the main document.
        supporting: Optional list of supplementary doc names.

    Returns:
        Concatenated text with per-doc headers ("=== Document N ... ===").
    """
    idx = _idx()
    parts: List[str] = []

    primary_path = _file_path_for(idx, _PROJECT_ID, primary)
    primary_text = _read_doc_text(primary_path, PRIMARY_MAX_CHARS)
    if primary_text:
        parts.append(f"=== Document 1 (PRIMARY): {primary} ===\n{primary_text}")
    else:
        parts.append(f"=== Document 1 (PRIMARY): {primary} ===\n(no extractable text)")

    for i, name in enumerate(supporting or [], start=2):
        path = _file_path_for(idx, _PROJECT_ID, name)
        text = _read_doc_text(path, SUPPORTING_MAX_CHARS)
        if text:
            parts.append(f"=== Document {i} (SUPPORTING): {name} ===\n{text}")
        else:
            parts.append(f"=== Document {i} (SUPPORTING): {name} ===\n(no extractable text)")

    return "\n\n".join(parts)


# --- Tool registry (convenience for agent construction) ------------------

ALL_TOOLS = [
    fetch_catalog_tool,
    read_doc_tool,
    list_docs_tool,
    load_multi_doc_tool,
]


if __name__ == "__main__":
    # Quick smoke test
    print(fetch_catalog_tool.invoke({"project_id": 1, "limit_chars": 500}))
    print("---")
    print(read_doc_tool.invoke({"name": "6 人物库.pdf", "max_chars": 300}))