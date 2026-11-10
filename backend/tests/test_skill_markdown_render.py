"""The skill viewer renders markdown — the checks that keep it honest.

A skill's `description` and its `instructions` are markdown: `## Instructions（指令）`, gates in bold, tables of
gates, fenced commands. Both were shown as plain text, so an agent's own documentation read as source code and
the work of reading a skill — the one thing this activity exists for — was half spent re-assembling the markup.

These checks assert the four things a reviewer of that change would want:

1. **The view uses the renderer** for both fields, and the raw text is still reachable (a dev may need to copy
   the source, and "rendered" must not be the only option).
2. **No raw HTML executes.** A SKILL.md is third-party text — 58 of the 102 skills are vendored MIT work — so the
   renderer must not be a `dangerouslySetInnerHTML` sink.
3. **A card stays plain text.** Cards clamp to three lines; markdown in them shows as literal backticks, which is
   the bug this file exists to prevent, one level down.
4. **`#`-links do nothing**, because the shell is a HashRouter and a hash change unmounts the view.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
VIEW = REPO / "src" / "components" / "layout2" / "SkillView.tsx"
MD = REPO / "src" / "components" / "layout2" / "MarkdownText.tsx"
HOME = REPO / "src" / "components" / "layout2" / "SkillHomePage.tsx"


def test_the_renderer_is_wired_into_the_skill_view():
    view = VIEW.read_text(encoding="utf-8")
    assert "import MarkdownText" in view, "SkillView does not import the markdown renderer"
    assert "<MarkdownText text={skill.description}" in view, "the description still renders as plain text"
    assert "<MarkdownText text={skill.instructions}" in view, "the instructions body still renders as plain text"


def test_the_raw_markdown_is_still_reachable():
    view = VIEW.read_text(encoding="utf-8")
    assert "setView('source')" in view or "setView(mode)" in view, (
        "there is no way to switch back to the source — a skill's markdown is what an agent reads, and a reader "
        "comparing the two needs it")
    assert "sv_rendered" in view and "sv_source" in view, "the rendered/source switch has no labels"


def test_the_renderer_cannot_execute_html():
    md = MD.read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in md, (
        "a SKILL.md is third-party text (58 of 102 skills are vendored MIT work) — it may not execute here")
    assert "react-markdown" in md, "the renderer should be react-markdown, which ignores raw HTML by default"
    assert "rehype-raw" not in md, "rehype-raw would enable exactly the raw HTML this view must not allow"


def test_hash_links_do_not_navigate():
    md = MD.read_text(encoding="utf-8")
    assert "startsWith('#')" in md, (
        "an in-document `#anchor` must not change the hash: the shell is a HashRouter and the view would unmount")


def test_cards_strip_markdown_instead_of_showing_asterisks():
    home = HOME.read_text(encoding="utf-8")
    assert "stripMarkdown(" in home, "the skill card still prints raw markdown in a three-line clamp"
    md = MD.read_text(encoding="utf-8")
    assert re.search(r"export function stripMarkdown", md), "stripMarkdown is not exported"


def test_the_prompt_tab_renders_behind_a_boundary():
    """A prompt is database text, and one pathological document must not blank the tab.

    The renderer is behind `MarkdownBoundary`, which falls back to the raw text and logs why. Without it a throw
    inside react-markdown unmounts the view: the user sees a blank page with nothing to act on, and the only trace
    is a console error they have no reason to open.
    """
    view = (REPO / "src" / "components" / "layout2" / "PromptDetailTab.tsx").read_text(encoding="utf-8")
    assert "<MarkdownBoundary" in view, "the prompt body renders without a boundary"
    md = (REPO / "src" / "components" / "layout2" / "MarkdownText.tsx").read_text(encoding="utf-8")
    assert "componentDidCatch" in md and "getDerivedStateFromError" in md
    assert "typeof rawText === 'string'" in view, (
        "a restored tab can arrive without promptText, and `promptText.length` then throws — which looks exactly "
        "like a blank page")


def test_copy_and_download_sit_in_the_header():
    """Both act on the whole skill, so they belong at the top — not at the end of a body that can be 45 KB.

    They used to live inside the Instructions card, after the rendered body: reaching them meant scrolling past
    everything you had just decided to copy.
    """
    view = (REPO / "src" / "components" / "layout2" / "SkillView.tsx").read_text(encoding="utf-8")
    header = view.split("{/* Header */}", 1)[1].split("{/* Description", 1)[0]
    assert "tr('c_copy')" in header and "tr('c_download')" in header, "the buttons left the header"
    assert header.index("tr('c_copy')") < header.index("tr('c_download')"), "order should be copy → download"
    assert "navigator.clipboard.writeText" in header, "the copy handler did not move with the button"
    rest = view.split("{/* Description", 1)[1]
    assert "tr('c_copy')" not in rest and "tr('c_download')" not in rest, (
        "a second copy of the buttons survived below the fold")


def test_the_view_puts_triggers_under_the_description_and_keeps_the_numbers_by_the_tags():
    """Reading order in the skill view: description → triggers → the chip row (tags, runs, rate, tools).

    Triggers are the sentences the matcher reads, so they sit where the reading starts, full width. The numbers belong
    with the chips they describe. Both were full-width rows somewhere below the fold before they were moved.
    """
    view = (REPO / "src" / "components" / "layout2" / "SkillView.tsx").read_text(encoding="utf-8")

    desc_at = view.index("{/* Description")
    triggers_at = view.index("{/* Triggers")
    chips_at = view.index("{/* Metadata chips")
    assert desc_at < triggers_at < chips_at, "expected description → triggers → metadata chips"

    triggers_block = view[triggers_at:chips_at]
    assert "skill.triggers.map" in triggers_block, "the triggers card is not the one under the description"
    assert "runs" not in triggers_block, "the numbers do not belong in the triggers block"

    chips_row = view[chips_at:].split("{/* Instructions", 1)[0]
    assert "<Tag size={11} /> Tags" in chips_row, "the tags card left the chip row"
    assert "runs" in chips_row and "served without error" in chips_row, (
        "the usage and success-rate boxes left the chip row")
    assert chips_row.index("Tags") < chips_row.index("runs") < chips_row.index("served without error"), (
        "order inside the chip row should be Tags → runs → success rate")
    assert "skill.triggers.map" not in chips_row, "a second copy of the triggers card is still in the chip row"
