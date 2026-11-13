#!/usr/bin/env python3
"""Bridge the ABox to SQL: reason over the individuals, then write what the reasoner concluded.

The platform answers questions with SQL over declared tables; the ABox lives in RDF and its useful
content (who matches which role) exists only after reasoning. This script is the single place those
two worlds meet:

    abox.ttl + reasoning.ttl  --HermiT-->  members of each defined role class
                                            |
                                            v
                    Postgres tables the ontology can declare metrics over:
                      candidate, skill, candidate_skill, role, role_required_skill, match
                      + reasoning_run (engine, elapsed, per-class counts)

The `match` table is written ONLY from the reasoner's answer — never from a SQL rule that re-implements
the definition. That is the whole point: `check_abox_sync.py` can then re-run the reasoner and demand
the table be identical, so a dashboard number cannot drift away from the entailment that produced it.

Ids are copied from the ABox so every row traces back to a scan:
    candidate.id = the ABox local name        candidate.source_file = the path it came from
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from rdflib import Graph, Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF  # noqa: E402

from features.ontology.reasoning import reasoner as R  # noqa: E402
from scripts.talent.fit import score as fit_score  # noqa: E402

DDL = """
drop table if exists candidate_role_fit;
drop table if exists candidate_match;
drop table if exists role_required_skill;
drop table if exists role;
drop table if exists candidate_skill;
drop table if exists skill;
drop table if exists candidate;
drop table if exists reasoning_run;

create table candidate (
    id              text primary key,
    role            text,
    years_experience int,
    education_rank  int,
    salary_min_k    int,
    salary_max_k    int,
    age             int,
    source_file     text not null,
    duplicate_of    text,
    missing_years   boolean not null default false,
    missing_education boolean not null default false,
    missing_skills  boolean not null default false
);
create table skill (
    skill   text primary key,
    category text
);
create table candidate_skill (
    candidate text not null references candidate(id),
    skill     text not null references skill(skill),
    primary key (candidate, skill)
);
create table role (
    role text primary key,
    required_years int,
    required_education_rank int,
    not_stated text
);
create table role_required_skill (
    role  text not null references role(role),
    skill text not null references skill(skill),
    primary key (role, skill)
);
-- one row per entailment: this is the table a dashboard panel reads
create table candidate_match (
    candidate text not null references candidate(id),
    role_class text not null,
    role text,
    primary key (candidate, role_class)
);
-- the RECOMMENDATION: who meets the bar (entailment) and how well (deterministic score).
-- The DL reasoner decides membership; it cannot order candidates, so the ordering is written here and
-- documented, rather than left to a feeling: 60 % skills, 25 % years, 15 % education floor.
create table candidate_role_fit (
    candidate text not null references candidate(id),
    role_class text not null,
    role text,
    matched_skills int not null,
    required_skills int not null,
    years_experience int,
    required_years int,
    years_margin int,
    education_rank int,
    required_education_rank int,
    fit_score numeric(6,2) not null,
    rank_in_role int not null,
    primary key (candidate, role_class)
);
create table reasoning_run (
    run_at      timestamptz not null default now(),
    engine      text not null,
    elapsed_ms  numeric,
    candidates  int not null,
    members     jsonb not null,
    consistent  boolean not null
);
"""


def _local(node) -> str:
    return str(node).rsplit("#", 1)[-1]


def _int(graph: Graph, subj: URIRef, prop: str) -> int | None:
    for value in graph.objects(subj, URIRef(prop)):
        if isinstance(value, Literal):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _text(graph: Graph, subj: URIRef, prop: str) -> str | None:
    for value in graph.objects(subj, URIRef(prop)):
        return str(value)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="the talent profile's *_settings.json")
    ap.add_argument("--dsn-db", required=True, help="database to write into")
    ap.add_argument("--dry-run", action="store_true", help="reason and print, write nothing")
    args = ap.parse_args()

    settings_path = pathlib.Path(args.profile).resolve()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    ns = (settings.get("ns") or "").rstrip("#") + "#"
    base = settings_path.parent
    abox = (base / (settings.get("abox") or "abox.ttl")).resolve()
    axioms = (base / (settings.get("reasoning") or "reasoning.ttl")).resolve()
    spec = json.loads((base / (settings.get("reasoning_spec") or "reasoning.json"))
                      .read_text(encoding="utf-8"))

    graph = R.load_graph([axioms, abox])
    classes = [ns + item["class"] for item in spec.get("inferred") or []]
    classes += [ns + item["class"] for item in spec.get("excluded") or []]
    classes = sorted(set(classes))
    result = R.reason(graph, engine=spec.get("reasoner") or "hermit", watch_classes=classes)
    if not result.consistent:
        print("REFUSING to materialise an inconsistent ontology: " + "; ".join(result.notes))
        return 2

    # ── read the ABox back out as rows
    def subjects_of(cls: str) -> list[str]:
        return sorted(_local(s) for s in graph.subjects(RDF.type, URIRef(ns + cls)))

    candidates = subjects_of("Candidate")
    skills = subjects_of("SkillTag")
    roles = subjects_of("Role")

    cand_rows = []
    css_rows = []
    for cid in candidates:
        node = URIRef(ns + cid)
        missing = {_local(o) for o in graph.objects(node, URIRef(ns + "missingData"))}
        skills_of = sorted(_local(o) for o in graph.objects(node, URIRef(ns + "hasSkill")))
        cand_rows.append((
            cid,
            _local(_text(graph, node, ns + "appliedFor") or "") or None,
            _int(graph, node, ns + "yearsExperience"),
            _int(graph, node, ns + "educationRank"),
            _int(graph, node, ns + "salaryMinK"),
            _int(graph, node, ns + "salaryMaxK"),
            _int(graph, node, ns + "age"),
            _text(graph, node, ns + "sourceFile") or "",
            _local(_text(graph, node, "http://www.w3.org/2002/07/owl#sameAs") or "") or None,
            "UnknownYears" in missing,
            "UnknownEducation" in missing,
            "UnknownSkills" in missing,
        ))
        css_rows += [(cid, skill) for skill in skills_of]

    skill_rows = []
    for skill in skills:
        node = URIRef(ns + skill)
        types = [_local(t) for t in graph.objects(node, RDF.type)]
        category = next((t for t in types if t not in ("SkillTag", "NamedIndividual")), None)
        skill_rows.append((skill, category))

    role_rows = []
    rrs_rows = []
    for rid in roles:
        node = URIRef(ns + rid)
        role_rows.append((rid, _int(graph, node, ns + "requiredYears"),
                          _int(graph, node, ns + "requiredEducationRank"),
                          _text(graph, node, ns + "notStated")))
        rrs_rows += [(rid, _local(o)) for o in graph.objects(node, URIRef(ns + "requiresSkill"))]

    match_rows = []
    for iri in classes:
        cls_local = _local(iri)
        for member in result.members_of(iri):
            match_rows.append((_local(member), cls_local,
                               _local(_text(graph, URIRef(member), ns + "appliedFor") or "") or None))

    # ── the recommendation table: membership from the reasoner, ordering from a written rule
    skill_categories_by_candidate: dict[str, set[str]] = {}
    for cid, skill in css_rows:
        category = next((cat for s_name, cat in skill_rows if s_name == skill and cat), None)
        skill_categories_by_candidate.setdefault(cid, set())
        if category:
            skill_categories_by_candidate[cid].add(category)

    role_requirements = {}
    for rid, r_years, r_rank, _not_stated in role_rows:
        # key by the BARE role name: ABox individuals are `role_<岗位>`, match classes `matches_<岗位>`,
        # and the two must meet in the same dictionary (first attempt keyed by the prefixed name and
        # produced 204 entitlements with 0 rows in the recommendation table).
        if rid.startswith("role_"):
            rid = rid[len("role_"):]
        cats = set()
        for r_role, skill in rrs_rows:
            # rrs_rows carry the ABox names (`role_<岗位>`); `rid` was stripped above, so compare the
            # bare names or every role ends up with "0 required skills" and a perfect-looking row.
            if r_role.removeprefix("role_") != rid:
                continue
            pruned = [cat for s_name, cat in skill_rows if s_name == skill and cat]
            cats |= set(pruned)
        role_requirements[rid] = (r_years, r_rank, cats)

    def _fit(cid: str, rid: str) -> tuple | None:
        r_years, r_rank, required_cats = role_requirements.get(rid, (None, None, set()))
        cand = next((row for row in cand_rows if row[0] == cid), None)
        if cand is None:
            return None
        years, edu_rank = cand[2], cand[3]
        held = skill_categories_by_candidate.get(cid, set())
        matched = len(held & required_cats)
        total = len(required_cats)
        score = fit_score(matched_skills=matched, required_skills=total, years=years,
                          required_years=r_years, education_rank=edu_rank,
                          required_education_rank=r_rank)
        years_margin = (years - r_years) if (years is not None and r_years is not None) else None
        return (cid, None, rid, matched, total, years, r_years, years_margin, edu_rank, r_rank,
                score, 0)

    # A duplicate scan is the SAME person (`:sameAs` in the ABox, `duplicate_of` here). Ranking both
    # would push a real candidate down one rank for every duplicate file — measured on the client's
    # dossier: 7 such pairs, and 副总助理's top 2 rows were the same person twice.
    duplicates = {row[0] for row in cand_rows if row[8]}
    fit_rows = []
    for iri in classes:
        cls_local = _local(iri)
        for member in result.members_of(iri):
            cid = _local(member)
            if cid in duplicates:
                continue
            # the JD's role: the class name minus its prefix. NOT the candidate's applied role —
            # ranking a 副总助理 applicant inside the 业务跟单 requirement must still say 业务跟单.
            jd_role = cls_local[len("matches_"):] if cls_local.startswith("matches_") else cls_local
            applied = _local(_text(graph, URIRef(member), ns + "appliedFor") or "") or None
            # The score is against the JD the candidate MATCHED, not the one they applied for: a
            # 品质经理 applicant who clears the 业务跟单 bar must be scored against 业务跟单's
            # requirements. Scoring against the applied role left 159 rows with 0/0 skills and no
            # required years — measured by the sync gate, which re-derived them and disagreed.
            row = _fit(cid, jd_role) if jd_role in role_requirements else None
            if row is None:
                continue
            fit_rows.append((row[0], cls_local, jd_role) + row[3:11])
    # rank inside each role: fit desc, then years desc, then id — a stated tie-break, not insertion order
    fit_rows.sort(key=lambda r: (r[1], -float(r[10]), -(r[7] or 0), r[0]))
    ranked, seen = [], {}
    for row in fit_rows:
        seen[row[1]] = seen.get(row[1], 0) + 1
        ranked.append(row[:11] + (seen[row[1]],))

    print(f"reasoner {result.engine} · {result.elapsed_ms:.0f} ms · consistent={result.consistent}")
    for iri in classes:
        print(f"  {_local(iri):26s} {len(result.members_of(iri)):4d} member(s)")
    print(f"  candidates {len(cand_rows)} · skills {len(skill_rows)} · roles {len(role_rows)} · "
          f"matches {len(match_rows)} · ranked {len(ranked)}")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    import psycopg2
    from psycopg2.extras import execute_values, Json

    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"), port=int(os.environ.get("PGPORT", 5432)),
        dbname=args.dsn_db, user=os.environ.get("PGUSER", "langconfig"),
        password=os.environ.get("PGPASSWORD", ""))
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(DDL)
            if cand_rows:
                execute_values(cur, "insert into candidate values %s", cand_rows)
            if skill_rows:
                execute_values(cur, "insert into skill values %s", skill_rows)
            if css_rows:
                execute_values(cur, "insert into candidate_skill (candidate, skill) values %s",
                               css_rows)
            if role_rows:
                execute_values(cur, "insert into role values %s", role_rows)
            if rrs_rows:
                execute_values(cur, "insert into role_required_skill (role, skill) values %s",
                               rrs_rows)
            if match_rows:
                execute_values(cur, "insert into candidate_match (candidate, role_class, role) "
                                    "values %s", match_rows)
            if ranked:
                execute_values(cur, "insert into candidate_role_fit (candidate, role_class, role, "
                                    "matched_skills, required_skills, years_experience, required_years, "
                                    "years_margin, education_rank, required_education_rank, fit_score, "
                                    "rank_in_role) values %s", ranked)
            cur.execute("insert into reasoning_run (engine, elapsed_ms, candidates, members, "
                        "consistent) values (%s,%s,%s,%s,%s)",
                        (result.engine, round(result.elapsed_ms, 3), len(cand_rows),
                         Json({_local(k): len(v) for k, v in result.members.items()}),
                         result.consistent))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"wrote {args.dsn_db}: candidate {len(cand_rows)}, candidate_skill {len(css_rows)}, "
          f"role {len(role_rows)}, role_required_skill {len(rrs_rows)}, match {len(match_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
