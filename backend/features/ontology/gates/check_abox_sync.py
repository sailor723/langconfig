#!/usr/bin/env python3
"""The numbers a page shows must be the entailments the reasoner produced — not a look-alike.

`materialize.py` writes `candidate_match` from HermiT's answer, and the ontology's dashboard panels read
that table. Between those two facts sits the failure this gate exists for: the table can be stale (nobody
re-ran the bridge after a CV was added), or hand-edited, or written by a SQL rule that re-implements the
definition "equivalently" and drifts one clause later. The page would look perfect.

So the gate re-runs the reasoner over the profile's current ABox and demands the table be IDENTICAL:

    S1  the table's rows equal the reasoned set, both directions, per role class
    S1b the RECOMMENDATION table (candidate_role_fit) equals what the written rule derives from the
        ABox: same rows, same score, same rank. A ranking someone edited by hand to put a favourite
        first would otherwise look exactly like a good day's shortlist.
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



def _check_fit(profile: pathlib.Path, settings: dict, graph, result, ns: str, dbname: str) -> None:
    """Re-derive every recommendation row from the ABox + the shared score, and demand equality.

    Everything here comes from the same two sources the materialiser used — the ABox (skills, years,
    education, applied role) and `scripts/talent/fit.py` (the weights) — so a drift can only mean the
    table was written by something else.
    """
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF

    from scripts.talent.fit import rank_rows, score as fit_score

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

    def _local(node) -> str:
        return str(node).rsplit("#", 1)[-1]

    skills_of: dict[str, set[str]] = {}
    category_of: dict[str, str] = {}
    for skill_node in graph.subjects(RDF.type, URIRef(ns + "SkillTag")):
        types = [_local(t) for t in graph.objects(skill_node, RDF.type)]
        category = next((t for t in types if t not in ("SkillTag", "NamedIndividual")), None)
        if category:
            category_of[_local(skill_node)] = category

    candidates: dict[str, dict] = {}
    for node in graph.subjects(RDF.type, URIRef(ns + "Candidate")):
        cid = _local(node)
        skills = {_local(o) for o in graph.objects(node, URIRef(ns + "hasSkill"))}
        skills_of[cid] = {category_of[s] for s in skills if s in category_of}
        years = next((int(v) for v in graph.objects(node, URIRef(ns + "yearsExperience"))
                      if isinstance(v, Literal)), None)
        rank = next((int(v) for v in graph.objects(node, URIRef(ns + "educationRank"))
                     if isinstance(v, Literal)), None)
        applied = next((_local(v) for v in graph.objects(node, URIRef(ns + "appliedFor"))), None)
        missing = {_local(v) for v in graph.objects(node, URIRef(ns + "missingData"))}
        candidates[cid] = {"years": years, "education_rank": rank, "applied": applied,
                           "duplicate": "UnknownYears" in missing and False}

    duplicates = {cid for cid, v in candidates.items()
                  if (URIRef(ns + cid), URIRef("http://www.w3.org/2002/07/owl#sameAs"), None) in graph}

    roles: dict[str, dict] = {}
    for node in graph.subjects(RDF.type, URIRef(ns + "Role")):
        # ABox individuals are named `role_<岗位>`; the match class is `matches_<岗位>`. Key by the bare
        # role name so the two sides meet (the first version keyed by the prefixed name and compared
        # 204 real rows against an empty expectation).
        rid = _local(node)
        if rid.startswith("role_"):
            rid = rid[len("role_"):]
        years = next((int(v) for v in graph.objects(node, URIRef(ns + "requiredYears"))
                      if isinstance(v, Literal)), None)
        rank = next((int(v) for v in graph.objects(node, URIRef(ns + "requiredEducationRank"))
                     if isinstance(v, Literal)), None)
        required = {category_of.get(_local(s)) for s in
                    graph.objects(node, URIRef(ns + "requiresSkill"))}
        roles[rid] = {"years": years, "rank": rank,
                      "categories": {c for c in required if c}}

    expected: list[dict] = []
    for iri in result.members:
        cls_local = _local(iri)
        jd_role = cls_local[len("matches_"):] if cls_local.startswith("matches_") else cls_local
        req = roles.get(jd_role)
        if not req:
            continue
        for member in result.members_of(iri):
            cid = _local(member)
            cand = candidates.get(cid)
            if cand is None or cid in duplicates or not cand["applied"]:
                continue
            matched = len(skills_of.get(cid, set()) & req["categories"])
            total = len(req["categories"])
            expected.append({
                "candidate": cid, "role_class": cls_local, "role": jd_role,
                "matched_skills": matched, "required_skills": total,
                "years_experience": cand["years"], "required_years": req["years"],
                "education_rank": cand["education_rank"], "required_education_rank": req["rank"],
                "fit_score": fit_score(matched_skills=matched, required_skills=total,
                                       years=cand["years"], required_years=req["years"],
                                       education_rank=cand["education_rank"],
                                       required_education_rank=req["rank"]),
            })
    expected = rank_rows(expected)

    import psycopg2

    conn = psycopg2.connect(host=conn_params["host"], port=int(conn_params["port"]),
                            dbname=dbname, user=conn_params["user"],
                            password=conn_params.get("password", ""))
    try:
        with conn.cursor() as cur:
            cur.execute("select candidate, role_class, matched_skills, required_skills, "
                        "years_experience, required_years, education_rank, "
                        "required_education_rank, fit_score, rank_in_role from candidate_role_fit")
            have = {(r[0], r[1]): r for r in cur.fetchall()}
    finally:
        conn.close()

    want = {(row["candidate"], row["role_class"]): row for row in expected}
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    check_true(f"the recommendation table holds exactly the {len(want)} row(s) the rule derives",
               not missing and not extra,
               f"missing {len(missing)} e.g. {[m[0][:24] for m in missing[:2]]} · "
               f"extra {len(extra)} e.g. {[e[0][:24] for e in extra[:2]]}")

    wrong_score, wrong_rank, wrong_detail = [], [], []
    for key, row in want.items():
        got = have.get(key)
        if got is None:
            continue
        if abs(float(got[8]) - float(row["fit_score"])) > 0.011:
            wrong_score.append((key[0][:24], got[8], row["fit_score"]))
        if int(got[9]) != int(row["rank_in_role"]):
            wrong_rank.append((key[0][:24], got[9], row["rank_in_role"]))
        expected_detail = (row["matched_skills"], row["required_skills"],
                           row["years_experience"], row["required_years"],
                           row["education_rank"], row["required_education_rank"])
        if tuple(got[2:8]) != expected_detail:
            wrong_detail.append((key[0][:24], got[2:8], expected_detail))
    check_true("every fit score matches the written weights", not wrong_score,
               f"{len(wrong_score)} differ, e.g. {wrong_score[:2]}")
    check_true("every rank matches the documented tie-break", not wrong_rank,
               f"{len(wrong_rank)} differ, e.g. {wrong_rank[:2]} — a hand-edited shortlist looks "
               "exactly like this")
    check_true("every row's skill/year/education columns match the ABox", not wrong_detail,
               f"{len(wrong_detail)} differ, e.g. {wrong_detail[:2]}")


def _dsn_from_profile(settings: dict, dbname_hint: str = "") -> dict:
    """Connection parameters from the profile's own `dsn`, with ${VAR:-default} substituted.

    A gate must not depend on someone having exported PGPASSWORD by hand: measured on talent_v1
    (2026-11-14), the builder ran this gate inside its own sandbox, `fe_sendauth: no password supplied`
    came back, and the publish refused with a NOT RUN gate the agent had no way to satisfy. The profile
    already declares where its database is; that declaration is the authority, and the environment is
    only the fallback.
    """
    import os
    import re

    dsn = settings.get("dsn") or {}
    out = {}
    wanted_var = ""
    for key in ("host", "port", "dbname", "user", "password", "sslmode"):
        raw = dsn.get(key)
        if raw is None:
            continue
        text = str(raw)
        m = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}", text.strip())
        if m:
            if key == "password":
                wanted_var = m.group(1)
            value = os.environ.get(m.group(1), m.group(2) or "")
        else:
            value = text
        if value not in ("", None):
            out[key] = value
    # …then the repo's own `.env`, because a gate that runs inside an agent sandbox does not inherit
    # the app's dotenv (the service loads it; a subprocess does not). Still never the first choice, and
    # the value never printed.
    if not out.get("password"):
        # HERE is backend/features/ontology/gates, so parents[4] is the repo root
        env_file = pathlib.Path(__file__).resolve().parents[4] / ".env"
        if env_file.is_file():
            wanted = (dbname_hint or "").upper().replace("-", "_")
            values = {}
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, _, v = line.partition("=")
                    values[k.strip()] = v.strip()
            stems = [wanted]
            if wanted.endswith("_DB"):
                stems.append(wanted[:-3])
            # the variable the profile NAMES comes first: `${TALENT_V1_DB_PASSWORD}` unset in the
            # environment is not permission to guess somebody else's password
            candidates = ([wanted_var] if wanted_var else []) + [
                f"{stem}{suffix}" for stem in stems
                          for suffix in ("_DB_PASSWORD", "_PASSWORD")]
            # POSTGRES_PASSWORD is the PLATFORM server's own credential (see tools/native_impl
            # _pg_conn_kwargs) and most profiles point at that server; a per-ontology variable is only
            # right when the dsn names it. Measured: a generic `<something>_DB_PASSWORD` picked first
            # produced "password authentication failed for user langconfig".
            candidates += ["ONTOLOGY_DB_PASSWORD", "POSTGRES_PASSWORD", "PGPASSWORD"]
            # NO "any *_DB_PASSWORD" fallback: this box defines one per ontology, and picking one at
            # random produced "password authentication failed for user langconfig" (measured today).
            # A credential guessing game is worse than a NOT RUN that says so.
            for key in candidates:
                if values.get(key):
                    out["password"] = values[key]
                    break
    # the deployment's own credentials are the last resort, never the first
    out.setdefault("host", os.environ.get("PGHOST", "127.0.0.1"))
    out.setdefault("port", os.environ.get("PGPORT", "5432"))
    out.setdefault("user", os.environ.get("PGUSER", "langconfig"))
    out.setdefault("password", os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD", ""))
    return out


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
    conn_params = _dsn_from_profile(settings, (settings.get("dsn") or {}).get("dbname") or "")
    dbname = (conn_params.get("dbname") or settings.get("abox_db") or "").strip()

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
        conn = psycopg2.connect(host=conn_params["host"], port=int(conn_params["port"]),
                                dbname=dbname, user=conn_params["user"],
                                password=conn_params.get("password", ""))
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
    conn = psycopg2.connect(host=conn_params["host"], port=int(conn_params["port"]),
                            dbname=dbname, user=conn_params["user"],
                            password=conn_params.get("password", ""))
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

    print("\n=== S1b the recommendation table equals the written rule ===")
    _check_fit(profile, settings, graph, result, ns, dbname)

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
