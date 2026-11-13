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


def test_the_sync_gate_finds_its_own_credentials(monkeypatch, tmp_path):
    """A gate that only runs when somebody exported PGPASSWORD is a gate that silently does not run.

    Measured on talent_v1 (2026-11-14): the builder ran it in its own sandbox, got `fe_sendauth: no
    password supplied`, and the publish refused on a NOT RUN gate the agent could not satisfy. The
    precedence that must hold: the dsn's own ${VAR} first, then the platform's credentials — and never a
    random per-ontology *_DB_PASSWORD, which authenticates as the wrong user.
    """
    import importlib.util
    import json

    gate_path = REPO / "backend" / "features" / "ontology" / "gates" / "check_abox_sync.py"
    spec = importlib.util.spec_from_file_location("_sync_gate_creds", gate_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setenv("TALENT_V1_DB_PASSWORD", "from-the-env")
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-postgres")
    monkeypatch.setenv("PGPASSWORD", "from-pgpassword")
    settings = {"dsn": {"host": "127.0.0.1", "port": 5432, "dbname": "talent_db",
                        "user": "langconfig", "password": "${TALENT_V1_DB_PASSWORD}"}}
    got = module._dsn_from_profile(settings, "talent_db")
    assert got["password"] == "from-the-env", got
    assert (got["host"], got["port"], got["user"]) == ("127.0.0.1", "5432", "langconfig")

    monkeypatch.delenv("TALENT_V1_DB_PASSWORD", raising=False)
    got = module._dsn_from_profile(settings, "talent_db")
    assert got["password"] in ("from-pgpassword", "from-postgres"), got


def test_a_baked_default_never_beats_the_platform_credentials(monkeypatch):
    """The seed templates carry `user: ${ONTOLOGY_DB_USER:-weiping}` from a developer machine.

    Measured on the deployment: a run whose environment lacked ONTOLOGY_DB_USER fell back to `weiping`
    and the gate reported "password authentication failed for user weiping" against a healthy database.
    A `${VAR:-default}` default is the WEAKEST source, not the first.
    """
    import importlib.util

    gate_path = REPO / "backend" / "features" / "ontology" / "gates" / "check_abox_sync.py"
    spec = importlib.util.spec_from_file_location("_sync_gate_defaults", gate_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    for var in ("ONTOLOGY_DB_USER", "ONTOLOGY_DB_HOST", "PGUSER", "POSTGRES_USER",
                "PGHOST", "POSTGRES_HOST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PGUSER", "langconfig")
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    settings = {"dsn": {"host": "${ONTOLOGY_DB_HOST:-127.0.0.1}",
                        "user": "${ONTOLOGY_DB_USER:-weiping}",
                        "dbname": "talent_db", "password": ""}}
    got = module._dsn_from_profile(settings, "talent_db")
    assert got["user"] == "langconfig", got
    assert "password" in got and got["password"] != "", "an empty dsn password must not shadow the env"
