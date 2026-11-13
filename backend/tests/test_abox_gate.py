"""The A-family gate (check_abox.py) over a real profile directory — and every way it must go red.

Team-4's ontology answers "which candidates match this job", a fact nobody stored. That makes the
gate the only thing standing between a demo and a lie: an entailed member can become an asserted one
(copy the answer into the ABox and the reasoner looks brilliant), an exclusion can quietly stop being
excluded, a mutation can change nothing and still report PASS.

So each test here is a mutation of a GREEN profile, and the assertion is that the gate notices:
asserting a member, dropping an exclusion, breaking the falsification spec, leaking PII, losing
coverage, and losing a file.

Exit codes are part of the contract too: 0 green, 1 red, 2 NOT RUN (an unrun gate is not a pass).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
GATE = BACKEND / "features" / "ontology" / "gates" / "check_abox.py"

NS = "http://example.org/talent#"

AXIOMS = """
@prefix : <http://example.org/talent#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Candidate a owl:Class .
:Skill a owl:Class .
:CAD a owl:Class ; rdfs:subClassOf :Skill .
:hasSkill a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :Skill .
:yearsExperience a owl:DatatypeProperty ; rdfs:domain :Candidate ; rdfs:range xsd:integer .
:JobOpening a owl:Class .

:matchesDesignEngineer a owl:Class ;
    owl:equivalentClass [ owl:intersectionOf (
        :Candidate
        [ a owl:Restriction ; owl:onProperty :hasSkill ; owl:someValuesFrom :CAD ]
        [ a owl:Restriction ; owl:onProperty :yearsExperience ;
          owl:someValuesFrom [ a rdfs:Datatype ; owl:onDatatype xsd:integer ;
                               owl:withRestrictions ( [ xsd:minInclusive 3 ] ) ] ]
    ) ] .
"""

ABOX = """
@prefix : <http://example.org/talent#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:SolidWorks a :CAD .
:Excel a :Skill .
:job_design a :JobOpening .
:cand_01 a :Candidate ; :hasSkill :SolidWorks ; :yearsExperience 7 .
:cand_02 a :Candidate ; :hasSkill :Excel ;       :yearsExperience 9 .
:cand_03 a :Candidate ; :hasSkill :SolidWorks ; :yearsExperience 1 .
"""

SPEC = {
    "reasoner": "hermit",
    "inferred": [{"class": "matchesDesignEngineer", "members": ["cand_01"],
                  "why": "CAD skill + 7y >= 3y"}],
    "excluded": [{"class": "matchesDesignEngineer", "individuals": ["cand_02", "cand_03"],
                  "why": "no CAD skill / 1 year < 3"}],
    "falsify": [
        {"label": "drop the class definition",
         "drop": {"subject": "matchesDesignEngineer", "predicate": "equivalentClass"},
         "class": "matchesDesignEngineer", "then_excluded": ["cand_01"]},
        {"label": "drop one skill assertion",
         "drop": {"subject": "cand_01", "predicate": "hasSkill"},
         "class": "matchesDesignEngineer", "then_excluded": ["cand_01"]},
    ],
    "coverage": {"source_files": 3, "loaded_individuals": 4,
                 "required_props": [{"class": "Candidate", "prop": "yearsExperience"}],
                 "allow_missing_props": ["hasSkill"]},
    "pii": {"patterns": [r"\b1[3-9]\d{9}\b", r"[\w.+-]+@[\w-]+\.[\w.]+"], "max_name_chars": 30},
}


def _profile(tmp_path: pathlib.Path, *, axioms: str = AXIOMS, abox: str = ABOX,
             spec: dict | None = None, skip: str = "") -> pathlib.Path:
    d = tmp_path / "talent_test"
    (d / "ontology").mkdir(parents=True, exist_ok=True)
    (d / "talent_test_settings.json").write_text(json.dumps({
        "title": "talent gate fixture",
        "ns": NS.rstrip("#"),
        "ontology_dir": "ontology",
        "abox": "abox.ttl",
        "reasoning": "reasoning.ttl",
        "reasoning_spec": "reasoning.json",
        "dsn": {},
    }), encoding="utf-8")
    if skip != "axioms":
        (d / "reasoning.ttl").write_text(axioms, encoding="utf-8")
    if skip != "abox":
        (d / "abox.ttl").write_text(abox, encoding="utf-8")
    if skip != "spec":
        (d / "reasoning.json").write_text(json.dumps(spec or SPEC, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return d / "talent_test_settings.json"


def _run(profile: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GATE), "--profile", str(profile)],
                          capture_output=True, text=True, cwd=str(BACKEND))
    return proc.returncode, proc.stdout + proc.stderr


def test_a_green_abox_profile_passes(tmp_path):
    code, out = _run(_profile(tmp_path))
    assert code == 0, out
    assert "0 failed" in out and "green" in out
    assert "A7 falsification" in out


def test_an_asserted_member_is_caught(tmp_path):
    """Copying the answer into the ABox makes the reasoner look brilliant. A2 must refuse it."""
    asserted = ABOX + '\n:cand_01 a :matchesDesignEngineer .\n'
    code, out = _run(_profile(tmp_path, abox=asserted))
    assert code == 1, out
    assert "not asserted in abox.ttl" in out and "copied answer, not a reasoned one" in out


def test_a_member_that_stops_being_entailed_is_caught(tmp_path):
    """Break the datum (1 year -> 7 years is fine; drop the skill is not) and A2 must notice."""
    weaker = ABOX.replace(":hasSkill :SolidWorks ; :yearsExperience 7", ":yearsExperience 7")
    applied = json.loads(json.dumps(SPEC))
    applied["falsify"] = []
    code, out = _run(_profile(tmp_path, abox=weaker, spec=applied))
    assert code == 1, out
    assert "the reasoner finds" in out


def test_an_exclusion_that_leaks_is_caught(tmp_path):
    leaked = json.loads(json.dumps(SPEC))
    leaked["excluded"] = [{"class": "matchesDesignEngineer", "individuals": ["cand_01"]}]
    code, out = _run(_profile(tmp_path, spec=leaked))
    assert code == 1, out
    assert "wrongly a member" in out


def test_a_falsification_that_changes_nothing_is_caught(tmp_path):
    """The mutation must remove a triple, or it proves nothing — the D-family lesson."""
    broken = json.loads(json.dumps(SPEC))
    broken["falsify"] = [{"label": "drop a predicate nobody uses",
                          "drop": {"subject": "cand_01", "predicate": "noSuchProperty"},
                          "class": "matchesDesignEngineer", "then_excluded": ["cand_01"]}]
    code, out = _run(_profile(tmp_path, spec=broken))
    assert code == 1, out
    assert "mutation removed something" in out
    assert "mutation that changes nothing proves nothing" in out


def test_pii_in_the_abox_is_caught(tmp_path):
    leaky = ABOX + '\n:cand_09 a :Candidate ; :hasSkill :Excel ; :yearsExperience 4 .\n'
    leaky = leaky.replace(":cand_09 ", ':cand_09 :contact "13800138000" .\n:cand_09 ')
    code, out = _run(_profile(tmp_path, abox=leaky))
    assert code == 1, out
    assert "no match for" in out


def test_coverage_gap_is_caught(tmp_path):
    short = json.loads(json.dumps(SPEC))
    short["coverage"]["loaded_individuals"] = 99
    code, out = _run(_profile(tmp_path, spec=short))
    assert code == 1, out
    assert "unaccounted for" in out or "carries" in out


def test_missing_files_report_not_run(tmp_path):
    code, out = _run(_profile(tmp_path, skip="abox"))
    assert code == 2, out
    assert "NOT RUN" in out and "abox.ttl" in out


def test_a_missing_profile_reports_not_run(tmp_path):
    code, out = _run(tmp_path / "nope_settings.json")
    assert code == 2, out
    assert "NOT RUN" in out
