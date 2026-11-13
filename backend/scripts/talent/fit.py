"""The recommendation score, in ONE place, so the table and the gate cannot disagree.

Two facts decide a shortlist and they come from different machinery:

  * **membership** — the reasoner entails `:matches_<role>` from the JD's axioms (skills union, years
    facet, education facet). Not this file's business;
  * **order** — among candidates who clear the bar, who to call first. A DL reasoner has no opinion
    about order, so the rule is written down here and used by BOTH the materialiser and the gate:

        60 % of the required skill categories held
        25 % years, capped at 1.0
        15 % the education floor, met or not
        ties: more years first, then candidate id (stable, so a re-run cannot reshuffle a tie)

Why 60/25/15: the client's own job descriptions lead with 技能 then 经验 then 学历 (`资格要求` blocks),
and a shortlist that lets a 20-year veteran with half the skills outrank a full match would contradict
that. The weights are a decision, not a measurement — they are written here, printed in the report, and
the gate re-derives every row from them, so changing them changes the table and the gate together.
"""
from __future__ import annotations

#: weights, stated once
WEIGHTS = {"skills": 60.0, "years": 25.0, "education": 15.0}


def score(*, matched_skills: int, required_skills: int, years: int | None,
          required_years: int | None, education_rank: int | None,
          required_education_rank: int | None) -> float:
    """The fit score, 0–100. `required_*` of None means the JD stated nothing, which cannot count
    against a candidate — an unstated floor is a gap in the JD, not a fault in the person."""
    skills_ratio = (matched_skills / required_skills) if required_skills else 0.0
    years_ratio = min(1.0, (years or 0) / required_years) if required_years else 1.0
    if not required_education_rank:
        education_ok = 1.0
    else:
        education_ok = 1.0 if (education_rank is not None
                               and education_rank >= required_education_rank) else 0.0
    return round(WEIGHTS["skills"] * skills_ratio + WEIGHTS["years"] * years_ratio
                 + WEIGHTS["education"] * education_ok, 2)


def order_key(row: dict) -> tuple:
    """Sort key inside one role: score desc, then years desc, then id — the documented tie-break."""
    return (-float(row["fit_score"]), -(row.get("years_experience") or 0), row["candidate"])


def rank_rows(rows: list[dict]) -> list[dict]:
    """Assign `rank_in_role` (1-based) inside each role_class, using `order_key`."""
    out = []
    counters: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: (r["role_class"],) + order_key(r)):
        counters[row["role_class"]] = counters.get(row["role_class"], 0) + 1
        out.append(dict(row, rank_in_role=counters[row["role_class"]]))
    return out
