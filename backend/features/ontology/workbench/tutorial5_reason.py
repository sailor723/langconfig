#!/usr/bin/env python3
"""tutorial5_reason.py — the video's 5:30 case, run live for the tutorial page.

Two modes, both IN MEMORY (no database, no files):

  stored   the 3 stored triples:
               :dana a :PremiumCustomer
               :order50317 :customer :dana
               :PremiumCustomer rdfs:subClassOf :Customer
           ASK before → false, run owlrl (forward-chaining), ASK after → true

  promote  the same graph WITHOUT :dana a :PremiumCustomer (the "action has not run yet"),
           then the promote action ADDS that triple, then the reasoner runs:
           ASK before → false, after the action → false, after the reasoner → true

Output: one JSON object with the triples, the ASK results, the inferred triple and the
triple counts. Run with the ontology venv (rdflib + owlrl):
    ../.venv/bin/python tutorial5_reason.py stored
"""
from __future__ import annotations

import json
import sys

from rdflib import Graph, Namespace, RDF, RDFS
from rdflib.namespace import XSD  # noqa: F401  (kept for parity with the video's Turtle)


EX = Namespace("http://example.org/video-case#")


def announce(g: Graph) -> dict:
    return {"triples": len(g)}


EX2 = Namespace("http://example.org/retail#")   # the live-data namespace


def build(mode: str):
    g = Graph()
    g.bind("ex", EX)
    # the ontology rule (always stored)
    g.add((EX.PremiumCustomer, RDFS.subClassOf, EX.Customer))
    # the order → Dana context triple (not what makes the inference work)
    g.add((EX.order50317, EX.customer, EX.dana))
    if mode == "stored":
        g.add((EX.dana, RDF.type, EX.PremiumCustomer))
    return g


def build_live(customer_id: int) -> Graph:
    """The same three facts, taken from the LIVE database instead of typed by hand."""
    import json as _json
    import pathlib as _pathlib
    import psycopg2
    base = _pathlib.Path(__file__).resolve().parent
    cfg = _json.loads((base / "settings.json").read_text())["dsn"]
    conn = psycopg2.connect(host=cfg["host"], port=int(cfg["port"]),
                            dbname=cfg["dbname"], user=cfg["user"],
                            password=cfg["password"])
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, tier FROM customers WHERE id = %s", (customer_id,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"no customer {customer_id}")
        _, name, tier = row
        cur.execute("SELECT id FROM orders WHERE customer_id = %s ORDER BY id", (customer_id,))
        orders = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    g = Graph()
    g.bind("ex", EX2)
    g.add((EX2.PremiumCustomer, RDFS.subClassOf, EX2.Customer))
    cust = EX2[f"customer/{customer_id}"]
    for oid in orders:
        g.add((EX2[f"order/{oid}"], EX2.customer, cust))
    if tier == "PREMIUM":
        g.add((cust, RDF.type, EX2.PremiumCustomer))
    return g


def ask_customer2(g: Graph, cust) -> bool:
    return bool(g.query(
        "ASK { <%s> a <%s> }" % (cust, EX2.Customer)).askAnswer)


def ask_customer(g: Graph) -> bool:
    return bool(g.query(
        "ASK { <%s> a <%s> }" % (EX.dana, EX.Customer)).askAnswer)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stored"
    customer_id = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    if mode not in ("stored", "promote", "live"):
        print(json.dumps({"ok": False, "error": f"unknown mode {mode!r}"}))
        return 1

    if mode == "live":
        g = build_live(customer_id)
        cust = EX2[f"customer/{customer_id}"]
        out = {"ok": True, "mode": mode, "customer_id": customer_id,
               "turtle": g.serialize(format="turtle"), "before": ask_customer2(g, cust),
               "before_triples": len(g)}
        import owlrl
        owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(g)
        out["after"] = ask_customer2(g, cust)
        out["after_triples"] = len(g)
        out["inferred"] = [[str(s_), str(p_), str(o_)] for s_, p_, o_ in
                           g.triples((cust, RDF.type, EX2.Customer))]
        out["customer_types"] = sorted(str(o) for o in g.objects(cust, RDF.type))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    g = build(mode)
    out = {"ok": True, "mode": mode, "turtle": g.serialize(format="turtle"),
           "before": ask_customer(g), "before_triples": len(g)}

    if mode == "promote":
        # the "action" adds the membership fact — exactly what actions.py does
        g.add((EX.dana, RDF.type, EX.PremiumCustomer))
        out["after_action"] = ask_customer(g)
        out["after_action_triples"] = len(g)

    # the reasoner: forward-chaining RDFS/OWL-RL closure
    import owlrl
    owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(g)
    out["after"] = ask_customer(g)
    out["after_triples"] = len(g)
    new = [(str(s), str(p), str(o)) for s, p, o in
           g.triples((EX.dana, RDF.type, EX.Customer))]
    out["inferred"] = [[s, p, o] for s, p, o in new]
    out["customer_types"] = sorted(str(o) for o in g.objects(EX.dana, RDF.type))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
