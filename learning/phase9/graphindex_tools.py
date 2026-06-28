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

import json
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Iterable, List, Optional

# Repo + backend path resolution (works in script and REPL)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langchain_core.tools import tool  # noqa: E402

from services.neo4j_document_index import Neo4jDocumentIndex  # noqa: E402

# Reuse the catalog + file reader logic from route_semantic to keep
# one source of truth for "how to read a doc" and "how to format catalog".
from legacy.route_semantic import (  # noqa: E402
    fetch_catalog as _fetch_catalog,
    format_catalog as _format_catalog,
    _file_path_for as _file_path_for,
    _read_doc_text as _read_doc_text,
    SUPPORTING_MAX_CHARS,
    PRIMARY_MAX_CHARS,
    route_by_llm as _route_by_llm,
    make_llm as _make_routing_llm,
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


# ---------------------------------------------------------------------------
# Active doc scope (per-request, set by stream_graphindex_chat)
# ---------------------------------------------------------------------------
# When non-None, all 5 tools only see / read docs whose name is in this set.
# Carried via ContextVar so the LLM-facing tool signatures don't have to
# expose a `scope` argument (keeps the agent's prompt cache hot).
#
#   None              → no filter, all docs visible (current behavior)
#   set([...])        → only these doc names are visible
# ---------------------------------------------------------------------------
_active_doc_scope: ContextVar[Optional[set]] = ContextVar(
    "active_doc_scope", default=None
)


def set_active_doc_scope(scope) -> object:
    """Set the active doc scope. Returns a token to pass to reset_active_doc_scope.

    Accepts:
      None             → no filter
      [] / "all"       → no filter
      [name1, name2]   → only these doc names
    """
    if scope is None or scope == "all" or (isinstance(scope, (list, tuple, set)) and len(scope) == 0):
        return _active_doc_scope.set(None)
    return _active_doc_scope.set(set(scope))


def reset_active_doc_scope(token) -> None:
    """Restore the previous scope (use with the token from set_active_doc_scope)."""
    _active_doc_scope.reset(token)


def get_active_doc_scope() -> Optional[set]:
    """Return the current active doc scope (or None = no filter)."""
    return _active_doc_scope.get()


def _filter_rows_by_scope(rows: list, scope: Optional[set]) -> list:
    """Apply the active scope to a list of catalog rows. Unknown names are dropped."""
    if scope is None:
        return rows
    return [r for r in rows if r.get("name") in scope]


# --- Tool 1: fetch_catalog_tool -------------------------------------------

@tool
def fetch_catalog_tool(project_id: int = 1,
                       limit_chars: int = 200_000) -> str:
    """Fetch the document catalog (names + about + supported_queries +
    out_of_scope + nested exclude metadata) for a project, formatted as
    a human-readable string the LLM can read directly.

    If the caller has set an active doc scope (via
    `set_active_doc_scope`), only the in-scope docs are returned.

    Args:
        project_id: Neo4j project id (default 1).
        limit_chars: Truncate the formatted catalog at this many chars.

    Returns:
        Formatted catalog text. Returns "NO_DOCS" if the project has none
        (or none match the active scope).
    """
    idx = _idx()
    rows = _fetch_catalog(idx, project_id)
    rows = _filter_rows_by_scope(rows, get_active_doc_scope())
    if not rows:
        return "NO_DOCS"
    text = _format_catalog(rows)
    if len(text) > limit_chars:
        text = text[:limit_chars] + f"\n... [truncated at {limit_chars:,} chars]"
    return text


# --- Tool 2: read_doc_tool ------------------------------------------------

@tool
def read_doc_tool(name: str, max_chars: int = 10_000_000) -> str:
    """Read a single document's content from filesystem (PDF / MD / TXT).

    The default max_chars=10_000_000 is effectively no cap for normal
    documents (10-K, contracts, reports) — the LLM will see the full
    document in one call. MiniMax M3 supports 1M-token context. Use
    a smaller value if you want to limit context size manually.

    If the caller has set an active doc scope, this tool refuses to
    read docs outside the scope (returns a SCOPE_ERROR string).

    Args:
        name: Exact document name (e.g. "nke-10k-2023.pdf").
        max_chars: Hard cap on returned characters (default 10M).

    Returns:
        The document text with --- Page N --- markers, or an error string
        if the file is missing or the doc is outside the active scope.
    """
    scope = get_active_doc_scope()
    if scope is not None and name not in scope:
        return (
            f"SCOPE_ERROR: doc {name!r} is not in the active scope. "
            f"Active scope contains {len(scope)} doc(s)."
        )
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

    If the caller has set an active doc scope, only in-scope names
    are returned.

    Args:
        project_id: Neo4j project id (default 1).

    Returns:
        List of document names.
    """
    idx = _idx()
    rows = _fetch_catalog(idx, project_id)
    rows = _filter_rows_by_scope(rows, get_active_doc_scope())
    return [r["name"] for r in rows]


# --- Tool 4: load_multi_doc_tool -----------------------------------------

@tool
def load_multi_doc_tool(primary: str,
                         supporting: Optional[List[str]] = None) -> str:
    """Load primary + supporting documents into a single context string.

    Use this when you need to combine several documents before asking the
    LLM to synthesize an answer. By default both primary and supporting
    docs are read in FULL (no effective cap, just a 10M-char safety
    net). MiniMax M3 supports 1M-token context, so even a 500-page
    primary + 3 supporting docs will fit in one call.

    If the caller has set an active doc scope, docs outside the scope
    are replaced with a SCOPE_ERROR placeholder in the returned string.

    Args:
        primary: Exact name of the main document.
        supporting: Optional list of supplementary doc names.

    Returns:
        Concatenated text with per-doc headers ("=== Document N ... ===").
    """
    idx = _idx()
    scope = get_active_doc_scope()
    parts: List[str] = []

    if scope is not None and primary not in scope:
        parts.append(
            f"=== Document 1 (PRIMARY): {primary} ===\n"
            f"SCOPE_ERROR: doc {primary!r} is not in the active scope."
        )
    else:
        primary_path = _file_path_for(idx, _PROJECT_ID, primary)
        primary_text = _read_doc_text(primary_path, PRIMARY_MAX_CHARS)
        if primary_text:
            parts.append(f"=== Document 1 (PRIMARY): {primary} ===\n{primary_text}")
        else:
            parts.append(f"=== Document 1 (PRIMARY): {primary} ===\n(no extractable text)")

    for i, name in enumerate(supporting or [], start=2):
        if scope is not None and name not in scope:
            parts.append(
                f"=== Document {i} (SUPPORTING): {name} ===\n"
                f"SCOPE_ERROR: doc {name!r} is not in the active scope."
            )
            continue
        path = _file_path_for(idx, _PROJECT_ID, name)
        text = _read_doc_text(path, SUPPORTING_MAX_CHARS)
        if text:
            parts.append(f"=== Document {i} (SUPPORTING): {name} ===\n{text}")
        else:
            parts.append(f"=== Document {i} (SUPPORTING): {name} ===\n(no extractable text)")

    return "\n\n".join(parts)


# --- Tool 5: route_query_tool --------------------------------------------

@tool
def route_query_tool(query: str, project_id: int = 1) -> str:
    """Find the top 1-3 documents that best match a user query (progressive
    disclosure: the small "what exists" step before loading full text).

    This tool performs **LLM semantic routing**: it loads the project's
    catalog (name + about + supported_queries + excludes) and asks an LLM
    to pick the best primary doc plus 0-3 cross-domain supporting docs.

    Call this FIRST when answering a user question, then pass the
    returned names to load_multi_doc_tool.

    If the caller has set an active doc scope, the catalog fed to the
    LLM is pre-filtered to in-scope docs only. If the scope is empty
    for this project, returns `{"primary": null, "reasoning": "NO_DOCS_IN_SCOPE"}`.

    Args:
        query: The user's natural-language question.
        project_id: Neo4j project id (default 1).

    Returns:
        JSON string with shape:
          {
            "primary": "<exact doc name>",
            "primary_domain": "<short tag>",
            "primary_confidence": 0.0-1.0,
            "supporting": [{"name": "<exact doc name>", "reason": "..."}],
            "reasoning": "<one short sentence>",
            "cache_read_tokens": <int>
          }
        or
          {
            "primary": null,
            "reasoning": "<why no doc matches>",
            "cache_read_tokens": <int>
          }
    """
    idx = _idx()
    rows = _fetch_catalog(idx, project_id)
    rows = _filter_rows_by_scope(rows, get_active_doc_scope())
    if not rows:
        return json.dumps({
            "primary": None,
            "reasoning": "NO_DOCS_IN_SCOPE",
            "cache_read_tokens": 0,
        })
    # Use the same routing LLM as the legacy route_semantic.py path
    routing_llm = _make_routing_llm()
    decision, cache_read = _route_by_llm(query, rows, routing_llm)
    return json.dumps({
        "primary": decision.primary,
        "primary_domain": decision.primary_domain,
        "primary_confidence": decision.primary_confidence,
        "supporting": [
            {"name": s.name, "reason": s.reason} for s in decision.supporting
        ],
        "reasoning": decision.reasoning,
        "cache_read_tokens": cache_read,
    }, ensure_ascii=False)


# --- Tool registry (convenience for agent construction) ------------------

ALL_TOOLS = [
    fetch_catalog_tool,
    read_doc_tool,
    list_docs_tool,
    load_multi_doc_tool,
    route_query_tool,
]


if __name__ == "__main__":
    # Quick smoke test
    print(fetch_catalog_tool.invoke({"project_id": 1, "limit_chars": 500}))
    print("---")
    print(read_doc_tool.invoke({"name": "6 人物库.pdf", "max_chars": 300}))