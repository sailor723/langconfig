"""ABox writer: one document's enrichment -> one Turtle (.ttl) file.

The enrichment dict matches the shape produced by the LLM extraction in
learning/phase9/graphindex/index_build.py (Neo4jDocumentEnrichment), so the
ingest seam is a drop-in: the same structured output that today becomes
Neo4j properties becomes RDF triples here.

Only rdflib is needed (no owlready2, no Neo4j) — this module just emits
standard RDF fragments.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from rdflib import Graph, Literal, Namespace, RDF, RDFS

ONTOLOGY_IRI = "http://langconfig.local/graphindex"
GI = Namespace(ONTOLOGY_IRI + "#")

TRIPLE_DIR = Path(__file__).resolve().parent / "artifacts" / "triples"

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def slugify(text: str) -> str:
    """Turn an entity/doc name into a URI local name (camelCase, ASCII).

    "European EV Market" -> "europeanEvMarket"; "BYD" -> "byd".
    """
    words = _WORD_RE.findall(text)
    if not words:
        return "unnamed"
    return words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])


def enrichment_to_triples(doc_name: str,
                          file_path: str,
                          enrichment: Dict[str, Any],
                          out_dir: Path = TRIPLE_DIR) -> Path:
    """Write one document's enrichment as a Turtle ABox fragment."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"doc_{slugify(doc_name)}.ttl"

    g = Graph()
    g.bind("gi", GI)
    doc_uri = GI[f"doc_{slugify(doc_name)}"]

    g.add((doc_uri, RDF.type, GI.Document))
    g.add((doc_uri, GI.hasTitle, Literal(doc_name)))
    g.add((doc_uri, GI.hasSummary,
           Literal(enrichment.get("what_this_document_is_about") or "")))
    g.add((doc_uri, GI.filePath, Literal(file_path)))
    for sq in enrichment.get("supported_queries") or []:
        g.add((doc_uri, GI.supportedQuery, Literal(sq)))

    categories = enrichment.get("categories") or {}
    g.add((doc_uri, GI.hasGenre, GI[categories.get("genre") or "other"]))
    g.add((doc_uri, GI.hasPrimarySubject,
           GI[categories.get("primary_subject") or "other"]))
    for qt in categories.get("question_types") or []:
        g.add((doc_uri, GI.answersQuestionType, GI[qt]))

    for ent in enrichment.get("entities") or []:
        name = ent.get("name") or ""
        etype = ent.get("entity_type") or "Concept"
        ent_uri = GI[slugify(name)]
        g.add((doc_uri, GI.mentionsEntity, ent_uri))
        g.add((ent_uri, RDF.type, GI[etype]))
        g.add((ent_uri, RDFS.label, Literal(name)))

    g.serialize(out, format="turtle")
    return out
