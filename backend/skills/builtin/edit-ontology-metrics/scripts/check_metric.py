#!/usr/bin/env python3
"""Compile a metric from an ontology profile, run it under the guardrails, and check it.

Three questions, in the order an editor needs them:

1. **Does everything still compile?** Every declared metric compiles or refuses BY NAME. No
   database needed for this half, so it is cheap enough to run after every edit.
2. **What does this one metric compile to, and what does it return?** `--metric` prints the SQL
   the compiler produced and the number the database gives under the profile's guardrails
   (page cap, statement timeout, plan budget).
3. **Is the number right?** `--truth` does not take a number you copied from the compiler: it
   compares against a route *you* wrote (`--independent "select …"`), because agreement with
   itself proves nothing. If both are given, they are compared and disagreement is a failure.

Why a script and not "read the compiler": the compiler (`retail_graph/sqlgen.py`) and the guardrails
(`retail_graph/guard.py`) live in the ontology repo, and this file is the only place that knows how
to point them at a `work/<key>/` copy. It never writes anything.

Usage (from anywhere; `PY` must have psycopg2 + rdflib):

    PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
    $PY scripts/check_metric.py --profile work/logistics/logistics_settings.json
    $PY scripts/check_metric.py --profile … --metric tripCount --sql
    $PY scripts/check_metric.py --profile … --metric totalRevenue \
        --independent "select sum(freight_fee) from trips"

Environment:
    ONTOLOGY_REPO   the ontology repository root (default /Users/weiping/dev/Learn/ontology)

Exit: 0 everything asked for passed, 1 something failed or refused.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology").expanduser()


def _die(message: str) -> "int":
    print(f"ERROR: {message}")
    return 1


def _load_compiler():
    """The repo's compiler and guardrails — not a copy of them."""
    graph_dir = pathlib.Path(__file__).resolve().parents[4] / "features" / "ontology" / "compiler"
    if not graph_dir.is_dir():
        raise SystemExit(f"ERROR: no compiler at {graph_dir} (set ONTOLOGY_REPO)")
    if str(graph_dir) not in sys.path:
        sys.path.insert(0, str(graph_dir))
    import guard  # noqa: E402
    import sqlgen  # noqa: E402

    return sqlgen, guard


def _configure(sqlgen, profile_path: pathlib.Path):
    prof = json.loads(profile_path.read_text(encoding="utf-8"))
    root = profile_path.resolve().parent
    overlay = prof.get("overlay")
    sqlgen.reconfigure(
        ns=prof.get("ns"),
        ontology_dir=str((root / (prof.get("ontology_dir") or "ontology")).resolve()),
        overlay=str((root / overlay).resolve()) if overlay else "",
        drop_overlay=not overlay,
    )
    return prof, sqlgen.load()


def _connect(prof: dict):
    import psycopg2

    dsn = prof.get("dsn") or {}
    if isinstance(dsn, str) and dsn:
        return psycopg2.connect(dsn)
    if not isinstance(dsn, dict) or not dsn.get("dbname"):
        raise SystemExit("ERROR: the profile has no dsn{dbname:…} — nothing to run against")
    parts = {k: v for k, v in dsn.items() if v not in (None, "")}
    return psycopg2.connect(**parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="the ontology's *_settings.json (in your work copy)")
    ap.add_argument("--metric", help="one metric to inspect and run")
    ap.add_argument("--sql", action="store_true", help="print the compiled SQL")
    ap.add_argument("--truth", type=float, help="the number you obtained another way")
    ap.add_argument("--independent", help="a SQL query YOU wrote, by a different route (prints and compares)")
    ap.add_argument("--max-rows", type=int, default=None, help="override guard.max_rows for this run")
    args = ap.parse_args()

    profile_path = pathlib.Path(args.profile).expanduser()
    if not profile_path.is_file():
        return _die(f"no profile at {profile_path}")

    sqlgen, guard = _load_compiler()
    try:
        prof, graph = _configure(sqlgen, profile_path)
    except Exception as exc:                                    # noqa: BLE001
        return _die(f"the ontology does not load: {type(exc).__name__}: {exc}")

    metrics = sqlgen.metrics(graph)
    if not metrics:
        return _die("the graph declares no metrics — check ontology_dir/overlay in the profile")

    failed = False
    print(f"profile: {profile_path}")
    print(f"ns:      {prof.get('ns')}")
    print(f"metrics: {len(metrics)} declared")
    print("")

    # 1. everything compiles, or refuses by name --------------------------------------------
    compiled, refused = [], []
    for name in sorted(metrics):
        try:
            sqlgen.compile_metric(graph, name)
            compiled.append(name)
        except Exception as exc:                                # noqa: BLE001
            refused.append((name, str(exc).splitlines()[0] if str(exc) else type(exc).__name__))
    print(f"compile: {len(compiled)} compiled, {len(refused)} refused by name")
    for name, why in refused:
        print(f"  REFUSED {name}: {why}")
    print("")

    if not args.metric:
        if args.truth is not None or args.independent:
            return _die("--truth/--independent need --metric (they are about one number)")
        return 0 if compiled else 1

    # 2. one metric: SQL + the number under the guardrails ----------------------------------
    if args.metric not in metrics:
        near = [m for m in metrics if args.metric.lower() in m.lower()]
        return _die(f"{args.metric!r} is not a declared metric"
                    + (f" — did you mean: {', '.join(sorted(near))}" if near else ""))

    try:
        compiled_metric = sqlgen.compile_metric(graph, args.metric)
    except Exception as exc:                                    # noqa: BLE001
        print(f"REFUSED {args.metric}: {exc}")
        return 1
    # compile_metric returns a Compiled(metric, sql, notes) — the notes say which joins and
    # which declared filters went in, so they are printed rather than dropped.
    sql = getattr(compiled_metric, "sql", compiled_metric)
    notes = list(getattr(compiled_metric, "notes", []) or [])
    if notes:
        print("notes: " + " · ".join(str(n) for n in notes))
    if args.sql:
        print("compiled SQL:")
        print(sql.strip())
        print("")

    cfg = guard.config()
    if isinstance(prof.get("guard"), dict):
        cfg.update({k: v for k, v in prof["guard"].items() if v is not None})
    if args.max_rows is not None:
        cfg["max_rows"] = args.max_rows

    conn = _connect(prof)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # mode="declared", not "rows": a declared metric is never windowed. The definition
            # promises the whole set, so a now-relative window would silently change the number
            # it means (measured on tripCount: mode="rows" narrowed trips to the last 90 days and
            # answered 3950 where the definition says 4050).
            g = guard.run(cur, sql, cfg=cfg, mode="declared")
            rows = g.get("rows") or []
            cols = g.get("cols") or []
            if rows and len(cols) and len(rows[0]) > 1:
                # a GROUP BY metric's first cell is a dimension KEY, not the number: print the
                # pairs, because "damagedBoxesByRouteVersion = 'v2'" is a value nobody can check
                print(f"{args.metric} ({len(rows)} row(s), plan_rows={g.get('plan_rows')}):")
                for row in rows[:20]:
                    key = " / ".join("" if cell is None else str(cell) for cell in row[:-1])
                    print(f"  {key} = {row[-1]!r}")
                if len(rows) > 20:
                    print(f"  … {len(rows) - 20} more row(s)")
                value = rows[0][-1]
            else:
                value = rows[0][0] if rows and rows[0] else None
                print(f"{args.metric} = {value!r}   (plan_rows={g.get('plan_rows')}, "
                      f"guard={'on' if cfg.get('enabled') else 'off'})")
            for note in g.get("notes") or []:
                print(f"  guard: {note}")
            if args.independent:
                try:
                    cur.execute(args.independent)
                    indep = cur.fetchone()[0]
                except Exception as exc:                        # noqa: BLE001
                    print(f"  independent route FAILED: {type(exc).__name__}: {exc}")
                    return 1
                print(f"  independent route says {indep!r}")
                same = (value == indep) or (
                    isinstance(value, (int, float)) and isinstance(indep, (int, float))
                    and abs(float(value) - float(indep)) < 1e-6)
                print(f"  [{'PASS' if same else 'FAIL'}] the two routes agree")
                failed = failed or not same
            if args.truth is not None:
                same = (value == args.truth) or (
                    isinstance(value, (int, float)) and abs(float(value) - float(args.truth)) < 1e-6)
                print(f"  [{'PASS' if same else 'FAIL'}] equals --truth {args.truth!r}")
                failed = failed or not same
    finally:
        conn.close()

    print("")
    print("a number that runs is not a number that is right: write the second route yourself "
          "(--independent), or say the check is NOT RUN.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
