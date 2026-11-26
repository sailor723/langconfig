#!/usr/bin/env python3
"""The graph a page shows must be the entailments the reasoner produced — not a look-alike.

`project_graph.py` writes the Neo4j graph from HermiT's answer, and any graph view reads that. Between
those two facts sits the failure this gate exists for, and it is the same one `check_abox_sync.py`
guards against next door: the graph can be **stale** (nobody re-ran the projection after a CV changed),
**hand-edited** (someone dragged a candidate into a role), or **written by a query that re-implements the
definition "equivalently"** and drifts one clause later. A graph that is wrong in any of those ways looks
exactly like a good day's shortlist — and Neo4j has no gate of its own, so nothing else would notice.

So this gate re-runs the reasoner over the profile's current ABox and demands the graph be IDENTICAL:

    G1  every node the ABox asserts exists, with the same properties (277 candidates / 53 skills / role set)
    G2  HAS_SKILL / APPLIED_FOR edges equal the ABox's assertions — both directions
    G3  MATCHES edges equal the reasoned set, per role: nothing missing, nothing stale
    G4  every MATCHES property (fitScore / rankInRole / matchedSkills / requiredSkills) equals what
        `fit.py` derives — a rank edited by hand to put a favourite first would otherwise look normal
    G5  REQUIRES edges exist only for roles that have a JD (`hasJd: true`), and equal the role's
        `:requiresSkill` assertions
    G6  no duplicate scan is ranked (7 duplicate CVs would otherwise push real people down)
    G7  the ontology is still consistent

WHY A SEPARATE GATE AND NOT A FLAG ON `check_abox_sync`: that gate reads Postgres. The point of moving a
projection to another store is that nobody has to trust the move — so the two gates must be able to run
independently. When Postgres goes away, this one is the only thing left standing between the reasoner and
the picture.

Usage:
    python features/ontology/gates/check_graph_sync.py --profile features/ontology/profiles/talent_v1/talent_v1_settings.json
    ... --as-json

Connection: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE (defaults bolt://localhost:7687, neo4j).

Exit: 0 all checks pass, 1 a check failed, 2 not run (missing profile / no ABox / reasoner or driver
unavailable / cannot reach the database).
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
FAILS = 0


def check_true(label: str, cond: bool, detail: str = "") -> None:
    global OK, CHECKS, FAILS
    CHECKS += 1
    good = bool(cond)
    OK = OK and good
    FAILS += 0 if good else 1
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + ("" if good else f" — {detail}"))


def not_run(label: str, why: str) -> None:
    print(f"  [NOT RUN] {label} — {why}")


def _role_name(name: str) -> str:
    """`role_副总助理` and `副总助理` are the same role.

    Stripping the prefix on one side only is the exact bug this codebase has now made twice: the first
    version of `check_abox_sync` compared 204 real rows against an empty expectation, and the first
    version of `project_graph.py` invented 12 phantom `hasJd:false` roles beside the 10 real ones.
    """
    return name[len("role_"):] if name.startswith("role_") else name


# ─────────────────────────────────────────────────────────── expectations from RDF
def expected(profile: pathlib.Path, settings: dict, ns: str):
    """Everything the graph must contain, derived from the ABox + HermiT + the shared score."""
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF

    from features.ontology.reasoning import reasoner as R
    from scripts.talent.fit import score as fit_score

    base = profile.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    spec = json.loads((base / (settings.get("reasoning_spec") or "reasoning.json"))
                      .read_text(encoding="utf-8"))

    graph = R.load_graph([axioms, abox])
    classes = sorted({ns + item["class"] for item in
                      (spec.get("inferred") or []) + (spec.get("excluded") or [])})
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=classes)

    def _local(node) -> str:
        return str(node).rsplit("#", 1)[-1]

    def _int(node, prop):
        for value in graph.objects(node, URIRef(prop)):
            if isinstance(value, Literal):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _str(node, prop):
        for value in graph.objects(node, URIRef(prop)):
            return str(value) if isinstance(value, Literal) else _local(value)
        return None

    category_of: dict[str, str | None] = {}
    for node in graph.subjects(RDF.type, URIRef(ns + "SkillTag")):
        types = [_local(t) for t in graph.objects(node, RDF.type)]
        category_of[_local(node)] = next(
            (t for t in types if t not in ("SkillTag", "NamedIndividual")), None)

    candidates: dict[str, dict] = {}
    for node in graph.subjects(RDF.type, URIRef(ns + "Candidate")):
        cid = _local(node)
        missing = {_local(o) for o in graph.objects(node, URIRef(ns + "missingData"))}
        candidates[cid] = {
            "id": cid,
            "appliedRole": _role_name(_str(node, ns + "appliedFor")) if _str(node, ns + "appliedFor") else None,
            "years": _int(node, ns + "yearsExperience"),
            "educationRank": _int(node, ns + "educationRank"),
            "age": _int(node, ns + "age"),
            "salaryMinK": _int(node, ns + "salaryMinK"),
            "salaryMaxK": _int(node, ns + "salaryMaxK"),
            "sourceFile": _str(node, ns + "sourceFile"),
            "duplicateOf": _role_name(_str(node, "http://www.w3.org/2002/07/owl#sameAs"))
            if _str(node, "http://www.w3.org/2002/07/owl#sameAs") else None,
            "missingYears": "UnknownYears" in missing,
            "missingEducation": "UnknownEducation" in missing,
            "missingSkills": "UnknownSkills" in missing,
            "skills": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "hasSkill"))),
        }

    roles: dict[str, dict] = {}
    for node in graph.subjects(RDF.type, URIRef(ns + "Role")):
        name = _role_name(_local(node))
        roles[name] = {
            "name": name,
            "hasJd": True,
            "requiredYears": _int(node, ns + "requiredYears"),
            "requiredEducationRank": _int(node, ns + "requiredEducationRank"),
            "notStated": _str(node, ns + "notStated"),
            "requires": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "requiresSkill"))),
        }
    # a role someone applied to but no JD describes is still a Role node — `hasJd: false`
    for cand in candidates.values():
        name = cand["appliedRole"]
        if name and name not in roles:
            roles[name] = {"name": name, "hasJd": False, "requiredYears": None,
                           "requiredEducationRank": None, "notStated": None, "requires": []}

    matches: dict[tuple[str, str], dict] = {}
    for iri in classes:
        local = _local(iri)
        role_name = local[len("matches_"):] if local.startswith("matches_") else local
        role = roles.get(role_name)
        if role is None or not role["hasJd"]:
            continue
        required = {category_of.get(s) for s in role["requires"]} - {None}
        for member in result.members_of(iri):
            cid = _local(member)
            cand = candidates.get(cid)
            if cand is None or cand["duplicateOf"]:
                continue
            held = {category_of.get(s) for s in cand["skills"]} - {None}
            matched = len(held & required)
            matches[(cid, role_name)] = {
                "candidate": cid, "role": role_name,
                "fitScore": fit_score(matched_skills=matched, required_skills=len(required),
                                      years=cand["years"],
                                      required_years=role["requiredYears"],
                                      education_rank=cand["educationRank"],
                                      required_education_rank=role["requiredEducationRank"]),
                "matchedSkills": matched, "requiredSkills": len(required),
            }

    ordered = sorted(matches.values(), key=lambda m: (m["role"], -m["fitScore"], m["candidate"]))
    seen: dict[str, int] = {}
    for row in ordered:
        seen[row["role"]] = seen.get(row["role"], 0) + 1
        row["rankInRole"] = seen[row["role"]]

    return {"candidates": candidates, "roles": roles, "matches": matches,
            "result": result, "category_of": category_of}


# ─────────────────────────────────────────────────────────── read the graph back
def actual(driver, database: str) -> dict:
    with driver.session(database=database) as session:
        candidates = {row["id"]: row for row in session.run("""
            MATCH (c:Candidate)
            RETURN c.id AS id, c.appliedRole AS appliedRole, c.years AS years,
                   c.educationRank AS educationRank, c.age AS age,
                   c.salaryMinK AS salaryMinK, c.salaryMaxK AS salaryMaxK,
                   c.sourceFile AS sourceFile, c.duplicateOf AS duplicateOf,
                   c.missingYears AS missingYears, c.missingEducation AS missingEducation,
                   c.missingSkills AS missingSkills
        """).data()}

        skills = {row["name"]: row for row in session.run(
            "MATCH (s:Skill) RETURN s.name AS name, s.category AS category").data()}

        roles = {row["name"]: row for row in session.run("""
            MATCH (r:Role)
            RETURN r.name AS name, r.hasJd AS hasJd, r.requiredYears AS requiredYears,
                   r.requiredEducationRank AS requiredEducationRank, r.notStated AS notStated
        """).data()}

        has_skill = {(row["c"], row["s"]) for row in session.run(
            "MATCH (c:Candidate)-[:HAS_SKILL]->(s:Skill) RETURN c.id AS c, s.name AS s").data()}

        applied = {(row["c"], row["r"]) for row in session.run(
            "MATCH (c:Candidate)-[:APPLIED_FOR]->(r:Role) RETURN c.id AS c, r.name AS r").data()}

        requires = {(row["r"], row["s"]) for row in session.run(
            "MATCH (r:Role)-[:REQUIRES]->(s:Skill) RETURN r.name AS r, s.name AS s").data()}

        matches = {(row["c"], row["r"]): row for row in session.run("""
            MATCH (c:Candidate)-[m:MATCHES]->(r:Role)
            RETURN c.id AS c, r.name AS r, m.fitScore AS fitScore, m.rankInRole AS rankInRole,
                   m.matchedSkills AS matchedSkills, m.requiredSkills AS requiredSkills
        """).data()}

    for row in matches.values():
        row["candidate"], row["role"] = row["c"], row["r"]

    return {"candidates": candidates, "skills": skills, "roles": roles,
            "has_skill": has_skill, "applied": applied, "requires": requires, "matches": matches}


# ─────────────────────────────────────────────────────────── the checks
def run_checks(want: dict, got: dict) -> None:
    print("\n=== G1 nodes: the graph holds what the ABox asserts ===")
    for label, wanted, found in (
        ("Candidate", want["candidates"], got["candidates"]),
        ("Skill", want["category_of"], got["skills"]),
        ("Role", want["roles"], got["roles"]),
    ):
        missing = set(wanted) - set(found)
        extra = set(found) - set(wanted)
        check_true(f"{label}: {len(wanted)} asserted, none missing",
                   not missing, f"missing {sorted(missing)[:5]}")
        check_true(f"{label}: no {label} the ABox does not assert",
                   not extra, f"extra {sorted(extra)[:5]}")

    wrong_cat = sorted(name for name, cat in want["category_of"].items()
                       if name in got["skills"] and got["skills"][name]["category"] != cat)
    check_true("every Skill carries the category the TBox reasons over",
               not wrong_cat, f"{len(wrong_cat)} wrong, e.g. {wrong_cat[:3]}")

    wrong_prop = []
    for cid, exp in want["candidates"].items():
        row = got["candidates"].get(cid)
        if row is None:
            continue
        for key in ("appliedRole", "years", "educationRank", "age", "salaryMinK",
                    "salaryMaxK", "sourceFile", "duplicateOf",
                    "missingYears", "missingEducation", "missingSkills"):
            if row.get(key) != exp.get(key):
                wrong_prop.append((cid, key, exp.get(key), row.get(key)))
    check_true("every Candidate property equals the ABox value (missing is not zero)",
               not wrong_prop, f"{len(wrong_prop)} differ, e.g. {wrong_prop[:2]}")

    print("\n=== G2 edges: HAS_SKILL / APPLIED_FOR are the ABox's assertions ===")
    want_hs = {(cid, skill) for cid, cand in want["candidates"].items() for skill in cand["skills"]}
    check_true(f"HAS_SKILL holds exactly the {len(want_hs)} asserted pair(s)",
               got["has_skill"] == want_hs,
               f"missing {len(want_hs - got['has_skill'])}, extra {len(got['has_skill'] - want_hs)}")

    want_af = {(cid, cand["appliedRole"]) for cid, cand in want["candidates"].items()
               if cand["appliedRole"]}
    check_true(f"APPLIED_FOR holds exactly the {len(want_af)} asserted pair(s)",
               got["applied"] == want_af,
               f"missing {len(want_af - got['applied'])}, extra {len(got['applied'] - want_af)}")

    print("\n=== G3 MATCHES: the reasoned set, nothing missing and nothing stale ===")
    want_m = set(want["matches"])
    got_m = set(got["matches"])
    check_true(f"MATCHES holds exactly the {len(want_m)} entailed pair(s)",
               got_m == want_m,
               f"missing {len(want_m - got_m)}, stale {len(got_m - want_m)}"
               + (f", e.g. stale {sorted(got_m - want_m)[:2]}" if got_m - want_m else ""))

    print("\n=== G6 no duplicate scan is ranked ===")
    dupes = {cid for cid, cand in want["candidates"].items() if cand["duplicateOf"]}
    ranked_dupes = sorted(cid for cid, _ in got_m if cid in dupes)
    check_true(f"no duplicate scan is ranked ({len(dupes)} duplicate CV(s) in the ABox)",
               not ranked_dupes, f"{len(ranked_dupes)} ranked, e.g. {ranked_dupes[:3]}")

    print("\n=== G4 MATCHES properties: the score and rank the written rule derives ===")
    wrong_score, wrong_rank, wrong_detail = [], [], []
    for key, exp in want["matches"].items():
        row = got["matches"].get(key)
        if row is None:
            continue
        if row.get("fitScore") != exp["fitScore"]:
            wrong_score.append((key, exp["fitScore"], row.get("fitScore")))
        if row.get("rankInRole") != exp["rankInRole"]:
            wrong_rank.append((key, exp["rankInRole"], row.get("rankInRole")))
        if (row.get("matchedSkills"), row.get("requiredSkills")) != (exp["matchedSkills"],
                                                                    exp["requiredSkills"]):
            wrong_detail.append((key, (exp["matchedSkills"], exp["requiredSkills"]),
                                 (row.get("matchedSkills"), row.get("requiredSkills"))))
    check_true("every fitScore matches the written weights", not wrong_score, f"e.g. {wrong_score[:2]}")
    check_true("every rankInRole matches the documented tie-break", not wrong_rank, f"e.g. {wrong_rank[:2]}")
    check_true("every matched/required skill count matches the ABox", not wrong_detail,
               f"e.g. {wrong_detail[:2]}")

    print("\n=== G5 REQUIRES: only roles with a JD, equal to :requiresSkill ===")
    want_r = {(role["name"], skill) for role in want["roles"].values()
              if role["hasJd"] for skill in role["requires"]}
    check_true(f"REQUIRES holds exactly the {len(want_r)} asserted pair(s)",
               got["requires"] == want_r,
               f"missing {len(want_r - got['requires'])}, extra {len(got['requires'] - want_r)}")

    jdless = {name for name, role in want["roles"].items() if not role["hasJd"]}
    leaking = sorted(name for name, _ in got["requires"] if name in jdless)
    check_true(f"no REQUIRES edge leaves a role without a JD ({len(jdless)} such role(s))",
               not leaking, f"{leaking[:3]}")

    wrong_flag = sorted(name for name, role in want["roles"].items()
                        if name in got["roles"] and bool(got["roles"][name].get("hasJd")) != role["hasJd"])
    check_true("every Role's hasJd flag equals whether the ABox declares a :Role individual",
               not wrong_flag, f"{wrong_flag[:3]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--as-json", action="store_true")
    ap.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""))
    ap.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    if not profile.is_file():
        print(f"NOT RUN — no profile at {profile}")
        return 2
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = profile.parent

    print(f"profile: {profile}")
    print(f"graph:   {args.uri} / {args.database}")

    if not ((base / (settings.get("abox") or "abox.ttl")).is_file()
            and (base / (settings.get("reasoning") or "reasoning.ttl")).is_file()
            and (base / (settings.get("reasoning_spec") or "reasoning.json")).is_file()):
        print("\nNOT RUN — this profile declares no ABox (need abox.ttl + reasoning.ttl + reasoning.json)")
        return 2

    from features.ontology.reasoning import reasoner as R

    usable, why = R.available()
    if not usable:
        print(f"\nNOT RUN — the reasoner is unavailable: {why}")
        return 2

    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        print(f"\nNOT RUN — the neo4j driver is unavailable: {exc}")
        return 2

    try:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
        driver.verify_connectivity()
    except Exception as exc:
        print(f"\nNOT RUN — cannot reach the graph at {args.uri}: {exc}")
        return 2

    try:
        want = expected(profile, settings, ns)
        print(f"\nreasoner: {want['result'].engine} · {want['result'].elapsed_ms:.0f} ms"
              f" · consistent={want['result'].consistent}")
        if not want["result"].consistent:
            print("\nREFUSING — an inconsistent ontology cannot be projected or checked")
            return 1
        got = actual(driver, args.database)
        print(f"expected: {len(want['candidates'])} candidates · {len(want['category_of'])} skills · "
              f"{len(want['roles'])} roles · {len(want['matches'])} reasoned match(es)")
        print(f"in graph: {len(got['candidates'])} candidates · {len(got['skills'])} skills · "
              f"{len(got['roles'])} roles · {len(got['matches'])} MATCHES edge(s)")
        run_checks(want, got)
        print("\n=== G7 the ontology is still consistent ===")
        check_true("the reasoner accepted the ontology", want["result"].consistent)
    finally:
        driver.close()

    print(f"\n{CHECKS} checks · {FAILS} failed · {'green' if OK else 'RED'}")
    if args.as_json:
        print(json.dumps({"ok": OK, "checks": CHECKS}, ensure_ascii=False))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
