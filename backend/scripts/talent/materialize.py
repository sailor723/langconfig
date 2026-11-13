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

DDL = """
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

    print(f"reasoner {result.engine} · {result.elapsed_ms:.0f} ms · consistent={result.consistent}")
    for iri in classes:
        print(f"  {_local(iri):26s} {len(result.members_of(iri)):4d} member(s)")
    print(f"  candidates {len(cand_rows)} · skills {len(skill_rows)} · roles {len(role_rows)} · "
          f"matches {len(match_rows)}")

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
