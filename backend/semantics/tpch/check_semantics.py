#!/usr/bin/env python
"""check_semantics — does `tpch/SEMANTICS.md` still describe the database?

The failure this prevents is the one that cost the Sun Hing case its credibility:
a KPI document that restates numbers in prose drifts away from the data, and then
two sources of truth disagree about what "revenue" or "on target" means. Here the
document is the *contract* and the database is the *fact*, so a gate can check the
two agree — before any model is asked to rely on it.

What is checked (each one a comparison, not a sentence):

  1. PARSE   every KPI row in the doc (A1-A9 in `unit_registry`, B1-B4 doc-defined)
             parses to (id, formula, expected value).
  2. AGREE   the SAME quantity computed against PostgreSQL equals the documented
             value to the stated precision. The SQL lives here, not in the doc, so
             changing a number in the doc cannot silently change the query too.
  3. COVER   every `measure` declared in the database's own `unit_registry` is
             described in section A — a measure nobody documented is a measure a
             model will invent. Section B rows are allowed to have no registry row,
             and that gap is reported (not failed) so it stays visible.
  4. MUTATE  the gate can fail: `--mutate` perturbs one documented value and
             requires the comparison to go red. A gate that cannot fail proves
             nothing.

Run::

    backend/.venv/bin/python backend/semantics/tpch/check_semantics.py
    ... --mutate     # prove the gate detects a wrong number
    ... --verbose    # print every value, matched or not

Exit 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
DOC = HERE / "SEMANTICS.md"

def _target_dsn() -> dict:
    """Where to run the checks: the app's own `tpch` target, when it resolves.

    The hardcoded literal below (host 127.0.0.1 / user weiping / no password) is a
    trust-auth local install. On a machine whose Postgres asks for a password the
    checker died with "fe_sendauth: no password supplied" — from the UI that is a
    red 校验 with no explanation, which reads like the semantic document is wrong.

    Reading the same target the agent uses keeps one answer to "which server, with
    which role": `SQL_TARGETS` (env) wins over the built-in target, exactly as it
    does for `sql_db_query`. Loaded by path, not `sys.path`, because putting
    backend/langgraph on the path shadows the real `langgraph` package.
    """
    import importlib.util

    backend_dir = HERE.parents[1]
    mod_path = backend_dir / "langgraph" / "sql_setup_db.py"
    if not mod_path.exists():
        return {}
    # `backend/` on sys.path, not `backend/langgraph/`: the module resolves its own
    # siblings as `langgraph.connection` / `langgraph.prebuilt`, which only import
    # when the PARENT of that package is on the path. Without it the import raises,
    # the DSN silently falls back to the hardcoded literal, and the gate fails with
    # "no password supplied" — the exact symptom this function exists to remove.
    added = str(backend_dir) not in sys.path
    if added:
        sys.path.insert(0, str(backend_dir))
    try:
        spec = importlib.util.spec_from_file_location("_sql_setup_db_for_semantics", mod_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        params = mod._target_params("tpch")
        if not params:
            # TPC-H installed ON the platform server: same host/role as the app.
            params = dict(mod._connection_params())
            params["dbname"] = "tpch"
        return dict(params) if params else {}
    except Exception as exc:  # noqa: BLE001 — a broken import must not hide the checks
        print(f"  ! target lookup failed ({type(exc).__name__}: {exc}); using the built-in DSN")
        return {}
    finally:
        if added:
            try:
                sys.path.remove(str(backend_dir))
            except ValueError:
                pass


# Resolution order: the app's target (SQL_TARGETS aware) → this file's default.
DSN = {**dict(host="127.0.0.1", port=5432, dbname="tpch", user="weiping"), **_target_dsn()}

# The query for each KPI id. Deliberately independent of the doc's prose: the doc
# states the number, this states how it is produced, and neither is derived from
# the other.
QUERIES: dict[str, tuple[str, int]] = {
    # id -> (sql, decimal places to compare at)
    "A1": ("SELECT SUM(l_extendedprice * (1 - l_discount)) FROM lineitem", 2),
    "A2": ("SELECT SUM(l_extendedprice) FROM lineitem", 2),
    "A3": ("SELECT SUM(l_extendedprice * l_discount) FROM lineitem", 2),
    "A4": ("SELECT SUM(l_extendedprice * (1 - l_discount)) / COUNT(*) FROM lineitem", 2),
    "A5": (
        "SELECT SUM(ps.ps_supplycost * l.l_quantity) FROM lineitem l "
        "JOIN partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey",
        2,
    ),
    "A6": (
        "SELECT SUM(l.l_extendedprice * (1 - l.l_discount)) - SUM(ps.ps_supplycost * l.l_quantity)"
        " FROM lineitem l JOIN partsupp ps"
        " ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey",
        2,
    ),
    "A7": (
        "SELECT 100 * (SUM(l.l_extendedprice * (1 - l.l_discount))"
        " - SUM(ps.ps_supplycost * l.l_quantity)) / SUM(l.l_extendedprice * (1 - l.l_discount))"
        " FROM lineitem l JOIN partsupp ps"
        " ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey",
        2,
    ),
    "A8": ("SELECT SUM(l_extendedprice * l_discount) / SUM(l_extendedprice) FROM lineitem", 6),
    "A9": (
        "SELECT AVG(v) FROM (SELECT o.o_orderkey,"
        " SUM(l.l_extendedprice * (1 - l.l_discount)) AS v"
        " FROM orders o JOIN lineitem l ON l.l_orderkey = o.o_orderkey GROUP BY 1) t",
        2,
    ),
    "B1": (
        "SELECT 100.0 * COUNT(*) FILTER (WHERE l_shipdate > l_commitdate) / COUNT(*) FROM lineitem",
        2,
    ),
    "B2": ("SELECT 100.0 * COUNT(*) FILTER (WHERE l_returnflag = 'R') / COUNT(*) FROM lineitem", 2),
    "B3": ("SELECT COUNT(*) FROM customer WHERE c_acctbal >= 5000", 0),
    "B4": ("SELECT COUNT(*) FROM supplier WHERE s_acctbal < 0", 0),
    # Not KPIs: the two numbers that prove rule 8's fan-out warning, so the rule
    # cannot quietly become wrong when the data changes.
    "R1": ("SELECT SUM(o_totalprice) FROM orders WHERE o_orderdate >= DATE '1998-01-01'", 0),
    "R2": (
        "SELECT SUM(o.o_totalprice) FROM lineitem l JOIN orders o ON o.o_orderkey = l.l_orderkey"
        " WHERE o.o_orderdate >= DATE '1998-01-01'",
        0,
    ),
}

# The database's own semantic layer: every `measure` row here must be documented in
# section A, otherwise the doc is claiming to be the KPI contract while quietly
# omitting what the DB already declares.
# The registry keys measures by (table_name, column_name) and carries no rule id
# column — the M-xxxx ids live in the free-text `note`. Select the pair only.
REGISTRY_QUERY = "SELECT table_name, column_name FROM unit_registry WHERE kind = 'measure'"

# measure (entity.name) -> the doc id that covers it.
REGISTRY_TO_DOC = {
    "order_line.revenue": "A1",
    "order_line.gross_revenue": "A2",
    "order_line.total_discount": "A3",
    "order_line.average_line_value": "A4",
    "order_line.supply_cost": "A5",
    "order_line.contribution_margin": "A6",
    "order_line.contribution_margin_pct": "A7",
    "order_line.weighted_average_discount": "A8",
    "sales_order.average_order_value": "A9",
}


def parse_doc(text: str) -> dict[str, float]:
    """KPI rows -> {id: value}. Rows look like `| A1 | name | … | 20,535,072,231.4150 |`."""
    values: dict[str, float] = {}
    for line in text.splitlines():
        # Tables nest inside numbered list items (indented by spaces), so match on
        # the first non-space character — otherwise an indented KPI table is
        # silently invisible to the gate.
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"[ABR]\d+", cells[0]):
            continue
        raw = cells[-1]
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", raw)
        if not m:
            continue
        values[cells[0]] = float(m.group(0).replace(",", ""))
    return values


def run_all(dsn: dict, overrides: dict[str, float] | None = None) -> tuple[dict[str, float], list[str]]:
    """Measure every KPI; return {id: actual} plus the registry rows."""
    import psycopg2

    actual: dict[str, float] = {}
    conn = psycopg2.connect(**dsn)
    try:
        with conn.cursor() as cur:
            for kpi_id, (sql, _) in QUERIES.items():
                cur.execute(sql)
                actual[kpi_id] = float(cur.fetchone()[0])
            cur.execute(REGISTRY_QUERY)
            registry = [f"{r[0]}.{r[1]}" for r in cur.fetchall()]
    finally:
        conn.close()
    if overrides:
        actual.update(overrides)
    return actual, registry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true", help="prove the gate fails on a wrong number")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--doc", default=str(DOC))
    args = ap.parse_args()

    doc_path = Path(args.doc)
    if not doc_path.is_file():
        print(f"missing {doc_path}", file=sys.stderr)
        return 2
    documented = parse_doc(doc_path.read_text(encoding="utf-8"))
    if not documented:
        print("no KPI rows parsed out of the document", file=sys.stderr)
        return 2

    overrides = None
    if args.mutate:
        # Perturb ONE value by 1% and require the comparison to notice.
        first = sorted(documented)[0]
        overrides = {first: documented[first] * 1.01}
        print(f"  MUTATION: {first} measured as {overrides[first]:.4f} instead of "
              f"{documented[first]:.4f} — the gate must fail\n")

    actual, registry = run_all(DSN, overrides)

    print(f"== check_semantics: {doc_path.name} vs tpch @ {DSN['host']}:{DSN['port']}")
    failures: list[str] = []
    for kpi_id in sorted(QUERIES):
        _, places = QUERIES[kpi_id]
        if kpi_id not in documented:
            failures.append(f"{kpi_id}: documented in the gate but missing from the doc")
            print(f"  {kpi_id:<4} MISSING in doc")
            continue
        want, got = documented[kpi_id], actual[kpi_id]
        ok = round(want, places) == round(got, places)
        if not ok:
            failures.append(f"{kpi_id}: doc says {want} but the database says {got}")
        if args.verbose or not ok:
            flag = "ok  " if ok else "FAIL"
            print(f"  {kpi_id:<4} {flag} doc={want:>20,.{places}f}   db={got:>20,.{places}f}")
        elif kpi_id in ("A1", "A4", "A7", "B1"):
            print(f"  {kpi_id:<4} ok   {got:,.{places}f}")

    # COVER: the DB's own registry must be fully described by section A.
    covered = {REGISTRY_TO_DOC.get(m) for m in registry}
    undocumented = [m for m in registry if m not in REGISTRY_TO_DOC]
    if undocumented:
        for m in undocumented:
            failures.append(f"unit_registry measure '{m}' is not documented in section A")
    doc_a = {k for k in documented if k.startswith("A")}
    orphan_a = sorted(doc_a - {c for c in covered if c})
    print(f"\n  registry measures: {len(registry)} | covered by A: "
          f"{len(registry) - len(undocumented)} | doc-only A rows: {orphan_a or 'none'}")
    b_rows = sorted(k for k in documented if k.startswith("B"))
    print(f"  section B (no registry row yet): {b_rows}")

    if failures:
        print("\nGATE FAIL")
        for f in failures:
            print("  - " + f)
        if args.mutate:
            print("\n  (mutation detected — the gate can fail, as intended)")
            return 0
        return 1
    print("\nGATE PASS — every documented number reproduces on the database"
          " and every registry measure is described")
    if args.mutate:
        print("  BUT the mutation was NOT detected — the gate is not actually comparing values")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
