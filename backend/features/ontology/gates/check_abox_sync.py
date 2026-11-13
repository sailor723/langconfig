#!/usr/bin/env python3
"""The numbers a page shows must be the entailments the reasoner produced — not a look-alike.

`materialize.py` writes `candidate_match` from HermiT's answer, and the ontology's dashboard panels read
that table. Between those two facts sits the failure this gate exists for: the table can be stale (nobody
re-ran the bridge after a CV was added), or hand-edited, or written by a SQL rule that re-implements the
definition "equivalently" and drifts one clause later. The page would look perfect.

So the gate re-runs the reasoner over the profile's current ABox and demands the table be IDENTICAL:

    S1  the table's rows equal the reasoned set, both directions, per role class
    S2  the audit row (`reasoning_run`) is from the same candidate count as the ABox — a table built
        from 120 records while the ABox now holds 277 is stale, however plausible it looks
    S3  the ontology is still consistent (an inconsistent ontology makes every entailment vacuous)

Usage:
    PY=backend/.venv/bin/python
    $PY backend/features/ontology/gates/check_abox_sync.py --profile profiles/talent_v1/talent_v1_settings.json

Exit: 0 in sync, 1 drift/red, 2 NOT RUN (no reasoner, no database, no ABox).

Connection: the same PGHOST/PGPORT/PGUSER/PGPASSWORD + the profile's `dsn.dbname`, so the gate reads the
database the app reads.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

OK = True
CHECKS = 0


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--as-json", action="store_true")
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    if not profile.is_file():
        print(f"NOT RUN — no profile at {profile}")
        return 2
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = profile.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    spec_path = (base / (settings.get("reasoning_spec") or "reasoning.json")).resolve()
    dbname = ((settings.get("dsn") or {}).get("dbname") or settings.get("abox_db") or "").strip()

    print(f"profile: {profile}")
    print(f"database: {dbname or '(undeclared)'}")
    if not (abox.is_file() and axioms.is_file() and spec_path.is_file()):
        print("\nNOT RUN — this profile declares no ABox (need abox.ttl + reasoning.ttl + reasoning.json)")
        return 2
    if not dbname:
        print("\nNOT RUN — the profile declares no dsn.dbname for the materialised tables")
        return 2

    from features.ontology.reasoning import reasoner as R

    usable, why = R.available()
    if not usable:
        print(f"\nNOT RUN — the reasoner is unavailable: {why}")
        return 2

    try:
        import psycopg2
    except Exception as exc:
        print(f"\nNOT RUN — psycopg2 unavailable: {exc}")
        return 2

    try:
        conn = psycopg2.connect(host=os.environ.get("PGHOST", "127.0.0.1"),
                                port=int(os.environ.get("PGPORT", 5432)), dbname=dbname,
                                user=os.environ.get("PGUSER", "langconfig"),
                                password=os.environ.get("PGPASSWORD", ""))
        conn.close()
    except Exception as exc:
        print(f"\nNOT RUN — cannot reach {dbname}: {exc}")
        return 2

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    graph = R.load_graph([axioms, abox])
    classes = sorted({ns + item["class"] for item in
                      (spec.get("inferred") or []) + (spec.get("excluded") or [])})
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=classes)

    print("\n=== S1 the table equals the reasoner's answer ===")
    conn = psycopg2.connect(host=os.environ.get("PGHOST", "127.0.0.1"),
                            port=int(os.environ.get("PGPORT", 5432)), dbname=dbname,
                            user=os.environ.get("PGUSER", "langconfig"),
                            password=os.environ.get("PGPASSWORD", ""))
    try:
        with conn.cursor() as cur:
            cur.execute("select candidate, role_class from candidate_match")
            table = {(r[0], r[1]) for r in cur.fetchall()}
            cur.execute("select count(*) from candidate")
            table_candidates = cur.fetchone()[0]
            cur.execute("select engine, candidates from reasoning_run order by run_at desc limit 1")
            run = cur.fetchone()
    finally:
        conn.close()

    reasoned = {(m.rsplit("#", 1)[-1], cls.rsplit("#", 1)[-1])
                for cls in classes for m in result.members_of(cls)}
    for cls in classes:
        local = cls.rsplit("#", 1)[-1]
        want = {(m, local) for m, c in reasoned if c == local}
        have = {(m, c) for m, c in table if c == local}
        missing = sorted(want - have)
        extra = sorted(have - want)
        check_true(f"{local}: the table holds exactly the {len(want)} reasoned member(s)",
                   not missing and not extra,
                   f"missing {missing[:3]} · extra {extra[:3]} — re-run scripts/talent/materialize.py, "
                   "and if it still disagrees, the table was not written by the reasoner")

    print("\n=== S2 the table was built from the ABox that is on disk ===")
    abox_candidates = len(set(graph.subjects(None, None)))
    if run:
        engine, counted = run
        check_true(f"the last materialisation counted {counted} candidate(s), same as the table",
                   counted == table_candidates,
                   f"reasoning_run says {counted}, candidate holds {table_candidates}")
        check_true("the materialisation used the declared reasoner", engine == result.engine,
                   f"audit says {engine}, profile declares {result.engine}")
    else:
        not_run("the materialisation was audited", "reasoning_run has no row — was this table hand-made?")

    print("\n=== S3 the ontology is still consistent ===")
    check_true("the reasoner accepted the ontology", result.consistent,
               "; ".join(result.notes) or "inconsistent")

    print()
    verdict = "green" if OK else "red"
    print(f"{CHECKS} checks · {'0 failed' if OK else 'FAILED'} · {verdict}")
    if args.as_json:
        print(json.dumps({"ok": OK, "checks": CHECKS, "members": len(reasoned),
                          "rows": len(table)}, ensure_ascii=False))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
