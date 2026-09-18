"""Phase 9 / Step 2.6 — deterministic RDF/OWL document index (trial).

A self-contained trial of the agreed architecture:

  Probabilistic ingestion (LLM)  ->  per-document RDF triples (.ttl)
  Schema + rules (TBox)          ->  graphindex-ontology.owl (Protégé-editable)
  Reasoner (owlready2)           ->  materialized closure (index_closure.ttl)
  Retrieval (rdflib + SPARQL)    ->  rule-based query translation, no LLM

Pipeline modules:

  tbox.py    Build the OWL TBox (classes, individuals, object/data
             properties, derived classes) from the ontology md.
  ingest.py  One document's enrichment -> one Turtle ABox fragment.
  reason.py  Merge TBox + ABox, run the reasoner, export the closure.
  query.py   Rule-based intent extraction -> SPARQL over the closure.
  demo.py    End-to-end trial with sample enrichments + sample queries.

Run from learning/phase9/:

    python -m rdfindex.demo

Neo4j / LangChain / the LLM are NOT used here: the enrichment dicts fed to
ingest.py are stand-ins for what `extract_document_enrichment` in
graphindex/index_build.py already produces.
"""
