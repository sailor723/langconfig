"""The sidebar's bottom Search row — the checks a machine can make.

Measured context: the search panel was found twice by mistake, because its only entry was a 14px glyph in
the sidebar's 35px header and the panel it opens looks like the tree's own filter box. A permanent row at
the bottom of the sidebar was added (`e688d95b`) with both entries live.

What is pinned here is only what static analysis can honestly settle:

1. the labels are i18n keys, not literals — the shell is bilingual and a hardcoded label breaks one side;
2. both keys exist in **both** language blocks;
3. the row sits between the content area and the status bar (i.e. it is the bottom, not a second header);
4. the row toggles the same `sidebarView` expression as the header icon — one view, two doors;
5. the whole sidebar (row included) is absent under Settings and Vault, which return null.

What this file cannot settle: that a click *feels* right, that the row flips to "Back to the file list"
while search is open, and that the Chinese labels render. Those are marked PARTIAL in
`docs/specs/sidebar-search-entry.validation.md`, with what would settle them.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SIDEBAR = REPO / "src" / "components" / "layout2" / "LeftSidebar.tsx"
I18N = REPO / "src" / "i18n" / "index.ts"


def _sidebar() -> str:
    return SIDEBAR.read_text(encoding="utf-8")


def test_labels_come_from_i18n_not_from_the_component():
    src = _sidebar()
    assert "tr('sb_search_entry')" in src and "tr('sb_search_back')" in src, (
        "the bottom row must take its labels from i18n (tr('sb_search_entry') / tr('sb_search_back'))")
    # a literal would mean one language silently wins
    assert "Search workspace files & workflows" not in src, (
        "the label is hardcoded in the component — it belongs in src/i18n/index.ts")


def test_both_labels_exist_in_both_languages():
    text = I18N.read_text(encoding="utf-8")
    for key in ("sb_search_entry", "sb_search_back"):
        hits = re.findall(rf'"{key}":\s*"([^"]*)"', text)
        assert len(hits) == 2, f'{key} must be defined twice (en + zh), found {len(hits)}'
        assert all(h.strip() for h in hits), f"{key} has an empty translation: {hits}"
        assert hits[0] != hits[1], f"{key} has the same text in both languages: {hits[0]!r}"


def test_the_row_is_below_the_content_and_above_the_status_bar():
    # Anchors are the JSX comment markers, not bare words: "Status bar" also appears in the file's own
    # header comment (line 8), which made an earlier version of this check compare line 8 against the row.
    src = _sidebar()
    content = src.index("{/* ── Content ")
    row = src.index("{/* ── Bottom entry: search")
    status = src.index("{/* ── Status bar")
    assert content < row < status, (
        "the search row must sit after the content area and before the status bar — it is the bottom "
        f"entry, not another header (content@{content}, row@{row}, status@{status})")


def test_both_doors_open_the_same_view():
    src = _sidebar()
    toggle = "setSidebarView(isSearch ? 'explorer' : 'search')"
    assert src.count(toggle) >= 2, (
        "the header icon and the bottom row must both call the same toggle expression; one of them "
        "has drifted (a second way to set the view is how two panels start)")


def test_the_sidebar_still_disappears_in_settings_and_vault():
    src = _sidebar()
    assert "if (!sidebarOpen || activeActivity === 'settings' || activeActivity === 'vault') return null;" in src, (
        "the guard that hides the whole sidebar must stay: the bottom row is inside it, so Settings and "
        "Vault must not show a search entry that points at the side bar's view state")
