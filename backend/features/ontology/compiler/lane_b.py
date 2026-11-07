#!/usr/bin/env python3
"""Lane-B data for the settings UI: SPARQL/Ontop counts, side by side with lane A.

Lane A (compiled SQL) comes from graph_view's payload: axiom → WHERE predicate →
source DB. Lane B asks the SAME question through a SPARQL endpoint (Ontop over a
virtual RDF graph + R2RML mapping), so the settings page can show whether the two
approaches agree on the demo data — and where one of them cannot answer at all.

What is intentionally NOT compared: aggregates (orderRevenue, averageOrderValue).
SPARQL can express them only when the endpoint's mapping covers the underlying
table; the demo endpoint maps customers only. The page says so instead of implying
a false equality.

Prints one JSON object on stdout. Run by serve_ui.py (cube-venv python, which has
rdflib/psycopg2 needed by graph_view). Safe to run by hand:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python lane_b.py --endpoint ...
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import graph_view  # noqa: E402  (payload builder: lane A values)

HEADERS = {"Accept": "application/sparql-results+json",
           "Content-Type": "application/x-www-form-urlencoded"}


def sparql(endpoint: str, query: str) -> dict:
    req = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"query": query}).encode(),
                                 headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def count_of(endpoint: str, iri: str) -> int:
    j = sparql(endpoint, f"SELECT (COUNT(?x) AS ?n) WHERE {{ ?x a <{iri}> }}")
    return int(j["results"]["bindings"][0]["n"]["value"])


def served_classes(endpoint: str) -> set[str]:
    """Class local names the endpoint actually has (so a 0 is 'no data', not 'not mapped')."""
    j = sparql(endpoint, "SELECT DISTINCT ?c WHERE { ?x a ?c }")
    return {row["c"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            for row in j["results"]["bindings"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True, help="SPARQL endpoint (Ontop)")
    ap.add_argument("--ontop-ns", default="http://example.org/retail#",
                    help="namespace the endpoint's ontology uses for the same class names")
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()

    out: dict = {"endpoint": args.endpoint, "ontop_ns": args.ontop_ns,
                 "ok": False, "rows": [], "note": None}

    payload = graph_view.build_payload(args.sample)
    classes = [n for n in payload.get("nodes", [])
               if n.get("term") in ("Class", "Defined class") and n.get("name")]

    try:
        served = served_classes(args.endpoint)
        for n in classes:
            name = n["name"]
            lane_a = n.get("value")
            if name in served:
                lane_b = count_of(args.endpoint, args.ontop_ns + name)
            else:
                lane_b = None
            out["rows"].append({
                "name": name,
                "laneA": lane_a,
                "laneB": lane_b,
                "served": name in served,
                "match": (lane_a == lane_b) if lane_b is not None else None,
            })
        out["ok"] = True
        out["note"] = ("aggregate metrics are lane A only: the demo endpoint's R2RML mapping "
                       "covers customers, not orders — a gap in the mapping, not in reasoning")
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"endpoint unavailable: {exc}"
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
