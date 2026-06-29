#!/usr/bin/env python3
"""
Phase 9 / Step 2.6 — semantic LLM-based doc routing.

Builds a one-shot catalog from Neo4j (each doc + its out_of_scope neighbors'
full metadata), then asks an LLM to pick the best document for a query.

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
    """Pull docs (all or scoped) + their out_of_scope neighbors' full metadata.

    If *doc_scope* is ``"all"`` (the default), returns ALL docs in the project.
    Otherwise it's treated as a JSON array of doc names to scope to.
    """
    if doc_scope == "all":
        cypher = """
MATCH (d:Document {project_id: $pid})
WITH d, coalesce(d.out_of_scope, []) AS ex_names
UNWIND (CASE WHEN size(ex_names) = 0 THEN [null] ELSE ex_names END) AS ex_name
WITH d, ex_name
OPTIONAL MATCH (other:Document {project_id: $pid, name: ex_name})
WITH d, collect({
    name: other.name,
    about: COALESCE(other.what_this_document_is_about, other.content_preview, ''),
    supports: COALESCE(other.supported_queries, other.search_terms, [])
}) AS excluded_full
RETURN d.name AS name,
       d.context_doc_id AS cid,
       d.file_path AS fp,
       COALESCE(d.what_this_document_is_about, d.content_preview, '') AS about,
       COALESCE(d.supported_queries, d.search_terms, []) AS supports,
       excluded_full AS excludes
ORDER BY d.name
"""
        return idx._run_cypher(cypher, {"pid": project_id})

    # Scoped: filter by specific doc names
    scope_list: List[str] = json.loads(doc_scope) if isinstance(doc_scope, str) else doc_scope
    cypher = """
MATCH (d:Document {project_id: $pid})
WHERE d.name IN $scope_list
WITH d, coalesce(d.out_of_scope, []) AS ex_names
UNWIND (CASE WHEN size(ex_names) = 0 THEN [null] ELSE ex_names END) AS ex_name
WITH d, ex_name
OPTIONAL MATCH (other:Document {project_id: $pid, name: ex_name})
WHERE other.name IN $scope_list OR other IS NULL
WITH d, collect({
    name: other.name,
    about: COALESCE(other.what_this_document_is_about, other.content_preview, ''),
    supports: COALESCE(other.supported_queries, other.search_terms, [])
}) AS excluded_full
RETURN d.name AS name,
       d.context_doc_id AS cid,
       d.file_path AS fp,
       COALESCE(d.what_this_document_is_about, d.content_preview, '') AS about,
       COALESCE(d.supported_queries, d.search_terms, []) AS supports,
       excluded_full AS excludes
ORDER BY d.name
"""
    return idx._run_cypher(cypher, {"pid": project_id, "scope_list": scope_list})


# --- Catalog formatting for LLM --------------------------------------------

def format_catalog(rows: List[Dict[str, Any]]) -> str:
    """Render the catalog as a human-readable string for the LLM."""
    parts = []
    for i, r in enumerate(rows, 1):
        ex_lines = []
        for ex in r["excludes"]:
            name = ex.get("name")
            if not name:  # null from OPTIONAL MATCH (referenced doc missing)
                continue
            about = ex.get("about") or "(empty)"
            supports = (ex.get("supports") or [])[:5]
            ex_lines.append(
                f"  - {name}\n"
                f"    about: {about}\n"
                f"    supports: {supports}"
            )
        excludes_str = "\n".join(ex_lines) if ex_lines else "  (none)"
        about = r["about"] or "(empty)"
        supports = (r["supports"] or [])[:5]
        parts.append(
            f"[{i}] {r['name']}\n"
            f"  about: {about}\n"
            f"  supports: {supports}\n"
            f"  excludes:\n{excludes_str}"
        )
    return "\n\n".join(parts)


# --- LLM routing ------------------------------------------------------------

ROUTING_SYSTEM_TEMPLATE = """You are a routing agent. Analyze the available documents and select ALL documents that are relevant to the user's query.

Think step by step:
1. Understand what information the user needs
2. Scan each document's about/supports/excludes to determine relevance
3. Select 1-N documents that together best answer the query
4. Order them by relevance (most relevant first)

Use semantic understanding, not just keyword overlap. Consider:
- What the document is about (about field)
- What questions the document can answer (supports field)
- What topics the document explicitly does NOT cover (excludes field)

Available documents in this project:
{catalog}

Reply ONLY with a JSON object on a single line:
{{"documents": [{{"name": "<exact doc name>", "confidence": <0.0-1.0>, "reason": "<why this doc fits the query>"}}], "reasoning": "<one short sentence explaining overall strategy>"}}

If NONE of the documents are relevant, reply:
{{"documents": [], "reasoning": "<why no documents match>"}}

Do NOT include any <think> blocks, commentary, or extra text."""


@dataclass
class MatchedDoc:
    name: str
    confidence: float
    reason: str


@dataclass
class RouteDecision:
    documents: List[MatchedDoc]                 # ordered by relevance (best first)
    reasoning: str


def _parse_decision(text: str) -> RouteDecision:
    """Extract JSON decision from LLM response. Handles both v1 ({name, confidence})
    and v2 ({primary, primary_domain, supporting, ...}) schemas."""
    # Strip <think>...</think> if present
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    # Find the first balanced {...} JSON object (handles nested braces too)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in: {text[:200]}")
    depth, in_string, escape = 0, False, False
    end = -1
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        # JSON was truncated (e.g. LLM hit max_tokens). Try to recover by
        # truncating at the last complete nested object/array boundary.
        # Heuristic: cut off trailing unclosed strings/arrays.
        partial = text[start:]
        last_full = partial.rfind("},")  # end of nested object
        if last_full < 0:
            last_full = partial.rfind("],")  # end of array
        if last_full < 0:
            raise ValueError(f"unbalanced JSON in: {text[:200]}")
        truncated = partial[:last_full + 1]
        opens = truncated.count("{") - truncated.count("}")
        brackets = truncated.count("[") - truncated.count("]")
        truncated += "]" * max(brackets, 0) + "}" * max(opens, 0)
        try:
            data = json.loads(truncated)
        except Exception:
            raise ValueError(f"unbalanced JSON in: {text[:200]}")
    else:
        data = json.loads(text[start:end + 1])

    # v3 schema: {"documents": [{"name": ..., "confidence": ..., "reason": ...}], "reasoning": "..."}
    if "documents" in data:
        docs_raw = data.get("documents", [])
        documents = [
            MatchedDoc(
                name=d.get("name", ""),
                confidence=float(d.get("confidence", 0.0)),
                reason=d.get("reason", ""),
            )
            for d in docs_raw
            if d.get("name")
        ]
        return RouteDecision(
            documents=documents,
            reasoning=data.get("reasoning", ""),
        )

    # v2 schema: {"primary": ..., "primary_domain": ..., "primary_confidence": ..., "supporting": [...]}
    if "primary" in data:
        supporting_raw = data.get("supporting", [])
        documents: List[MatchedDoc] = []
        primary_name = data.get("primary")
        if primary_name:
            documents.append(MatchedDoc(
                name=primary_name,
                confidence=float(data.get("primary_confidence", 0.0)),
                reason=data.get("reasoning", ""),
            ))
            for s in supporting_raw:
                if s.get("name"):
                    documents.append(MatchedDoc(
                        name=s["name"],
                        confidence=0.0,
                        reason=s.get("reason", ""),
                    ))
        return RouteDecision(
            documents=documents,
            reasoning=data.get("reasoning", ""),
        )

    # v1 fallback: {"name": ..., "confidence": ..., "reasoning": "..."}
    name = data.get("name")
    if name:
        return RouteDecision(
            documents=[MatchedDoc(
                name=name,
                confidence=float(data.get("confidence", 0.0)),
                reason=data.get("reasoning", ""),
            )],
            reasoning=data.get("reasoning", ""),
        )

    return RouteDecision(documents=[], reasoning=data.get("reasoning", ""))


def make_routing_llm() -> BaseChatModel:
    """Lightweight local model for doc matching (routing). Default: Ollama gemma4."""
    return init_chat_model(
        model=os.getenv("GRAPHINDEX_ROUTING_MODEL", "gemma4"),
        model_provider="ollama",
        temperature=0.0,
        max_tokens=int(os.getenv("GRAPHINDEX_ROUTING_MAX_TOKENS", "2048")),
    )


def make_answer_llm() -> BaseChatModel:
    """Full-power model for synthesis answers. Default: Minimax M3."""
    if not os.getenv("MINIMAX_API_KEY"):
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=os.getenv("GRAPHINDEX_MODEL", "minimax-m3"),
        model_provider="openai",
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.0,
        max_tokens=int(os.getenv("GRAPHINDEX_ANSWER_MAX_TOKENS", "8192")),
    )


def route_by_llm(
    query: str,
    rows: List[Dict[str, Any]],
    llm: BaseChatModel,
) -> tuple[RouteDecision, int]:
    """Use LLM to route a query. Returns (decision, cache_read_tokens)."""
    catalog = format_catalog(rows)
    system = ROUTING_SYSTEM_TEMPLATE.format(catalog=catalog)

    resp = llm.invoke([
        SystemMessage(content=system),    # stable → prompt cache
        HumanMessage(content=query),
    ])
    decision = _parse_decision(resp.content if isinstance(resp.content, str) else str(resp.content))

    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))
    return decision, cache_read


# --- String-matching baseline ------------------------------------------------

def route_by_string(
    query: str,
    rows: List[Dict[str, Any]],
    project_id: int = int(os.getenv("GRAPHINDEX_DEFAULT_PROJECT_ID", "1")),
) -> Optional[str]:
    """Use base's string-matching scoring (returns doc name or None)."""
    # Build Neo4jDocumentRecord-like objects from the catalog rows
    from services.neo4j_document_index import Neo4jDocumentRecord
    docs = []
    for r in rows:
        # out_of_scope names are stored as a list of dicts in our format
        # (from OPTIONAL MATCH), but base expects a list of strings
        excluded_names = [ex["name"] for ex in (r["excludes"] or []) if ex.get("name")]
        docs.append(Neo4jDocumentRecord(
            project_id=project_id,
            name=r["name"],
            file_path=r["fp"] or "",
            description="",  # not pulled in our catalog query
            tags=[],
            what_this_document_is_about=r["about"],
            supported_queries=list(r["supports"] or []),
            out_of_scope=excluded_names,
            search_terms=[],
            content_preview="",
            doc_index_id=None,
            context_doc_id=r["cid"] or 0,
        ))
    best = choose_best_document_match(query, docs)
    return best.name if best else None


# --- Pretty printer ---------------------------------------------------------

def print_catalog(rows: List[Dict[str, Any]]) -> None:
    print(f"\n{'='*70}\nCATALOG: {len(rows)} document(s)\n{'='*70}\n")
    print(format_catalog(rows))
    print()


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
    documents: List[MatchedDoc],
) -> str:
    """Concatenate matched docs into a single human-readable string.

    Reads full text for each document, ordered by relevance (best first).
    First doc is marked PRIMARY, rest are SUPPORTING with their reason.
    """
    parts: List[str] = []
    for i, doc in enumerate(documents, start=1):
        path = _file_path_for(index, project_id, doc.name)
        max_chars = _PRIMARY_MAX_CHARS if i == 1 else _SUPPORTING_MAX_CHARS
        text = _read_doc_text(path, max_chars)
        label = "PRIMARY" if i == 1 else "SUPPORTING"
        reason_line = f"\n[Reason: {doc.reason}]" if doc.reason else ""
        parts.append(
            f"=== Document {i} ({label}): {doc.name} ==={reason_line}\n{text}"
            if text else
            f"=== Document {i} ({label}): {doc.name} ==={reason_line}\n(no extractable text)"
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


def print_decision(documents: List[MatchedDoc], reasoning: str = "") -> None:
    if not documents:
        print(f"  → (no match)")
        if reasoning:
            print(f"     {reasoning}")
        return
    for i, doc in enumerate(documents):
        label = "best" if i == 0 else f"   #{i+1}"
        print(f"  {label:<6} → {doc.name}  (confidence={doc.confidence:.2f})")
        if doc.reason:
            print(f"          {doc.reason}")
    if reasoning:
        print(f"  strategy: {reasoning}")


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / Step 2.6 — semantic LLM doc routing.",
    )
    parser.add_argument("--query", metavar="TEXT",
                        help="Route a query and print best match")
    parser.add_argument("--show-catalog", action="store_true",
                        help="Pretty-print the catalog")
    parser.add_argument("--compare", action="store_true",
                        help="Compare string-matching vs LLM routing on --query")
    parser.add_argument("--no-llm", action="store_true",
                        help="Use string-matching only (skip LLM call)")
    parser.add_argument("--show-prompt", action="store_true",
                        help="Print the full LLM prompt (system + user) for --query")
    parser.add_argument("--query-answer", metavar="TEXT",
                        help="Full end-to-end: route query, load multi-doc context, "
                             "and run synthesis LLM call")
    parser.add_argument("--project-id", type=int,
                        default=int(os.getenv("GRAPHINDEX_DEFAULT_PROJECT_ID", "1")),
                        help="Neo4j project id (default: from .env)")
    parser.add_argument("--doc-scope", metavar="NAMES", nargs="*", default=["all"],
                        help="Doc names to scope to (space-separated), "
                             "or \"all\" for all docs in project")
    args = parser.parse_args()
    project_id = args.project_id
    doc_scope: str = args.doc_scope
    # nargs="*" returns a list. If it's ["all"], treat as the sentinel string "all".
    # Otherwise join into a JSON array string for Cypher.
    if isinstance(doc_scope, list):
        if doc_scope == ["all"]:
            doc_scope = "all"
        else:
            import json
            doc_scope = json.dumps(doc_scope)  # → '["doc1", "doc2"]'

    if not any([args.query, args.show_catalog, args.query_answer]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    _neo4j_url = os.getenv("NEO4J_URL", "http://localhost:7474")
    print(f"🔌 Neo4j: {_neo4j_url}")
    idx = Neo4jDocumentIndex(
        base_url=_neo4j_url,
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )

    # Fetch catalog
    rows = fetch_catalog(idx, project_id, doc_scope=doc_scope)
    print(f"   {len(rows)} doc(s) found\n")

    if args.show_catalog:
        print_catalog(rows)
        return 0

    # Show the prompt the LLM would see, then exit (no LLM call)
    if args.show_prompt:
        # Use --query-answer as the query if --query wasn't given
        prompt_query = args.query or args.query_answer
        if not prompt_query:
            print("  ✗ --show-prompt needs --query or --query-answer")
            return 1
        catalog = format_catalog(rows)
        system_prompt = ROUTING_SYSTEM_TEMPLATE.format(catalog=catalog)
        print(f"\n{'='*70}\nSYSTEM MESSAGE ({len(system_prompt):,} chars)\n{'='*70}\n")
        print(system_prompt)
        print(f"\n{'='*70}\nUSER MESSAGE\n{'='*70}\n")
        print(prompt_query)
        print()
        return 0

    if not args.query and not args.query_answer:
        return 0

    # Unified query (used by --query, --compare, --query-answer)
    query = args.query or args.query_answer

    # String-matching baseline
    if args.compare:
        t0 = time.time()
        string_result = route_by_string(query, rows)
        string_time = time.time() - t0
        print(f"Query: {query!r}")
        if string_result:
            print(f"  string   → {string_result}")
        else:
            print(f"  string   → (no match)")
        print(f"   ({string_time*1000:.0f} ms)")

    # LLM routing (uses fast local model for doc matching)
    if not args.no_llm:
        routing_llm = make_routing_llm()
        answer_llm = make_answer_llm()
        t0 = time.time()
        decision, cache_read = route_by_llm(query, rows, routing_llm)
        llm_time = time.time() - t0
        if not args.compare:
            print(f"Query: {query!r}")
        print_decision(decision.documents, decision.reasoning)
        print(f"   ({llm_time:.2f}s, cache_read={cache_read:,})")

    # End-to-end: route (Gemma4) + load docs + synthesize answer (Minimax M3)
    if args.query_answer:
        routing_llm = make_routing_llm()
        answer_llm = make_answer_llm()
        t0 = time.time()
        decision, route_cache = route_by_llm(args.query_answer, rows, routing_llm)
        route_time = time.time() - t0
        print(f"\nQuery: {args.query_answer!r}")
        print_decision(decision.documents, decision.reasoning)
        print(f"   (route: {route_time:.2f}s, cache_read={route_cache:,})")

        if not decision.documents:
            print("\n  ✗ no relevant documents — cannot synthesize answer")
            return 1

        # Load multi-doc context (all matched docs, ordered by relevance)
        t0 = time.time()
        context = load_doc_context(idx, project_id, decision.documents)
        load_time = time.time() - t0
        total_chars = len(context)
        print(f"\n  loaded {total_chars:,} chars  ({load_time:.1f}s)")

        # Synthesize answer
        t0 = time.time()
        answer, ans_cache = answer_from_docs(args.query_answer, context, answer_llm)
        ans_time = time.time() - t0
        print(f"  synthesized  ({ans_time:.1f}s, cache_read={ans_cache:,})")

        print(f"\n{'='*70}\nANSWER\n{'='*70}\n")
        print(answer)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())