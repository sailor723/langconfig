#!/usr/bin/env python3
"""
Phase 9 / Step 3 — eval suite for the routing layer.

Runs a hand-labeled query set against:
  - string-matching routing (base's choose_best_document_match)
  - LLM semantic routing (route_semantic.route_by_llm)

Reports:
  - top-1 hit rate
  - top-3 hit rate (primary + supporting in ground truth set)
  - latency stats (mean / max / cache_read)
  - confusion matrix (which docs were mis-routed)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Allow running as a script from anywhere
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    Neo4jDocumentRecord,
    choose_best_document_match,
    normalize_lookup_terms,
)
from legacy.route_semantic import (  # noqa: E402
    fetch_catalog,
    route_by_llm,
    route_by_string,
    make_llm,
)

# --- Eval query set --------------------------------------------------------

EVAL_QUERIES: List[Dict[str, Any]] = [
    # Category A: simple EN with literal doc match
    {"q": "Nike revenue 2023",
     "category": "A_simple_en_literal",
     "primary": "nke-10k-2023.pdf",
     "supporting": []},

    {"q": "Nike 10-K annual report financial statements",
     "category": "A_simple_en_literal",
     "primary": "nke-10k-2023.pdf",
     "supporting": []},

    # Category B: simple ZH
    {"q": "苏格拉底思想",
     "category": "B_simple_zh",
     "primary": "6 人物库.pdf",
     "supporting": []},

    {"q": "孔子语录",
     "category": "B_simple_zh",
     "primary": "6 人物库.pdf",
     "supporting": []},

    # Category C: conceptual — query term is NOT in any field, requires semantic match
    {"q": "binary classification neural network",
     "category": "C_conceptual",
     "primary": "C1M2.pdf",
     "supporting": []},

    {"q": "reinforcement learning Q-learning Deep Q-Network",
     "category": "C_conceptual",
     "primary": "lecture-notes-9.pdf",
     "supporting": []},

    {"q": "face recognition Siamese triplet loss",
     "category": "C_conceptual",
     "primary": "C4M4.pdf",
     "supporting": []},

    {"q": "word embedding Word2Vec GloVe",
     "category": "C_conceptual",
     "primary": "C5M2.pdf",
     "supporting": []},

    # Category D: cross-domain — primary + supporting
    {"q": "compare Nike strategy with industry trends",
     "category": "D_cross_domain",
     "primary": "nke-10k-2023.pdf",
     "supporting": ["Departmental Survey for Biz Strategy.pdf",
                    "Strategic Framework Presentation.pdf"]},

    {"q": "apply entrepreneur thinking to AI strategy framework",
     "category": "D_cross_domain",
     "primary": "Strategic Framework Presentation.pdf",
     "supporting": ["6 人物库.pdf"]},

    # Category E: irrelevant — expect no match (or low confidence)
    {"q": "what is the weather today in Tokyo",
     "category": "E_irrelevant",
     "primary": None,
     "supporting": []},

    {"q": "how do I bake a chocolate cake",
     "category": "E_irrelevant",
     "primary": None,
     "supporting": []},

    # Category F: ambiguous (multiple plausible docs)
    {"q": "deep learning course logistics grading",
     "category": "F_ambiguous",
     "primary": "Week1_slides.pdf",
     "supporting": []},

    {"q": "machine learning project planning error analysis",
     "category": "F_ambiguous",
     "primary": "lecture-notes-6.pdf",
     "supporting": []},
]


@dataclass
class EvalResult:
    query: str
    category: str
    expected_primary: Optional[str]
    expected_supporting: List[str]
    actual_primary: Optional[str]
    actual_supporting: List[str]
    actual_confidence: float
    latency_s: float
    cache_read: int = 0

    @property
    def primary_hit(self) -> bool:
        if self.expected_primary is None:
            return self.actual_primary is None
        return self.actual_primary == self.expected_primary

    @property
    def supporting_hit(self) -> bool:
        # Any expected supporting doc appearing in actual supporting set
        if not self.expected_supporting:
            return True  # nothing expected → trivially correct
        actual_names = {s.name for s in self.actual_supporting}
        return any(s in actual_names for s in self.expected_supporting)

    @property
    def top3_hit(self) -> bool:
        # Either primary is correct, OR any expected supporting is present
        if self.primary_hit:
            return True
        if not self.expected_supporting:
            return False
        actual_names = {s.name for s in self.actual_supporting}
        return any(s in actual_names for s in self.expected_supporting)


# --- Eval runner ----------------------------------------------------------

def _to_record(r: Dict[str, Any]) -> Neo4jDocumentRecord:
    """Convert a catalog row into a Neo4jDocumentRecord for string matching."""
    excluded_names = [ex["name"] for ex in (r["excludes"] or []) if ex.get("name")]
    return Neo4jDocumentRecord(
        project_id=1,
        name=r["name"],
        file_path=r["fp"] or "",
        description="",
        tags=[],
        what_this_document_is_about=r["about"],
        supported_queries=list(r["supports"] or []),
        out_of_scope=excluded_names,
        search_terms=[],
        content_preview="",
        doc_index_id=None,
        context_doc_id=r["cid"] or 0,
    )


def run_string_eval(queries: List[Dict], rows: List[Dict]) -> List[EvalResult]:
    """Run base's string-matching routing on each query, using a thin wrapper
    so we can capture the actual choice and a (placeholder) confidence."""
    records = [_to_record(r) for r in rows]
    results: List[EvalResult] = []
    for q in queries:
        t0 = time.time()
        best = choose_best_document_match(q["q"], records)
        latency = time.time() - t0
        results.append(EvalResult(
            query=q["q"],
            category=q["category"],
            expected_primary=q["primary"],
            expected_supporting=q.get("supporting", []),
            actual_primary=best.name if best else None,
            actual_supporting=[],
            actual_confidence=1.0 if best else 0.0,
            latency_s=latency,
        ))
    return results


def run_llm_eval(queries: List[Dict], rows: List[Dict],
                 llm) -> List[EvalResult]:
    """Run LLM semantic routing on each query."""
    results: List[EvalResult] = []
    for q in queries:
        t0 = time.time()
        decision, cache_read = route_by_llm(q["q"], rows, llm)
        latency = time.time() - t0
        results.append(EvalResult(
            query=q["q"],
            category=q["category"],
            expected_primary=q["primary"],
            expected_supporting=q.get("supporting", []),
            actual_primary=decision.primary,
            actual_supporting=list(decision.supporting),
            actual_confidence=decision.primary_confidence,
            latency_s=latency,
            cache_read=cache_read,
        ))
    return results


def summarize(results: List[EvalResult]) -> Dict[str, Any]:
    """Compute headline metrics + per-category breakdown."""
    total = len(results)
    primary_hits = sum(1 for r in results if r.primary_hit)
    top3_hits = sum(1 for r in results if r.top3_hit)
    latencies = [r.latency_s for r in results]
    by_cat: Dict[str, Dict[str, Any]] = {}

    for r in results:
        s = by_cat.setdefault(r.category, {
            "n": 0, "primary_hit": 0, "top3_hit": 0, "supporting_hit": 0,
            "false_positives": 0, "false_negatives": 0,
        })
        s["n"] += 1
        if r.primary_hit:
            s["primary_hit"] += 1
        if r.top3_hit:
            s["top3_hit"] += 1
        if r.supporting_hit:
            s["supporting_hit"] += 1
        if r.expected_primary is None and r.actual_primary is not None:
            s["false_positives"] += 1
        if r.expected_primary is not None and r.actual_primary is None:
            s["false_negatives"] += 1

    return {
        "total": total,
        "primary_accuracy": primary_hits / total if total else 0,
        "top3_accuracy": top3_hits / total if total else 0,
        "latency_mean": statistics.mean(latencies) if latencies else 0,
        "latency_max": max(latencies) if latencies else 0,
        "by_category": by_cat,
    }


def render_report(name: str, summary: Dict, results: List[EvalResult]) -> str:
    """Render a human-readable report block."""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  {name}")
    lines.append(f"{'='*70}")
    lines.append(f"  queries run:        {summary['total']}")
    lines.append(f"  primary accuracy:   {summary['primary_accuracy']*100:.0f}%")
    lines.append(f"  top-3 accuracy:     {summary['top3_accuracy']*100:.0f}%")
    lines.append(f"  latency mean:       {summary['latency_mean']*1000:.0f} ms")
    lines.append(f"  latency max:        {summary['latency_max']*1000:.0f} ms")
    lines.append("")
    lines.append(f"  per-category:")
    for cat, s in sorted(summary["by_category"].items()):
        pa = s["primary_hit"] / s["n"] * 100 if s["n"] else 0
        t3 = s["top3_hit"] / s["n"] * 100 if s["n"] else 0
        sup = s["supporting_hit"] / s["n"] * 100 if s["n"] else 0
        lines.append(f"    {cat:30s}  n={s['n']}  primary={pa:3.0f}%  "
                     f"top3={t3:3.0f}%  supporting={sup:3.0f}%")
    lines.append("")
    lines.append("  misroutes:")
    for r in results:
        if not r.primary_hit:
            lines.append(f"    ✗ [{r.category}] {r.query!r}")
            lines.append(f"        expected:  {r.expected_primary}")
            lines.append(f"        actual:    {r.actual_primary}")
    return "\n".join(lines)


# --- Main -----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 9 eval suite for routing.")
    parser.add_argument("--method", choices=["string", "llm", "both"], default="both")
    parser.add_argument("--output", metavar="FILE", default=None,
                        help="Write JSON results to FILE")
    args = parser.parse_args()

    # Connect to Neo4j + load catalog
    print(f"🔌 Neo4j: http://localhost:7474")
    idx = Neo4jDocumentIndex()
    rows = fetch_catalog(idx, 1)
    print(f"   catalog: {len(rows)} docs")

    print(f"\n📋 Eval set: {len(EVAL_QUERIES)} queries across 6 categories\n")

    string_summary = None
    string_results = []
    llm_summary = None
    llm_results = []

    if args.method in ("string", "both"):
        string_results = run_string_eval(EVAL_QUERIES, rows)
        string_summary = summarize(string_results)
        print(render_report("STRING MATCHING (base)", string_summary, string_results))

    if args.method in ("llm", "both"):
        llm = make_llm()
        llm_results = run_llm_eval(EVAL_QUERIES, rows, llm)
        llm_summary = summarize(llm_results)
        print(render_report("LLM SEMANTIC (route_semantic)", llm_summary, llm_results))

    # Side-by-side
    if args.method == "both" and string_summary and llm_summary:
        print(f"\n{'='*70}\n  SIDE-BY-SIDE\n{'='*70}")
        for cat in sorted(set(q["category"] for q in EVAL_QUERIES)):
            cs = string_summary["by_category"].get(cat, {})
            cl = llm_summary["by_category"].get(cat, {})
            n = cs.get("n", 0)
            if not n:
                continue
            sp = cs["primary_hit"] / n * 100
            lp = cl["primary_hit"] / n * 100
            delta = lp - sp
            print(f"  {cat:30s}  string={sp:3.0f}%  llm={lp:3.0f}%  "
                  f"Δ={delta:+3.0f}pp")

    # Persist
    if args.output:
        out = {
            "queries": EVAL_QUERIES,
            "string_results": [
                {k: v for k, v in vars(r).items()} for r in string_results
            ],
            "llm_results": [
                {k: v for k, v in vars(r).items()} for r in llm_results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\n💾 wrote {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())