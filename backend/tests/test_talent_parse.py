"""What the CV scan parser may and may not claim, asserted on the client's real file names.

Three sources of truth, in descending honesty (2026-11-14: all 277 PDFs are scans, 0 extractable
characters): the ROLE FOLDER a human filed it under, the FILENAME the recruiting platform wrote, and
the OCR text. Each test below is a real file name from the dossier, because the failure that matters
is not "does the regex run" but "does a fresher come out as a 26-year veteran".

The rule the module exists to enforce: unknown stays unknown. A missing year of experience and a
zero year of experience are different statements about a person, and an ontology that conflates them
cannot be trusted with the rest.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from scripts.talent.parse import build_record, parse_filename, parse_path, parse_text  # noqa: E402


# ── the exported filename shape ───────────────────────────────────────────────

def test_exported_name_gives_role_city_band_and_years():
    got = {k: v.value for k, v in
           parse_filename("【设计助理工程师_东莞 7-10K】雷__ 1年").items() if v.value is not None}
    assert got == {"applied_role": "设计助理工程师", "city": "东莞", "salary_min_k": 7,
                   "salary_max_k": 10, "years_experience": 1, "name_masked": "雷__"}


def test_ten_years_or_more_is_ten_not_a_range():
    got = parse_filename("【汽车线束高线工程师_东莞 10-14K】何__ 10年以上")
    assert got["years_experience"].value == 10
    assert got["salary_min_k"].value == 10 and got["salary_max_k"].value == 14


def test_a_graduation_year_is_not_years_of_experience():
    """Measured: `马__ 26年应届生` parsed as 26 years of experience — a fresher as a veteran."""
    got = parse_filename("【人资专员_东莞 5-6K】马__ 26年应届生")
    assert got["years_experience"].value is None, "26年应届生 is a graduation year"
    assert got["applied_role"].value == "人资专员"


def test_the_legacy_shape_yields_age_and_a_masked_name_only():
    got = parse_filename("唐__-42岁-智通简历-编号(______)")
    assert got["age"].value == 42
    assert got["name_masked"].value == "唐__"
    assert got["years_experience"].value is None and got["salary_min_k"].value is None


# ── the folder a human filed it under ────────────────────────────────────────

def test_path_gives_department_and_role_folder():
    dept, role = parse_path("07、业务课侯选人简历/业务跟单/【业务跟单_东莞 6-8K】张__ 3年.pdf")
    assert dept.value == "07、业务课" and dept.source == "path"
    assert role.value == "业务跟单" and role.source == "path"


# ── OCR text: tolerant patterns, and evidence kept ───────────────────────────

def test_ocr_misspellings_still_match_the_right_skill():
    """The client's scans render CorelDRAW as `coneidw` and Photoshop as `Photoshog`."""
    text = "熟练 CAD、SolidWorks，Photoshop、coneidw、AI、办公软件 本人专科毕业"
    got = parse_text(text)
    assert "SolidWorks" in got["skills"]
    assert "CorelDRAW" in got["skills"], "coneidw is CorelDRAW on these scans"
    assert "Photoshop" in got["skills"]
    assert got["education"].value == "大专" and got["education"].source == "ocr"


def test_education_prefers_the_highest_level_found():
    got = parse_text("本科毕业，后攻读硕士，MBA")
    assert got["education"].value == "硕士"


def test_work_years_only_from_a_phrase_that_names_work():
    assert parse_text("工作年限：8年")["years_experience_from_text"].value == 8
    assert parse_text("2019年毕业")["years_experience_from_text"].value is None


# ── the record: sources are labelled, unknown is not zero ────────────────────

def test_missing_fields_are_missing_not_zero():
    rec = build_record("04、技术课候选人简历/设计工程师/唐__-42岁-智通简历-编号(______).pdf",
                       "唐__-42岁-智通简历-编号(______)", "")
    d = rec.to_dict()
    assert d["years_experience"] == {"value": None, "source": "missing"}, d["years_experience"]
    assert any("not 0" in w for w in d["warnings"]), "an unknown year must say so out loud"
    assert any("no OCR text" in w for w in d["warnings"])
    assert d["education"]["source"] == "missing"
    assert d["age"]["source"] == "filename"


def test_filename_facts_beat_ocr_and_say_which_won():
    rel = "07、业务课侯选人简历/业务跟单/【业务跟单_东莞 6-8K】张__ 3年.pdf"
    rec = build_record(rel, "【业务跟单_东莞 6-8K】张__ 3年", "工作经验：9年")
    d = rec.to_dict()
    assert d["years_experience"]["value"] == 3 and d["years_experience"]["source"] == "filename", (
        "the recruiting platform's own statement outranks an OCR phrase")


def test_ocr_years_are_used_when_the_name_has_none():
    rec = build_record("04、技术课候选人简历/设计工程师/唐__-42岁-智通简历-编号(______).pdf",
                       "唐__-42岁-智通简历-编号(______)", "工作经验：9年 熟练CAD")
    d = rec.to_dict()
    assert d["years_experience"]["value"] == 9 and d["years_experience"]["source"] == "ocr"


def test_appledouble_sidecars_are_not_cvs(tmp_path):
    """`._name.pdf` is a macOS resource fork, not a résumé."""
    import subprocess

    import re

    src = (REPO / "backend" / "scripts" / "talent" / "extract.py").read_text(encoding="utf-8")
    assert 'pdf.name.startswith("._")' in src, "the sidecar filter is gone; the dossier doubles itself"
    assert '.DS_Store' in src
