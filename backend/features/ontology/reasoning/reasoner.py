#!/usr/bin/env python3
"""Reasoning over an ABox: one place that turns a TBox + individuals into entailments.

WHY A DL REASONER AND NOT OWL 2 RL (measured 2026-11-14, both on this repo's venv and on the
deployment, same TBox and ABox):

    :matchesDesignEngineer ≡ :Candidate ⊓ (:hasSkill some :CAD)
                                       ⊓ (:yearsExperience some xsd:integer[>=3])

    engine                      needs          category + skill taxonomy   numeric facet ">=3"
    HermiT via owlready2        Java            ✅                          ✅
    owlrl (OWL 2 RL, pure py)   rdflib only     ✅                          ❌ (match class stays empty)

Recruiting judgement is almost entirely thresholds — years, salary band, education level, "3 of 4
dimensions" — and OWL 2 RL's datatype rules explicitly do not decide facets (`rl-dt-*` covers literal
types and equality only). A pure-Python chainer therefore cannot close the questions this ontology
exists to answer. HermiT can, in ~270 ms on this shape.

The second measured lesson is in `tests/test_abox_reasoning.py`: skills must be INDIVIDUALS of a class
(`:SolidWorks a :CAD`), not subclasses of it. `rdfs:subClassOf` says nothing about an individual that
was never typed with the subclass, so a taxonomy over classes classifies nothing that the data
actually names.

This module deliberately does NOT diff serialised graphs. owlready2 rebuilds blank nodes on save (the
first prototype's "inferred triples" were 22 anonymous-class regenerations, not entailments), so the
only trustworthy answers are asked of the reasoner directly: "who is in this class now", "which
classes are unsatisfiable", "is the ontology consistent".
"""
from __future__ import annotations

import contextlib
import pathlib
import shutil
import tempfile
import time
from dataclasses import dataclass, field

#: IRI of owl:Nothing / owl:Thing — the two poles every DL reasoner reasons towards.
OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def available() -> tuple[bool, str]:
    """(usable, why not) — a gate must be able to say NOT RUN instead of passing quietly."""
    try:
        import owlready2  # noqa: F401
    except Exception as exc:
        return False, f"owlready2 is not installed ({exc}) — pip install owlready2"
    java = shutil.which("java")
    if not java and not __import__("os").environ.get("JAVA_HOME"):
        return False, ("no java on PATH: HermiT is a Java reasoner — install a JRE "
                       "(debian/ubuntu: apt-get install default-jre-headless)")
    return True, ""


@dataclass
class ReasonResult:
    """What the reasoner answered, in the terms a gate can assert on."""

    engine: str
    consistent: bool = True
    inconsistent_classes: list[str] = field(default_factory=list)
    unsatisfiable_classes: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    #: class IRI -> individual IRIs, as the reasoner sees them AFTER reasoning (asserted + inferred)
    members: dict[str, list[str]] = field(default_factory=dict)

    def members_of(self, class_iri: str) -> list[str]:
        return list(self.members.get(class_iri) or [])

    def is_member(self, class_iri: str, individual_iri: str) -> bool:
        return individual_iri in set(self.members.get(class_iri) or [])


def load_graph(paths: list[pathlib.Path]):
    """Parse every TTL into one rdflib graph — the asserted side, exactly as the files say."""
    from rdflib import Graph

    g = Graph()
    for path in paths:
        p = pathlib.Path(path)
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        # A TTL file may carry a settings-style JSON block? No: ontology files are pure Turtle. If it
        # fails to parse we raise rather than skipping — a silently skipped file is a silent TBox.
        g.parse(data=text, format="turtle")
    return g


def _iri_of(entity) -> str:
    return str(getattr(entity, "iri", "") or "")


def reason(graph, engine: str = "hermit", *, infer_property_values: bool = True,
           watch_classes: list[str] | None = None) -> ReasonResult:
    """Run the reasoner over `graph` and report consistency + membership of `watch_classes`.

    `watch_classes` are full IRIs (or `ns#Local` built by the caller); only those are returned, because
    materialising every class in a real ontology is how this becomes slow for no gain.
    """
    usable, why = available()
    if not usable:
        raise RuntimeError(why)
    if engine.lower() not in ("hermit", "hermit2", "pellet"):
        raise ValueError(f"unsupported reasoner {engine!r} (this module wires HermiT; owlrl is a "
                         "different, weaker contract — see the module docstring)")

    import owlready2

    java = shutil.which("java")
    if java:
        owlready2.JAVA_EXE = java

    result = ReasonResult(engine=engine.lower())
    rdfxml = graph.serialize(format="xml")
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        owl_file = pathlib.Path(td) / "ontology.owl"
        owl_file.write_text(rdfxml, encoding="utf-8")
        # ONE WORLD PER CALL. owlready2 caches entities globally by IRI, so a second `reason()` over a
        # mutated graph answered with the FIRST run's class objects and reported membership that the
        # mutation had already removed (measured: falsification "passed" while proving nothing).
        # An isolated world also keeps two profiles from polluting each other inside one process.
        world = owlready2.World()
        onto = world.get_ontology(owl_file.as_uri()).load()
        # HermiT prints to stdout; a gate's output must stay its own report.
        with contextlib.redirect_stdout(_devnull()), contextlib.redirect_stderr(_devnull()):
            with onto:
                try:
                    # `world` is not a keyword here (owlready2 0.51): passing it raised TypeError,
                    # which the except below swallowed as "inconsistent" — a reasoning gate that never
                    # ran would have reported the ontology broken. The isolated World is enough: the
                    # entities resolved below come from `onto`, so no global IRI cache is consulted.
                    owlready2.sync_reasoner([onto], infer_property_values=infer_property_values,
                                            debug=0)
                except Exception as exc:  # OwlReadyInconsistentOntologyError and friends
                    result.consistent = False
                    result.notes.append(f"reasoner refused the ontology: {type(exc).__name__}: {exc}")
        result.elapsed_ms = (time.perf_counter() - t0) * 1000

        try:
            result.inconsistent_classes = sorted(
                _iri_of(c) for c in onto.inconsistent_classes() if _iri_of(c))
        except Exception:
            pass
        try:
            result.unsatisfiable_classes = sorted(
                _iri_of(c) for c in onto.classes() if owlready2.Nothing in list(c.ancestors()))
        except Exception:
            pass

        by_iri = {_iri_of(c): c for c in onto.classes() if _iri_of(c)}
        for iri in watch_classes or []:
            cls = by_iri.get(iri)
            if cls is None:
                result.notes.append(f"class {iri} is not in the ontology — cannot ask who is in it")
                continue
            try:
                result.members[iri] = sorted(_iri_of(i) for i in cls.instances())
            except Exception as exc:
                result.notes.append(f"class {iri}: {type(exc).__name__}: {exc}")
    return result


class _devnull:
    def __enter__(self):
        import os
        self._fh = open(os.devnull, "w")
        return self._fh

    def __exit__(self, *exc):
        self._fh.close()
        return False


# ─────────────────────────────────────────────── mutations (a gate that cannot go red is not a gate)
def mutate(graph, *, subject: str, predicate: str, obj: str | None = None,
           namespace: str = ""):
    """Return a COPY of `graph` with one axiom removed — the falsification input.

    Names in the removal spec are local names (`matchesDesignEngineer`, `equivalentClass`); the IRIs
    are built from `namespace` (the profile's `ns`) and the well-known OWL/RDF prefixes. Removing the
    definition of a class must make its inferred members disappear: if it does not, the membership was
    asserted rather than reasoned and the gate that "proved" it proved nothing.
    """
    from rdflib import Graph
    import re

    copy = Graph()
    for prefix, ns in graph.namespaces():
        copy.bind(prefix, ns)
    for triple in graph:
        copy.add(triple)

    def expand(name: str) -> str:
        known = {
            "equivalentClass": "http://www.w3.org/2002/07/owl#equivalentClass",
            "intersectionOf": "http://www.w3.org/2002/07/owl#intersectionOf",
            "onProperty": "http://www.w3.org/2002/07/owl#onProperty",
            "someValuesFrom": "http://www.w3.org/2002/07/owl#someValuesFrom",
            "Restriction": "http://www.w3.org/2002/07/owl#Restriction",
            "Class": "http://www.w3.org/2002/07/owl#Class",
            "subClassOf": "http://www.w3.org/2000/01/rdf-schema#subClassOf",
        }
        if name in known:
            return known[name]
        if re.match(r"^(https?|urn|file):", name):
            return name
        return f"{namespace}{name}"

    from rdflib import URIRef

    s = URIRef(expand(subject))
    p = URIRef(expand(predicate))
    o = URIRef(expand(obj)) if obj else None
    removed = 0
    for triple in list(copy.triples((s, p, o))):
        copy.remove(triple)
        removed += 1
    return copy, removed
