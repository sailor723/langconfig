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


# ══════════════════════════════════════════════════════════════════════════════
# v2 — 梯度计分（已实现，**默认不启用**；见 work/talent/B_experiment.md 第三轮）
#
# 为什么要有 v2：v1 的年限封顶 1.0、学历二值，实测把 122/148 人钉在年限 1.0，
# 全池只有 2–24 个不同分值。而年限倍率在本语料里横跨 0–7×（门槛 3 年那一档：
# <1× 26 人、1–1.5× 25、1.5–2× 13、2–3× 22、3–5× 59、≥5× 3）——封顶在 1× 抹掉了
# 全部差异。所以改成**绝对年限分档**，不用倍率（倍率无上界，无法向 HR 解释）。
#
# 三条与 v1 不同的约定：
#   1. 年限按绝对年数分档，学历按等级分档，都不再二值；
#   2. 未知项**不进分子也不进分母**，并单独报出——不按 0 分（判为不及格是错的），
#      也不静默给满分（见下方 completeness）；
#   3. 同时返回 `completeness`（观测到的权重占比）。**不完整不能因为"查不到"排到完整的人前面**，
#      所以排序键是（分数, 完整度, 年限, id），不是（分数, 年限, id）。
#
# 门槛（required_years）在 v2 里**只当标记**，不再参与计分（决定 D10：年限/学历退出成员判定）。
# ══════════════════════════════════════════════════════════════════════════════

#: 绝对年限分档：(上界, 分值)，上界 None 表示"及以上"
YEAR_BANDS: tuple[tuple[int | None, float], ...] = (
    (1, 0.10), (3, 0.30), (5, 0.50), (10, 0.75), (None, 1.00),
)

#: 学历等级分档：2=中专/高中 3=大专 4=本科 5=硕士 6=博士。超过硕士不再加分。
EDU_BANDS: dict[int, float] = {2: 0.40, 3: 0.60, 4: 0.85, 5: 1.00, 6: 1.00}


def years_fraction(years: int | None) -> float | None:
    """年限 → [0,1]；None 表示未读到（调用方必须当"未知"，不是 0）。"""
    if years is None:
        return None
    for limit, value in YEAR_BANDS:
        if limit is None or years < limit:
            return value
    return 1.00


def education_fraction(rank: int | None, required_rank: int | None) -> float | None:
    """学历 → [0,1]。JD 未声明门槛时，读到了就算满（门槛缺失是 JD 的缺口，不是人的问题）。"""
    if required_rank is None:
        return None if rank is None else 1.00
    if rank is None:
        return None
    return EDU_BANDS.get(rank, 0.60)


def score_from_parts(*, skills_ratio: float, years: int | None,
                     required_years: int | None, education_rank: int | None,
                     required_education_rank: int | None) -> tuple[float, float, list[str]]:
    """v2 的核心：**接受已算好的技能覆盖率**，不再自己数技能。

    为什么要这一层：要求模型（`requirement` 表）上线后，"技能"这一项是
    **每条要求的覆盖率之均值**，不是"命中几个技能 / 要求几个技能"。若评分另算一套，
    分数与闸门就会各说各话——那正是这套系统一直在修的那类 bug。
    """
    parts: list[tuple[str, float, float]] = [("skills", skills_ratio, WEIGHTS["skills"])]
    unknowns: list[str] = []

    yf = years_fraction(years)
    if yf is None:
        unknowns.append("years")
    else:
        parts.append(("years", yf, WEIGHTS["years"]))

    ef = education_fraction(education_rank, required_education_rank)
    if ef is None:
        unknowns.append("education")
    else:
        parts.append(("education", ef, WEIGHTS["education"]))

    observed_w = sum(w for _, _, w in parts)
    score = round(100 * sum(r * w for _, r, w in parts) / observed_w, 2) if observed_w else 0.0
    completeness = round(100 * observed_w / sum(WEIGHTS.values()), 1)
    return score, completeness, unknowns


def score_v2(*, matched_skills: int, required_skills: int, years: int | None,
             required_years: int | None, education_rank: int | None,
             required_education_rank: int | None) -> tuple[float, float, list[str]]:
    """梯度分数。返回 `(score, completeness, unknowns)`。

    `completeness` 是**观测到的权重占总权重的百分比**（60/85/100 之类），供排序与披露使用。
    `required_years` 保留在签名里只为兼容调用方，v2 不拿它计分（D10）。
    """
    skills_ratio = (matched_skills / required_skills) if required_skills else 0.0
    return score_from_parts(skills_ratio=skills_ratio, years=years, required_years=required_years,
                            education_rank=education_rank,
                            required_education_rank=required_education_rank)


def order_key_v2(row: dict) -> tuple:
    """v2 排序键：分数 desc → **完整度 desc** → 年限 desc → id。

    完整度放在第二位，是因为实测：纯按分数排时 top-12 里信息完整者 0/12
    （满分被"年限没读到"的人占满）；加上完整度后 11/12。
    """
    return (-float(row.get("fit_score") or 0), -float(row.get("completeness") or 0),
            -(row.get("years_experience") or 0), row["candidate"])


def rank_rows_v2(rows: list[dict]) -> list[dict]:
    """同 `rank_rows`，但用 `order_key_v2`。"""
    out = []
    counters: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: (r["role_class"],) + order_key_v2(r)):
        counters[row["role_class"]] = counters.get(row["role_class"], 0) + 1
        out.append(dict(row, rank_in_role=counters[row["role_class"]]))
    return out
