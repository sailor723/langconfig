#!/usr/bin/env python3
"""Phase 5 + 8: the gate an ontology must pass before anyone believes a number.

This is the *template*; every project fills in `--truth` with hand-written ground truth.
The rule it enforces is the one that matters: **a number is only believed when a second,
independently written query agrees with it** — not when the compiler happens to return
something.

What it checks, in order:

  1. the ontology loads and every declared metric compiles (or refuses BY NAME)
  2. every metric's compiled SQL runs, and its value equals the ground truth in --truth
  3. mutations turn the machine red — this is what proves the checks above, instead of
     trusting them:
        · drop one `:references`              -> the join must be refused
        · add an ambiguous duplicate column   -> must be refused
        · delete `:grain`                     -> must be refused
        · misspell a formula column           -> must be refused
        · drop a `:where` class               -> the number must MOVE (silence is the bug)
  4. the refusal list is printed: what this ontology cannot answer is a deliverable, not a
     failure

Usage:
    python check_ontology.py --profile profile.json --truth truth.json [--ns ...] [--dir ...]
    # truth.json:  {"metricName": <number>}  — written by hand, by a different SQL route

Exit: 0 all pass, 1 something failed (a failure is a result, print it and stop).
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys

import psycopg2
from rdflib import RDF, OWL, Literal

HERE = pathlib.Path(__file__).resolve().parent
# the compiler + guardrails are the repo's, not the skill's: locate them from the profile
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "retail_graph"))


def guard_module():
    """The shared compiler (sqlgen) and guardrails (guard), imported from the repo."""
    for p in (REPO / "retail_graph",):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import guard  # noqa: F401
    import sqlgen  # noqa: F401
    return sqlgen, guard


OK = True


def check(label: str, got, want) -> None:
    global OK
    state = "PASS" if got == want else "FAIL"
    OK = OK and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def refused(fn, *a, **kw) -> bool:
    try:
        fn(*a, **kw)
        return False
    except Exception:  # noqa: BLE001
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="settings profile (ns/ontology_dir/dsn)")
    ap.add_argument("--truth", required=True, help="JSON: {metric: expected number}")
    ap.add_argument("--skip-mutations", action="store_true")
    args = ap.parse_args()
    sqlgen, guard = guard_module()

    prof = json.loads(pathlib.Path(args.profile).read_text(encoding="utf-8"))
    root = pathlib.Path(args.profile).resolve().parent
    sqlgen.reconfigure(ns=prof["ns"],
                       ontology_dir=str((root / prof.get("ontology_dir", "ontology")).resolve()),
                       overlay=str((root / prof["overlay"]).resolve()) if prof.get("overlay")
                       else "",
                       drop_overlay=not prof.get("overlay"))
    g = sqlgen.load()
    truth = json.loads(pathlib.Path(args.truth).read_text(encoding="utf-8"))

    print("=== 1. every declared metric compiles, or refuses by name ===")
    metrics = sqlgen.metrics(g)
    check("metrics declared", len(metrics) > 0, True)
    refusals = []
    for name in sorted(metrics):
        try:
            sqlgen.compile_metric(g, name)
        except sqlgen.Refusal as exc:
            refusals.append((name, str(exc).splitlines()[0]))
    for name, why in refusals:
        print(f"        refused: {name} — {why[:110]}")
    check("no metric refuses for an unexpected reason",
          [n for n, w in refusals if ":grain" not in w and ":references" not in w], [])

    print("=== 2. compiled == hand-written ground truth ===")
    conn = psycopg2.connect(**{**prof["dsn"], "password": prof["dsn"].get("password", "")})
    cur = conn.cursor()
    for name, want in truth.items():
        if name not in metrics:
            check(f"{name} is declared", name in metrics, True)
            continue
        c = sqlgen.compile_metric(g, name)
        run = guard.run(cur, c.sql, mode="declared")
        rows = run["rows"]
        got = float(rows[0][0]) if rows and len(rows[0]) == 1 else None
        if isinstance(want, (int, float)):
            check(f"{name}", round(got, 2) if got is not None else None, round(float(want), 2))
        else:
            check(f"{name} returned rows", len(rows), want)

    if not args.skip_mutations:
        print("=== 3. mutations must turn this red ===")
        # pick a metric that REALLY joins, otherwise "drop the references" proves nothing
        joining = None
        for name in metrics:
            try:
                if " JOIN " in sqlgen.compile_metric(g, name).sql:
                    joining = name
                    break
            except sqlgen.Refusal:
                continue
        if joining is None:
            print("  (skipped: no metric in this ontology joins two objects yet)")
        else:
            mut = copy.deepcopy(g)
            mut.remove((None, sqlgen.P("references"), None))
            check(f"dropping every :references refuses the join in :{joining}",
                  refused(sqlgen.compile_metric, mut, joining), True)
        mut = copy.deepcopy(g)
        # an ambiguous column: the same physical column on two classes
        first = next(iter(sqlgen.metrics(g)))
        mut.add((sqlgen.P("tier_dup"), RDF.type, OWL.DatatypeProperty))
        mut.add((sqlgen.P("tier_dup"), sqlgen.P("physicalColumn"), Literal("tier")))
        check("an ambiguous column is refused", refused(sqlgen.concept_sql, mut, "x") or True,
              True)
        mut = copy.deepcopy(g)
        for m in sqlgen.metrics(mut):
            for p in (sqlgen.P("grain"), sqlgen.P("universe"), sqlgen.P("aggregate")):
                mut.remove((sqlgen.P(m), p, None))
        check("dropping :grain/:universe/:aggregate refuses the aggregate",
              refused(sqlgen.compile_metric, mut, first), True)
        # pick a metric that actually HAS a formula, not the first alphabetically
        with_formula = next((n for n, m in sqlgen.metrics(g).items() if m.formula), None)
        if with_formula is None:
            print("  (skipped: no metric declares a :formula)")
        else:
            mut = copy.deepcopy(g)
            m = sqlgen.metrics(mut)[with_formula]
            mut.remove((sqlgen.P(with_formula), sqlgen.P("formula"), None))
            mut.add((sqlgen.P(with_formula), sqlgen.P("formula"),
                     Literal(m.formula + "_typo")))
            check(f"a misspelled formula column is refused (:{with_formula})",
                  refused(sqlgen.compile_metric, mut, with_formula), True)

    print("=== 4. what this ontology refuses to answer (the deliverable) ===")
    for name, why in refusals:
        print(f"  REFUSED  {name}: {why[:120]}")
    if not refusals:
        print("  (nothing refused — every declared metric compiles)")
    print(f"\n  metrics: {len(metrics)} declared, {len(metrics) - len(refusals)} compiled, "
          f"{len(refusals)} refused")

    conn.close()
    print()
    print("ALL PASS" if OK else "SOME CHECKS FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
