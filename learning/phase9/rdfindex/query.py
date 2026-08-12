"""Deterministic query side: rule-based intent extraction -> SPARQL.

No LLM, no embeddings, no reasoning at query time: the free-text query is
reduced to (entities, question-type hints) by simple string rules, a fixed
SPARQL template is built from those, and it runs against the pre-materialized
closure (index_closure.ttl).

Derived classes like gi:FinancialReport exist in the closure only because the
reasoner inferred them at ingest — queries reference them directly.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import Graph, Namespace, RDF, RDFS, URIRef

from .reason import CLOSURE_PATH

ONTOLOGY_IRI = "http://langconfig.local/graphindex"
GI = Namespace(ONTOLOGY_IRI + "#")

_STOPWORDS = {
    "a", "an", "about", "are", "can", "do", "does", "for", "how",
    "i", "in", "is", "me", "of", "show", "tell", "the", "this",
    "what", "which", "who", "and", "or", "to", "with", "by", "on",
}

# question_type hints: a small deterministic keyword table. This is the
# "rule-based extraction" half of the query pipeline.
_QT_KEYWORDS: Dict[str, List[str]] = {
    "financial_metric": ["financial", "revenue", "profit", "margin", "cash",
                         "ebitda", "income", "earnings", "metric"],
    "comparison": ["compare", "comparison", "vs", "versus", "against"],
    "trend_analysis": ["trend", "growth", "market share", "outlook",
                       "forecast", "projection"],
    "strategy_recommendation": ["strategy", "recommend", "recommendation",
                                "invest", "expansion"],
    "regulatory": ["regulatory", "regulation", "compliance", "sec", "filing"],
}

# question types that map to a derived class (reasoning showcase): when the
# hint fires we query the derived class instead of the raw property.
_DERIVED_BY_QT = {
    "financial_metric": GI.FinancialReport,
    "comparison": GI.ComparisonReport,
}


def load_index(path: Path = CLOSURE_PATH) -> Graph:
    """Load the materialized closure for SPARQL querying."""
    g = Graph()
    g.bind("gi", GI)  # generated queries rely on this prefix
    g.parse(path, format="turtle")
    return g


# --- intent extraction (deterministic string rules) -------------------------

def _known_entities(graph: Graph) -> List[tuple]:
    """All labeled individuals that are entities (any EntityType subclass)."""
    q = """PREFIX gi: <http://langconfig.local/graphindex#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT DISTINCT ?e ?label WHERE {
             ?e rdf:type ?cls .
             ?cls rdfs:subClassOf* gi:EntityType .
             ?e rdfs:label ?label . }"""
    return [(row["e"], str(row["label"])) for row in graph.query(q)]


def extract_entities(graph: Graph, query: str) -> List[URIRef]:
    """String-match query text against known entity labels (longest first)."""
    q = query.lower()
    hits = sorted(
        ((len(label), uri) for uri, label in _known_entities(graph)
         if label.lower() in q),
        reverse=True,
    )
    return [uri for _, uri in hits]


def question_hints(query: str) -> List[str]:
    """Keyword-table question-type detection."""
    q = query.lower()
    return [qt for qt, kws in _QT_KEYWORDS.items() if any(k in q for k in kws)]


# --- SPARQL construction -----------------------------------------------------

def _values_block(var: str, uris) -> str:
    return f"VALUES ?{var} {{ {' '.join(f'<{u}>' for u in uris)} }}"


def _build_query(entities: List[URIRef], qtypes: List[str],
                 query: str) -> Optional[str]:
    """Build a fixed SPARQL template from the extracted intent.

    Returns None when there is genuinely nothing to match.
    """
    parts: List[str] = []
    used_derived = False
    for qt in qtypes:
        if qt in _DERIVED_BY_QT and entities:
            parts.append(f"?doc rdf:type gi:{_DERIVED_BY_QT[qt].split('#')[-1]} .")
            used_derived = True
            break

    if entities:
        parts.append("?doc gi:mentionsEntity ?e .")
        parts.append(_values_block("e", entities))
    if qtypes and not used_derived:
        parts.append("?doc gi:answersQuestionType ?qt .")
        parts.append(_values_block("qt", [GI[qt] for qt in qtypes]))
    if not parts:
        # No entity and no hint: last-resort substring match on title.
        tokens = [t for t in re.split(r"\W+", query.lower())
                  if t and t not in _STOPWORDS]
        if not tokens:
            return None
        conds = " || ".join(f"CONTAINS(LCASE(?title), '{t}')" for t in tokens)
        parts.append(f"FILTER({conds})")
    parts.append("?doc gi:hasTitle ?title .")
    # Every generated query declares its prefixes inline: rdflib does not
    # fall back to the graph's bound namespaces when resolving `gi:`.
    return ("PREFIX gi: <" + ONTOLOGY_IRI + "#>\n"
            "SELECT DISTINCT ?doc ?title WHERE {\n  "
            + "\n  ".join(parts) + "\n}")


# --- query entry point -------------------------------------------------------

def search(graph: Graph, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Deterministic routing: extract intent -> SPARQL -> ranked docs."""
    query = query.strip()
    if not query:
        return []

    entities = extract_entities(graph, query)
    qtypes = question_hints(query)
    sparql = _build_query(entities, qtypes, query)
    if sparql is None:
        return []

    results: List[Dict[str, Any]] = []
    for row in graph.query(sparql):
        doc = row["doc"]
        title = str(row["title"])
        matched = [e for e in entities if (doc, GI.mentionsEntity, e) in graph]
        reasons = []
        if matched:
            labels = [str(l) for e in matched for l in graph.objects(e, RDFS.label)]
            reasons.append("mentions " + ", ".join(labels))
        if qtypes:
            reasons.append("answers " + ", ".join(qtypes))
        # Ranking: more matched entities wins, then presence of question-type
        # hints; a derived-class hit is the strongest signal.
        score = len(matched) * 10 + len(qtypes) * 3 + (5 if qtypes else 0)
        results.append({"doc": str(doc), "title": title,
                        "score": score, "reasons": reasons})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]
