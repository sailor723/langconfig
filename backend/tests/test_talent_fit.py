"""The recommendation score and its tie-break, asserted once — the materialiser and the gate share it.

The score is a DECISION, not a measurement: the client's job descriptions lead with 技能, then 经验, then
学历, so a shortlist that let a veteran with half the skills outrank a full match would contradict the
document it is built from. It is written here so the table and the gate cannot drift apart, and so a
later change to the weights is a change to one file plus its tests.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from scripts.talent.fit import WEIGHTS, order_key, rank_rows, score  # noqa: E402


def test_full_match_scores_one_hundred():
    assert score(matched_skills=3, required_skills=3, years=10, required_years=2,
                 education_rank=3, required_education_rank=2) == 100.0


def test_skills_dominate_the_score():
    """A candidate with all the skills but only the minimum years beats one with half of them."""
    full = score(matched_skills=3, required_skills=3, years=2, required_years=2,
                 education_rank=2, required_education_rank=2)
    half = score(matched_skills=1, required_skills=3, years=20, required_years=2,
                 education_rank=2, required_education_rank=2)
    assert full > half, (full, half)


def test_an_unstated_floor_never_counts_against_a_candidate():
    """No stated years and no stated education are gaps in the JD, not faults in the person."""
    assert score(matched_skills=1, required_skills=1, years=None, required_years=None,
                 education_rank=None, required_education_rank=None) == 100.0


def test_a_missing_education_rank_fails_only_the_education_part():
    without = score(matched_skills=1, required_skills=1, years=5, required_years=2,
                    education_rank=None, required_education_rank=4)
    with_it = score(matched_skills=1, required_skills=1, years=5, required_years=2,
                    education_rank=4, required_education_rank=4)
    assert with_it - without == WEIGHTS["education"]


def test_years_ratio_is_capped():
    at_min = score(matched_skills=1, required_skills=1, years=2, required_years=2,
                   education_rank=None, required_education_rank=None)
    way_over = score(matched_skills=1, required_skills=1, years=40, required_years=2,
                     education_rank=None, required_education_rank=None)
    assert at_min == way_over == 100.0


def test_rank_ties_break_by_years_then_id():
    rows = [
        {"candidate": "b", "role_class": "matches_X", "fit_score": 80.0, "years_experience": 5},
        {"candidate": "a", "role_class": "matches_X", "fit_score": 80.0, "years_experience": 9},
        {"candidate": "c", "role_class": "matches_X", "fit_score": 90.0, "years_experience": 1},
        {"candidate": "d", "role_class": "matches_X", "fit_score": 80.0, "years_experience": 9},
    ]
    ranked = rank_rows(rows)
    order = [(r["candidate"], r["rank_in_role"]) for r in ranked]
    assert order == [("c", 1), ("a", 2), ("d", 3), ("b", 4)], order


def test_ranks_are_per_role_not_global():
    rows = [
        {"candidate": "a", "role_class": "matches_X", "fit_score": 90.0, "years_experience": 3},
        {"candidate": "b", "role_class": "matches_Y", "fit_score": 99.0, "years_experience": 3},
    ]
    ranked = rank_rows(rows)
    assert {r["role_class"]: r["rank_in_role"] for r in ranked} == {"matches_X": 1, "matches_Y": 1}


def test_the_gate_re_derives_the_ranking_from_this_module():
    """A guard against the gate growing its own copy of the formula — that is what S1b exists for."""
    gate = (REPO / "backend" / "features" / "ontology" / "gates" / "check_abox_sync.py").read_text(
        encoding="utf-8")
    assert "from scripts.talent.fit import rank_rows, score as fit_score" in gate, (
        "the sync gate must import the same scoring module, not re-implement the weights")
    assert "60" not in gate.split("def _check_fit")[1][:2000] or "WEIGHTS" in gate, (
        "weights must come from scripts/talent/fit.py")
