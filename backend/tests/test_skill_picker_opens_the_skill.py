"""The Skills picker's cards must open the skill they show — pinned statically.

Measured: the picker's subtitle said "Pick an existing skill to clone", and every card ran through the
clone path (`skill_id: undefined`), so clicking a skill opened a blank editor titled "Clone: …" while the
skill's real definition was nowhere. The left sidebar, which opens the skill itself, was correct — that
asymmetry is the bug, and it is invisible to a loader or a type-checker because both paths compile.

What can be checked without a browser:
  * the picker routes skill cards to `openSkillCard` (a detail/editor tab for the existing id), not to the
    clone tab builder;
  * cloning survives as its own action, so the old behaviour is not simply deleted;
  * a card without a `skill_id` is refused with a message instead of opening an editor for nothing;
  * the sidebar/homepage and the picker agree on the tab shape for the same skill.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PICKER = REPO / "src" / "components" / "layout2" / "TemplatePicker.tsx"
SIDEBAR = REPO / "src" / "components" / "layout2" / "SkillBrowserSidebar.tsx"
HOME = REPO / "src" / "components" / "layout2" / "SkillHomePage.tsx"


def _picker() -> str:
    return PICKER.read_text(encoding="utf-8")


def test_skill_cards_open_the_skill_not_a_clone():
    src = _picker()
    assert "if (activity === 'skills') { openSkillCard(tmpl); return; }" in src, (
        "clicking a skill card must open that skill; it currently falls through to the clone path")
    open_fn = src[src.index("const openSkillCard"):src.index("const handlePick")]
    assert "skill-${skill.skill_id}" in open_fn and "skill-edit-${skill.skill_id}" in open_fn, (
        "openSkillCard must build the same two tab ids the sidebar uses (detail for builtin, editor for "
        "personal) — a third spelling is how the two surfaces drifted apart")


def test_cloning_is_kept_as_an_explicit_action():
    src = _picker()
    assert "const handleClone" in src, "the clone behaviour must remain reachable (as its own action)"
    assert "onSecondary: () => handleClone(tmpl)" in src, "no card carries the clone action"
    assert "tp_clone_skill" in src, "the clone action has no label"


def test_a_card_without_a_skill_id_is_refused():
    src = _picker()
    assert "if (!skill.skill_id) {" in src and "setError(" in src, (
        "a card with no id must say so, not open `skill-edit-undefined` — an editor with no skill is "
        "indistinguishable from 'new skill'")


def test_picker_and_sidebar_agree_on_the_tab_ids():
    picker, sidebar = _picker(), SIDEBAR.read_text(encoding="utf-8")
    for tab_id in ("skill-${skill.skill_id}", "skill-edit-${skill.skill_id}"):
        assert tab_id in picker, f"picker lost {tab_id}"
        assert tab_id in sidebar, f"sidebar no longer builds {tab_id} — the shapes have diverged"
    # both must send `skillId` for the detail view, which is what SkillView reads
    assert "data: { skillId: skill.skill_id, skill }" in picker
    assert "data: { skillId: skill.skill_id, skill }" in sidebar


def test_homepage_cards_keep_the_same_rule():
    home = HOME.read_text(encoding="utf-8")
    assert "isBuiltin ? openSkill(skill) : openEdit(skill)" in home, (
        "the homepage's rule (builtin → detail, personal → editor) is the behaviour the picker now copies; "
        "if it changes here, change the picker too")
    assert re.search(r"id: `skill-\$\{skill\.skill_id\}`", home)
