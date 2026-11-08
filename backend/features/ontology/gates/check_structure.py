#!/usr/bin/env python3
"""check_structure.py — S1: the structure layer says only things that are TRUE OF THE DATABASE.

`01-structure.ttl` is the first artifact a build produces, and it used to have no gate at all: it only had to
parse. That is why these gates exist — each one is a way a structure file can look finished and be wrong:

  S1a  every `owl:Class` names a table that exists, and a primary key the table really has
  S1b  every data property names a column that exists ON ITS CLASS'S TABLE (not on some other table)
  S1c  every object property names its own column and `:references` a class whose key column exists
  S1d  a local property name belongs to ONE domain (RDF has one property per name; `:id` on six classes
       compiles to an ambiguity the compiler refuses everywhere — measured on the retail ontology)
  S1e  no orphan properties (a domain that is not a declared class)
  S1f  every table in the database has a class — "18 tables, 15 classes" must not pass silently
  S1g  the file loads at all, and declares at least one class

Nothing here needs the compiler: it is a structural diff between the declarations and `information_schema`,
so it can run before any metric compiles. `--strict-coverage` is the default (S1f); a profile that
deliberately leaves a table out says so with `--allow-uncovered <table>`.

    python check_structure.py --profile ../profiles/new_coldchain/new_coldchain_settings.json

Exit: 0 all green, 1 something failed, 2 could not run (and says why).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "compiler"))     # the compiler's dsn/config helpers

import psycopg2  # noqa: E402
from rdflib import OWL, RDF, RDFS, URIRef  # noqa: E402

import dsn as _dsn  # noqa: E402
from rdflib import Graph  # noqa: E402

OK = True
CHECKS = 0


def check(label: str, got, want) -> None:
    global OK, CHECKS
    CHECKS += 1
    good = got == want
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}: got {got!r}, want {want!r}")


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


def key_parts(pk) -> list[str]:
    """`:primaryKey "route_id, seq"` is how this repo declares a composite key (clinic, logistics both do it).
    Treating the string as one column made the gate report a real ontology as broken — the gate was wrong."""
    if pk is None:
        return []
    return [part.strip() for part in str(pk).split(",") if part.strip()]


def local(node) -> str:
    s = str(node)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


GRAPH = None


def one(subject, predicate):
    """The first object of (subject, predicate) — `GRAPH` is the parsed structure file."""
    if GRAPH is None:                                          # pragma: no cover
        return None
    for v in GRAPH.objects(subject, predicate):
        return v
    return None


class Schema:
    """What the DATABASE actually has, so a declaration can be compared with it."""

    def __init__(self, cur):
        self.tables: dict[str, set[str]] = {}
        cur.execute("select table_name, column_name from information_schema.columns "
                    "where table_schema not in ('pg_catalog','information_schema')")
        for table, column in cur.fetchall():
            self.tables.setdefault(table, set()).add(column)

    def has_table(self, t: str) -> bool:
        return t in self.tables

    def has_column(self, t: str, c: str) -> bool:
        return c in (self.tables.get(t) or set())


def _platform_tables() -> set[str]:
    """Tables the FEATURE itself creates in the ontology's database (read from the compiler's DDL).

    `nl.py` keeps refusal telemetry in `nl_events` and `actions.py` keeps the write trail in
    `audit_events`; both live in whatever database the profile names. Deriving the set from
    `CREATE TABLE IF NOT EXISTS <name>` in the compiler is why this list cannot rot: a new platform
    table is covered by the code that creates it, and the gate prints the set on every run.
    """
    import re as _re
    compiler = pathlib.Path(__file__).resolve().parents[1] / "compiler"
    found: set[str] = set()
    for path in sorted(compiler.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:                                     # noqa: BLE001
            continue
        found.update(m.group(1).lower()
                     for m in _re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".]+)",
                                           text, _re.I))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", required=True, help="the profile json (dsn + ontology_dir + overlay)")
    ap.add_argument("--allow-uncovered", action="append", default=[],
                    help="a table this ontology deliberately does not model (repeatable)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    path = pathlib.Path(args.profile).expanduser().resolve()
    if not path.is_file():
        print(f"no profile at {path}")
        return 2
    prof = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    onto_dir = pathlib.Path(prof.get("ontology_dir") or "ontology")
    if not onto_dir.is_absolute():
        onto_dir = base / onto_dir
    structure = onto_dir / "01-structure.ttl"
    if not structure.is_file():
        print(f"no structure file: {structure}")
        return 2

    try:
        conn = psycopg2.connect(**_dsn.resolved(prof))
        conn.autocommit = True
    except Exception as exc:                                  # noqa: BLE001
        print(f"cannot connect to the profile's database ({type(exc).__name__}: {exc})")
        return 2
    cur = conn.cursor()
    schema = Schema(cur)
    conn.close()

    print(f"profile:   {path}")
    print(f"structure: {structure}")
    print(f"tables in the database: {len(schema.tables)}")

    # ── S1g  it loads, and it declares something
    print("\n=== S1g the file loads and declares classes ===")
    g = Graph()
    global GRAPH
    GRAPH = g
    try:
        g.parse(str(structure), format="turtle")
        check_true("the file parses as turtle", True)
    except Exception as exc:                                  # noqa: BLE001
        check_true("the file parses as turtle", False, f"{type(exc).__name__}: {exc}")
        return 1
    ns = None
    classes = [s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)]
    if classes:
        ns = str(classes[0]).rsplit("#", 1)[0] + "#"
    PT = URIRef(ns + "physicalTable") if ns else URIRef("urn:x:physicalTable")
    PK = URIRef(ns + "primaryKey") if ns else URIRef("urn:x:primaryKey")
    PC = URIRef(ns + "physicalColumn") if ns else URIRef("urn:x:physicalColumn")
    REF = URIRef(ns + "references") if ns else URIRef("urn:x:references")
    check_true("at least one owl:Class", bool(classes), "0 classes")
    if not classes:
        return 1

    # ── S1a  class -> table + primary key
    print("\n=== S1a every class names a real table and a real primary key ===")
    table_of: dict[str, str] = {}
    covered_cols_pk: set[tuple[str, str]] = set()
    for cls in classes:
        name = local(cls)
        t = one(cls, PT)
        if t is None:
            check_true(f"{name} names :physicalTable", False, "no :physicalTable")
            continue
        table = str(t)
        table_of[name] = table
        check_true(f"{name} -> table {table} exists", schema.has_table(table),
                   f"{table} is not a table in this database")
        pk = one(cls, PK)
        if pk is None:
            check_true(f"{name} names :primaryKey", False, "no :primaryKey")
        else:
            parts = key_parts(pk)
            missing = [c for c in parts if not schema.has_column(table, c)]
            check_true(f"{name} primary key {pk} is a column of {table}", not missing,
                       f"{table} has no column(s) {missing}")

        for key_col in key_parts(pk):
            covered_cols_pk.add((table, key_col))

    # ── S1b/S1c  properties
    print("\n=== S1b data properties name a column on THEIR OWN table ===")
    data_props = [p for p in g.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(p, URIRef)]
    object_props = [p for p in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(p, URIRef)]
    print(f"  data properties: {len(data_props)} · object properties: {len(object_props)}")
    by_name: dict[str, set[str]] = {}
    orphans: list[str] = []

    def domains(prop) -> list[str]:
        return [local(d) for d in g.objects(prop, RDFS.domain) if isinstance(d, URIRef)]

    for prop in data_props:
        name = local(prop)
        doms = domains(prop)
        for d in doms:
            by_name.setdefault(name, set()).add(d)
        if not doms:
            orphans.append(name)
            continue
        col = one(prop, PC)
        if col is None:
            check_true(f":{name} names :physicalColumn", False, "no :physicalColumn")
            continue
        for d in doms:
            table = table_of.get(d)
            check_true(f":{name} → {d}.{col}", bool(table) and schema.has_column(table, str(col)),
                       f"{table or '(unknown class ' + d + ')'} has no column {col}")

    print("\n=== S1c object properties name their column and reference a real key ===")
    for prop in object_props:
        name = local(prop)
        doms = domains(prop)
        for d in doms:
            by_name.setdefault(name, set()).add(d)
        if not doms:
            orphans.append(name)
            continue
        col = one(prop, PC)
        target = one(prop, REF)
        if col is None or target is None:
            check_true(f":{name} names :physicalColumn and :references", False,
                       f"column={col} references={target}")
            continue
        tname = local(target)
        ttable = table_of.get(tname)
        tpk = one(target, PK)
        for d in doms:
            table = table_of.get(d)
            check_true(f":{name} → {d}.{col} exists", bool(table) and schema.has_column(table, str(col)),
                       f"{table or d} has no column {col}")
        check_true(f":{name} references {tname}.{tpk}", bool(ttable) and bool(tpk)
                   and schema.has_column(ttable, str(tpk)), f"{ttable or tname} has no column {tpk}")

    # ── S1b2  column coverage: a class that declares its table but no properties is empty scaffolding
    print("\n=== S1b2 every column of every modelled table is reachable through a property ===")
    covered_cols: set[tuple[str, str]] = set()
    for prop in list(data_props) + list(object_props):
        col = one(prop, PC)
        if col is None:
            continue
        for d in domains(prop):
            table = table_of.get(d)
            if table:
                covered_cols.add((table, str(col)))
    missing: dict[str, list[str]] = {}
    for name, table in table_of.items():
        gaps = sorted(c for c in (schema.tables.get(table) or set()) if (table, c) not in covered_cols)
        if gaps:
            missing[name] = gaps
    total_gaps = sum(len(v) for v in missing.values())
    check_true("no column is left unmodelled", not missing,
               f"{total_gaps} columns over {len(missing)} classes, e.g. "
               + "; ".join(f"{k}: {v[:4]}" for k, v in list(missing.items())[:3]))

    # ── S1d  one property name, one domain
    print("\n=== S1d a property name belongs to ONE domain ===")
    shared = {n: sorted(d) for n, d in by_name.items() if len(d) > 1}
    check_true("no property name is shared by two classes", not shared,
               "; ".join(f":{n} -> {d}" for n, d in list(shared.items())[:4]))

    print("\n=== S1b3 every class has at least one property ===")
    empty_classes = [n for n in table_of if not any(d == n for ds in by_name.values() for d in ds)]
    check_true("no class is property-less", not empty_classes, f"{len(empty_classes)}: {empty_classes[:6]}")

    # ── S1e  no orphans
    print("\n=== S1e no orphan properties ===")
    check_true("every property names a domain", not orphans, f"{len(orphans)} without rdfs:domain: {orphans[:6]}")

    # ── S1f  coverage
    print("\n=== S1f every table in the database is modelled ===")
    # Telemetry tables the FEATURE creates in the ontology's own database (nl_events from nl.py,
    # audit_events from actions.py) are not business tables: asking a question must not make the
    # ontology look incomplete. They are read from the compiler's own DDL rather than listed here,
    # so a new platform table is covered the day it is written — and they are PRINTED, never
    # silently dropped. Measured on ECS: one question through the Query page created nl_events in
    # new_coldchain, and this gate then reported "1 uncovered: ['nl_events']" against an ontology
    # whose mapping was complete.
    platform_tables = _platform_tables()
    print(f"platform tables (created by the feature, not by the operation): "
          f"{sorted(platform_tables) or 'none'}")
    covered = set(table_of.values()) | set(args.allow_uncovered) | platform_tables
    uncovered = sorted(t for t in schema.tables if t not in covered)
    check_true("no table is silently left out", not uncovered,
               f"{len(uncovered)} uncovered: {uncovered}")

    print()
    verdict = "green" if OK else "red"
    print(f"{CHECKS} checks · {'0 failed' if OK else 'FAILED'} · {verdict}")
    if args.as_json:
        print(json.dumps({"ok": OK, "checks": CHECKS, "verdict": verdict,
                          "tables": len(schema.tables), "classes": len(classes),
                          "data_properties": len(data_props), "object_properties": len(object_props),
                          "uncovered": uncovered,
                          "columns_missing": total_gaps}, ensure_ascii=False))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
