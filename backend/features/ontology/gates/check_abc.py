#!/usr/bin/env python3
"""A1–A6: the mock ABC cold-chain profile — objects, definitions, metrics, actions, guard.

The point of this gate is that the *definitions* are compiled, not typed into reports:
overload is a predicate, "failed delivery" is a 4-way union, "at risk driver" is a 3-way
union on a windowed snapshot, and the two writes are declared actions with audit.
"""
from __future__ import annotations

import pathlib
import sys

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

import psycopg2  # noqa: E402

import actions  # noqa: E402
import guard    # noqa: E402
import sqlgen   # noqa: E402

ok = True
PROFILE = profile_dir("abc") / "abc_settings.json"


def check(label, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def main() -> int:
    import json
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    sqlgen.reconfigure(ns=prof["ns"], ontology_dir=str(profile_dir("abc") / prof["ontology_dir"]),
                       drop_overlay=True)
    g = sqlgen.load()
    import dsn as _dsn

    conn = psycopg2.connect(**_dsn.resolved(prof))
    cur = conn.cursor()

    print("=== A1 the objects and their links ===")
    for cls, table in (("Trip", "trips"), ("Stop", "stops"), ("Vehicle", "vehicles"),
                       ("Driver", "drivers"), ("Route", "routes"), ("Complaint", "complaints")):
        check(f":{cls} -> {table}", sqlgen._one(g, sqlgen.P(cls), sqlgen.P("physicalTable")),
              table)
    check("Stop -> Trip is declared", sqlgen._one(g, sqlgen.P("tripOf"),
                                                  sqlgen.P("references")) is not None, True)

    print("=== A2 definitions are COMPILED, not written by hand ===")
    pred, notes = sqlgen.concept_predicate(g, "FailedDelivery")
    check("failed delivery is a union of four criteria",
          pred.count(" OR "), 3)
    check("and it is reported as a union", any("union" in n for n in notes), True)
    pred_trip, notes_trip = sqlgen.concept_predicate(g, "OverloadedTrip")
    check("overload compares columns (declared predicate)",
          "load_boxes >= box_capacity_snapshot" in pred_trip, True)
    check("and it says it is declared by hand",
          any(":physicalPredicate" in n for n in notes_trip), True)
    pred_risk, notes_risk = sqlgen.concept_predicate(g, "AtRiskDriver")
    check("at-risk driver is a union of three criteria", pred_risk.count(" OR "), 2)

    print("=== A3 the metrics answer, and the rates are not integers ===")
    want = {"trips": 4050, "overloadedTrips": 1489, "atRiskDrivers": 29,
            "unjudgedComplaints": 3167}
    for name, expected in want.items():
        c = sqlgen.compile_metric(g, name)
        got = int(guard.run(cur, c.sql, mode="declared")["rows"][0][0])
        check(name, got, expected)
    rate = float(guard.run(cur, sqlgen.compile_metric(g, "overloadRate").sql,
                           mode="declared")["rows"][0][0])
    check("overload rate is a real fraction, not integer 0",
          (rate > 0.3 and rate < 0.45), True)
    stops_per_trip = float(guard.run(cur, sqlgen.compile_metric(g, "stopsPerTrip").sql,
                                     mode="declared")["rows"][0][0])
    check("stops per trip", round(stops_per_trip, 1), 12.6)
    for name in ("onTimeRate", "complaintRate", "permitCoverage", "damagePer1kStops"):
        v = float(guard.run(cur, sqlgen.compile_metric(g, name).sql,
                            mode="declared")["rows"][0][0])
        check(f"{name} is computed", v > 0, True)

    print("=== A4 the two writes are declared actions with audit ===")
    import importlib
    importlib.reload(actions)          # SCHEMA is read at import: reload after pointing it
    actions.SCHEMA = (profile_dir("abc") / prof["actions_file"]).resolve()
    compiled = actions.compile_actions(g, actions.load_config())
    check("two actions", sorted(compiled), ["AssignTrip", "JudgeLiability"])
    check("AssignTrip checks the three objects", len(compiled["AssignTrip"]["checks"]), 3)
    check("every action audits", all(a.get("audit") for a in compiled.values()), True)
    # an effect may only write action-owned state
    check("trip.driver_id is action-owned", sqlgen._one(g, sqlgen.P("driver_id"),
                                                        sqlgen.P("state")), "action")

    print("=== A5 the guardrails fit this profile ===")
    guard.SETTINGS = PROFILE
    cfg = guard.config()
    check("stops is a big table here", cfg["big_tables"].get("stops"), "trip_date")
    listing = guard.apply("SELECT id FROM stops", cfg, mode="rows")
    check("a listing is windowed and capped",
          ("trip_date >= now()" in listing["sql"], "LIMIT" in listing["sql"]), (True, True))
    metric = guard.apply("SELECT count(*) FROM stops", cfg, mode="declared")
    check("a metric is not windowed", "now() - interval" in metric["sql"], False)

    print("=== A5b the training tutorial exists and answers ===")
    import serve_ui
    serve_ui.SETTINGS = PROFILE
    tut = profile_dir("abc") / "tutorial"
    check("the shell exists", (tut / "shell.html").exists(), True)
    steps = sorted(p.name for p in tut.glob("step*.html"))
    check("eight step pages", len(steps), 8)
    shell = (tut / "shell.html").read_text(encoding="utf-8")
    check("the rail lists eight steps", shell.count('class="stepbtn'), 8)
    for q, want in (("哪些车没有核心区路权", "VehicleNoPermit"),
                    ("超载率", "overloadRate"),
                    ("按线路版本看单趟站点数", "stopsByVersion")):
        out = serve_ui.abct_ask(q)
        check(f"tutorial asks {q!r}", (out.get("result") or {}).get("name"), want)
    over = serve_ui.abct_overload_compile(100)
    check("the overload gate compiles at 100%", over["count"], 1489)
    tighter = serve_ui.abct_overload_compile(90)
    check("and moves when the threshold moves", tighter["count"] > over["count"], True)

    print("=== A6 the profile is wired like the others ===")
    check("namespace", prof["ns"], "https://cube.local/ontology/abc#")
    check("own generated page", prof["app_html"], "ontology.html")
    check("actions file", prof["actions_file"], "schema/actions.yml")
    check("read-only lane B (no mapping)", prof["features"]["lane_b"], False)
    check("writes off for nobody: actions on", prof["features"]["actions"], True)
    check("three dataset tabs declared", len(prof["profiles"]), 3)

    conn.close()
    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
