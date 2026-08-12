"""Materialize the reasoner's closure into the query store.

Pipeline (matches the agreed design):
  1. Merge the TBox (.owl) + every per-document ABox fragment (.ttl) into
     one combined graph (rdflib).
  2. Load that graph into owlready2 and run the reasoner (sync_reasoner).
     This *materializes* inferred facts — e.g. "doc X is a FinancialReport" —
     as ordinary triples.
  3. Export the reasoned closure as index_closure.ttl, the artifact every
     query reads. Query time is then pure SPARQL: no reasoning, no LLM.

The reasoner runs at ingest time (or after a schema change), never at
query time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from owlready2 import World, sync_reasoner
from rdflib import Graph, OWL, RDF, URIRef

from .tbox import ARTIFACT_DIR, ONTOLOGY_IRI

TRIPLE_DIR = ARTIFACT_DIR / "triples"
COMBINED_PATH = ARTIFACT_DIR / "combined.ttl"
COMBINED_NT_PATH = ARTIFACT_DIR / "combined.nt"  # owlready2 cannot parse turtle
CLOSURE_PATH = ARTIFACT_DIR / "index_closure.ttl"


def merge_abox(tbox_path: Path,
               triple_dir: Path,
               out: Path = COMBINED_PATH) -> Graph:
    """Merge the TBox + all per-doc ABox fragments into one graph."""
    g = Graph()
    g.parse(tbox_path, format="xml")  # RDF/XML as saved by owlready2
    for ttl in sorted(triple_dir.glob("*.ttl")):
        g.parse(ttl, format="turtle")
    # Guarantee an ontology declaration so owlready2 attaches the file to
    # the right ontology.
    if (URIRef(ONTOLOGY_IRI), RDF.type, OWL.Ontology) not in g:
        g.add((URIRef(ONTOLOGY_IRI), RDF.type, OWL.Ontology))
    g.serialize(out, format="turtle")
    return g


def materialize(tbox_path: Path,
                triple_dir: Path,
                out: Path = CLOSURE_PATH) -> dict:
    """Run the reasoner over TBox + ABox and export the materialized closure.

    Returns triple counts so callers can show how much the reasoner inferred.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_abox(tbox_path, triple_dir)
    before = len(merged)
    # owlready2 0.51's parsers only handle ntriples / rdfxml / owlxml (no
    # turtle), and format="turtle" silently falls through to the OWL/XML
    # parser, loading nothing. Serialize the merged graph to NTriples so
    # the reasoner actually sees the TBox + ABox triples.
    merged.serialize(COMBINED_NT_PATH, format="ntriples", encoding="utf-8")

    # Load the combined file fresh into an isolated world (no contamination
    # across repeated runs / imports).
    world = World()
    onto = world.get_ontology(ONTOLOGY_IRI)
    with open(COMBINED_NT_PATH, "rb") as f:
        onto.load(fileobj=f, format="ntriples")
    # HermiT (the default) runs via Java; owlready2 0.51 offers no
    # non-Java reasoner. sync_reasoner picks hermit automatically.
    sync_reasoner(onto)

    # world.as_rdflib_graph() includes the inferred triples.
    closure = world.as_rdflib_graph()
    closure.serialize(out, format="turtle")

    return {
        "combined_triples": before,
        "closure_triples": len(closure),
        "inferred": len(closure) - before,
    }
