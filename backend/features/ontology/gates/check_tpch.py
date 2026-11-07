#!/usr/bin/env python3
"""T1–T7: the TPCH profile runs on the retail app — and retail is unchanged.

The TPCH ontology already proved its numbers in `sql-first/` (compiled == hand-written ground
truth). What this gate proves is the *second* claim: the same app, pointed at another profile,
still answers those numbers through the capability graph, the compiler and the guardrails —
while retail keeps working and the six metrics that do not compile are named, not hidden.

    $P check_tpch.py
"""
from __future__ import annotations

import json
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

import guard    # noqa: E402
import i18n     # noqa: E402
import nl       # noqa: E402
import serve_ui  # noqa: E402
import sqlgen   # noqa: E402

ok = True
TPCH = profile_dir("tpch") / "tpch_settings.json"


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def use(profile: pathlib.Path | None) -> dict:
    """Switch this process to a profile, the way `--settings` does."""
    import os
    target = (profile or profile_dir("retail") / "settings.json").resolve()
    os.environ["APP_SETTINGS"] = str(target)     # nl/actions read the profile from here too
    serve_ui.SETTINGS = target
    i18n.SETTINGS = serve_ui.SETTINGS
    guard.SETTINGS = serve_ui.SETTINGS
    s = serve_ui.load_settings()
    serve_ui.apply_profile(s)
    return s


def main() -> int:
    retail = use(None)
    tpch = use(TPCH)

    print("=== T1 the profile points at the TPCH ontology ===")
    check("namespace", tpch["ns"], "https://cube.local/ontology/tpch#")
    check("ontology folder", tpch["ontology_dir"], "ontology")
    check("overlay", tpch["overlay"], "metrics_ext.ttl")
    g = sqlgen.load()
    check("the graph is the TPCH one", len(g) > 700, True)
    check("retail's ontology is not loaded", "tbl_tier" in " ".join(
        str(o) for o in g.objects()), False)

    print("=== T2 the numbers are sql-first's ground truth ===")
    conn = psycopg2.connect(**{**tpch["dsn"], "password": tpch["dsn"].get("password", "")})
    cur = conn.cursor()
    truth = {
        "netRevenue": 20535072231.4150,
        "averageLineValue": 34192.5235,
        "lineItems": 600572,
        "highBalanceCustomers": 6733,
    }
    for name, want in truth.items():
        c = sqlgen.compile_metric(g, name)
        res = guard.run(cur, c.sql, mode="declared")
        got = float(res["rows"][0][0])
        check(f"{name}", round(got, 2), round(float(want), 2))

    print("=== T3 :LateLine is the one declared predicate, and it says so ===")
    pred, notes = sqlgen.concept_predicate(g, "LateLine")
    check("the predicate compiles", pred, "l_shipdate > l_commitdate")
    check("and it is reported as declared by hand",
          any(":physicalPredicate" in n for n in notes), True)
    res = guard.run(cur, f"SELECT count(*) FROM lineitem WHERE {pred}", mode="declared")
    check("late lines match sql-first's measured 302,748", int(res["rows"][0][0]), 302748)
    # an axiom AND a declared predicate is ambiguous: refuse rather than pick one
    from rdflib import RDF, Literal
    import copy
    mut = copy.deepcopy(g)
    mut.add((sqlgen.P("HighValueOrder"), sqlgen.P("physicalPredicate"),
             Literal("o_totalprice > 1")))
    try:
        sqlgen.concept_predicate(mut, "HighValueOrder")
        check("both an axiom and a declared predicate is refused", "compiled", "refused")
    except sqlgen.Refusal:
        check("both an axiom and a declared predicate is refused", "refused", "refused")

    print("=== T4 the menu is the TPCH one, and every metric compiles ===")
    menu = nl.menu(g)
    check("15 classes on the menu", len(menu["classes"]), 15)
    check("17 metrics on the menu", len(menu["metrics"]), 17)
    check("no actions in a read-only profile", menu["actions"], [])
    refused = []
    for x in menu["metrics"]:
        try:
            sqlgen.compile_metric(g, x["name"])
        except sqlgen.Refusal as exc:
            refused.append((x["name"], str(exc).splitlines()[0]))
    check("all 17 compile — the derived ones were revived", refused, [])

    print("=== T4b the revived + enriched numbers ===")
    for name, want in (("supplyCost", 7657917294.19),
                       ("contributionMargin", 12877154937.225),
                       ("totalDiscount", 1080857048.825),
                       ("lateLineRevenue", 10361016648.2079),
                       ("returnedLineValue", 5071818532.942),
                       ("highValueOrders", 148552)):
        c = sqlgen.compile_metric(g, name)
        got = float(guard.run(cur, c.sql, mode="declared")["rows"][0][0])
        check(name, round(got, 2), round(want, 2))
    pct = float(guard.run(cur, sqlgen.compile_metric(g, "contributionMarginPct").sql,
                          mode="declared")["rows"][0][0])
    check("contributionMarginPct is a percentage (:scale)", round(pct, 2), 62.71)
    check("supplyCost joins partsupp on BOTH key columns",
          "AND lineitem.l_suppkey = partsupp.ps_suppkey"
          in sqlgen.compile_metric(g, "supplyCost").sql, True)
    for name, n in (("netRevenueByRegion", 5), ("netRevenueByNation", 25),
                    ("netRevenueByProduct", 1000), ("lineItemsByReturnFlag", 3)):
        rows = guard.run(cur, sqlgen.compile_metric(g, name).sql, mode="declared")["rows"]
        check(f"{name} groups", len(rows), n)


    print("=== T5 the profile switches off what TPCH does not have ===")
    check("actions off", tpch["features"]["actions"], False)
    check("lane B off (no R2RML mapping for tpch)", tpch["features"]["lane_b"], False)
    check("tutorial off (retail's story)", tpch["features"]["tutorial"], False)
    for path in ("/actions", "/backlog", "/tutorial", "/compare"):
        feat = serve_ui.FEATURE_OF[path]
        check(f"{path} is not served", serve_ui._features().get(feat, True), False)

    print("=== T6 guardrails follow the profile, not retail ===")
    cfg = guard.config()
    check("lineitem is a big table here", cfg["big_tables"].get("lineitem"), "l_shipdate")
    listing = guard.apply("SELECT l_orderkey FROM lineitem", cfg, mode="rows")
    check("a listing is windowed and capped",
          ("l_shipdate >= now()" in listing["sql"], "LIMIT" in listing["sql"]), (True, True))
    metric = guard.apply("SELECT sum(l_extendedprice) FROM lineitem", cfg, mode="declared")
    check("a declared metric is never windowed", "now() - interval" in metric["sql"], False)
    check("and the scan is reported", any("unbounded scan" in n for n in metric["notes"]), True)
    conn.close()

    print("=== T7 retail is untouched by all of this ===")
    use(None)
    s = serve_ui.load_settings()
    check("retail namespace is back", s["ns"], "https://cube.local/ontology/retail#")
    gr = sqlgen.load()
    check("retail graph is retail's", len(gr) < 400, True)
    conn = psycopg2.connect(**{**retail["dsn"]})
    cur = conn.cursor()
    c = sqlgen.compile_metric(gr, "orderRevenue")
    check("retail orderRevenue is still 969.50",
          round(float(guard.run(cur, c.sql, mode="declared")["rows"][0][0]), 2), 969.50)
    check("retail metric count", len(sqlgen.metrics(gr)), 16)
    conn.close()

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
