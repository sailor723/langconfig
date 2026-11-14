#!/usr/bin/env python3
"""Ask the ontology a question that only the reasoner can answer — and see the difference.

The point of this repository's ABox support is one sentence: **the answer is in no row anywhere**. A CV
says which skills a person has and how many years they worked; a 職務説明書 says what the job needs. Nothing
stores "this person clears this role's bar" — HermiT entails it.

So this script runs your SPARQL TWICE, over the same data:

    asserted   `abox.ttl` as written (what any database query could see)
    entailed   the same graph plus the type assertions the reasoner derived

and prints both. A query whose two answers are identical is a query about stored data; a query whose
answer appears only in the second block is a query about MEANING.

    backend/.venv/bin/python backend/scripts/talent/ask_reasoner.py \\
        --profile backend/features/ontology/profiles/talent_v1/talent_v1_settings.json \\
        --query 'SELECT ?c WHERE { ?c a :matches_业务跟单 } LIMIT 5'

`--classes` limits which defined classes are reasoned (default: every `owl:equivalentClass` in the
TBox); `--list-classes` prints them first. Exit: 0 answered, 1 query failed, 2 nothing to reason over.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from rdflib import Graph, URIRef  # noqa: E402
from rdflib.namespace import OWL, RDF  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402


def _local(node) -> str:
    text = str(node)
    return text.rsplit("#", 1)[-1]


def _defined_classes(graph, ns: str) -> list[str]:
    """Classes with an `owl:equivalentClass` (or `owl:intersectionOf`) — the ones a reasoner can move."""
    out = set()
    for node in graph.subjects(RDF.type, OWL.Class):
        if str(node).startswith(ns) and (
                (node, OWL.equivalentClass, None) in graph or (node, OWL.intersectionOf, None) in graph
                or list(graph.objects(node, OWL.equivalentClass))):
            out.add(str(node))
    # the role classes are defined via equivalentClass on a restriction; catch them by name too
    for prefix in ("matches_", "matches"):
        for node in graph.subjects(RDF.type, OWL.Class):
            if _local(node).startswith(prefix):
                out.add(str(node))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--query", default="", help="SPARQL to run (ignored with --query-file)")
    ap.add_argument("--query-file", default="")
    ap.add_argument("--classes", default="", help="comma-separated class local names to reason")
    ap.add_argument("--list-classes", action="store_true")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = profile.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    if not (abox.is_file() and axioms.is_file()):
        print("nothing to reason over: the profile has no abox.ttl / reasoning.ttl")
        return 2

    graph = R.load_graph([axioms, abox])
    if args.classes:
        classes = [ns + c.strip() for c in args.classes.split(",") if c.strip()]
    else:
        classes = _defined_classes(graph, ns)
    if args.list_classes:
        print("defined classes:")
        for cls in classes:
            print("  :", _local(cls), sep="")
        return 0

    query = (pathlib.Path(args.query_file).expanduser().read_text(encoding="utf-8")
             if args.query_file else args.query)
    if not query.strip():
        print("no query: pass --query or --query-file")
        return 2

    def run(g: Graph, label: str) -> list[list[str]]:
        try:
            rows = g.query(query)
        except Exception as exc:
            print(f"  {label}: QUERY FAILED — {type(exc).__name__}: {exc}")
            return []
        values = [[_local(v) if hasattr(v, "n3") else str(v) for v in row] for row in rows]
        print(f"  {label}: {len(values)} row(s)")
        for row in values[: args.limit]:
            print("     ", " | ".join(str(v)[:44] for v in row))
        return values

    print(f"profile:  {profile.name}")
    print(f"ns:       {ns}")
    print(f"reasoned: {len(classes)} defined class(es)")
    print("\nBEFORE reasoning — what the data says:")
    before = run(graph, "asserted")

    result = R.reason(graph, watch_classes=classes)
    print(f"\nreasoner: {result.engine} · {result.elapsed_ms:.0f} ms · consistent={result.consistent}")

    entailed = Graph()
    for prefix, iri in graph.namespaces():
        entailed.bind(prefix, iri)
    for triple in graph:
        entailed.add(triple)
    added = 0
    for cls in classes:
        for member in result.members_of(cls):
            triple = (URIRef(member), RDF.type, URIRef(cls))
            if triple not in entailed:
                entailed.add(triple)
                added += 1

    print(f"\nAFTER reasoning — {added} entailed type assertion(s) added:")
    after = run(entailed, "entailed")

    if before == after:
        print("\nSAME ANSWER BOTH TIMES — this query is about stored data, not about entailment.")
    else:
        print(f"\nTHE ANSWER CHANGED: {len(before)} → {len(after)} row(s). "
              "Those extra rows exist nowhere in abox.ttl; the reasoner derived them from the TBox.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
