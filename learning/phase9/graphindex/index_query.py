#!/usr/bin/env python3
"""
Phase 9 — GraphIndex query CLI (read-only routing + QA).

Split out of index_build.py so build and query pipelines have separate
entry points and separate concerns:

  index_build.py   --rebuild-one / --build-graph / --build-embeddings ...
  index_query.py   --query "..." / --qa "..." / --entity-query "..." / --entity NAME

Shared document loaders and the LLM factory still live in index_build.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

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
    Neo4jDocumentRecord,
)
from services.neo4j_embedding_matcher import Neo4jEmbeddingMatcher  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

# Shared helpers from the build module. Try plain import first (script mode);
# fall back to the package path for `python -m learning.phase9.graphindex...`.
try:
    from index_build import _PROJECT_ID, load_doc_context, load_document_content, make_llm
except ImportError:
    from learning.phase9.graphindex.index_build import (  # noqa: E402
        _PROJECT_ID,
        load_doc_context,
        load_document_content,
        make_llm,
    )


# --- Routing -----------------------------------------------------------------

def find_best_semantic_or_string(
    index: Neo4jDocumentIndex,
    project_id: int,
    query_text: str,
    scope: Optional[list[str]] = None,
) -> tuple[Optional[Neo4jDocumentRecord], str]:
    """Try the Neo4j vector-index matcher first, then fall back to string scoring.

    The embedding path is ANN (fast); the string scorer (choose_best_document_match)
    is kept as the safety net when embeddings/index are unavailable or the top
    vector hit is below threshold.
    """
    try:
        matcher = Neo4jEmbeddingMatcher(index)
        best = matcher.find_best(project_id, query_text, scope=scope)
        if best is not None:
            return best, "embedding"
    except Exception as e:
        print(f"  (embedding matcher unavailable: {e})")
    return index.find_best_document(project_id=project_id, query=query_text, scope=scope), "string"


def find_best_entity_then_docs(
    index: Neo4jDocumentIndex,
    project_id: int,
    query_text: str,
    top_docs: int = 3,
    scope: Optional[list[str]] = None,
) -> tuple[Optional[list[str]], Optional[dict], str]:
    """Entity-first routing: semantic entity search -> MENTIONS -> doc names.

    Returns (doc_names, entity, method). method == "entity" on success;
    (None, None, "entity") on any failure (index missing, gate rejects,
    no docs) so callers can fall back to the document-level matcher.
    """
    try:
        matcher = Neo4jEmbeddingMatcher(index)
        entity = matcher.find_best_entity(project_id, query_text)
        if entity is None:
            return None, None, "entity"
        docs = index.find_docs_mentioning_entity(project_id, entity["name"])
        if not docs:
            return None, None, "entity"
        # Deterministic ranking: subject-role docs first, then by name.
        role_rank = {"subject": 0, "competitor": 1, "partner": 2,
                     "source": 3, "author": 4, "other": 5}
        docs.sort(key=lambda d: (role_rank.get(d.get("role"), 9), d["doc_name"]))
        if scope:
            docs = [d for d in docs if d["doc_name"] in scope]
        doc_names = [d["doc_name"] for d in docs[:top_docs]]
        return doc_names, entity, "entity"
    except Exception as e:
        print(f"  (entity matcher unavailable: {e})")
        return None, None, "entity"


# --- Commands ----------------------------------------------------------------

def cmd_entity(index: Neo4jDocumentIndex, entity_name: str,
               project_id: int = _PROJECT_ID) -> int:
    """Show which documents mention one entity (graph query)."""
    docs = index.find_docs_mentioning_entity(project_id, entity_name)
    if not docs:
        print(f"  ✗ no Entity node named {entity_name!r} in project {project_id}")
        return 1
    print(f"  ✓ {entity_name!r} mentioned by {len(docs)} doc(s):")
    for d in docs:
        print(f"    - {d['doc_name']}  [role: {d['role']}]")
    return 0


def cmd_entity_query(index: Neo4jDocumentIndex, query_text: str,
                     project_id: int = _PROJECT_ID) -> int:
    """Debug: semantic search over Entity nodes, print best + its docs."""
    matcher = Neo4jEmbeddingMatcher(index)
    entity = matcher.find_best_entity(project_id, query_text)
    if entity is None:
        print("  ✗ no entity match (index missing or below confidence gate)")
        return 1
    print(f"  ✓ best entity: {entity['name']}  [{entity['entity_type']}]  "
          f"(score={entity['score']:.3f}, {entity['doc_count']} doc(s))")
    for d in index.find_docs_mentioning_entity(project_id, entity["name"]):
        print(f"    - {d['doc_name']}  [as {d['role']}]")
    return 0


def cmd_query(index: Neo4jDocumentIndex, query_text: str,
              project_id: int = _PROJECT_ID,
              scope: Optional[list[str]] = None) -> int:
    """Route a query using the current enrichment state and print top candidates."""
    docs = index.list_documents(project_id=project_id)
    print(f"\nQuery ({query_text!r}) — project {project_id}\n")
    if not docs:
        print(f"  ✗ no documents in project {project_id}")
        return 1
    best, method = find_best_semantic_or_string(index, project_id, query_text, scope=scope)
    if best is None:
        print("  ✗ no match")
        return 1
    score = getattr(best, "match_score", None)
    score_str = f"  (score={score:.3f})" if score is not None else ""
    print(f"  ✓ best match: {best.name}  [via {method}]{score_str}")
    print(f"    about: {best.what_this_document_is_about[:200]}")
    print(f"    file: {best.file_path}")
    return 0


def _answer_from_context(
    llm: BaseChatModel,
    query_text: str,
    context: str,
    max_chars: int = 12000,
) -> int:
    """Shared LLM answer synthesis: context KV -> answer (strips <think>)."""
    print(f"    {len(context)} chars context\n")
    print("=" * 70)
    resp = llm.invoke([
        SystemMessage(content=(
            "You are a precise Q&A assistant. Answer the user's question "
            "based solely on the provided document content. "
            "If the document doesn't contain enough information, say so. "
            "Be concise and cite relevant parts."
        )),
        HumanMessage(content=(
            f"Question: {query_text}\n\n"
            f"--- Context ---\n\n{context[:max_chars]}"
        )),
    ])
    answer = resp.content if isinstance(resp.content, str) else str(resp.content)
    # Strip <think>...</think> reasoning blocks (MiniMax often returns them)
    if "<think>" in answer:
        answer = answer.split("</think>", 1)[1].strip() if "</think>" in answer else answer.split("<think>", 1)[0].strip()
    print(f"Answer:\n{answer.strip()}")
    print("=" * 70)
    return 0


def cmd_qa(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    query_text: str,
    project_id: int = _PROJECT_ID,
    scope: Optional[list[str]] = None,
) -> int:
    """Entity-first QA: semantic entity -> MENTIONS docs -> KV -> LLM.

    Falls back to the document-level matcher (find_best_semantic_or_string)
    when no entity clears the semantic gate or the best entity has no docs.
    """
    docs = index.list_documents(project_id=project_id)
    if not docs:
        print(f"  ✗ no documents in project {project_id}")
        return 1

    # 1) Entity-first path: best Entity node -> its docs via MENTIONS.
    doc_names, entity, method = find_best_entity_then_docs(
        index, project_id, query_text, scope=scope,
    )
    if doc_names:
        print(f"  ✓ entity: {entity['name']}  [{entity['entity_type']}]  "
              f"(score={entity['score']:.3f}, {entity['doc_count']} doc(s))")
        mentions = index.find_docs_mentioning_entity(project_id, entity["name"])
        reasons = {
            m["doc_name"]: f"mentions entity '{entity['name']}' as {m['role']}"
            for m in mentions
            if m["doc_name"] in doc_names
        }
        context = load_doc_context(index, project_id, doc_names, reasons=reasons)
        print(f"  ✓ matched {len(doc_names)} doc(s) via entity "
              f"{entity['name']}: {', '.join(doc_names)}")
        return _answer_from_context(llm, query_text, context)

    # 2) Fallback: document-level semantic / string match.
    best, method = find_best_semantic_or_string(index, project_id, query_text, scope=scope)
    if best is None:
        print("  ✗ no match found")
        return 1
    print(f"  ✓ matched: {best.name}  [via {method}]")
    print(f"    about: {best.what_this_document_is_about[:200]}")
    content = load_document_content(best.file_path) if best.file_path else ""
    if not content:
        print(f"  ✗ empty content at {best.file_path}")
        return 1
    return _answer_from_context(llm, query_text, f"--- Document: {best.name} ---\n\n{content}")


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 — GraphIndex query CLI (routing + QA).",
    )
    parser.add_argument("--project-id", type=int, default=_PROJECT_ID,
                        help=f"Neo4j project id (default: {_PROJECT_ID}, "
                             "from GRAPHINDEX_DEFAULT_PROJECT_ID env var)")
    parser.add_argument("--query", metavar="TEXT",
                        help="Route a query (embedding first, string fallback) and print best match")
    parser.add_argument("--qa", metavar="TEXT",
                        help="Full QA: semantic entity -> MENTIONS docs -> KV -> LLM (doc fallback)")
    parser.add_argument("--entity-query", metavar="TEXT",
                        help="Semantic search over Entity nodes, print best + its docs")
    parser.add_argument("--entity", metavar="NAME",
                        help="Show which documents mention one entity (graph query)")
    parser.add_argument("--doc-scope", metavar="NAMES", nargs="*", default=None,
                        help="Scope search to specific doc names (space-separated)")
    args = parser.parse_args()
    project_id = args.project_id

    if not any([args.query, args.qa, args.entity_query, args.entity]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    _neo4j_url = os.getenv("NEO4J_URL", "http://localhost:7474")
    print(f"🔌 Neo4j: {_neo4j_url}")
    index = Neo4jDocumentIndex(
        base_url=_neo4j_url,
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    index.ensure_constraints()
    print(f"   constraints ensured")

    # Build LLM lazily — only QA needs it.
    llm: Optional[BaseChatModel] = None
    if args.qa:
        llm = make_llm()
        print(f"🔌 LLM: {os.getenv('GRAPHINDEX_MODEL', 'minimax-m3')}\n")

    if args.query:
        return cmd_query(index, args.query, project_id=project_id, scope=args.doc_scope)
    if args.qa:
        return cmd_qa(index, llm, args.qa, project_id=project_id, scope=args.doc_scope)
    if args.entity_query:
        return cmd_entity_query(index, args.entity_query, project_id=project_id)
    if args.entity:
        return cmd_entity(index, args.entity, project_id=project_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
