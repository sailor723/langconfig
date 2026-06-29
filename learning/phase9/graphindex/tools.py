#!/usr/bin/env python3
"""
Phase 9 / tools — tool functions for the DeepAgent chat.

These are the building blocks exposed to the agent. Each function
wraps a Phase 9 legacy operation (listing, routing, reading, answering).

The agent calls these via ``StructuredTool`` wrappers injected into
``create_deep_agent()``.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool

from learning.phase9.graphindex.build_index import Neo4jDocumentIndex
from learning.phase9.graphindex.route import (
    fetch_catalog,
    load_doc_context,
    make_routing_llm,
    make_answer_llm,
    MatchedDoc,
    route_by_llm,
    _file_path_for,
    _read_doc_text,
)


# ---------------------------------------------------------------------------
# Request-scoped ContextVars (set per-request by the backend)
# ---------------------------------------------------------------------------

_active_project_id: ContextVar[Optional[int]] = ContextVar(
    "_active_project_id", default=None
)
_active_doc_scope: ContextVar[Optional[set]] = ContextVar(
    "active_doc_scope", default=None
)


def set_active_project_id(project_id: Optional[int]):
    _active_project_id.set(project_id)


def get_active_project_id() -> Optional[int]:
    return _active_project_id.get()


def reset_active_project_id():
    _active_project_id.set(None)


def set_active_doc_scope(scope) -> object:
    if scope is None or scope == "all" or (isinstance(scope, (list, tuple, set)) and len(scope) == 0):
        return _active_doc_scope.set(None)
    return _active_doc_scope.set(set(scope))


def reset_active_doc_scope(token) -> None:
    _active_doc_scope.reset(token)


def get_active_doc_scope() -> Optional[set]:
    return _active_doc_scope.get()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_neo4j_index(project_id: int) -> Neo4jDocumentIndex:
    return Neo4jDocumentIndex(
        base_url=os.getenv("NEO4J_URL", "http://localhost:7474"),
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_list_docs(project_id: int) -> str:
    """List all documents in the project catalog."""
    idx = _build_neo4j_index(project_id)
    rows = fetch_catalog(idx, project_id, doc_scope="all")
    if not rows:
        return "No documents found in this project."
    lines = [f"📚 {len(rows)} document(s):"]
    for r in rows:
        about = (r.get("about") or "")[:120]
        lines.append(f"  • {r['name']}  — {about}")
    return "\n".join(lines)


def tool_query_docs(query: str, project_id: int) -> str:
    """Find documents that match a query.

    Returns an ordered list of matched documents with confidence scores
    and reasons why each document is relevant.
    """
    idx = _build_neo4j_index(project_id)
    rows = fetch_catalog(idx, project_id, doc_scope="all")
    if not rows:
        return "No documents found in this project."

    routing_llm = make_routing_llm()
    decision, _ = route_by_llm(query, rows, routing_llm)
    if not decision.documents:
        return "No relevant documents found for this query."

    parts: List[str] = []
    for i, doc in enumerate(decision.documents, start=1):
        label = "BEST" if i == 1 else f"#{i}"
        parts.append(
            f"[{label}] {doc.name}  (confidence={doc.confidence:.2f})\n"
            f"       Reason: {doc.reason}"
        )
    if decision.reasoning:
        parts.append(f"\nStrategy: {decision.reasoning}")
    return "\n".join(parts)


def tool_read_doc(name: str, project_id: int) -> str:
    """Read the full text of a document by its filename."""
    idx = _build_neo4j_index(project_id)
    path = _file_path_for(idx, project_id, name)
    if not path:
        return f"Document '{name}' not found in Neo4j."
    max_chars = int(os.getenv("GRAPHINDEX_PRIMARY_MAX_CHARS", "10000000"))
    text = _read_doc_text(path, max_chars)
    if not text:
        return f"Document '{name}' has no extractable text."
    return f"=== {name} ===\n{text}"


def tool_answer(query: str, doc_names: str, project_id: int) -> str:
    """Synthesize an answer from one or more documents.

    **doc_names** is a JSON array of document filenames, e.g.
    ``'["01_tesla_q3_strategy.pdf", "02_tesla_product_lineup_2025.md"]'``.
    """
    idx = _build_neo4j_index(project_id)
    try:
        names: List[str] = json.loads(doc_names)
    except json.JSONDecodeError:
        return f"Invalid doc_names format: {doc_names}"
    if not names:
        return "No document names provided."

    docs = [MatchedDoc(name=n, confidence=1.0, reason="") for n in names]
    context = load_doc_context(idx, project_id, docs)
    answer_llm = make_answer_llm()
    system = SystemMessage(
        content="You are a research analyst. Answer the user's query based "
                "solely on the provided documents. Use citations like "
                "(Document N, Filename) to reference sources."
    )
    user = HumanMessage(content=f"Query: {query}\n\nDocuments:\n{context}")
    result = answer_llm.invoke([system, user])
    return str(result.content)


# ---------------------------------------------------------------------------
# StructuredTool factory
# ---------------------------------------------------------------------------

def make_tools(project_id: int) -> List[StructuredTool]:
    """Build the tool list for the DeepAgent.

    Each tool wraps a ``tool_*`` function with *project_id* pre-bound.
    """
    def list_docs() -> str:
        return tool_list_docs(project_id)

    def query_docs(query: str) -> str:
        return tool_query_docs(query, project_id)

    def read_doc(name: str) -> str:
        return tool_read_doc(name, project_id)

    def answer(query: str, doc_names: str) -> str:
        return tool_answer(query, doc_names, project_id)

    return [
        StructuredTool.from_function(
            func=list_docs,
            name="list_docs",
            description="List all available documents in the project catalog. "
                        "Returns document names with short descriptions.",
        ),
        StructuredTool.from_function(
            func=query_docs,
            name="query_docs",
            description="Find documents matching a user query. "
                        "Returns an ordered list of matched documents with "
                        "confidence scores and relevance reasons.",
        ),
        StructuredTool.from_function(
            func=read_doc,
            name="read_doc",
            description="Read the full text of a document by its filename. "
                        "Use this AFTER query_docs to get the actual content.",
        ),
        StructuredTool.from_function(
            func=answer,
            name="answer",
            description="Synthesize an answer from one or more documents. "
                        "Argument doc_names is a JSON array of filenames, "
                        "e.g. '[\"doc1.md\", \"doc2.pdf\"]'. "
                        "Use this AFTER query_docs and read_doc.",
        ),
    ]
