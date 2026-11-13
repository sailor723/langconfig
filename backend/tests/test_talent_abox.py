"""The ABox builder and the "excused gap" rule, on records shaped like the client's own.

Two rules are worth pinning, because both were learned on the real 277 scans:

  * a candidate whose OCR text named no recognisable skill must be MARKED (`:missingData
    :UnknownSkills`), not left bare — "has no skills" and "we could not read it" are different
    statements about a person, and only the second may be excused by the gate;
  * a skill individual is typed into its CATEGORY (`:skill_SolidWorks a :CAD`), because that is what
    the role definitions reason over. The first spike typo'd the category as `:CAT` and the reasoner
    correctly matched nobody — a whole role silently became unanswerable.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from scripts.talent.build_abox import build  # noqa: E402
from scripts.talent.jd_parse import requirements_from_text, role_from_filename  # noqa: E402

NS = "https://cube.local/ontology/talent_v1#"
GATE = BACKEND / "features" / "ontology" / "gates" / "check_abox.py"


def _rec(**kw) -> dict:
    base = {
        "candidate_id": "x", "source_file": "03、管理科/人资专员/x.pdf",
        "department": {"value": "03、管理科", "source": "path"},
        "role_folder": {"value": "人资专员", "source": "path"},
        "applied_role": {"value": None, "source": "missing"},
        "city": {"value": "东莞", "source": "filename"},
        "salary_min_k": {"value": 5, "source": "filename"},
        "salary_max_k": {"value": 6, "source": "filename"},
        "years_experience": {"value": 5, "source": "filename"},
        "age": {"value": None, "source": "missing"},
        "name_masked": {"value": "何__", "source": "filename"},
        "education": {"value": "大专", "source": "ocr"},
        "skills": ["招聘", "Excel"], "skills_raw": [], "ocr_chars": 900, "warnings": [],
    }
    base.update(kw)
    return base


def test_skill_individuals_are_typed_into_their_category():
    turtle, stats = build([_rec()])
    assert ":skill_招聘 a :RecruitingSkill, :SkillTag" in turtle, turtle[:800]
    assert ":skill_Excel a :SpreadsheetSoftware, :SkillTag" in turtle
    assert stats["with_skills"] == 1


def test_a_candidate_with_no_recognised_skill_is_marked_not_bare():
    turtle, stats = build([_rec(candidate_id="y", skills=[])])
    assert ":missingData :UnknownSkills" in turtle, "a data gap must be distinguishable from a fact"
    assert stats["unknown_skills"] == 1


def test_unknown_years_and_education_are_recorded_as_missing():
    turtle, stats = build([_rec(candidate_id="z", years_experience={"value": None, "source": "missing"},
                                education={"value": None, "source": "missing"})])
    assert ":missingData :UnknownYears" in turtle and ":missingData :UnknownEducation" in turtle
    assert ":yearsExperience" not in turtle
    assert stats["unknown_years"] == 1 and stats["unknown_education"] == 1


def test_a_duplicate_scan_is_linked_not_counted_twice():
    turtle, stats = build([_rec(candidate_id="a", duplicate_of="03、管理科/人资专员/dup.pdf",
                                source_file="03、管理科/人资专员/a.pdf")])
    assert ":sameAs :cand_dup" in turtle
    assert stats["duplicates"] == 1


def test_requirements_become_role_individuals_with_the_stated_floor():
    req = requirements_from_text("业务跟单", "学历：高中及以上；经验：2年以上订单跟单经验；熟练ERP与Excel")
    turtle, _ = build([_rec()], [req])
    assert ":role_业务跟单 a :Role" in turtle
    assert ":requiredYears 2" in turtle
    assert ":requiredEducationRank 2" in turtle


def test_jd_role_names_survive_numbers_and_versions():
    assert role_from_filename("2. 业务跟单职务说明书") == "业务跟单"
    assert role_from_filename("关务报关员职务说明书-11.7") == "关务报关员"
    assert role_from_filename("2.副总助理职务说明书 - 最新修改版") == "副总助理"


def test_jd_states_what_it_cannot_state():
    req = requirements_from_text("专案工程师", "1、电线连接器加工行业产品开发3年以上经验；4、CAD二维制图")
    assert req["min_years"] == 3
    assert "AutoCAD" in req["skills"]
    assert "education_floor" in req["missing"], "no education line in this JD, so it must say so"


# ── the gate's "excused gap" rule ────────────────────────────────────────────

AXIOMS = """@prefix : <https://cube.local/ontology/talent_v1#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Candidate a owl:Class .
:Role a owl:Class .
:SkillTag a owl:Class .
:hasSkill a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :SkillTag .
:appliedFor a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :Role .
:missingData a owl:ObjectProperty .
"""

ABOX_TMPL = """@prefix : <https://cube.local/ontology/talent_v1#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Candidate a owl:Class . :Role a owl:Class . :SkillTag a owl:Class .
:hasSkill a owl:ObjectProperty ; rdfs:domain :Candidate ; rdfs:range :SkillTag .
:appliedFor a owl:ObjectProperty . :missingData a owl:ObjectProperty .
:UnknownSkills a owl:NamedIndividual .
:r1 a :Role .
:c1 a :Candidate ; :appliedFor :r1 ; :hasSkill :s1 .
:c2 a :Candidate ; :appliedFor :r1 {MARK} .
"""


def _profile(tmp_path: pathlib.Path, marked: bool) -> pathlib.Path:
    d = tmp_path / "p"
    (d / "ontology").mkdir(parents=True, exist_ok=True)
    (d / "reasoning.ttl").write_text(AXIOMS, encoding="utf-8")
    (d / "abox.ttl").write_text(
        ABOX_TMPL.replace("{MARK}", "; :missingData :UnknownSkills" if marked else ""), encoding="utf-8")
    (d / "reasoning.json").write_text(json.dumps({
        "reasoner": "hermit",
        "coverage": {"source_files": 2, "loaded_individuals": 2,
                     "required_props": [{"class": "Candidate", "prop": "hasSkill",
                                         "unless_marked": "UnknownSkills"}]},
    }), encoding="utf-8")
    prof = d / "p_settings.json"
    prof.write_text(json.dumps({"ns": NS.rstrip("#"), "ontology_dir": "ontology",
                                "abox": "abox.ttl", "reasoning": "reasoning.ttl",
                                "reasoning_spec": "reasoning.json", "dsn": {}}), encoding="utf-8")
    return prof


def _run(profile: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GATE), "--profile", str(profile)],
                          capture_output=True, text=True, cwd=str(BACKEND))
    return proc.returncode, proc.stdout + proc.stderr


def test_a_marked_gap_is_excused(tmp_path):
    code, out = _run(_profile(tmp_path, marked=True))
    assert "excuses it" in out, out
    assert "no individual" not in out.lower() or "FAIL" not in out
    assert code == 0, out


def test_an_unmarked_gap_is_not_excused(tmp_path):
    code, out = _run(_profile(tmp_path, marked=False))
    assert code == 1, out
    assert "every :Candidate carries :hasSkill" in out
