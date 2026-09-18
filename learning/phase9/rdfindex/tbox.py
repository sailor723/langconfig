"""OWL TBox (schema + rules) for the GraphIndex document ontology.

Trial version of the deterministic RDF/OWL document index.

Builds an OWL ontology programmatically from the single source of truth
(.Codex/docs/graphindex-ontology.md), so the controlled vocabularies
(entity_type, genre, primary_subject, question_types, role) stay editable
in one place — or in Protégé, by opening the generated
artifacts/graphindex-ontology.owl.

The reasoner-relevant content lives in the *derived classes* at the
bottom: they encode relevance rules such as "any document of genre
financial_data is a FinancialReport". reason.py runs the reasoner over
this TBox + the ABox once, at ingest time; queries only ever read the
materialized closure, so retrieval is fully deterministic.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

from owlready2 import (
    DataProperty,
    ObjectProperty,
    Thing,
    World,
    get_ontology,
    sync_reasoner,  # noqa: F401  (re-exported for reason.py convenience)
)

# Ontology IRI: owlready2 appends '#' to individual names; rdflib Namespace
# (GI = Namespace(IRI + "#")) must agree so both sides address the same IRIs.
ONTOLOGY_IRI = "http://langconfig.local/graphindex"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
_ONTOLOGY_MD = REPO_ROOT / ".Codex" / "docs" / "graphindex-ontology.md"

# Built-in fallback keeps the TBox importable/buildable if the md is missing
# or unparseable (same vocabularies as graphindex/index_build.py).
_ONTOLOGY_FALLBACK: Dict[str, List[str]] = {
    "entity_type": [
        "Organization", "Industry", "Person", "Product", "Brand",
        "Geography", "Metric", "Department", "Concept",
    ],
    "role": ["subject", "competitor", "partner", "author", "source", "market", "other"],
    "genre": [
        "company_analysis", "industry_analysis", "comparison", "survey", "dossier",
        "strategic_framework", "financial_data", "source_document", "filing",
        "dashboard", "other",
    ],
    "primary_subject": [
        "economy_business_finance", "science_technology", "labour", "environment",
        "health", "education", "society", "politics", "other",
    ],
    "question_types": [
        "factual", "financial_metric", "comparison", "trend_analysis",
        "customer_support", "regulatory", "strategy_recommendation", "other",
    ],
}


# --- Markdown parsers (same logic as graphindex/index_build.py.load_ontology) ---

def _md_table_values(text: str, header: str) -> list[str]:
    """Collect first-column backticked tokens from a markdown table."""
    start = text.find(header)
    if start < 0:
        return []
    lines = text[start:].splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and "---" in line and i > 0:
            lines = lines[i + 1:]
            break
    values: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            if values:
                break
            continue
        m = re.search(r"`([a-zA-Z][a-zA-Z0-9_]*)`", line)
        if m and m.group(1) not in values:
            values.append(m.group(1))
    return values


def _md_brace_values(text: str) -> list[str]:
    """Parse the `` `role` ∈ `{a, b, c}` `` idiom."""
    m = re.search(r"`\{([^}`]+)\}`", text)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _md_inline_values(text: str, section: str) -> list[str]:
    """Collect backticked snake_case tokens from a markdown section."""
    start = text.find(section)
    if start < 0:
        return []
    body = text[start:]
    m = re.search(r"\n(?=#{2,3} )", body)
    if m:
        body = body[:m.start()]
    return list(dict.fromkeys(re.findall(r"`([a-z][a-z0-9_]*)`", body)))


def parse_vocab(md_path: Path = _ONTOLOGY_MD) -> Dict[str, List[str]]:
    """Parse the controlled vocabularies from the ontology md."""
    try:
        text = md_path.read_text(encoding="utf-8")
        parsed = {
            "entity_type": _md_table_values(text, "| `entity_type` |"),
            "role": _md_brace_values(text),
            "genre": _md_inline_values(text, "### 2.1 genre"),
            "primary_subject": _md_inline_values(text, "### 2.2 primary_subject"),
            "question_types": _md_inline_values(text, "### 2.4 question_types"),
        }
    except Exception as e:
        sys.stderr.write(f"WARNING: failed to read ontology md {md_path}: {e}\n")
        return dict(_ONTOLOGY_FALLBACK)
    return {field: (values if values else _ONTOLOGY_FALLBACK[field])
            for field, values in parsed.items()}


# --- TBox construction -----------------------------------------------------

def build_tbox(vocab: Optional[Dict[str, List[str]]] = None,
               out: Optional[Path] = None) -> World:
    """Build the OWL TBox and save it as RDF/XML (openable in Protégé).

    Returns the owlready2 World so callers can inspect the schema.
    """
    vocab = vocab or parse_vocab()
    out = out or ARTIFACT_DIR / "graphindex-ontology.owl"
    out.parent.mkdir(parents=True, exist_ok=True)

    world = World()
    onto = world.get_ontology(ONTOLOGY_IRI)
    with onto:
        # --- classes --------------------------------------------------------
        class Document(Thing):
            """A routed document node (equivalent to a :Document subject)."""

        class EntityType(Thing):
            """Root of the typed-entity hierarchy."""

        # Each entity_type value becomes a subclass of EntityType.
        entity_classes: Dict[str, Any] = {
            name: types.new_class(name, (EntityType,), {})
            for name in vocab["entity_type"]
        }
        Metric = entity_classes["Metric"]
        Organization = entity_classes["Organization"]

        class Genre(Thing):
            """Document genre (controlled vocabulary as individuals)."""

        class PrimarySubject(Thing):
            """IPTC-aligned top-level subject (individuals)."""

        class QuestionType(Thing):
            """Kinds of questions a document can answer (individuals)."""

        class Role(Thing):
            """Entity role relative to a document (individuals)."""

        # --- individuals for the controlled vocabularies --------------------
        genre_values = {v: onto.Genre(v) for v in vocab["genre"]}
        for v in vocab["primary_subject"]:
            onto.PrimarySubject(v)
        for v in vocab["question_types"]:
            onto.QuestionType(v)
        for v in vocab["role"]:
            onto.Role(v)

        # --- object properties ----------------------------------------------
        class mentionsEntity(ObjectProperty):
            domain = [Document]
            range = [EntityType]

        class hasGenre(ObjectProperty):
            domain = [Document]
            range = [Genre]

        class hasPrimarySubject(ObjectProperty):
            domain = [Document]
            range = [PrimarySubject]

        class answersQuestionType(ObjectProperty):
            domain = [Document]
            range = [QuestionType]

        # --- data properties --------------------------------------------------
        class hasTitle(DataProperty):
            domain = [Document]

        class hasSummary(DataProperty):
            domain = [Document]

        class filePath(DataProperty):
            domain = [Document]

        class supportedQuery(DataProperty):
            domain = [Document]

        # --- derived classes: the "rules" the reasoner will apply -------------
        # Relevance rules as equivalent-class axioms. The reasoner derives the
        # class memberships at ingest time, so queries can reference these
        # classes directly (see query.py).
        financial_data = genre_values["financial_data"]
        comparison = genre_values["comparison"]

        class FinancialReport(Document):
            """Any document whose genre is financial_data."""

            equivalent_to = [Document & hasGenre.value(financial_data)]

        class ComparisonReport(Document):
            """Any document whose genre is comparison."""

            equivalent_to = [Document & hasGenre.value(comparison)]

        class InvestmentGradeReport(Document):
            """Any document that mentions both a Metric and an Organization.

            The conjunction showcase: two independent facts (mentions a
            metric, mentions an organization) imply a new class membership
            that was never asserted directly.
            """

            equivalent_to = [
                Document & mentionsEntity.some(Metric) & mentionsEntity.some(Organization)
            ]

    onto.save(file=str(out), format="rdfxml")
    return world


if __name__ == "__main__":
    w = build_tbox()
    onto = w.get_ontology(ONTOLOGY_IRI)
    print(f"TBox built: {len(onto.classes())} classes, {len(onto.individuals())} individuals")
