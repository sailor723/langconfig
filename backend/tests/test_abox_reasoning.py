"""Reasoning that can be *wrong* — the ABox contract, proven on a synthetic TBox first.

The team-4 build (277 CV scans x 10 job descriptions) answers questions nobody stored: "which
candidates match this job". A reasoner can produce those answers, and it can also produce them for
the wrong reasons — data asserted instead of inferred, an axiom that no longer exists, an
unsatisfiable class that makes every answer true. So the contract has four parts and each one is
asserted here:

  1. **entailment appears** — the class is defined, nobody types the individual, reasoning finds it;
  2. **falsification goes red** — remove the axiom (or the individual's skill) and the member
     disappears. A membership that survives the removal was never reasoned;
  3. **the DL facet is the reason HermiT is here** — a candidate with 1 year must be excluded by
     `xsd:minInclusive 3`; OWL 2 RL cannot decide that (measured: owlrl leaves the class empty);
  4. **isolation** — two `reason()` calls in one process must not share owlready2's global entity
     cache, or a mutation silently answers with the previous run's class objects.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from rdflib import Graph  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402

NS = "http://example.org/talent#"

TBOX = """
@prefix : <http://example.org/talent#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Candidate a owl:Class .
:Skill a owl:Class .
:CAD a owl:Class ; rdfs:subClassOf :Skill .
:hasSkill a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :Skill .
:yearsExperience a owl:DatatypeProperty ; rdfs:domain :Candidate ; rdfs:range xsd:integer .

:matchesDesignEngineer a owl:Class ;
    owl:equivalentClass [ owl:intersectionOf (
        :Candidate
        [ a owl:Restriction ; owl:onProperty :hasSkill ; owl:someValuesFrom :CAD ]
        [ a owl:Restriction ; owl:onProperty :yearsExperience ;
          owl:someValuesFrom [ a rdfs:Datatype ; owl:onDatatype xsd:integer ;
                               owl:withRestrictions ( [ xsd:minInclusive 3 ] ) ] ]
    ) ] .
"""

ABOX = """
@prefix : <http://example.org/talent#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:SolidWorks a :CAD .
:Excel a :Skill .
:cand_01 a :Candidate ; :hasSkill :SolidWorks ; :yearsExperience 7 .
:cand_02 a :Candidate ; :hasSkill :Excel ;       :yearsExperience 9 .
:cand_03 a :Candidate ; :hasSkill :SolidWorks ; :yearsExperience 1 .
"""


def _graph() -> Graph:
    g = Graph()
    g.parse(data=TBOX, format="turtle")
    g.parse(data=ABOX, format="turtle")
    return g


pytestmark = pytest.mark.skipif(not R.available()[0], reason=f"reasoner unavailable: {R.available()[1]}")


def _members(result, local="matchesDesignEngineer") -> list[str]:
    return sorted(m.rsplit("#", 1)[-1] for m in result.members_of(NS + local))


def test_entailment_appears_for_a_candidate_nobody_typed():
    res = R.reason(_graph(), watch_classes=[NS + "matchesDesignEngineer"])
    assert res.consistent, res.notes
    assert _members(res) == ["cand_01"], (
        "expected exactly cand_01 (CAD skill AND >=3 years). cand_02 has no CAD skill, cand_03 has "
        f"1 year; got {_members(res)}")


def test_the_numeric_facet_is_what_excludes_the_junior():
    """The reason this platform uses HermiT: OWL 2 RL cannot decide `xsd:minInclusive`."""
    res = R.reason(_graph(), watch_classes=[NS + "matchesDesignEngineer"])
    assert "cand_03" not in _members(res), "the 1-year candidate was not excluded by the facet"


def test_removing_the_axiom_turns_the_entailment_red():
    """A gate that cannot go red is not a gate."""
    mutated, removed = R.mutate(_graph(), subject="matchesDesignEngineer",
                                predicate="equivalentClass", namespace=NS)
    assert removed == 1, "the mutation did not remove the class definition"
    res = R.reason(mutated, watch_classes=[NS + "matchesDesignEngineer"])
    assert _members(res) == [], (
        "membership survived the removal of its definition — so it was asserted, not reasoned")


def test_removing_one_individuals_skill_removes_only_that_individual():
    mutated, removed = R.mutate(_graph(), subject="cand_01", predicate="hasSkill", namespace=NS)
    assert removed == 1
    res = R.reason(mutated, watch_classes=[NS + "matchesDesignEngineer"])
    assert "cand_01" not in _members(res), "the skill assertion did not drive the membership"


def test_two_runs_in_one_process_do_not_share_the_entity_cache():
    """owlready2 caches entities globally by IRI; a shared cache made the falsification look green."""
    first = R.reason(_graph(), watch_classes=[NS + "matchesDesignEngineer"])
    mutated, _ = R.mutate(_graph(), subject="matchesDesignEngineer",
                          predicate="equivalentClass", namespace=NS)
    second = R.reason(mutated, watch_classes=[NS + "matchesDesignEngineer"])
    assert _members(first) == ["cand_01"]
    assert _members(second) == [], "the second run answered with the first run's class definition"


def test_a_missing_class_is_reported_not_silently_empty():
    res = R.reason(_graph(), watch_classes=[NS + "noSuchClass"])
    assert res.members_of(NS + "noSuchClass") == []
    assert any("noSuchClass" in note for note in res.notes), (
        "an unknown class must be named in the notes: an empty result and a typo look identical")


def test_unsupported_reasoner_name_is_refused_by_name():
    with pytest.raises(ValueError, match="owlrl"):
        R.reason(_graph(), engine="owlrl")
