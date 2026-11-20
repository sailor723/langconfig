#!/usr/bin/env python3
"""graph1 — project the reasoned talent ABox into Neo4j. The smallest graph that answers something.

WHAT THIS IS, AND WHAT IT IS NOT.

Neo4j is not a reasoner: Cypher has no OWL semantics, so `:matches_副总助理 ≡ :Candidate ⊓
(:hasSkill some :skillsFor_副总助理)` means nothing there. Every edge this script writes is therefore a
PROJECTION of two things that already exist and are already gated — `abox.ttl` (asserted facts) and
HermiT's answer (the MATCHES edges). Nothing is computed here that the reasoner did not decide; the only
arithmetic is the fit score, which comes from `fit.py` so the graph and the table cannot disagree.

    (:Candidate {id, appliedRole, years, educationRank, age, salaryMinK, salaryMaxK,
                 sourceFile, duplicateOf, missingYears, missingEducation, missingSkills})
    (:Skill     {name, category})
    (:Role      {name, hasJd, requiredYears, requiredEducationRank, notStated})

    (:Candidate)-[:HAS_SKILL]->(:Skill)
    (:Candidate)-[:APPLIED_FOR]->(:Role)
    (:Role)-[:REQUIRES]->(:Skill)                       only when the role has a JD
    (:Candidate)-[:MATCHES {fitScore, matchedSkills, requiredSkills, rankInRole}]->(:Role)   entailed

Three deliberate choices, each because the alternative looks right and is wrong:

  1. **Replaced as a SET per run, not merged.** A candidate HermiT no longer entails must lose the
     MATCHES edge, or the picture keeps a recommendation nobody can reproduce. So the talent subgraph is
     deleted and rewritten in one transaction rather than diffed.
  2. **`hasJd: false` roles are created.** 54 applicants filed themselves under jobs no JD describes
     (行政专员 28 · 技术经理主管 14 · 设计工程师 10 · 实验室技术员 2). A dangling reference hides that;
     a node with `hasJd:false` and no REQUIRES edge makes it one query.
  3. **Duplicates are excluded from MATCHES.** Measured: 7 duplicate scans account for 21 (candidate, role)
     entailments. Ranking both would push a real person down for every extra copy of their file — the same
     reason `materialize.py` excludes them from `candidate_role_fit`.

Usage:
    python -m scripts.talent.project_graph --profile features/ontology/profiles/talent_v1/talent_v1_settings.json
    python -m scripts.talent.project_graph --profile ... --dry-run      # reason + report, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))

from rdflib import Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402
from scripts.talent.fit import score as fit_score  # noqa: E402

OWL_SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"
NOT_A_CATEGORY = {"SkillTag", "NamedIndividual", "NamedEntity"}

WIPE = """
MATCH (n) WHERE n:Candidate OR n:Skill OR n:Role DETACH DELETE n
"""

INDEXES = [
    "CREATE INDEX candidate_id IF NOT EXISTS FOR (c:Candidate) ON (c.id)",
    "CREATE INDEX skill_name   IF NOT EXISTS FOR (s:Skill) ON (s.name)",
    "CREATE INDEX role_name    IF NOT EXISTS FOR (r:Role) ON (r.name)",
]

WRITE_CANDIDATES = """
UNWIND $rows AS r
MERGE (c:Candidate {id: r.id})
SET c = r
"""

WRITE_SKILLS = """
UNWIND $rows AS r
MERGE (s:Skill {name: r.name})
SET s.category = r.category
"""

WRITE_ROLES = """
UNWIND $rows AS r
MERGE (n:Role {name: r.name})
SET n.hasJd = r.hasJd,
    n.requiredYears = r.requiredYears,
    n.requiredEducationRank = r.requiredEducationRank,
    n.notStated = r.notStated
"""

WRITE_HAS_SKILL = """
UNWIND $rows AS r
MATCH (c:Candidate {id: r.c}), (s:Skill {name: r.s})
MERGE (c)-[:HAS_SKILL]->(s)
"""

WRITE_APPLIED_FOR = """
UNWIND $rows AS r
MATCH (c:Candidate {id: r.c}), (n:Role {name: r.r})
MERGE (c)-[:APPLIED_FOR]->(n)
"""

WRITE_REQUIRES = """
UNWIND $rows AS r
MATCH (n:Role {name: r.r}), (s:Skill {name: r.s})
MERGE (n)-[:REQUIRES]->(s)
"""

WRITE_MATCHES = """
UNWIND $rows AS r
MATCH (c:Candidate {id: r.c}), (n:Role {name: r.r})
MERGE (c)-[m:MATCHES]->(n)
SET m.fitScore = r.fitScore, m.matchedSkills = r.matchedSkills,
    m.requiredSkills = r.requiredSkills, m.rankInRole = r.rankInRole
"""


# ────────────────────────────────────────────────────────── read the ABox
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


def _first(graph, node, prop: str) -> str | None:
    for value in graph.objects(node, URIRef(prop)):
        return _local(value) if not isinstance(value, Literal) else str(value)
    return None


def _role_name(iri_or_name: str | None) -> str | None:
    """`role_副总助理` and `副总助理` are the same role. Stripping on ONE side only made every
    declared role look undeclared and invented a duplicate `role_副总助理` node beside it —
    seen as `roles 22(有JD 10)` with all 22 printed as orphans."""
    if not iri_or_name:
        return None
    return iri_or_name[len("role_"):] if iri_or_name.startswith("role_") else iri_or_name


def read_abox(graph, ns: str) -> dict:
    """Everything the graph needs, straight out of the ABox. No reasoning in here."""
    candidates = []
    for node in graph.subjects(RDF.type, URIRef(ns + "Candidate")):
        missing = {_local(o) for o in graph.objects(node, URIRef(ns + "missingData"))}
        candidates.append({
            "id": _local(node),
            "appliedRole": _role_name(_first(graph, node, ns + "appliedFor")),
            "years": _int_of(graph, node, ns + "yearsExperience"),
            "educationRank": _int_of(graph, node, ns + "educationRank"),
            "age": _int_of(graph, node, ns + "age"),
            "salaryMinK": _int_of(graph, node, ns + "salaryMinK"),
            "salaryMaxK": _int_of(graph, node, ns + "salaryMaxK"),
            "sourceFile": _first(graph, node, ns + "sourceFile"),
            "duplicateOf": _first(graph, node, OWL_SAME_AS),
            "missingYears": "UnknownYears" in missing,
            "missingEducation": "UnknownEducation" in missing,
            "missingSkills": "UnknownSkills" in missing,
            "skills": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "hasSkill"))),
        })

    skills = []
    for node in graph.subjects(RDF.type, URIRef(ns + "SkillTag")):
        types = [_local(t) for t in graph.objects(node, RDF.type)]
        skills.append({
            "name": _local(node),
            "category": next((t for t in types if t not in NOT_A_CATEGORY), None),
        })

    roles = []
    for node in graph.subjects(RDF.type, URIRef(ns + "Role")):
        roles.append({
            "name": _role_name(_local(node)),
            "hasJd": True,
            "requiredYears": _int_of(graph, node, ns + "requiredYears"),
            "requiredEducationRank": _int_of(graph, node, ns + "requiredEducationRank"),
            "notStated": _first(graph, node, ns + "notStated"),
            "requires": sorted(_local(o) for o in graph.objects(node, URIRef(ns + "requiresSkill"))),
        })

    return {"candidates": candidates, "skills": skills, "roles": roles}


def plan_roles(rows: dict) -> list[dict]:
    """Union of roles with a JD and roles people applied to. The difference is `hasJd: false`."""
    declared = {r["name"]: r for r in rows["roles"]}
    out = dict(declared)
    for cand in rows["candidates"]:
        name = cand["appliedRole"]
        if name and name not in out:
            out[name] = {"name": name, "hasJd": False, "requiredYears": None,
                         "requiredEducationRank": None, "notStated": None, "requires": []}
    return sorted(out.values(), key=lambda r: (not r["hasJd"], r["name"]))


# ────────────────────────────────────────────────────────── entail + score
def entail(graph, ns: str, spec: dict) -> tuple[list[dict], object]:
    """Run HermiT, then turn its answer into MATCHES rows with the same score `fit.py` gives the table."""
    classes = sorted({ns + item["class"] for item in
                      (spec.get("inferred") or []) + (spec.get("excluded") or [])})
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=classes)
    return classes, result


def build_matches(graph, ns: str, classes, result, rows: dict) -> list[dict]:
    role_by_name = {r["name"]: r for r in rows["roles"]}
    skill_category = {s["name"]: s["category"] for s in rows["skills"]}
    candidate_by_id = {c["id"]: c for c in rows["candidates"]}

    matches: list[dict] = []
    for iri in classes:
        local = _local(iri)
        role_name = local[len("matches_"):] if local.startswith("matches_") else local
        role = role_by_name.get(role_name)
        if role is None:
            continue
        required = {skill_category.get(s) for s in role["requires"]} - {None}
        for member in result.members_of(iri):
            cid = _local(member)
            cand = candidate_by_id.get(cid)
            if cand is None or cand["duplicateOf"]:
                continue
            held = {skill_category.get(s) for s in cand["skills"]} - {None}
            matched = len(held & required)
            matches.append({
                "c": cid, "r": role_name,
                "fitScore": fit_score(matched_skills=matched, required_skills=len(required),
                                      years=cand["years"],
                                      required_years=role["requiredYears"],
                                      education_rank=cand["educationRank"],
                                      required_education_rank=role["requiredEducationRank"]),
                "matchedSkills": matched, "requiredSkills": len(required),
            })

    matches.sort(key=lambda m: (m["r"], -m["fitScore"], m["c"]))
    seen: dict[str, int] = {}
    for row in matches:
        seen[row["r"]] = seen.get(row["r"], 0) + 1
        row["rankInRole"] = seen[row["r"]]
    return matches


# ────────────────────────────────────────────────────────── write
def write(driver, database: str, rows: dict, matches: list[dict]) -> dict:
    """Delete the talent subgraph, then rewrite it. One transaction — a half-written graph lies."""
    roles = plan_roles(rows)
    skill_rows = [{"name": s["name"], "category": s["category"]} for s in rows["skills"]]
    cand_rows = [{k: v for k, v in c.items() if k != "skills"} for c in rows["candidates"]]

    has_skill = [{"c": c["id"], "s": s} for c in rows["candidates"] for s in c["skills"]]
    applied = [{"c": c["id"], "r": c["appliedRole"]} for c in rows["candidates"] if c["appliedRole"]]
    requires = [{"r": r["name"], "s": s} for r in roles if r["hasJd"] for s in r["requires"]]

    with driver.session(database=database) as session:
        session.run(WIPE).consume()
        for stmt in INDEXES:
            session.run(stmt).consume()
        for stmt, data in (
            (WRITE_CANDIDATES, cand_rows),
            (WRITE_SKILLS, skill_rows),
            (WRITE_ROLES, roles),
            (WRITE_HAS_SKILL, has_skill),
            (WRITE_APPLIED_FOR, applied),
            (WRITE_REQUIRES, requires),
            (WRITE_MATCHES, matches),
        ):
            session.run(stmt, rows=data).consume()

        counts = session.run("""
            MATCH (n) WHERE n:Candidate OR n:Skill OR n:Role
            WITH labels(n)[0] AS label, count(*) AS n RETURN label, n ORDER BY label
        """).data()
        edges = session.run("""
            MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type
        """).data()

    return {"nodes": {row["label"]: row["n"] for row in counts},
            "edges": {row["type"]: row["n"] for row in edges}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--dry-run", action="store_true", help="reason and report; write nothing")
    ap.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""))
    ap.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).resolve()
    settings = json.loads(profile.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = profile.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    spec = json.loads((base / (settings.get("reasoning_spec") or "reasoning.json"))
                      .read_text(encoding="utf-8"))

    graph = R.load_graph([axioms, abox])
    rows = read_abox(graph, ns)
    classes, result = entail(graph, ns, spec)
    if not result.consistent:
        print("REFUSING to project an inconsistent ontology: " + "; ".join(result.notes))
        return 2

    matches = build_matches(graph, ns, classes, result, rows)
    roles = plan_roles(rows)
    orphans = [(r["name"], sum(1 for c in rows["candidates"] if c["appliedRole"] == r["name"]))
               for r in roles if not r["hasJd"]]

    print(f"reasoner {result.engine} · {result.elapsed_ms:.0f} ms · consistent={result.consistent}")
    print(f"  candidates {len(rows['candidates'])} · skills {len(rows['skills'])} · "
          f"roles {len(roles)}(有JD {sum(1 for r in roles if r['hasJd'])}) · matches {len(matches)}")
    if orphans:
        print(f"  hasJd=false: " + " · ".join(f"{n} {c}" for n, c in orphans))

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        driver.verify_connectivity()
        written = write(driver, args.database, rows, matches)
    finally:
        driver.close()

    print("  nodes: " + " · ".join(f"{k} {v}" for k, v in written["nodes"].items()))
    print("  edges: " + " · ".join(f"{k} {v}" for k, v in written["edges"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
