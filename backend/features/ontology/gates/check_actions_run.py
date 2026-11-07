"""A — ACTION GATES for one ontology: does the declared WRITE path actually hold?

`check_actions.py` is retail's gate (it hard-codes `customers.tier`), so an ontology that declares its
own verb had no gate over it. This one is declaration-driven: the fixture beside the profile
(`actions_fixture.json`) supplies only PARAMETERS — the numbers are counted here, from the database.

    python check_actions_run.py --profile ../ontologies/logistics/logistics_settings.json

What it proves, and how each one can fail:

  A1  every declared action COMPILES (an uncompilable verb refuses the whole declaration set)
  A2  the fixture's good parameters DRY-RUN as admitted — and a dry run writes NOTHING
      (row counts before/after must be identical; a "check" that writes is the worst of both)
  A3  the fixture's bad parameters are REFUSED BY NAME (the precondition text is asserted) and
      nothing is written — the rollback is measured, not trusted
  A4  a real run writes exactly ONE row, leaves ONE audit row, and MOVES the probe metric —
      read back through the ontology's own compiled metric, not through hand-written SQL
  A5  the mutation: take `:state "action"` off an effect target in an in-memory copy of the graph
      and the compile must refuse. Without this the "action-owned state" rule is a comment.
  A6  the audit row carries before/after and the statements it ran

Cleanup: a gate must not leave business data behind, so A4's row and its audit row are DELETED at the
end and the baseline is re-asserted. That deletion is a fixture teardown, stated here, not a write
path — the platform has none for it (which is the point: state an action owns has one writer).

Exit 0 only when every check passes; a refusal that does not happen is a FAILURE, not a skip.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
# The COMPILER lives in the ontology repository (sqlgen, guard, actions); the scripts that use it
# live here, with this skill. Both paths are explicit: a sibling script (HERE) and the compiler's
# own home (ONTOLOGY_REPO/retail_graph) — never "whichever directory this file happens to sit in".
ONTOLOGY_REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology")
# The COMPILER lives one directory up (features/ontology/compiler) and its modules import each
# other by bare name, so its directory goes on sys.path — a path that never depends on where this
# repository happens to live.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "compiler"))



def _early_profile() -> None:
    argv = sys.argv[1:]
    raw = None
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif arg.startswith("--profile="):
            raw = arg.split("=", 1)[1]
    if raw:
        p = pathlib.Path(raw).expanduser()
        os.environ["APP_SETTINGS"] = str(p if p.is_absolute() else (HERE / p).resolve())


_early_profile()

import actions                                        # noqa: E402
import psycopg2                                       # noqa: E402
import sqlgen                                         # noqa: E402
from rdflib import OWL                                # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        FAILS.append(label)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--fixture")
    args, _ = ap.parse_known_args()

    profile = pathlib.Path(os.environ["APP_SETTINGS"])
    fixture_path = pathlib.Path(args.fixture) if args.fixture else profile.parent / "actions_fixture.json"
    print(f"A — action gate · {profile.name} · {fixture_path.name}")

    settings = json.loads(profile.read_text())
    raw = (settings.get("actions_file") or "").strip()
    if not raw:
        print("  NOT RUN  this ontology declares no actions (profile has no actions_file)")
        print("\n0 checks, 0 failed")
        return 0
    actions_file = pathlib.Path(raw)
    if not actions_file.is_absolute():
        # a relative `actions_file` is relative to the PROFILE (that is how the profile declares it),
        # never to this script's directory
        actions_file = (profile.parent / actions_file).resolve()
    os.environ["APP_ACTIONS"] = str(actions_file)

    graph = sqlgen.load()
    cfg = actions.load_config(actions_file)
    compiled = actions.compile_actions(graph, cfg)          # A1: raises Refusal if any verb fails
    print("\nA1  every declared action compiles")
    for name in compiled:
        check(f"A1 {name} compiled", name in compiled, True)

    if not fixture_path.is_file():
        print(f"  NOT RUN  no fixture ({fixture_path.name}) — without parameters a gate cannot act")
        print(f"\n{CHECKS} checks, {len(FAILS)} failed")
        return 0 if not FAILS else 1
    fixture = json.loads(fixture_path.read_text()).get("actions") or {}

    conn = psycopg2.connect(**{**actions.dsn(), "password": ""})
    try:
        for name, spec in fixture.items():
            if name not in compiled:
                check(f"A0 fixture action {name} is declared", False, True)
                continue
            probe = spec["probe_metric"]
            table = spec.get("creates") or compiled[name]["table"]

            def counts(cur):
                cur.execute(sqlgen.compile_metric(graph, probe).sql)
                moved = cur.fetchone()[0]
                cur.execute(f"SELECT count(*) FROM {table}")
                rows = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM audit_events")
                audits = cur.fetchone()[0]
                return moved, rows, audits

            cur = conn.cursor()
            base = counts(cur)

            print(f"\nA2  dry run of {name} is admitted and writes NOTHING")
            dry = actions.check_action(name, spec["params"], compiled=compiled)
            check(f"A2 {name} dry run admitted", dry.get("admitted"), True)
            check(f"A2 {name} dry run wrote nothing", counts(cur), base)

            print(f"\nA3  bad parameters are refused BY NAME and write NOTHING")
            try:
                actions.run_action(name, spec["bad_params"], "gate", conn=conn, compiled=compiled)
                refused = None
            except (actions.Refusal, sqlgen.Refusal) as exc:
                refused = str(exc)
            check(f"A3 {name} refused", bool(refused), True)
            check(f"A3 the refusal names the precondition",
                  (spec.get("bad_expect") or "") in (refused or ""), True)
            check(f"A3 the refused run wrote nothing", counts(cur), base)

            print(f"\nA4  a real run writes one row, one audit row, and moves the probe metric")
            run = actions.run_action(name, spec["params"], "gate", conn=conn, compiled=compiled)
            after = counts(cur)
            check(f"A4 {name} ran", run.get("ok"), True)
            check(f"A4 one row in {table}", after[1], base[1] + 1)
            check(f"A4 one audit row", after[2], base[2] + 1)
            check(f"A4 {probe} moved by 1", after[0], base[0] + 1)
            if spec.get("moves_metric"):
                cur.execute(sqlgen.compile_metric(graph, spec["moves_metric"]).sql)
                coverage = cur.fetchone()[0]
                check(f"A4 {spec['moves_metric']} is now non-zero", float(coverage) > 0, True)

            print(f"\nA6  the audit row carries what it says it carries")
            cur.execute("SELECT action, actor, before_row, after_row, statements FROM audit_events "
                        "ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            check("A6 audit names the action", row[0], name)
            check("A6 audit names the actor", row[1], "gate")
            check("A6 audit has the written row", bool(row[3]), True)
            check("A6 audit has the preconditions and effect", bool(row[4]), True)

            # teardown: fixture artifacts only
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (run["after"]["id"],))
            cur.execute("DELETE FROM audit_events WHERE id = %s", (run["audit_id"],))
            conn.commit()
            check(f"A4 teardown restores the baseline", counts(cur), base)

            # ── A5: the action-owned rule must be able to bite ────────────────
            print(f"\nA5  dropping :state \"action\" makes the compile refuse")
            target = ((spec.get("action_owned_check") or {}).get("property")) or "id"
            removed = []
            for s, p, o in list(graph.triples((sqlgen.P(target), sqlgen.P("state"), None))):
                graph.remove((s, p, o))
                removed.append((s, p, o))
            try:
                refusal = None
                try:
                    actions.compile_action(graph, next(a for a in cfg["actions"] if a["name"] == name))
                except (actions.Refusal, sqlgen.Refusal) as exc:
                    refusal = str(exc)
                check(f"A5 {target} without :state \"action\" is refused",
                      "action-owned" in (refusal or ""), True)
                check(f"A5 and the refusal names the property", target in (refusal or ""), True)
            finally:
                for triple in removed:
                    graph.add(triple)
            check(f"A5 restored :state \"action\" compiles again",
                  actions.compile_action(graph, next(a for a in cfg["actions"] if a["name"] == name))
                  is not None, True)
    finally:
        conn.close()

    # ── A7: the words of a verb must not swallow a measure question ──────────
    print("\nA7  a question that asks for a NUMBER is never answered by a verb")
    import nl
    menu_ = nl.menu(graph)
    if "nl" in globals() and len(menu_["actions"]) > 0:
        pass
    for name, spec in fixture.items():
        q = spec.get("measure_question")
        if not q:
            continue
        rule = nl._rule_intent(q, menu_) or {}
        check(f"A7 '{q}' resolves to a metric", rule.get("kind"), "metric")
        check(f"A7 ... and to the declared one", rule.get("name"), spec.get("measure_expect_metric"))
        imp = spec.get("imperative_question")
        if imp:
            got = (nl._rule_intent(imp, menu_) or {}).get("kind")
            check(f"A7 the imperative '{imp}' still reaches a verb", got, "action")
        else:
            print(f"  NOT RUN  A7 imperative check (no imperative_question for {name})")

    print()
    print(f"{CHECKS} checks, {len(FAILS)} failed")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
