#!/usr/bin/env python3
"""THE QUERY THAT SHOWS A DL REASONER'S POWER — run it and read the two answers.

The same ontology file used by materialize.py, but this script is only about the
question. We ask SPARQL one thing:

    PREFIX ex: <http://example.org/retail#>
    SELECT ?c WHERE { ?c a ex:PremiumCustomer }

BEFORE reasoning the graph has no such triple: the data only says
    :customer_1 :hasTier :tier_PREMIUM      (and so on)
Nothing anywhere states ":customer_1 a :PremiumCustomer". The class is DEFINED:

    PremiumCustomer ≡ Customer ⊓ hasTier value tier_PREMIUM

owl:hasValue is outside OWL 2 QL, so a rewriting engine (Ontop) cannot derive
this from the SQL rows — that is why the runtime lane uses a materialized table.
HermiT can: it classifies the individuals against the value restriction, and
AFTER sync_reasoner the SPARQL query returns the members.

This is the "nobody stored it" case from the video — and it is genuinely beyond
plain SPARQL (no entailment) and beyond QL rewriting (hasValue). Only a DL
reasoner gets here.

Run:
    ../.venv/bin/python hermirt/query_reasoner.py
"""
from __future__ import annotations

import os

import owlready2
from owlready2 import Thing, default_world, get_ontology, sync_reasoner
import pg8000.dbapi

owlready2.JAVA_EXE = "/opt/homebrew/opt/openjdk/bin/java"

PG = dict(
    host=os.getenv("DEMO_PG_HOST", "127.0.0.1"),
    port=int(os.getenv("DEMO_PG_PORT", "15432")),
    database=os.getenv("DEMO_PG_DB", "retail_db"),
    user=os.getenv("DEMO_PG_USER", "postgres"),
    password=os.getenv("DEMO_PG_PASSWORD", "postgres"),
)

QUERY = """
PREFIX ex: <http://example.org/retail#>
SELECT ?c WHERE { ?c a ex:PremiumCustomer }
"""

CUSTOMERS = """
PREFIX ex: <http://example.org/retail#>
SELECT ?c WHERE { ?c a ex:Customer }
"""


def fetch_customers() -> list[tuple[int, str, str]]:
    conn = pg8000.dbapi.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT id, name, tier FROM customers ORDER BY id")
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def ask(query: str) -> list[str]:
    g = default_world.as_rdflib_graph()
    out = []
    for row in g.query(query):
        c = str(row[0])
        out.append(c.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
    return sorted(out)


def main() -> int:
    rows = fetch_customers()

    onto = get_ontology("http://example.org/retail#")
    with onto:
        class Customer(Thing):
            pass

        class Tier(Thing):
            pass

        class hasTier(owlready2.ObjectProperty):
            domain = [Customer]
            range = [Tier]

        class PremiumCustomer(Customer):
            pass

        tier_premium = Tier("tier_PREMIUM")
        tier_standard = Tier("tier_STANDARD")

        PremiumCustomer.equivalent_to = [Customer & hasTier.value(tier_premium)]

    with onto:
        for cust_id, _name, tier in rows:
            c = Customer(f"customer_{cust_id}")
            c.hasTier = [tier_premium if tier == "PREMIUM" else tier_standard]

    print("ABox asserted (nothing says 'a PremiumCustomer'):")
    for cust_id, name, tier in rows:
        print(f"  :customer_{cust_id}  hasTier  :tier_{tier:<8}  ({name})")

    before = ask(QUERY)
    print(f"\nBEFORE the reasoner — {QUERY.strip().splitlines()[-1]}")
    print(f"  rows: {before or '[]  (empty — the fact is not stored)'}")

    print("\nrunning HermiT ...")
    with onto:
        sync_reasoner()

    after = ask(QUERY)
    print(f"\nAFTER the reasoner — same query")
    print(f"  rows: {after}")

    cust = ask(CUSTOMERS)
    print(f"\nCustomer (entailed via PremiumCustomer ⊑ Customer): {len(cust)}  {cust}")

    ok = after and len(after) == 2 and len(cust) == len(rows)
    print("\nOK: the reasoner answered a question whose answer was never stored."
          if ok else "\nUNEXPECTED: check HermiT output above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
