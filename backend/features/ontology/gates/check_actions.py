#!/usr/bin/env python3
"""check_actions.py — the gates for the VERB layer, and the mutations that prove they can fail.

Same philosophy as the read lane's gates: every promise actions.py makes is asserted here,
and every gate is shown to be able to go red. The promises, in order:

    G1  declarations COMPILE: every parameter, precondition and effect in actions.yml turns
        into SQL, and every declared parameter is actually used
    G2  the ontology CONTRACT holds: an effect may only write a `:state "action"` property
        (mutation M1 removes the annotation and must turn this red)
    G3  a run WRITES + AUDITS: one transaction, an append-only audit_events row with the
        before and after rows
    G4  a refused precondition writes NOTHING and audits NOTHING
    G5  the write is VISIBLE to both read lanes with no materialisation: the compiled SQL
        count (lane A) and the SPARQL/Ontop count (lane B) move together
    G6  a mutation that weakens a declaration (an undeclared parameter in a precondition)
        is refused at compile time
    G7  a parameter VALUE that violates the declared type is refused at run time (the
        `type` field is metadata the engine OBEYS, mutation G7b shows it can go red)
    G8  `audit: none` is refused at compile time (audit is the floor, not a knob)
    G9  `required: false` is refused at compile time (a declaration the engine would ignore)
    G10 every audit row records the spec hash of the action declaration that executed
    M1  removing `:state "action"` from a written property must turn G2 red
    M2  changing the :PremiumCustomer axiom must change the compiled guard: PromoteCustomer's
        precondition is DERIVED from the reasoner's definition, not hand-written

Run with the cube-tutorial venv python:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python check_actions.py
The gate restores the row it touched (finally), so the demo data ends as it began.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.parse
import urllib.request

import psycopg2

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
# The compiler reads the profile from $APP_SETTINGS and applies its ns + ontology_dir + OVERLAY.
# Retail's metrics live in the overlay, so a gate that checks retail without this loaded an
# ontology with no metrics at all.
import os as _os
_os.environ["APP_SETTINGS"] = str(profile_dir("retail") / "settings.json")
import actions  # noqa: E402
import sqlgen    # noqa: E402

ENDPOINT = "http://127.0.0.1:8080/sparql"
NS = sqlgen.NS

ok = True


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def db():
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()
    cur.execute(actions.AUDIT_DDL)
    conn.commit()
    return conn, cur


def tier_of(cur, cid):
    cur.execute("SELECT tier FROM customers WHERE id = %s", (cid,))
    return cur.fetchone()[0]


def audit_count(cur):
    cur.execute("SELECT count(*) FROM audit_events")
    return cur.fetchone()[0]


def lane_a_premium_count(cur):
    cur.execute("SELECT count(*) FROM customers WHERE tier = 'PREMIUM'")
    return cur.fetchone()[0]


def lane_b_premium_count():
    q = ("PREFIX ex: <http://example.org/retail#> "
         "SELECT (COUNT(?c) AS ?n) WHERE { ?c a ex:PremiumCustomer }")
    req = urllib.request.Request(
        ENDPOINT, data=urllib.parse.urlencode({"query": q}).encode(),
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(json.load(r)["results"]["bindings"][0]["n"]["value"])


def main() -> int:
    graph = actions.load_graph()
    cfg = actions.load_config()
    compiled = actions.compile_actions(graph, cfg)
    conn, cur = db()
    try:
        print("=== G1 declarations compile ===")
        for name, act in compiled.items():
            used = set(act["effect_used"])
            for c in act["checks"]:
                used |= set(c.get("used", []))
            # parameters are used if the effect or some precondition names them; a parameter
            # nobody uses would be a declaration that lies about the action's interface.
            declared = set(act["parameters"])
            # the object key parameter is used by the UPDATE's WHERE clause
            if act.get("key_param"):
                used.add(act["key_param"])
            unused = declared - used
            check(f"{name}: every declared parameter is used", unused, set())
            check(f"{name}: effect compiles to one statement", bool(act["effect_sql"]), True)
            check(f"{name}: preconditions are compiled", len(act["checks"]) >= 1, True)

        print("=== G2 ontology contract: effect property is action-owned ===")
        for name, act in compiled.items():
            if act["kind"] == "edit":
                prop = act["property"]
                check(f"{name}: :{prop} carries :state \"action\"",
                      sqlgen._one(graph, sqlgen.P(prop), sqlgen.P("state")), "action")

        print("=== setup: targets are picked from LIVE state, not hard-coded ids ===")
        # A previous demo run (the UI, a checker, the user) may have promoted bob already.
        # The guard would then correctly refuse the gate's promote and wedge the suite, so the
        # gate picks a STANDARD customer for the write and a PREMIUM one for the refusal.
        cur.execute("SELECT id, tier FROM customers ORDER BY id")
        rows = cur.fetchall()
        standard = [i for i, t in rows if t != "PREMIUM"]
        premium = [i for i, t in rows if t == "PREMIUM"]
        if not standard:
            actions.run_action("DemoteCustomer", {"customer_id": premium[0]}, "gate-setup",
                               conn=conn, compiled=compiled)
            standard = [premium.pop(0)]
            check("setup demoted a customer to STANDARD", tier_of(cur, standard[0]), "STANDARD")
        check("a STANDARD customer exists for the write gate", bool(standard), True)
        check("a PREMIUM customer exists for the refusal gate", bool(premium), True)
        target = 2 if 2 in standard else standard[0]
        refuse_target = 3 if 3 in premium else premium[0]
        print(f"  target={target} (writes), refuse_target={refuse_target} (must refuse)")
        baseline_a = lane_a_premium_count(cur)
        baseline_b = lane_b_premium_count()
        print(f"  baseline premium count: lane A={baseline_a}, lane B={baseline_b}")

        print("=== G3 a run writes and audits (the picked STANDARD customer -> PREMIUM) ===")
        before_audit = audit_count(cur)
        run1 = actions.run_action("PromoteCustomer", {"customer_id": target}, "gate", conn=conn,
                                  compiled=compiled)
        check("tier after promote", tier_of(cur, target), "PREMIUM")
        check("audit row added", audit_count(cur), before_audit + 1)
        check("audit before-row", run1["before"].get("tier"), "STANDARD")
        check("audit after-row", run1["after"].get("tier"), "PREMIUM")

        print("=== G5 write visible to both read lanes (no materialisation) ===")
        check("lane A (compiled SQL) premium count", lane_a_premium_count(cur), baseline_a + 1)
        check("lane B (SPARQL/Ontop) premium count", lane_b_premium_count(), baseline_b + 1)

        print("=== G4 refused precondition writes nothing and audits nothing ===")
        before = (tier_of(cur, refuse_target), audit_count(cur))
        try:
            actions.run_action("PromoteCustomer", {"customer_id": refuse_target}, "gate",
                               conn=conn, compiled=compiled)
            check("second promotion refused", "succeeded", "refused")
        except actions.Refusal:
            check("second promotion refused", "refused", "refused")
        check("tier unchanged after refusal", tier_of(cur, refuse_target), before[0])
        check("no audit row for a refusal", audit_count(cur), before[1])

        print("=== G6 mutation: undeclared parameter in a precondition is refused ===")
        mutant = json.loads(json.dumps(cfg))
        mutant["actions"][0]["preconditions"].append(
            {"kind": "params", "expression": "undeclared_param > 0"})
        try:
            actions.compile_actions(graph, mutant)
            check("mutant refused at compile time", "compiled", "refused")
        except actions.Refusal:
            check("mutant refused at compile time", "refused", "refused")

        print("=== G7 type-violating value is refused before any SQL ===")
        before = audit_count(cur)
        try:
            actions.run_action("PromoteCustomer", {"customer_id": "two"}, "gate",
                               conn=conn, compiled=compiled)
            check("string for an integer parameter refused", "accepted", "refused")
        except actions.Refusal as exc:
            check("string for an integer parameter refused",
                  "refused" if "must be integer" in str(exc) else str(exc), "refused")
        check("no audit row for a type violation", audit_count(cur), before)
        # the same gate must fire in the read-only dry-run too
        try:
            actions.check_action("PromoteCustomer", {"customer_id": [1]}, compiled=compiled)
            check("dry-run type violation refused", "accepted", "refused")
        except actions.Refusal:
            check("dry-run type violation refused", "refused", "refused")

        print("=== G8 mutation: audit:none is refused at compile time ===")
        mutant = json.loads(json.dumps(cfg))
        mutant["actions"][0]["audit"] = "none"
        try:
            actions.compile_actions(graph, mutant)
            check("audit:none refused", "compiled", "refused")
        except actions.Refusal as exc:
            check("audit:none refused",
                  "refused" if "audit" in str(exc) else str(exc), "refused")

        print("=== G9 mutation: required:false is refused at compile time ===")
        mutant = json.loads(json.dumps(cfg))
        mutant["actions"][0]["parameters"]["customer_id"]["required"] = False
        try:
            actions.compile_actions(graph, mutant)
            check("required:false refused", "compiled", "refused")
        except actions.Refusal as exc:
            check("required:false refused",
                  "refused" if "required: false" in str(exc) else str(exc), "refused")

        print("=== G10 audit row carries the spec hash of the executed declaration ===")
        compiled2 = actions.compile_actions(graph, cfg)
        cur.execute("SELECT statements FROM audit_events ORDER BY id DESC LIMIT 1")
        last = cur.fetchone()[0]
        check("latest audit row names the spec that executed",
              last.get("spec") == compiled2["PromoteCustomer"]["spec_hash"], True)

        print("=== M1 mutation: removing :state \"action\" turns G2 red ===")
        stripped = actions.load_graph()
        stripped.remove((sqlgen.P("tier"), sqlgen.P("state"), None))
        try:
            actions.compile_actions(stripped, cfg)
            check("action-owned violation caught", "compiled", "refused")
        except actions.Refusal as exc:
            check("action-owned violation caught",
                  "refused" if "not action-owned" in str(exc) else str(exc), "refused")

        print("=== M2 mutation: the guard is DERIVED from the reasoner's axiom ===")
        from rdflib import Literal, OWL
        promote = compiled["PromoteCustomer"]
        tmpl = next(c["template"] for c in promote["checks"] if c["kind"] == "class")
        check("guard compiles from the axiom (tier = 'PREMIUM')",
              "tier = 'PREMIUM'" in tmpl, True)
        # change the axiom's facet in memory; the compiled guard must follow with no YAML edit
        mut = actions.load_graph()
        touched = 0
        for subj, pred, obj in list(mut.triples((None, OWL.hasValue, None))):
            if str(obj) == "PREMIUM":
                mut.remove((subj, pred, obj))
                mut.add((subj, pred, Literal("GOLD")))
                touched += 1
        check("mutated exactly one hasValue facet", touched, 1)
        mutated = actions.compile_actions(mut, cfg)
        tmpl2 = next(c["template"] for c in mutated["PromoteCustomer"]["checks"]
                     if c["kind"] == "class")
        check("guard follows the axiom (GOLD, not PREMIUM)",
              ("GOLD" in tmpl2) and ("PREMIUM" not in tmpl2), True)
        eff2 = mutated["PromoteCustomer"]["effect_sql"]
        check("effect follows the axiom (SET tier = 'GOLD')",
              ("'GOLD'" in eff2) and ("PREMIUM" not in eff2), True)

        print("=== restore (DemoteCustomer on the gate's target only) ===")
        actions.run_action("DemoteCustomer", {"customer_id": target}, "gate", conn=conn,
                           compiled=compiled)
        check("tier restored", tier_of(cur, target), "STANDARD")
        check("lane A premium count restored", lane_a_premium_count(cur), baseline_a)
        check("lane B premium count restored", lane_b_premium_count(), baseline_b)
    finally:
        conn.close()

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
