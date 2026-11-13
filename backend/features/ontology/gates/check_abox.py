#!/usr/bin/env python3
"""Per-ontology ABox gate: the individuals, and the entailments the reasoner must produce.

Every other gate in this directory judges a **TBox** — classes, properties, metrics, panels — over a
relational database that already holds the rows. This one judges an **ABox**: individuals written as
RDF, plus a reasoner's answers about them. That is a different contract, and it is the one team-4
needs (277 CV scans x 10 job descriptions), because the question "which candidates match this job"
is nowhere in the data: it has to be entailed.

    <profile>/abox.ttl            the individuals (asserted facts only)
    <profile>/reasoning.ttl       the DL axioms: class definitions the reasoner uses
    <profile>/reasoning.json      what must be TRUE after reasoning, and what must go RED without it

`reasoning.json`:

    {"reasoner": "hermit",
     "inferred": [{"class": "matchesDesignEngineer", "members": ["cand_01"],
                   "why": "CAD skill + 7y >= 3y"}],
     "excluded": [{"class": "matchesDesignEngineer", "individuals": ["cand_03"],
                   "why": "1 year < 3"}],
     "falsify":  [{"label": "drop the definition",
                   "drop": {"subject": "matchesDesignEngineer", "predicate": "equivalentClass"},
                   "class": "matchesDesignEngineer", "then_excluded": ["cand_01"]},
                  {"label": "drop one skill assertion",
                   "drop": {"subject": "cand_01", "predicate": "hasSkill"},
                   "class": "matchesDesignEngineer", "then_excluded": ["cand_01"]}],
     "coverage": {"source_files": 277, "loaded_individuals": 277,
                  "required_props": ["hasSkill", "yearsExperience"],
                  "allow_missing_props": ["yearsExperience"]},
     "pii":      {"patterns": ["\\b1[3-9]\\d{9}\\b", "[\\w.+-]+@[\\w-]+\\.[\\w.]+"],
                  "max_name_chars": 4}}

Families:

    A1  every individual is typed, and every type is declared in the TBox
    A2  an entailed member is ENTAILED — it must not be asserted in the ABox
    A3  declared exclusions stay excluded (the negative half of A2)
    A4  the ontology is consistent and declares no unsatisfiable class
    A5  ABox coverage: what was loaded matches what the source said, required properties present
    A6  no PII in the ABox (phone / email / over-long name)
    A7  FALSIFICATION — remove the axiom or the datum, and the entailment must disappear

A7 is the family that makes A2 mean something. The platform learned this at D-family: a gate that
cannot be made to go red is a gate that proves nothing, and "the reasoner said so" is exactly the
kind of evidence that quietly stops being true.

Usage:
    PY=backend/.venv/bin/python
    $PY backend/features/ontology/gates/check_abox.py --profile features/ontology/profiles/talent_v1/talent_v1_settings.json
    $PY …/check_abox.py --profile … --as-json

Exit: 0 all checks pass, 1 something failed, 2 nothing to check (and it says which file is missing).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
# `features.ontology.reasoning` is imported by its package path, so the BACKEND root goes on sys.path
# (HERE is backend/features/ontology/gates). Measured the hard way: run as a script, the first
# version put features/ontology on the path and every check died with ModuleNotFoundError: features.
sys.path.insert(0, str(HERE.parents[2]))

OK = True
CHECKS = 0


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


def _resolve(profile: pathlib.Path, name: str) -> pathlib.Path:
    return (profile.parent / name).resolve()


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--as-json", action="store_true")
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    if not profile.is_file():
        print(f"NOT RUN — no profile at {profile}")
        return 2

    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    onto_dir = (profile.parent / (settings.get("ontology_dir") or "ontology")).resolve()

    abox_path = _resolve(profile, settings.get("abox") or "abox.ttl")
    axioms_path = _resolve(profile, settings.get("reasoning") or "reasoning.ttl")
    spec_path = _resolve(profile, settings.get("reasoning_spec") or "reasoning.json")

    print(f"profile: {profile}")
    print(f"ns:      {ns}")
    print(f"abox:    {abox_path}")
    print(f"axioms:  {axioms_path}")
    print(f"spec:    {spec_path}")

    missing = [str(p.name) for p in (abox_path, axioms_path, spec_path) if not p.is_file()]
    if missing:
        print(f"\nNOT RUN — the profile declares an ABox but is missing {missing}. An ABox profile "
              "needs all three: abox.ttl (individuals), reasoning.ttl (axioms), reasoning.json "
              "(what must be true).")
        return 2

    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    from features.ontology.reasoning import reasoner as R

    usable, why = R.available()
    if not usable:
        print(f"\nNOT RUN — the reasoner is unavailable: {why}")
        return 2

    tbox_files = [axioms_path]
    for extra in ("01-structure.ttl", "02-meaning.ttl"):
        candidate = onto_dir / extra
        if candidate.is_file():
            tbox_files.append(candidate)
    graph = R.load_graph(tbox_files + [abox_path])

    # ── A1  typing
    print("\n=== A1 every individual is typed, and every type is declared ===")
    from rdflib import RDF, RDFS, URIRef
    from rdflib.namespace import OWL

    declared = {str(s) for s in graph.subjects(RDF.type, OWL.Class)}
    declared |= {str(s) for s in graph.subjects(RDF.type, RDFS.Class)}
    individuals: dict[str, set[str]] = {}
    for s, _, o in graph.triples((None, RDF.type, None)):
        if str(o) in declared:
            individuals.setdefault(str(s), set()).add(str(o))
    check_true("the ABox has individuals", bool(individuals),
               "no resource in abox.ttl carries rdf:type of a declared class")
    # A CLASS typed `owl:Class` is metamodelling, not an untyped individual — the first version of
    # this check reported the TBox's own classes as stray individuals (7 of them on a green fixture).
    metamodel = {str(OWL.Class), str(RDFS.Class), str(OWL.ObjectProperty), str(OWL.DatatypeProperty),
                 str(OWL.AnnotationProperty), str(OWL.Restriction), str(OWL.Ontology),
                 str(OWL.TransitiveProperty), str(OWL.FunctionalProperty), str(OWL.NamedIndividual)}
    untyped = sorted(str(s) for s, _, o in graph.triples((None, RDF.type, None))
                     if str(o) not in declared and str(o) not in metamodel
                     and not str(s).startswith(str(OWL)) and str(s) != str(OWL.Nothing)
                     and isinstance(s, URIRef) and "#" in str(s))
    check_true("no individual carries a type the TBox does not declare", not untyped,
               f"{len(untyped)}: {[_local(u) for u in untyped[:6]]}")
    print(f"  individuals: {len(individuals)}")

    # ── the reasoner, once, over everything the spec asks about
    watch = [ns + item["class"] for item in
             (spec.get("inferred") or []) + (spec.get("excluded") or [])]
    for f in spec.get("falsify") or []:
        if f.get("class"):
            watch.append(ns + f["class"])
    watch = sorted(set(watch))
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=watch)
    print(f"\nreasoner: {result.engine} · {result.elapsed_ms:.0f} ms")
    for note in result.notes:
        print(f"  note: {note}")

    # ── A2  entailment, not assertion
    print("\n=== A2 the members are ENTAILED (nobody typed them) ===")
    for item in spec.get("inferred") or []:
        cls = ns + item["class"]
        want = [ns + m for m in (item.get("members") or [])]
        got = set(result.members_of(cls))
        check_true(f"{item['class']}: the reasoner finds {[_local(m) for m in want]}",
                   all(m in got for m in want),
                   f"members are {sorted(_local(g) for g in got)}")
        asserted = [m for m in want if (URIRef(m), RDF.type, URIRef(cls)) in graph]
        check_true(f"{item['class']}: those members are not asserted in abox.ttl",
                   not asserted,
                   f"{[_local(a) for a in asserted]} carries rdf:type {item['class']} in the file — "
                   "that is a copied answer, not a reasoned one")

    # ── A3  exclusions
    print("\n=== A3 the declared exclusions stay out ===")
    for item in spec.get("excluded") or []:
        cls = ns + item["class"]
        got = set(result.members_of(cls))
        bad = [ns + i for i in (item.get("individuals") or []) if (ns + i) in got]
        check_true(f"{item['class']}: {item.get('why') or 'excluded'}",
                   not bad, f"wrongly a member: {[_local(b) for b in bad]}")

    # ── A4  consistency
    print("\n=== A4 the ontology is consistent ===")
    cons = spec.get("consistency") or {}
    if cons.get("must_be_consistent", True):
        check_true("the reasoner accepted the ontology", result.consistent,
                   "; ".join(result.notes) or "inconsistent")
    allowed_unsat = {ns + c for c in cons.get("unsatisfiable_allowed") or []}
    unsat = [c for c in result.unsatisfiable_classes if c not in allowed_unsat]
    check_true("no undeclared unsatisfiable class", not unsat,
               f"{[_local(u) for u in unsat]} — an unsatisfiable class makes every entailment vacuous")

    # ── A5  coverage
    print("\n=== A5 the ABox covers what the source had ===")
    cov = spec.get("coverage") or {}
    if "loaded_individuals" in cov:
        check_true(f"loaded {cov['loaded_individuals']} individual(s)", len(individuals) >=
                   int(cov["loaded_individuals"]),
                   f"abox.ttl carries {len(individuals)}")
    if "source_files" in cov:
        covered = int(cov.get("loaded_individuals") or 0)
        check_true(f"every source file became an individual ({cov['source_files']} files)", covered >=
                   int(cov["source_files"]),
                   f"{int(cov['source_files']) - covered} source(s) unaccounted for — an unparsed CV "
                   "must be declared as :Unknown, never dropped")
    allow_missing = set(cov.get("allow_missing_props") or [])
    # CLASS-scoped on purpose: "every individual has :yearsExperience" is nonsense for a skill or a
    # job opening, and a gate that demands it teaches the builder to invent the number.
    for entry in cov.get("required_props") or []:
        if isinstance(entry, str):
            cls_local, prop = "", entry
        else:
            cls_local, prop = entry.get("class") or "", entry.get("prop") or ""
        label = f"every :{cls_local or 'individual'} carries :{prop}"
        if prop in allow_missing:
            not_run(label, "declared as allowed-missing")
            continue
        lacking = sorted(
            _local(i) for i, types in individuals.items()
            if (not cls_local or (ns + cls_local) in types)
            and not list(graph.objects(URIRef(i), URIRef(ns + prop))))
        check_true(label, not lacking, f"{len(lacking)} lacking, e.g. {lacking[:5]}")

    # ── A6  PII
    print("\n=== A6 no PII in the ABox ===")
    pii = spec.get("pii") or {}
    text = abox_path.read_text(encoding="utf-8")
    for pattern in pii.get("patterns") or []:
        hits = re.findall(pattern, text)
        check_true(f"no match for /{pattern}/", not hits, f"{len(hits)} hit(s): {hits[:3]}")
    max_name = pii.get("max_name_chars")
    if max_name:
        long_names = [n for n in re.findall(r'"([^"]{2,})"', text) if len(n) > int(max_name)
                      and not n.startswith("http")]
        check_true(f"no literal longer than {max_name} chars (names stay masked)", not long_names,
                   f"{len(long_names)} e.g. {long_names[:3]}")

    # ── A7  falsification
    print("\n=== A7 falsification: remove the reason and the entailment must go ===")
    for item in spec.get("falsify") or []:
        drop = item.get("drop") or {}
        mutated, removed = R.mutate(graph, subject=drop.get("subject", ""),
                                    predicate=drop.get("predicate", ""),
                                    obj=drop.get("object"), namespace=ns)
        label = item.get("label") or f"drop {drop}"
        check_true(f"{label}: the mutation removed something", removed > 0,
                   "no triple matched the removal spec — a mutation that changes nothing proves nothing")
        if not removed:
            continue
        cls = ns + item["class"]
        after = set(R.reason(mutated, engine=spec.get("reasoner") or "hermit",
                             watch_classes=[cls]).members_of(cls))
        still = [ns + i for i in item.get("then_excluded") or [] if (ns + i) in after]
        check_true(f"{label}: {[_local(s) for s in still] or 'the entailment'} disappears",
                   not still, f"still entailed: {[_local(s) for s in still]} — those members were "
                              "asserted, not reasoned")

    print()
    verdict = "green" if OK else "red"
    print(f"{CHECKS} checks · {'0 failed' if OK else 'FAILED'} · {verdict}")
    if args.as_json:
        print(json.dumps({"ok": OK, "checks": CHECKS, "verdict": verdict,
                          "individuals": len(individuals),
                          "reasoner": result.engine,
                          "elapsed_ms": round(result.elapsed_ms, 1),
                          "unsatisfiable": [_local(u) for u in result.unsatisfiable_classes]},
                         ensure_ascii=False))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
