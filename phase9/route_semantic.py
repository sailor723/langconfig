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
    _env_path = Path(__file__).resolve().parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    choose_best_document_match,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402

# --- Constants ---------------------------------------------------------------

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"
NEO4J_URL = os.getenv("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
PROJECT_ID = 1
SESSION_START = time.time()


# --- Catalog fetch (1 Cypher → all docs + their out_of_scope neighbors) -----

CATALOG_CYPHER = """
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


def fetch_catalog(idx: Neo4jDocumentIndex, project_id: int) -> List[Dict[str, Any]]:
    """Pull all docs + their out_of_scope neighbors' full metadata in one Cypher."""
    return idx._run_cypher(CATALOG_CYPHER, {"pid": project_id})


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

ROUTING_SYSTEM_TEMPLATE = """You are a routing agent. Pick the SINGLE best document for the user query.

Use semantic understanding, not just keyword overlap. Consider:
- What the document is about (about field)
- What questions the document can answer (supports field)
- What topics the document explicitly does NOT cover (excludes — note the about/supports of each excluded doc)

Available documents in this project:
{catalog}

Reply ONLY with a JSON object on a single line:
{{"name": "<exact doc name>", "confidence": <0.0-1.0>, "reasoning": "<one short sentence>"}}

If NONE of the documents are relevant, reply:
{{"name": null, "confidence": 0.0, "reasoning": "<why>"}}

Do NOT include any <think> blocks, commentary, or extra text."""


@dataclass
class RouteDecision:
    name: Optional[str]
    confidence: float
    reasoning: str


def _parse_decision(text: str) -> RouteDecision:
    """Extract JSON decision from LLM response, handling <think> wrappers."""
    # Strip <think>...</think> if present
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    # Find the first {...} JSON object
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object found in: {text[:200]}")
    data = json.loads(match.group(0))
    name = data.get("name")
    return RouteDecision(
        name=name if name else None,
        confidence=float(data.get("confidence", 0.0)),
        reasoning=data.get("reasoning", ""),
    )


def make_llm() -> BaseChatModel:
    if not MINIMAX_API_KEY:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=MODEL,
        model_provider="openai",
        api_key=MINIMAX_API_KEY,
        base_url=MINIMAX_BASE_URL,
        temperature=0.0,
        max_tokens=512,
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
            project_id=PROJECT_ID,
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


def print_decision(label: str, name: Optional[str], reasoning: str = "",
                   confidence: float = 0.0) -> None:
    if name:
        print(f"  {label:<10} → {name}  (confidence={confidence:.2f})")
        if reasoning:
            print(f"              {reasoning}")
    else:
        print(f"  {label:<10} → (no match)")
        if reasoning:
            print(f"              {reasoning}")


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
    args = parser.parse_args()

    if not any([args.query, args.show_catalog]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    print(f"🔌 Neo4j: {NEO4J_URL}")
    idx = Neo4jDocumentIndex(
        base_url=NEO4J_URL,
        username=NEO4J_USER,
        password=NEO4J_PASSWORD,
    )

    # Fetch catalog
    rows = fetch_catalog(idx, PROJECT_ID)
    print(f"   {len(rows)} doc(s) found\n")

    if args.show_catalog:
        print_catalog(rows)
        return 0

    if not args.query:
        return 0

    # Show the prompt the LLM would see, then exit (no LLM call)
    if args.show_prompt:
        catalog = format_catalog(rows)
        system_prompt = ROUTING_SYSTEM_TEMPLATE.format(catalog=catalog)
        print(f"\n{'='*70}\nSYSTEM MESSAGE ({len(system_prompt):,} chars)\n{'='*70}\n")
        print(system_prompt)
        print(f"\n{'='*70}\nUSER MESSAGE\n{'='*70}\n")
        print(args.query)
        print()
        return 0

    # String-matching baseline
    if args.compare:
        t0 = time.time()
        string_result = route_by_string(args.query, rows)
        string_time = time.time() - t0
        print(f"Query: {args.query!r}")
        print_decision("string", string_result)
        print(f"   ({string_time*1000:.0f} ms)")

    # LLM routing
    if not args.no_llm:
        llm = make_llm()
        t0 = time.time()
        decision, cache_read = route_by_llm(args.query, rows, llm)
        llm_time = time.time() - t0
        if not args.compare:
            print(f"Query: {args.query!r}")
        print_decision("llm", decision.name, decision.reasoning, decision.confidence)
        print(f"   ({llm_time:.2f}s, cache_read={cache_read:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())