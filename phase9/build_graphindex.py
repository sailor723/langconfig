#!/usr/bin/env python3
"""
Phase 9 / Step 2.5 — complete GraphIndex builder.

Reuses the base project's Neo4j types and helpers (services/neo4j_document_index.py)
but adds an actual enrichment pipeline that the production sync in
backend/api/knowledge/rag.py never runs (it passes enrichment=None).

The enrichment generator (`extract_document_enrichment`) was lifted from
backend/scripts/test_neo4j_document_kv_roundtrip.py — it lived as a nested
function inside a script and was effectively dead code. We extract it to
module level so we can call it from anywhere, and we swap the LLM to
MiniMax M3 (consistent with dv_chat.py).

Commands:
  --show <name>           Dump the current node + enrichment for one doc
  --rebuild-one <name>    Rebuild enrichment for one doc (LLM call)
  --rebuild-project       Rebuild enrichment for every Document node (LLM call)
  --query <text>          Run choose_best_document_match on a query
  --no-llm                Skip enrichment, only show / query
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# .env resolution (works as script AND in REPL)
try:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

# Reuse base's Neo4j types + helpers
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentEnrichment,
    Neo4jDocumentIndex,
    build_document_node_properties,
    build_project_scope_names,
    choose_best_document_match,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

# --- Constants ---------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
NEO4J_URL = os.getenv("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
DOCS_BASE = REPO_ROOT / "backend/data/documents"
SESSION_START = time.time()


# --- Document loading (lifted from scripts/test_neo4j_document_kv_roundtrip.py) -

def _read_pdf_text(file_path: Path) -> str:
    """Read a PDF with PyMuPDF (preferred; already used by dv_chat.py)."""
    import fitz
    doc = fitz.open(str(file_path))
    parts: List[str] = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        if text:
            parts.append(f"--- Page {i+1}/{len(doc)} ---\n{text}")
    doc.close()
    return "\n\n".join(parts)


def _read_text_file(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="ignore")


def load_document_content(file_path: str) -> str:
    """Read the full text of a document based on its file extension."""
    p = Path(file_path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _read_pdf_text(p)
    if ext in {".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}:
        return _read_text_file(p)
    return _read_text_file(p)


def load_graphindex_metadata(file_path: str) -> dict:
    """For now we don't have a DocIndex client here; the full content is
    enough for the LLM to derive everything it needs. Returned as {} for
    compatibility with the build_document_node_properties signature."""
    return {}


# --- Enrichment schema (lifted from scripts/test_neo4j_document_kv_roundtrip.py) ---

class FewShotExample(BaseModel):
    query: str = Field(default="")
    answer_hint: str = Field(default="")


class DocumentEnrichmentOutput(BaseModel):
    what_this_document_is_about: str = Field(
        default="",
        description="One-sentence description of what this document covers.",
    )
    supported_queries: List[str] = Field(
        default_factory=list,
        description="Natural-language questions this document can answer.",
    )
    out_of_scope: List[str] = Field(
        default_factory=list,
        description="Topics this document does NOT cover (include names of other "
                    "project documents that handle those topics).",
    )
    few_shot: List[FewShotExample] = Field(default_factory=list)


# --- LLM + enrichment (lifted from scripts/test_neo4j_document_kv_roundtrip.py) --

def make_llm() -> BaseChatModel:
    if not MINIMAX_API_KEY:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=MODEL,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=0.2,
        max_tokens=2048,
    )


def extract_document_enrichment(
    llm: BaseChatModel,
    document_name: str,
    description: str,
    tags: List[str],
    graphindex_meta: dict,
    content: str,
    other_document_names: List[str],
) -> Neo4jDocumentEnrichment:
    """Use the LLM to create compact routing metadata for one document.

    Lifted from backend/scripts/test_neo4j_document_kv_roundtrip.py:103-160
    and adapted to use MiniMax M3 via init_chat_model.
    """
    structured_llm = llm.with_structured_output(DocumentEnrichmentOutput)
    content_excerpt = content[:6000]  # keep prompt bounded
    message = (
        "Create compact routing metadata for one document.\n"
        "We use this metadata only to choose the best document before "
        "loading full content.\n\n"
        f"Document name: {document_name}\n"
        f"Description: {description or 'N/A'}\n"
        f"Tags: {tags or []}\n"
        f"GraphIndex doc_name: {graphindex_meta.get('doc_name', '')}\n"
        f"GraphIndex page_count: {graphindex_meta.get('page_count', 0)}\n"
        f"GraphIndex content_preview: {graphindex_meta.get('content_preview', '')}\n"
        f"GraphIndex search_terms: {graphindex_meta.get('search_terms', [])[:20]}\n"
        f"Other documents in same project: {other_document_names}\n\n"
        "Return:\n"
        "1. what_this_document_is_about\n"
        "2. supported_queries\n"
        "3. out_of_scope (include names of other project documents that "
        "handle those topics — this is critical for routing)\n"
        "4. few_shot\n\n"
        "Rules:\n"
        "- Keep it concise and routing-oriented\n"
        "- out_of_scope must be definitive where possible\n"
        "- few_shot should be short examples of the kinds of questions "
        "this document can answer\n"
        "- Do not invent unsupported topics\n\n"
        f"Document excerpt:\n{content_excerpt}"
    )
    try:
        result = structured_llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Be precise, compact, and conservative. "
                "Do NOT include any <think> blocks or commentary in your output — "
                "return only the JSON object matching the schema."
            )),
            HumanMessage(content=message),
        ])
    except Exception as e:
        # MiniMax sometimes wraps its answer in <think>...</think> despite instructions.
        # Fall back to a plain text call and strip the reasoning block.
        print(f"    (structured output failed, retrying plain: {e})")
        resp = llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Reply with ONLY a JSON object matching this schema:\n"
                '{"what_this_document_is_about": str, '
                '"supported_queries": [str], '
                '"out_of_scope": [str], '
                '"few_shot": [{"query": str, "answer_hint": str}]}\n'
                "Do NOT include <think> blocks or commentary."
            )),
            HumanMessage(content=message),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        # Strip <think>...</think> block if present
        if "<think>" in text and "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        # Find the first { ... } JSON object in the response
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        data = json.loads(text)
        result = DocumentEnrichmentOutput(**data)
    return Neo4jDocumentEnrichment(
        what_this_document_is_about=result.what_this_document_is_about,
        supported_queries=list(result.supported_queries),
        out_of_scope=list(result.out_of_scope),
        few_shot=[ex.model_dump() for ex in result.few_shot],
    )


# --- File → property builder -------------------------------------------------

def build_properties(
    file_path: str,
    name: str,
    enrichment: Neo4jDocumentEnrichment,
    graphindex_meta: Optional[dict] = None,
    description: str = "",
    tags: Optional[List[str]] = None,
    context_doc_id: int = 0,
    project_id: int = 1,
) -> Dict[str, Any]:
    """Build a flat Neo4j property map for one document node."""
    return build_document_node_properties(
        project_id=project_id,
        context_doc_id=context_doc_id,
        doc_index_id=(graphindex_meta or {}).get("doc_index_id") or None,
        name=name,
        file_path=file_path,
        description=description,
        tags=tags or [],
        graphindex_meta=graphindex_meta or {},
        enrichment=enrichment,
    )


# --- Commands ----------------------------------------------------------------

def cmd_show(index: Neo4jDocumentIndex, name: str) -> int:
    """Show one node's full content."""
    node = index.get_document(project_id=1, name=name)
    if node is None:
        print(f"  ✗ no Document node with name={name!r}")
        return 1
    print(f"\n{'='*70}\nDocument: {node.name}\n{'='*70}")
    print(f"  context_doc_id  = {node.context_doc_id}")
    print(f"  doc_index_id    = {node.doc_index_id!r}")
    print(f"  file_path       = {node.file_path}")
    print(f"  page_count      = {node.page_count}")
    print(f"  description     = {node.description!r}")
    print(f"  tags            = {node.tags}")
    print(f"  search_terms    = {node.search_terms}")
    print(f"  about ({len(node.what_this_document_is_about)} chars):")
    if node.what_this_document_is_about:
        print(f"    {node.what_this_document_is_about}")
    print(f"  supported_queries ({len(node.supported_queries)}):")
    for q in node.supported_queries:
        print(f"    - {q}")
    print(f"  out_of_scope ({len(node.out_of_scope)}):")
    for q in node.out_of_scope:
        print(f"    - {q}")
    print(f"  few_shot ({len(node.few_shot)}):")
    for ex in node.few_shot:
        print(f"    - Q: {ex.get('query')}  A: {ex.get('answer_hint')}")
    return 0


def cmd_rebuild_one(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    name: str,
    all_names: List[str],
) -> int:
    """Rebuild enrichment for one doc and upsert it."""
    node = index.get_document(project_id=1, name=name)
    if node is None:
        print(f"  ✗ no Document node with name={name!r}")
        return 1
    content = load_document_content(node.file_path)
    if not content:
        print(f"  ✗ no content extracted from {node.file_path}")
        return 1
    graphindex_meta = load_graphindex_metadata(node.file_path)
    other_names = build_project_scope_names(name, all_names)

    print(f"  → generating enrichment for {name!r} "
          f"({len(content):,} chars)...")
    t0 = time.time()
    enrichment = extract_document_enrichment(
        llm=llm,
        document_name=name,
        description=node.description or "",
        tags=list(node.tags or []),
        graphindex_meta=graphindex_meta,
        content=content,
        other_document_names=other_names,
    )
    elapsed = time.time() - t0

    properties = build_properties(
        file_path=node.file_path,
        name=name,
        enrichment=enrichment,
        graphindex_meta=graphindex_meta,
        description=node.description or "",
        tags=list(node.tags or []),
        context_doc_id=node.context_doc_id,
        project_id=1,
    )
    index.upsert_document(project_id=1, name=name, file_path=node.file_path,
                          properties=properties)

    print(f"  ✓ upserted in {elapsed:.1f}s")
    print(f"    about: {enrichment.what_this_document_is_about[:120]}")
    print(f"    supports ({len(enrichment.supported_queries)}): "
          f"{enrichment.supported_queries[:3]}")
    print(f"    out_of_scope ({len(enrichment.out_of_scope)}): "
          f"{enrichment.out_of_scope[:3]}")
    return 0


def cmd_rebuild_project(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
) -> int:
    """Rebuild enrichment for every Document node in project 1."""
    docs = index.list_documents(project_id=1)
    all_names = [d.name for d in docs]
    print(f"\n{'='*70}\nRebuilding enrichment for {len(docs)} doc(s)\n{'='*70}\n")
    failed = 0
    for d in docs:
        ok = cmd_rebuild_one(index, llm, d.name, all_names)
        if ok != 0:
            failed += 1
        print()
    print(f"{'='*70}\n{len(docs) - failed}/{len(docs)} rebuilt successfully\n{'='*70}")
    return 0 if failed == 0 else 1


def cmd_query(index: Neo4jDocumentIndex, query_text: str) -> int:
    """Route a query using the current enrichment state and print top candidates."""
    docs = index.list_documents(project_id=1)
    print(f"\nQuery: {query_text!r}\n")
    if not docs:
        print("  ✗ no documents in project 1")
        return 1
    # Re-derive scores by calling the same function and printing the breakdown
    # (we don't have access to the internal scoring detail, so we just show
    # the winning doc)
    best = index.find_best_document(project_id=1, query=query_text)
    if best is None:
        print("  ✗ no match")
        return 1
    print(f"  ✓ best match: {best.name}  (context_doc_id={best.context_doc_id})")
    print(f"    about: {best.what_this_document_is_about[:200]}")
    print(f"    file: {best.file_path}")
    return 0


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 — complete GraphIndex builder.",
    )
    parser.add_argument("--show", metavar="NAME", help="Show a document node")
    parser.add_argument("--rebuild-one", metavar="NAME",
                        help="Rebuild enrichment for one doc")
    parser.add_argument("--rebuild-project", action="store_true",
                        help="Rebuild enrichment for every doc in project 1")
    parser.add_argument("--query", metavar="TEXT",
                        help="Route a query and print best match")
    args = parser.parse_args()

    if not any([args.show, args.rebuild_one, args.rebuild_project, args.query]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    print(f"🔌 Neo4j: {NEO4J_URL}")
    index = Neo4jDocumentIndex(
        base_url=NEO4J_URL,
        username=NEO4J_USER,
        password=NEO4J_PASSWORD,
    )
    index.ensure_constraints()
    print(f"   constraints ensured")

    # Build LLM (lazy — only when we need enrichment)
    llm: Optional[BaseChatModel] = None
    if args.rebuild_one or args.rebuild_project:
        llm = make_llm()
        print(f"🔌 LLM: {MODEL}\n")

    if args.show:
        return cmd_show(index, args.show)
    if args.rebuild_one:
        all_names = [d.name for d in index.list_documents(project_id=1)]
        return cmd_rebuild_one(index, llm, args.rebuild_one, all_names)
    if args.rebuild_project:
        return cmd_rebuild_project(index, llm)
    if args.query:
        return cmd_query(index, args.query)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
