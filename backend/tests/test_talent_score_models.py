"""The score catalogue is a gate, not a memo — every score named, gated, and carrying a denominator.

Why a test instead of a paragraph. There is exactly one number in the talent path that is
called plain `score`, and it gets read as four different things: the OWL necessary condition,
the gate verdict, the sort key, and "match rate" shown to HR. Those four have different
denominators and different valid comparison ranges, so the moment one of them is allowed to
stand in for another, a number that means "covered 1 of 1 requirement" is shown next to a
number that means "covered 2 of 2" — and neither the reader nor the SQL can tell.

`work/talent/score_models.yaml` is the catalogue; this file keeps it honest:

  1. it parses and every score has a name, a denominator, a gate and a status;
  2. the weight table adds back up to the 95 atomic JD requirements and to 100 per family;
  3. no score is quietly published while it is degenerate.

The SQL gates in the catalogue are run separately (`scripts.talent.check_score_models`)
because they need the live database; these assertions do not, so they run in the ordinary
suite and fail a commit rather than a demo.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from scripts.talent.check_score_models import check_structure  # noqa: E402

SPEC_PATH = REPO / "work" / "talent" / "score_models.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    with SPEC_PATH.open() as fh:
        return yaml.safe_load(fh)


def test_the_catalogue_parses_and_is_structurally_complete(spec):
    """One assertion for R1/R2/R3: named, denominator, gate — or the file is not a catalogue."""
    assert check_structure(spec) == []


def test_every_score_is_named_and_unique(spec):
    """A duplicate code would let two definitions hide behind one name."""
    codes = [s["code"] for s in spec["scores"]]
    assert len(codes) == len(set(codes))
    assert all(code.startswith("S") for code in codes)


def test_only_s0_is_allowed_to_be_a_jd_side_score(spec):
    """S0 scores the ruler, not the person. It must never claim comparability with a candidate."""
    jd_side = [s["code"] for s in spec["scores"] if s["code"].startswith("S0")]
    assert jd_side == ["S0_jd"]
    s0 = next(s for s in spec["scores"] if s["code"] == "S0_jd")
    assert "永" in s0["compared_within"] or "never" in s0["compared_within"].lower()


def test_the_two_live_scores_are_never_mergeable(spec):
    """S1 (necessary condition) and S2 (coverage) must not be added or averaged — the
    catalogue has to say so, because the tempting shortcut is to weight them."""
    pairs = {(row["a"], row["b"]) for row in spec["comparable"] if not row["allowed"]}
    assert ("S1_entailed", "S2_coverage") in pairs or ("S2_coverage", "S1_entailed") in pairs


def test_cross_role_comparison_of_the_coverage_score_is_forbidden(spec):
    """S2's denominator is 1 or 2 depending on the role; ranking across roles is not a
    small error, it is comparing a 1-question exam with a 2-question one."""
    forbidden = [row for row in spec["comparable"]
                 if row["a"] == "S2_coverage" and row["b"] == "S2_coverage"
                 and row.get("within") == "pool" and not row["allowed"]]
    assert forbidden, "catalogue must forbid cross-role S2 comparison"


def test_family_weights_add_up_to_the_95_atomic_requirements(spec):
    counts = spec["weights"]["family_counts"]
    assert sum(row["total"] for row in counts.values()) == 95
    for family, row in counts.items():
        assert sum(row[d] for d in "ABCDEFGH") == row["total"], family


def test_every_family_weight_skeleton_sums_to_one_hundred(spec):
    tol = spec["weights"]["rounding"]["sum_tolerance"]
    for family, row in spec["weights"]["skeleton"].items():
        if not isinstance(row, dict):
            continue
        total = sum(v for v in row.values() if isinstance(v, (int, float)))
        assert abs(total - 100) <= tol, f"{family} = {total}"


def test_a_blocked_score_says_what_it_is_blocked_on(spec):
    """A degenerate score that does not name its blocker will be published by accident."""
    for score in spec["scores"]:
        if score["status"] == "blocked":
            assert score.get("blocked_on"), score["code"]


def test_every_sql_gate_declares_what_a_hit_means(spec):
    """A gate without `expect` cannot be run: it is not decidable whether a row is the
    documented state or a defect."""
    for gate in spec["validation"]:
        if gate.get("kind") == "sql":
            assert gate.get("expect") in {"rows", "no_rows"}, gate["code"]
            assert gate.get("check", "").strip(), gate["code"]


def test_refused_scores_stay_refused(spec):
    """Recorded so they are not reinvented: an LLM-produced ranking makes "why is she 7th?"
    unanswerable, which is the one question this path exists to answer."""
    refused = {r["code"] for r in spec["refused"]}
    assert "S_llm_fit" in refused
    published = {s["code"] for s in spec["scores"]}
    assert not (refused & published)
