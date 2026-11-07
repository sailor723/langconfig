#!/usr/bin/env python3
"""Check a generated dataset against the SPEC that claims to describe it.

A mock dataset is a set of claims: "60 vehicles", "the merge made every route fuller", "46% of complaints
have no liability", "the complaints table has ONE timestamp". Those claims are what an ontology, a gate and a
demo all stand on, and a generator that does not verify them produces a dataset that *looks* like the story
and answers different questions. This script turns each claim into a query.

    python check_dataset.py --spec abc_coldchain.dataset.json            # exit 0 / 1
    python check_dataset.py --spec … --only planted_merge,overload_regime
    python check_dataset.py --spec … --json

Spec format (`<dataset>.dataset.json`):

{
  "name": "abc_coldchain",
  "dsn": {"host": "127.0.0.1", "port": 5432, "dbname": "abc_coldchain", "user": "weiping"},
  "tables":    [{"name": "trips", "rows": 4050, "why": "…"}],
  "foreign_keys": [{"table": "stops", "column": "trip_id", "ref_table": "trips"}],
  "invariants": [
     {"id": "stops_per_trip", "why": "并线必须让每条线更满（痛点二）",
      "sql": "SELECT r.version, round(avg(r.planned_stops),1) FROM routes r GROUP BY 1",
      "expect": {"v1": 10.2, "v2": 15.7}},                       // key → value
     {"id": "trips_total", "sql": "SELECT count(*) FROM trips", "expect": 4050},
     {"id": "overload_after", "why": "超载是并线的后果",
      "sql": "SELECT round(1.0*count(*) FILTER (WHERE t.load_weight >= t.weight_capacity_snapshot)/count(*),4) FROM trips t JOIN routes r ON r.id=t.route_id WHERE r.version='v2'",
      "expect_range": [0.70, 0.90]}                             // inclusive
  ],
  "constant_columns": [{"table": "complaints", "column": "opened_at", "why": "同一时刻批量回填：时间维度不可信"}],
  "null_rates": [{"table": "complaints", "column": "liability", "min": 0.30, "max": 0.60, "why": "责任未判定必须占相当比例"}]
}

Exit: 0 every claim held; 1 a claim failed (named, with the numbers); 2 the spec/connection is unusable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

FAILS: list[str] = []
CHECKS = 0
SKIPS: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        FAILS.append(label)


def close(label: str, got, want, tol: float = 1e-6) -> None:
    global CHECKS
    CHECKS += 1
    ok = got is not None and want is not None and abs(float(got) - float(want)) <= tol
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        FAILS.append(label)


def _rows(cur, sql: str) -> list[tuple]:
    cur.execute(sql)
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--only", help="comma-separated invariant ids")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    spec_path = pathlib.Path(args.spec).expanduser()
    if not spec_path.is_file():
        print(f"no spec at {spec_path}", file=sys.stderr)
        return 2
    spec = json.loads(spec_path.read_text())
    name = spec.get("name") or spec_path.stem
    dsn = dict(spec.get("dsn") or {})
    dsn.setdefault("password", "")
    only = {x.strip() for x in (args.only or "").split(",") if x.strip()}

    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is required (use the ontology repo's interpreter)", file=sys.stderr)
        return 2
    try:
        conn = psycopg2.connect(**dsn)
    except Exception as exc:                                    # noqa: BLE001
        print(f"cannot connect to {dsn.get('dbname')}: {exc}", file=sys.stderr)
        return 2

    print(f"DATASET {name} · {dsn.get('dbname')}")
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout='15s'")

        print("\nT  the tables the story needs")
        for table in spec.get("tables") or []:
            tname = table["name"]
            try:
                cur.execute(f"SELECT count(*) FROM {tname}")
                rows = cur.fetchone()[0]
            except Exception:                                   # noqa: BLE001
                check(f"T {tname} exists", False, True)
                continue
            check(f"T {tname} exists", True, True)
            if "rows" in table:
                close(f"T {tname} has {table['rows']} rows (got {rows})", rows, table["rows"], tol=0)
            else:
                print(f"       {tname}: {rows} rows")

        print("\nFK  every reference points at a row")
        for fk in spec.get("foreign_keys") or []:
            sql = (f"SELECT count(*) FROM {fk['table']} c LEFT JOIN {fk['ref_table']} p "
                   f"ON c.{fk['column']} = p.{fk.get('ref_column', 'id')} "
                   f"WHERE c.{fk['column']} IS NOT NULL AND p.{fk.get('ref_column', 'id')} IS NULL")
            close(f"FK {fk['table']}.{fk['column']} → {fk['ref_table']} has no orphans",
                  _rows(cur, sql)[0][0], 0, tol=0)

        print("\nI  the planted invariants (what the story claims the data shows)")
        for inv in spec.get("invariants") or []:
            iid = inv.get("id") or inv["sql"][:40]
            if only and iid not in only:
                SKIPS.append(iid)
                continue
            why = f" — {inv['why']}" if inv.get("why") else ""
            try:
                rows = _rows(cur, inv["sql"])
            except Exception as exc:                            # noqa: BLE001
                check(f"I {iid}{why}", f"query failed: {exc}", "a result")
                continue
            if "expect" in inv:
                want = inv["expect"]
                if isinstance(want, dict):
                    got = {str(k): v for k, v in rows}
                    missing = sorted(set(want) - set(got))
                    check(f"I {iid} groups{why}", missing, [])
                    for key, expected in want.items():
                        close(f"I {iid}[{key}]{why}", got.get(str(key)), expected)
                elif isinstance(want, (int, float)):
                    close(f"I {iid}{why}", rows[0][0], want)
                else:
                    check(f"I {iid}{why}", str(rows[0][0]), str(want))
            elif "expect_range" in inv:
                lo, hi = inv["expect_range"]
                value = rows[0][0]
                ok = value is not None and float(lo) <= float(value) <= float(hi)
                check(f"I {iid} in [{lo}, {hi}] (got {value}){why}", ok, True)
            else:
                SKIPS.append(f"{iid} (no expect/expect_range — the claim is not testable)")

        print("\nP  the pathologies the ontology must be able to refuse")
        for col in spec.get("constant_columns") or []:
            tname, cname = col["table"], col["column"]
            cur.execute(f"SELECT count(DISTINCT {cname}) FROM {tname}")
            distinct = cur.fetchone()[0]
            why = f" — {col['why']}" if col.get("why") else ""
            check(f"P {tname}.{cname} is constant (that IS the finding){why}", distinct, 1)

        for col in spec.get("null_rates") or []:
            tname, cname = col["table"], col["column"]
            cur.execute(f"SELECT count(*) FILTER (WHERE {cname} IS NULL)::numeric / NULLIF(count(*),0) "
                        f"FROM {tname}")
            rate = cur.fetchone()[0]
            lo = float(col.get("min", 0.0))
            hi = float(col.get("max", 1.0))
            why = f" — {col['why']}" if col.get("why") else ""
            check(f"P {tname}.{cname} NULL rate {rate} in [{lo}, {hi}]{why}",
                  rate is not None and lo <= float(rate) <= hi, True)
    finally:
        cur.close()
        conn.close()

    summary = {"dataset": name, "checks": CHECKS, "failed": len(FAILS), "failures": FAILS,
               "skipped": SKIPS}
    print()
    for item in SKIPS:
        print(f"NOT RUN: {item}")
    print(f"{CHECKS} checks, {len(FAILS)} failed")
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
