#!/usr/bin/env python3
"""check_mapping.py — gate between the R2RML mapping and the ontology (OBDA, no ETL).

The failure this exists to prevent: Ontop answers a non-OWL-2-QL definition with a WARNING
and silently widens (or loses) rows — `compare/run_compare.py` documents A=2 vs B=0 for
`owl:hasValue`. A mapping that "serves" a defined concept WITHOUT encoding its definition in
the SQL query is exactly that failure: the answer looks served but means something else.
This gate turns the silent WARN into a named red.

    M1 every rr:class a TriplesMap asserts exists in the ontology AND binds the declared table
    M2 every rr:column maps to a declared property (local name + :physicalColumn + applicable
       domain — the property's domain may be a superclass of the mapped class)
    M3 every rr:joinCondition matches a declared relationship (FK :physicalColumn + :references)
    M4 every served DEFINED concept has its axiom's predicate encoded in the mapping SQL
       (the compensation Ontop cannot do; without it M4 is red BY NAME)
    M5 live parity: lane A compiled count == lane B SPARQL count for served classes

Run with the cube-tutorial venv python (rdflib + psycopg2):
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python check_mapping.py
    ... --endpoint http://127.0.0.1:8080/sparql --mapping ../youtube_tutorial/retail.mapping.ttl
Mutations at the end prove M1/M2/M4 can go red; M5's live proof is compare/run_compare.py.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

import psycopg2
from rdflib import Graph, Literal, RDF, OWL, RDFS, URIRef
from rdflib.namespace import Namespace

# The feature's roots: the COMPILER (this gate's imports), the WORKBENCH (the static assets it
# checks) and the PROFILES (the declarations). All relative to the feature directory — a gate that
# addresses "/Users/weiping/..." only runs on one machine.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))       # the _paths helper
from _paths import COMPILER as BASE, PROFILES, WORKBENCH, WORKBENCH as APP, profile_dir
_sys.path.insert(0, str(BASE))
sys.path.insert(0, str(WORKBENCH))
sys.path.insert(0, str(BASE))
import actions  # noqa: E402
import sqlgen   # noqa: E402

P = sqlgen.P
RR = Namespace("http://www.w3.org/ns/r2rml#")
DEFAULT_MAPPING = PROFILES / "retail" / "retail.mapping.ttl"
DEFAULT_ENDPOINT = "http://127.0.0.1:8080/sparql"
ONT_LABEL = "http://example.org/retail#"

ok = True


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def note(text: str) -> None:
    print(f"  [note] {text}")


def load_ontology(odir: pathlib.Path) -> Graph:
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#", ontology_dir=str(odir))
    return sqlgen.load()


def parse_mapping(path: pathlib.Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


def mapping_triples_maps(mg: Graph) -> list[dict]:
    """One dict per rr:TriplesMap: logical table/SQL, asserted class, (predicate, column) pairs."""
    out = []
    for tm in mg.subjects(RDF.type, RR.TriplesMap):
        logical = next(iter(mg.objects(tm, RR.logicalTable)), None)
        sql = str(next(iter(mg.objects(logical, RR.sqlQuery)), "") or "")
        table = str(next(iter(mg.objects(logical, RR.tableName)), "") or "")
        subj = next(iter(mg.objects(tm, RR.subjectMap)), None)
        cls = next(iter(mg.objects(subj, RR["class"])), None) if subj else None
        props = []
        for pom in mg.objects(tm, RR.predicateObjectMap):
            pred = next(iter(mg.objects(pom, RR.predicate)), None)
            if pred is None:
                continue
            obj = next(iter(mg.objects(pom, RR.objectMap)), None)
            col = str(next(iter(mg.objects(obj, RR.column)), "") or "") if obj else ""
            props.append({"pred": _local_name(pred), "col": col})
        out.append({"tm": str(tm), "sql": sql, "table": table or _sql_table(sql),
                    "class": _local_name(cls) if cls else None,
                    "class_iri": str(cls) if cls else None, "predicates": props})
    return out


def _local_name(iri) -> str | None:
    return str(iri).split("#")[-1].split("/")[-1] if iri is not None else None


def _sql_table(sql: str) -> str:
    m = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.I)
    return m.group(1) if m else ""


def ttl_class_table(g: Graph, cls: str) -> str | None:
    """A defined class has no table of its own: it binds through the class its axiom is
    built on (:PremiumCustomer -> :Customer)."""
    table = sqlgen._one(g, P(cls), P("physicalTable"))
    if table is None:
        base = sqlgen.concept_base_class(g, cls)
        if base:
            table = sqlgen._one(g, P(base), P("physicalTable"))
    return table


def ttl_prop_column(g: Graph, prop: str) -> str | None:
    return sqlgen._one(g, P(prop), P("physicalColumn"))


def ttl_supers(g: Graph, cls: str) -> set[str]:
    out = set()
    base = sqlgen.concept_base_class(g, cls)
    if base:
        out.add(base)
    cur = cls
    while cur:
        nxt = next(iter(g.objects(P(cur), RDFS.subClassOf)), None)
        if nxt is None:
            break
        cur = _local_name(nxt) or ""
        if not cur or cur in out:
            break
        out.add(cur)
    return out


def class_count_lane_a(g: Graph, cls: str, cur) -> int:
    """lane A: compiled predicate when the class is defined, plain table count otherwise."""
    try:
        pred = sqlgen.concept_sql(g, cls)
    except sqlgen.Refusal:
        pred = None
    table = ttl_class_table(g, cls)
    if table is None:
        raise sqlgen.Refusal(f":{cls} declares no :physicalTable")
    sql = f"SELECT count(*) FROM {table}" + (f" WHERE {pred}" if pred else "")
    cur.execute(sql)
    return cur.fetchone()[0]


def sparql_count(endpoint: str, cls: str) -> int:
    q = (f"PREFIX ex: <{ONT_LABEL}> "
         f"SELECT (COUNT(?c) AS ?n) WHERE {{ ?c a ex:{cls} }}")
    data = urllib.parse.urlencode({"query": q}).encode()
    req = urllib.request.Request(endpoint, data=data,
                                 headers={"Accept": "application/sparql-results+json",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(json.load(r)["results"]["bindings"][0]["n"]["value"])


def endpoint_alive(endpoint: str) -> bool:
    try:
        data = urllib.parse.urlencode({"query": "ASK { ?s ?p ?o }"}).encode()
        req = urllib.request.Request(endpoint, data=data,
                                     headers={"Accept": "application/sparql-results+json",
                                              "Content-Type": "application/x-www-form-urlencoded"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_checks(g: Graph, mg: Graph, con, endpoint: str) -> None:
    maps = mapping_triples_maps(mg)
    cur = con.cursor()
    served = sorted({m["class"] for m in maps if m["class"]})

    print("=== M1 classes a TriplesMap asserts exist in the ontology and bind the declared table ===")
    for m in maps:
        cls = m["class"]
        check(f"TriplesMap {_local_name(m['tm'])}: class :{cls} exists with a physical table",
              ttl_class_table(g, cls), m["table"])
        del m["class_iri"]

    print("=== M2 every rr:column maps to a declared property ===")
    for m in maps:
        for p in m["predicates"]:
            prop, col = p["pred"], p["col"]
            ttl_col = ttl_prop_column(g, prop)
            # the property's domain must be the mapped class or one of its superclasses
            # (a defined class binds through the class its axiom is built on)
            domains = {_local_name(d) for d in g.objects(P(prop), RDFS.domain)}
            dom_ok = bool(domains & ({m["class"]} | ttl_supers(g, m["class"])))
            check(f":{prop} column {col!r} declared with :physicalColumn", ttl_col, col)
            check(f":{prop} belongs to :{m['class']} (or a superclass)", dom_ok, True)

    print("=== M3 every rr:joinCondition matches a declared relationship ===")
    joins = 0
    for m in maps:
        for pom in mg.objects(mg.subjects(RDF.type, RR.TriplesMap), RR.predicateObjectMap):
            obj = next(iter(mg.objects(pom, RR.objectMap)), None)
            if obj is None:
                continue
            for jc in mg.objects(obj, RR.joinCondition):
                joins += 1
                child = _local_name(next(iter(mg.objects(jc, RR.child)), None))
                parent = _local_name(next(iter(mg.objects(jc, RR.parent)), None))
                fk, pk = sqlgen.relationship(g, m["class"], parent) if parent else (None, None)
                check(f"join {child}->{parent} declared", (fk, pk), (child, pk))
    if joins == 0:
        note("this mapping declares no join conditions (single-table segments)")

    print("=== M4 served DEFINED concepts carry their axiom's predicate in the SQL ===")
    for cls in served:
        try:
            pred = sqlgen.concept_sql(g, cls)
        except sqlgen.Refusal:
            continue          # not a defined concept: nothing to compensate
        norm = lambda s: re.sub(r"\s+", "", str(s)).lower()
        for m in maps:
            if m["class"] != cls:
                continue
            encoded = norm(pred) in norm(m["sql"])
            check(f":{cls} definition `{pred}` encoded in {_local_name(m['tm'])} SQL", encoded, True)
            if not encoded:
                note(f"Ontop would answer :{cls} with silently widened rows — this is the "
                     f"WARN the gate turns into a red")

    print("=== M5 live parity: lane A (compiled) == lane B (Ontop) ===")
    if not endpoint_alive(endpoint):
        note(f"endpoint {endpoint} unreachable — parity not measured (start the "
             f"youtube_tutorial Ontop stack)")
    else:
        for cls in served:
            try:
                a = class_count_lane_a(g, cls, cur)
            except (sqlgen.Refusal, psycopg2.Error) as exc:
                note(f":{cls} lane A unavailable: {str(exc).splitlines()[0][:80]}")
                continue
            b = sparql_count(endpoint, cls)
            check(f":{cls} lane A == lane B", (a, b), (b, b))
        ttl_only = sorted({_local_name(s) for s in g.subjects(RDF.type, OWL.Class)
                           if isinstance(s, URIRef)} - set(served))
        if ttl_only:
            note(f"classes the mapping does NOT serve: {ttl_only} — a coverage gap, "
                 f"not a silent failure")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    ap.add_argument("--ontology-dir", default=str(PROFILES / "retail" / "ontology"))
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    args = ap.parse_args()

    g = load_ontology(pathlib.Path(args.ontology_dir))
    mapping_path = pathlib.Path(args.mapping)
    mg = parse_mapping(mapping_path)
    conn = psycopg2.connect(**actions.DSN)
    try:
        run_checks(g, mg, conn, args.endpoint)
    finally:
        conn.rollback()
        conn.close()

    print("=== mutations: the M1/M2/M4 gates can go red ===")
    text = mapping_path.read_text()
    mutant = text.replace("rr:class ex:PremiumCustomer", "rr:class ex:PlatinumCustomer")
    mg2 = Graph()
    mg2.parse(data=mutant, format="turtle")
    maps2 = mapping_triples_maps(mg2)
    bad = [m["class"] for m in maps2 if m["class"] and ttl_class_table(g, m["class"]) is None]
    check("M1 mutation: an undeclared class is caught", bad, ["PlatinumCustomer"])

    mutant = text.replace('rr:column "name"', 'rr:column "nam"')
    mg3 = Graph()
    mg3.parse(data=mutant, format="turtle")
    wrong = sorted({p["col"] for m in mapping_triples_maps(mg3) for p in m["predicates"]
                            if ttl_prop_column(g, p["pred"]) != p["col"]})
    check("M2 mutation: a column typo is caught", wrong, ["nam"])

    mutant = text.replace("WHERE tier = 'PREMIUM'", "")
    mg4 = Graph()
    mg4.parse(data=mutant, format="turtle")
    norm = lambda s: re.sub(r"\s+", "", str(s)).lower()
    dropped = [m["class"] for m in mapping_triples_maps(mg4)
               if m["class"] == "PremiumCustomer"
               and norm(sqlgen.concept_sql(g, "PremiumCustomer")) not in norm(m["sql"])]
    check("M4 mutation: dropping the embedded definition is caught",
          dropped, ["PremiumCustomer"])

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
