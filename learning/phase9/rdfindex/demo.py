"""End-to-end trial of the deterministic RDF/OWL document index.

Run from learning/phase9/:

    python -m rdfindex.demo

Flow: build TBox -> ingest sample enrichments -> materialize closure ->
run sample queries. No LLM and no Neo4j anywhere: the enrichment dicts are
stand-ins for what graphindex/index_build.py's extract_document_enrichment
already produces.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from rdflib import RDF

from . import ingest, query, reason, tbox
from .query import GI

ARTIFACTS = tbox.ARTIFACT_DIR

# --- Sample enrichments (shape = Neo4jDocumentEnrichment) -------------------
# Each entry is one LLM-extraction output as if produced by
# extract_document_enrichment (graphindex/index_build.py).

SAMPLE_DOCS: List[Dict[str, Any]] = [
    {
        "name": "byd_analysis_report.md",
        "file_path": "backend/data/documents/byd_analysis_report.md",
        "enrichment": {
            "what_this_document_is_about": "Deep dive into BYD's 2025 financial performance and EV strategy",
            "supported_queries": ["What is BYD's revenue?", "BYD operating profit margin",
                                  "BYD EV market position"],
            "entities": [
                {"name": "BYD", "entity_type": "Organization", "role": "subject"},
                {"name": "Revenue", "entity_type": "Metric", "role": "other"},
                {"name": "Operating Profit", "entity_type": "Metric", "role": "other"},
                {"name": "China", "entity_type": "Geography", "role": "market"},
            ],
            "categories": {
                "genre": "financial_data",
                "primary_subject": "economy_business_finance",
                "subjects": ["financial performance", "market position"],
                "question_types": ["financial_metric", "factual"],
                "financial_metrics": ["revenue", "operating_profit"],
            },
            "tags": ["byd", "ev", "financials"],
        },
    },
    {
        "name": "tesla_q3_strategy.md",
        "file_path": "backend/data/documents/tesla_q3_strategy.md",
        "enrichment": {
            "what_this_document_is_about": "Tesla's Q3 strategy memo: product roadmap and expansion plans",
            "supported_queries": ["What is Tesla's strategy?", "Tesla expansion plans"],
            "entities": [
                {"name": "Tesla", "entity_type": "Organization", "role": "subject"},
                {"name": "EV", "entity_type": "Industry", "role": "market"},
            ],
            "categories": {
                "genre": "strategic_framework",
                "primary_subject": "economy_business_finance",
                "subjects": ["strategy", "expansion"],
                "question_types": ["strategy_recommendation"],
                "financial_metrics": [],
            },
            "tags": ["tesla", "strategy"],
        },
    },
    {
        "name": "byd_vs_tesla_europe.md",
        "file_path": "backend/data/documents/byd_vs_tesla_europe.md",
        "enrichment": {
            "what_this_document_is_about": "Head-to-head comparison of BYD and Tesla in the European EV market",
            "supported_queries": ["How does BYD compare to Tesla in Europe?"],
            "entities": [
                {"name": "BYD", "entity_type": "Organization", "role": "competitor"},
                {"name": "Tesla", "entity_type": "Organization", "role": "competitor"},
                {"name": "European EV Market", "entity_type": "Industry", "role": "subject"},
                {"name": "Europe", "entity_type": "Geography", "role": "market"},
            ],
            "categories": {
                "genre": "comparison",
                "primary_subject": "economy_business_finance",
                "subjects": ["competitive analysis"],
                "question_types": ["comparison", "trend_analysis"],
                "financial_metrics": [],
            },
            "tags": ["byd", "tesla", "europe"],
        },
    },
    {
        "name": "european_ev_market_report.md",
        "file_path": "backend/data/documents/european_ev_market_report.md",
        "enrichment": {
            "what_this_document_is_about": "European EV market share trends by manufacturer",
            "supported_queries": ["What is Tesla's market share in Europe?",
                                  "European EV market outlook"],
            "entities": [
                {"name": "European EV Market", "entity_type": "Industry", "role": "subject"},
                {"name": "Tesla", "entity_type": "Organization", "role": "partner"},
                {"name": "BYD", "entity_type": "Organization", "role": "competitor"},
                {"name": "Europe", "entity_type": "Geography", "role": "market"},
                {"name": "Market Share", "entity_type": "Metric", "role": "other"},
            ],
            "categories": {
                "genre": "industry_analysis",
                "primary_subject": "economy_business_finance",
                "subjects": ["market share", "outlook"],
                "question_types": ["trend_analysis", "financial_metric"],
                "financial_metrics": ["market_share"],
            },
            "tags": ["ev", "europe", "market-share"],
        },
    },
    {
        "name": "ev_consumer_survey.md",
        "file_path": "backend/data/documents/ev_consumer_survey.md",
        "enrichment": {
            "what_this_document_is_about": "Consumer survey on EV ownership experience and charging habits",
            "supported_queries": ["What do EV owners think about charging?"],
            "entities": [
                {"name": "EV Owners", "entity_type": "Concept", "role": "subject"},
                {"name": "Charging Network", "entity_type": "Concept", "role": "other"},
                {"name": "Europe", "entity_type": "Geography", "role": "market"},
            ],
            "categories": {
                "genre": "survey",
                "primary_subject": "society",
                "subjects": ["consumer behavior"],
                "question_types": ["factual", "customer_support"],
                "financial_metrics": [],
            },
            "tags": ["survey", "ev", "charging"],
        },
    },
]

SAMPLE_QUERIES: List[tuple] = [
    ("what are BYD's financial metrics", "BYD + financial_metric -> FinancialReport (derived class)"),
    ("compare BYD vs Tesla in Europe", "BYD, Tesla, Europe + comparison -> ComparisonReport (derived class)"),
    ("tesla market share in europe", "Tesla, Europe, Market Share + trend_analysis -> generic routing"),
    ("strategic recommendations for tesla", "Tesla + strategy_recommendation -> generic routing"),
    ("how to bake a chocolate cake", "out-of-domain -> deterministic rejection"),
]


def _derived_members(graph, cls_name: str) -> List[str]:
    """Document individuals (doc_*) that the reasoner typed into a derived class."""
    return sorted(
        str(s).split("#")[-1]
        for s, _, o in graph.triples((None, RDF.type, GI[cls_name]))
        if str(s).split("#")[-1].startswith("doc_")
    )


def main() -> None:
    print("=" * 78)
    print("Deterministic RDF/OWL document index — trial")
    print("=" * 78)

    # 1. TBox -----------------------------------------------------------------
    print("\n[1] Building TBox from .Codex/docs/graphindex-ontology.md ...")
    vocab = tbox.parse_vocab()
    w = tbox.build_tbox(vocab)
    onto = w.get_ontology(tbox.ONTOLOGY_IRI)
    print(f"    vocabularies: entity_type={len(vocab['entity_type'])}, "
          f"genre={len(vocab['genre'])}, question_types={len(vocab['question_types'])}")
    print(f"    classes={len(list(onto.classes()))}, "
          f"individuals={len(list(onto.individuals()))}")
    print(f"    saved -> artifacts/graphindex-ontology.owl (open in Protege)")

    # 2. Ingest ABox ----------------------------------------------------------
    print("\n[2] Ingesting sample enrichments -> per-doc Turtle fragments ...")
    for doc in SAMPLE_DOCS:
        out = ingest.enrichment_to_triples(doc["name"], doc["file_path"], doc["enrichment"])
        print(f"    wrote {out.name}")
    print(f"    ABox fragments in artifacts/triples/")

    # 3. Materialize -----------------------------------------------------------
    print("\n[3] Running the reasoner (materialize closure) ...")
    t0 = time.perf_counter()
    stats = reason.materialize(ARTIFACTS / "graphindex-ontology.owl", reason.TRIPLE_DIR)
    dt = (time.perf_counter() - t0) * 1000
    print(f"    combined={stats['combined_triples']} triples, "
          f"closure={stats['closure_triples']} triples, "
          f"+{stats['inferred']} inferred")
    print(f"    reasoner took {dt:.0f} ms -> artifacts/index_closure.ttl")

    # Show that derived-class memberships are materialized (never asserted).
    graph = query.load_index()
    for cls in ("FinancialReport", "ComparisonReport", "InvestmentGradeReport"):
        members = _derived_members(graph, cls)
        print(f"    inferred {cls}: {members}")

    # 4. Queries ----------------------------------------------------------------
    print("\n[4] Sample queries (rule-based extraction -> SPARQL, no LLM) ...")
    for q, note in SAMPLE_QUERIES:
        t0 = time.perf_counter()
        results = query.search(graph, q)
        dt = (time.perf_counter() - t0) * 1000
        print(f"\n  Q: {q!r}  ({note})  [{dt:.1f} ms]")
        if not results:
            print("    -> no match (deterministic rejection)")
        for r in results:
            print(f"    -> {r['title']}  (score {r['score']}; {', '.join(r['reasons'])})")


if __name__ == "__main__":
    main()
