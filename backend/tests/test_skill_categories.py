"""Every skill has exactly one home in the taxonomy — checked against the same rules the UI uses.

The Skills activity used to group by `source_type` alone (Builtin / My Skills), which stops being useful at
110 skills. The Tools activity already had a real taxonomy: a `category` on every tool, a sidebar row per
category with a count, category badges on the cards, and a tab that lists one category.

The skills taxonomy lives in ONE file — `src/components/layout2/skill-categories.rules.json` — because this
test has to map the same skills through the same rules. A second copy of a taxonomy is how two surfaces
start disagreeing. This test is the reason a new skill cannot appear under "Other" by accident: adding a
skill without a category fails here, on the machine that added it.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILLS = REPO / "backend" / "skills" / "builtin"
RULES = REPO / "src" / "components" / "layout2" / "skill-categories.rules.json"

#: The only skills allowed to sit in `other`: they are demos, not work.
OTHER_ALLOWED = {"friendly-weather-greeter"}


def _rules() -> dict:
    return json.loads(RULES.read_text(encoding="utf-8"))


def _skill_ids() -> list[str]:
    return sorted(d.name for d in SKILLS.iterdir() if (d / "SKILL.md").is_file())


def _frontmatter_tags(skill_id: str) -> list[str]:
    text = (SKILLS / skill_id / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    head = text.split("---")[1] if text.startswith("---") else ""
    m = re.search(r"^tags:\s*\n((?:\s+-\s.*\n)+)", head, re.M)
    if m:
        return [ln.strip()[2:].strip() for ln in m.group(1).splitlines() if ln.strip().startswith("-")]
    m = re.search(r"^tags:\s*\[(.*)\]\s*$", head, re.M)
    if m:
        return [t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]
    return []


def category_for(skill_id: str, rules: dict) -> str:
    """The SAME order the TypeScript applies: prefix → override → tag rule → other."""
    for prefix, category in (rules["rules"]["prefix"] or {}).items():
        if skill_id.startswith(prefix):
            return category
    overrides = rules["overrides"] or {}
    if skill_id in overrides:
        return overrides[skill_id]
    # the TS tag rules, in order; mirrored here because the point of this test is to disagree loudly if
    # the two ever diverge on the current skill set
    tag_rules = [
        ("ontology", "ontology"), ("semantic-layer", "ontology"),
        ("data-analysis", "data"), ("sql", "data"), ("pandas", "data"), ("csv", "data"),
        ("langgraph", "ecosystem"), ("langchain", "ecosystem"), ("deepagents", "ecosystem"),
        ("testing", "quality"), ("review", "quality"), ("security", "quality"), ("debugging", "quality"),
        ("requirements", "requirements"), ("planning", "requirements"), ("tickets", "requirements"),
        ("research", "research"), ("web-search", "research"),
        ("writing", "documents"), ("documentation", "documents"), ("presentation", "documents"),
        ("agents", "agents"), ("skills", "agents"), ("tools", "agents"),
    ]
    tags = {t.lower() for t in _frontmatter_tags(skill_id)}
    for tag, category in tag_rules:
        if tag in tags:
            return category
    return "other"


def test_the_rules_file_declares_a_real_taxonomy():
    rules = _rules()
    ids = [c["id"] for c in rules["categories"]]
    assert len(ids) >= 5, "a taxonomy with fewer than five groups is not a taxonomy"
    assert len(ids) == len(set(ids)), "two categories share an id"
    for c in rules["categories"]:
        assert c["label"] and c["blurb"], f"{c['id']} needs a label and a one-line blurb"
    assert "other" in ids, "there must be a place for the uncategorised, so the UI never renders blank"


@pytest.mark.parametrize("skill_id", _skill_ids())
def test_every_skill_lands_in_a_declared_category(skill_id: str):
    rules = _rules()
    category = category_for(skill_id, rules)
    declared = {c["id"] for c in rules["categories"]}
    assert category in declared, (
        f"{skill_id} → {category!r}, which is not a declared category — add it to "
        "src/components/layout2/skill-categories.rules.json")


def test_nobody_drifts_into_other():
    rules = _rules()
    strays = [s for s in _skill_ids()
              if category_for(s, rules) == "other" and s not in OTHER_ALLOWED]
    assert not strays, (
        "these skills have no category (they would silently pile up under 'Other'): "
        f"{strays} — add an override in skill-categories.rules.json")


def test_overrides_only_name_skills_that_exist():
    rules = _rules()
    existing = set(_skill_ids())
    ghosts = sorted(set(rules["overrides"]) - existing)
    assert not ghosts, f"the rules name skills that are not in the library: {ghosts}"


def test_every_category_is_used():
    rules = _rules()
    used = {category_for(s, rules) for s in _skill_ids()}
    empty = [c["id"] for c in rules["categories"] if c["id"] not in used]
    assert not empty, f"categories with nothing in them would render as dead rows: {empty}"
