"""The sidebar must highlight the category of the skill that is OPEN — pinned statically.

Why this is a test and not a habit: the highlight is derived, not clicked. A reader reaches a skill from five
places (sidebar row, category grid, home-page card, badge, picker, a search result), and only the sidebar row
carries a click that could plausibly "own" the state. Deriving it from the active tab is what makes the
highlight true in all five cases; a test keeps it derived instead of drifting back to click state.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SIDEBAR = REPO / "src" / "components" / "layout2" / "SkillBrowserSidebar.tsx"


def _src() -> str:
    return SIDEBAR.read_text(encoding="utf-8")


def test_the_active_category_is_derived_from_the_active_tab():
    src = _src()
    assert "activeTabId" in src.split("const renderCategoryGroupRow")[0], (
        "the sidebar must read the active tab — a highlight driven by the click that opened something is "
        "wrong the moment the skill is opened from anywhere else")
    block = src[src.index("const activeCategory"):src.index("const renderCategoryGroupRow")]
    assert "skill-cat-" in block, "a category tab must resolve to its own row"
    assert re.search(r"\^skill-\(\?:edit-\)\?\(\.\+\)\$", block), (
        "both skill tab shapes (view and edit) must resolve to the skill's category")


def test_the_open_skill_resolves_through_the_taxonomy_not_by_name():
    src = _src()
    block = src[src.index("const activeCategory"):src.index("const renderCategoryGroupRow")]
    assert "categoryForSkill(" in block, (
        "the category must come from the shared taxonomy (categoryForSkill), so the highlight and the rows "
        "can never disagree")
    assert "skills.find(x => x.skill_id === skillId)" in block, (
        "prefer the loaded row (it carries tags); fall back to the bare id when the list is filtered")


def test_the_row_renders_the_highlight_as_state_not_as_hover():
    src = _src()
    # "const renderCategory" is a PREFIX of "const renderCategoryGroupRow", so the end marker must be the
    # definition itself (`const renderCategory = (`) — the first attempt sliced an empty string and the
    # assertion failed for a reason that had nothing to do with the highlight.
    row = src[src.index("const renderCategoryGroupRow"):]
    marker = "const renderCategory = ("
    row = row[:row.index(marker)] if marker in row else row
    assert "const isActive = activeCategory === category;" in row
    assert "data-active={isActive ? '1' : '0'}" in row, (
        "data-active lets the property be asserted from a DOM test instead of guessing at styles")
    assert "background: isActive ? t.bgSelected : 'transparent'" in row
    assert "borderLeft: `2px solid ${isActive ? t.accent : 'transparent'}`" in row, (
        "the accent bar is the second signal the other rails in this shell use for 'where you are'")
    # hover must not overwrite the active fill
    assert "onMouseLeave={e => { e.currentTarget.style.background = isActive ? t.bgSelected : 'transparent'; }}" in row
