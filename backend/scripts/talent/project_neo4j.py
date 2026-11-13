#!/usr/bin/env python3
"""Project the reasoned ABox into Neo4j — a READ-ONLY graph, never the source of truth.

Neo4j cannot be the reasoner: Cypher has no OWL semantics, so `:matches_<role> ≡ :Candidate ⊓
(:hasSkill some :skillsFor_<role>) ⊓ (years ≥ 2)` has no meaning there (measured alternative: owlrl, the
pure-Python OWL 2 RL chainer, turns every threshold class into the empty set; HermiT is the only engine
here that decides a facet). What Neo4j is genuinely good at is TRAVERSAL:

    * who else looks like this candidate (shared skills, N hops)
    * which required skills never co-occur in the pool
    * the path that explains a recommendation (candidate → skill → role → requirement)

So the graph is a projection of two things that already exist and are already gated:
`abox.ttl` (asserted facts) and the reasoner's answer (the `MATCHES` edges). `check_graph_sync.py`
re-derives both and demands the graph be identical, which is what keeps a pretty picture honest.

Node/edge model (deliberately small):

    (:Candidate {id, appliedRole, years, educationRank, missingYears|missingEducation|missingSkills,
                 salaryMinK, salaryMaxK, age, sourceFile, duplicateOf})
    (:Skill {name, category})
    (:Role {name, requiredYears, requiredEducationRank, notStated})
    (:ReasoningRun {runAt, engine, elapsedMs, candidates, matches, consistent})

    (:Candidate)-[:HAS_SKILL]->(:Skill)
    (:Candidate)-[:APPLIED_FOR]->(:Role)
    (:Role)-[:REQUIRES]->(:Skill)
    (:Candidate)-[:MATCHES {fitScore, rankInRole, matchedSkills, requiredSkills}]->(:Role)   ← entailed

Idempotent: nodes are MERGEd by id, the `MATCHES`/`HAS_SKILL`/`APPLIED_FOR` edges of a role are replaced
in one transaction, and stale `MATCHES` edges (a member the reasoner no longer entails) are deleted —
otherwise an old entitlement would survive forever and look like a recommendation.

Connection: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (defaults bolt://127.0.0.1:7687, neo4j).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from rdflib import Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402
from scripts.talent.fit import score as fit_score  # noqa: E402

OWL_SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"


def _local(node) -> str:
    return str(node).rsplit("#", 1)[-1]


def _int_of(graph, node, prop: str) -> int | None:
    for value in graph.objects(node, URIRef(prop)):
        if isinstance(value, Literal):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _text_of(graph, node, prop: str) -> str | None:
    for value in graph.objects(node, URIRef(prop)):
        return str(value)
    return None


def build_rows(graph, ns: str) -> dict:
    """Everything the graph needs, read out of the ABox (no reasoning here — that is `reason`)."""
    candidates, skills, roles = [], [], []
    for node in graph.subjects(RDF.type, URIRef(ns + "Candidate")):
        missing = {_local(o) for o in graph.objects(node, URIRef(ns + "missingData"))}
        candidates.append({
            "id": _local(node),
            "appliedRole": _local(_text_of(graph, node, ns + "appliedFor") or "") or None,
            "years": _int_of(graph, node, ns + "yearsExperience"),
            "educationRank": _int_of(graph, node, ns + "educationRank"),
            "salaryMinK": _int_of(graph, node, ns + "salaryMinK"),
            "salaryMaxK": _int_of(graph, node, ns + "salaryMaxK"),
            "age": _int_of(graph, node, ns + "age"),
            "sourceFile": _text_of(graph, node, ns + "sourceFile"),
            "duplicateOf": _local(_text_of(graph, node, OWL_SAME_AS) or "") or None,
            "missingYears": "UnknownYears" in missing,
            "missingEducation": "UnknownEducation" in missing,
            "missingSkills": "UnknownSkills" in missing,
            "skills": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "hasSkill"))),
        })
    for node in graph.subjects(RDF.type, URIRef(ns + "SkillTag")):
        types = [_local(t) for t in graph.objects(node, RDF.type)]
        category = next((t for t in types if t not in ("SkillTag", "NamedIndividual")), None)
        skills.append({"name": _local(node), "category": category})
    for node in graph.subjects(RDF.type, URIRef(ns + "Role")):
        name = _local(node)
        if name.startswith("role_"):
            name = name[len("role_"):]
        roles.append({
            "name": name,
            "requiredYears": _int_of(graph, node, ns + "requiredYears"),
            "requiredEducationRank": _int_of(graph, node, ns + "requiredEducationRank"),
            "notStated": _text_of(graph, node, ns + "notStated"),
            "requires": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "requiresSkill"))),
        })
    return {"candidates": candidates, "skills": skills, "roles": roles}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--dry-run", action="store_true", help="reason and print, write nothing")
    ap.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    ap.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""))
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = profile.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    spec_path = (base / (settings.get("reasoning_spec") or "reasoning.json")).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    graph = R.load_graph([axioms, abox])
    classes = sorted({ns + item["class"] for item in
                      (spec.get("inferred") or []) + (spec.get("excluded") or [])})
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=classes)
    if not result.consistent:
        print("REFUSING to project an inconsistent ontology: " + "; ".join(result.notes))
        return 2

    rows = build_rows(graph, ns)
    role_by_name = {r["name"]: r for r in rows["roles"]}
    skill_category = {s["name"]: s["category"] for s in rows["skills"]}
    candidate_by_id = {c["id"]: c for c in rows["candidates"]}

    matches = []
    for iri in classes:
        cls_local = _local(iri)
        role_name = cls_local[len("matches_"):] if cls_local.startswith("matches_") else cls_local
        requirement = role_by_name.get(role_name)
        if not requirement:
            continue
        required_cats = {skill_category.get(s) for s in requirement["requires"]} - {None}
        for member in result.members_of(iri):
            cid = _local(member)
            cand = candidate_by_id.get(cid)
            if cand is None or cand["duplicateOf"]:
                continue
            held = {skill_category.get(s) for s in cand["skills"]} - {None}
            matched = len(held & required_cats)
            matches.append({
                "candidate": cid, "role": role_name,
                "fitScore": fit_score(matched_skills=matched, required_skills=len(required_cats),
                                      years=cand["years"],
                                      required_years=requirement["requiredYears"],
                                      education_rank=cand["educationRank"],
                                      required_education_rank=requirement["requiredEducationRank"]),
                "matchedSkills": matched, "requiredSkills": len(required_cats),
            })
    matches.sort(key=lambda m: (m["role"], -m["fitScore"], m["candidate"]))
    seen: dict[str, int] = {}
    for row in matches:
        seen[row["role"]] = seen.get(row["role"], 0) + 1
        row["rankInRole"] = seen[row["role"]]

    print(f"reasoner {result.engine} · {result.elapsed_ms:.0f} ms · consistent={result.consistent}")
    print(f"  candidates {len(rows['candidates'])} · skills {len(rows['skills'])} · "
          f"roles {len(rows['roles'])} · matches {len(matches)}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if not args.password:
        print("no NEO4J_PASSWORD — refusing to write (set it from /root/.neo4j_initial_pw)")
        return 2

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        with driver.session() as session:
            session.run(
                "CREATE CONSTRAINT candidate_id IF NOT EXISTS FOR (c:Candidate) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE")
            session.run("CREATE CONSTRAINT role_name IF NOT EXISTS FOR (r:Role) REQUIRE r.name IS UNIQUE")

            session.run("""
                UNWIND $rows AS row
                MERGE (c:Candidate {id: row.id})
                SET c.appliedRole = row.appliedRole, c.years = row.years,
                    c.educationRank = row.educationRank, c.salaryMinK = row.salaryMinK,
                    c.salaryMaxK = row.salaryMaxK, c.age = row.age, c.sourceFile = row.sourceFile,
                    c.duplicateOf = row.duplicateOf, c.missingYears = row.missingYears,
                    c.missingEducation = row.missingEducation, c.missingSkills = row.missingSkills
            """, rows=rows["candidates"])
            session.run("""
                UNWIND $rows AS row
                MERGE (s:Skill {name: row.name}) SET s.category = row.category
            """, rows=rows["skills"])
            session.run("""
                UNWIND $rows AS row
                MERGE (r:Role {name: row.name})
                SET r.requiredYears = row.requiredYears,
                    r.requiredEducationRank = row.requiredEducationRank,
                    r.notStated = row.notStated
            """, rows=rows["roles"])

            # edges are replaced as a set per run: an edge that is no longer asserted must disappear,
            # or the graph keeps a fact the ABox no longer says (and the sync gate would be right to fail)
            session.run("MATCH (:Candidate)-[e:HAS_SKILL]->(:Skill) DELETE e")
            session.run("MATCH (:Candidate)-[e:APPLIED_FOR]->(:Role) DELETE e")
            session.run("MATCH (:Role)-[e:REQUIRES]->(:Skill) DELETE e")
            session.run("MATCH (:Candidate)-[e:MATCHES]->(:Role) DELETE e")

            per_candidate = [{"id": c["id"], "skills": c["skills"],
                              "appliedRole": (c["appliedRole"] or "").removeprefix("role_") or None}
                             for c in rows["candidates"]]
            session.run("""
                UNWIND $rows AS row
                MATCH (c:Candidate {id: row.id})
                UNWIND row.skills AS skill
                MATCH (s:Skill {name: skill})
                MERGE (c)-[:HAS_SKILL]->(s)
            """, rows=per_candidate)
            session.run("""
                UNWIND $rows AS row
                WITH row WHERE row.appliedRole IS NOT NULL
                MATCH (c:Candidate {id: row.id}), (r:Role {name: row.appliedRole})
                MERGE (c)-[:APPLIED_FOR]->(r)
            """, rows=per_candidate)
            session.run("""
                UNWIND $rows AS row
                MATCH (r:Role {name: row.name})
                UNWIND row.requires AS skill
                MATCH (s:Skill {name: skill})
                MERGE (r)-[:REQUIRES]->(s)
            """, rows=rows["roles"])
            session.run("""
                UNWIND $rows AS row
                MATCH (c:Candidate {id: row.candidate}), (r:Role {name: row.role})
                MERGE (c)-[m:MATCHES]->(r)
                SET m.fitScore = row.fitScore, m.rankInRole = row.rankInRole,
                    m.matchedSkills = row.matchedSkills, m.requiredSkills = row.requiredSkills
            """, rows=matches)

            counts = session.run("""
                OPTIONAL MATCH (c:Candidate) WITH count(c) AS candidates
                OPTIONAL MATCH (s:Skill) WITH candidates, count(s) AS skills
                OPTIONAL MATCH (r:Role) WITH candidates, skills, count(r) AS roles
                OPTIONAL MATCH ()-[m:MATCHES]->() WITH candidates, skills, roles, count(m) AS matches
                OPTIONAL MATCH ()-[h:HAS_SKILL]->() WITH candidates, skills, roles, matches,
                                                              count(h) AS hasSkill
                RETURN candidates, skills, roles, matches, hasSkill
            """).single()
            session.run("""
                MATCH (rr:ReasoningRun) DELETE rr
            """)
            session.run("""
                CREATE (:ReasoningRun {runAt: datetime(), engine: $engine, elapsedMs: $elapsed,
                                       candidates: $candidates, matches: $matches,
                                       consistent: $consistent})
            """, engine=result.engine, elapsed=round(result.elapsed_ms, 1),
                candidates=counts["candidates"], matches=counts["matches"],
                consistent=result.consistent)
    finally:
        driver.close()

    print(f"neo4j: Candidate {counts['candidates']} · Skill {counts['skills']} · "
          f"Role {counts['roles']} · MATCHES {counts['matches']} · HAS_SKILL {counts['hasSkill']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
