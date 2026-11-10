"""Chinese is the skill language; English is an archive nothing loads — and the backlog is honest.

The decision (2026-11-09): **the text an agent reads is Chinese.** `backend/skills/builtin/<id>/SKILL.md`
holds the Chinese working text, and the English it came from is kept in
`backend/skills/en-originals/<id>/SKILL.md` — outside both skill roots the loader scans, so nothing stages
it, indexes it, or puts it in a context unless a caller asks for `lang="en"` by name.

That leaves two ways to be dishonest, and this file closes both:

1. **A translation that is not one.** Structural parity is checked: same number of `##` headings, same
   number of fenced code blocks. A Chinese file that dropped a step is a different procedure under the same
   name, and no loader can see it. CJK density catches "run through a translator that gave up".
2. **A backlog that is decoration.** `backend/skills/pending-zh.txt` lists the skills still in English, and
   it is checked in BOTH directions: a translated skill must leave the list, a listed skill must actually
   still be English. So the file cannot drift into a wish-list, and nobody can claim 102 Chinese skills.

Text meaning is not machine-checkable and is not attempted here.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILTIN = REPO / "backend" / "skills" / "builtin"
ARCHIVE = REPO / "backend" / "skills" / "en-originals"
PENDING = REPO / "backend" / "skills" / "pending-zh.txt"
ZH_NATIVE = REPO / "backend" / "skills" / "zh-native.txt"


def _skill_ids() -> list[str]:
    return sorted(d.name for d in BUILTIN.iterdir() if (d / "SKILL.md").is_file())


def _archived() -> dict[str, pathlib.Path]:
    if not ARCHIVE.is_dir():
        return {}
    return {d.name: d / "SKILL.md" for d in ARCHIVE.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()}


def _list_file(path: pathlib.Path) -> set[str]:
    """One skill id per line; every `#` line is a comment (a wrapped paragraph is NOT an id).

    Measured: the first version of this reader took every non-comment line as an id, so the file's own
    explanation produced "skills" called `are still English and nobody should pretend otherwise.`.
    """
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", line):
            out.add(line)
    return out


def _pending() -> set[str]:
    return _list_file(PENDING)


def _zh_native() -> set[str]:
    return _list_file(ZH_NATIVE)


def _body(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    end = text.find("\n---", 3)
    return text[end + 4:] if text.startswith("---") and end != -1 else text


def _frontmatter(path: pathlib.Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    fields, key = {}, None
    for line in (text[3:end] if end != -1 else "").splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip().strip('"')
        elif key and line.strip():
            fields[key] += " " + line.strip().strip('"')
    return fields


def _cjk(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _prose(text: str) -> str:
    """The parts of a body that get translated: fenced blocks are code or templates, not prose.

    The floor is derived from these words only. Counting code words as if they needed Chinese set a floor that
    no honest translation could reach — measured on `debugging`, 679 English words of which ~208 are prose.
    """
    out, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def _floor(english_text: str) -> int:
    """How much Chinese this English earns: 0.6 CJK characters per English prose word, minimum 3.

    Measured across the hand translations: 1.14-1.91 CJK per English word. A translation cannot be larger
    than its source, so the floor has to scale with it rather than being a fixed number.
    """
    return max(3, round(len(re.findall(r"\b[A-Za-z]{3,}\b", _prose(english_text))) * 0.6))


def _shape(text: str) -> tuple[int, int]:
    headings = sum(1 for ln in text.splitlines() if re.match(r"^##\s+", ln))
    fences = sum(1 for ln in text.splitlines() if ln.startswith("```"))
    return headings, fences


def test_the_archive_is_outside_the_scanned_roots():
    """If the English originals sat under builtin/, the loader would index them as skills."""
    assert ARCHIVE.is_dir(), "the English originals must exist (they are the source of the Chinese text)"
    assert BUILTIN not in ARCHIVE.parents, "the archive must not live inside the scanned skill root"
    assert ARCHIVE.parent.name == "skills", (
        f"{ARCHIVE} is not beside the builtin/ and personal/ roots — check where the loader scans")


def test_there_is_at_least_one_translated_skill():
    archived = _archived()
    assert archived, "no skill has Chinese text yet, which makes `lang` and this file pointless"


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_a_translated_skill_is_actually_chinese(skill_id: str):
    """Chinese enough *for this original* — the size floor scales, the density check does not.

    A fixed floor of 200 CJK characters was wrong for one honest reason: a translation cannot be larger
    than its source. `ticket-classifier` is a two-line SKILL.md whose whole body is a title, so no faithful
    translation of it reaches 200 characters, and the old rule made an honest job look like a failure.
    Measured across the first five hand translations, Chinese runs 1.14-1.91 CJK characters per English
    word, so 0.6 is a floor that a real translation clears and a half-translated one does not.
    """
    body = _body(BUILTIN / skill_id / "SKILL.md")
    en_words = len(re.findall(r"\b[A-Za-z]{3,}\b", _prose(_body(ARCHIVE / skill_id / "SKILL.md"))))
    cjk = _cjk(body)
    latin = len(re.findall(r"\b[A-Za-z]{3,}\b", body))
    floor = _floor(_body(ARCHIVE / skill_id / "SKILL.md"))
    assert cjk >= floor, (
        f"{skill_id}: {cjk} CJK characters against {en_words} English words in the original (floor "
        f"{floor}) — agents are reading English")
    assert cjk >= latin * 0.15, (
        f"{skill_id}: {latin} English words against {cjk} CJK characters — the body is mostly untranslated")


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_structure_matches_the_english_original(skill_id: str):
    zh_headings, zh_fences = _shape(_body(BUILTIN / skill_id / "SKILL.md"))
    en_headings, en_fences = _shape(_body(_archived()[skill_id]))
    assert zh_headings == en_headings, (
        f"{skill_id}: {zh_headings} `##` headings in Chinese vs {en_headings} in the original — a dropped "
        "step is a different procedure under the same name")
    assert zh_fences == en_fences, (
        f"{skill_id}: {zh_fences} code fences vs {en_fences} — the commands are the part that gets executed, "
        "so they must survive translation")


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_the_frontmatter_records_where_english_lives(skill_id: str):
    fm = _frontmatter(BUILTIN / skill_id / "SKILL.md")
    assert fm.get("lang") == "zh", f"{skill_id}: frontmatter must say lang: zh"
    assert fm.get("source", "").endswith(f"en-originals/{skill_id}/SKILL.md"), (
        f"{skill_id}: frontmatter must point at the archived original, so a reader can find the English")
    assert fm.get("translated") in {"human", "machine"}, (
        f"{skill_id}: say whether a human or a machine produced this text")


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_the_loader_delimiters_survive_translation(skill_id: str):
    """`## Instructions` and `## Examples` are delimiters, not prose — the loader and the DB round-trip
    both match them by prefix.

    Found the hard way: the first five translations rendered the heading as `## 指令`, which stopped
    `SkillLoader._parse_body_sections` recognising the structured format. It did not fail, it silently
    switched to "the whole body is the instructions" — so `examples` became None and the examples block
    was no longer presented as examples. 66 of the 102 skills use that heading, so the convention is:
    keep the English word that starts the line and put the Chinese in parentheses after it.
    """
    for heading in ("## Instructions", "## Examples"):
        en_body, zh_body = _body(_archived()[skill_id]), _body(BUILTIN / skill_id / "SKILL.md")
        en_has = any(ln.startswith(heading) for ln in en_body.splitlines())
        zh_has = any(ln.startswith(heading) for ln in zh_body.splitlines())
        assert not (en_has and not zh_has), (
            f"{skill_id}: the English original has a `{heading}` line and the Chinese does not. Do not "
            f"translate that word — write `{heading}（…）` so the loader still finds it")


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_the_loader_still_parses_the_chinese_skill(skill_id: str):
    """A skill that parses is the minimum: name, description and instructions all non-empty."""
    from core.skills.loader import SkillLoader

    parsed = SkillLoader().load_skill(str(BUILTIN / skill_id))
    assert parsed is not None, f"{skill_id}: SkillLoader refused the Chinese SKILL.md"
    assert parsed.name and parsed.description, f"{skill_id}: name/description did not survive"
    # The floor comes from the ENGLISH instructions, not the English body: when `## Instructions` is present
    # the loaded body is only that section, so a body-derived floor would demand more Chinese than the
    # source contains and reject honest work (it did — and padding is the wrong way out).
    english = SkillLoader().load_skill(str(ARCHIVE / skill_id))
    assert _cjk(parsed.instructions) >= _floor(english.instructions if english else ""), (
        f"{skill_id}: the parsed instructions are not Chinese — the `## Instructions` line may have been "
        "translated, which silently turns the whole body into the instructions section")


def test_every_skill_is_in_exactly_one_language_state():
    """Three states, and every skill must be in exactly one: translated, authored in Chinese, or pending.

    A skill in no list has no declared language, which is the state this whole file exists to end.
    """
    archived, zh_native, pending, ids = set(_archived()), _zh_native(), _pending(), set(_skill_ids())
    both = sorted((archived & zh_native) | (archived & pending) | (zh_native & pending))
    assert not both, f"these skills are claimed by more than one language state: {both}"
    unknown = sorted((archived | zh_native | pending) - ids)
    assert not unknown, f"a language list names skills that do not exist: {unknown}"
    untracked = sorted(ids - archived - zh_native - pending)
    assert not untracked, (
        f"these skills have no declared language (not translated, not authored in Chinese, not pending): "
        f"{untracked}")


@pytest.mark.parametrize("skill_id", sorted(_zh_native()))
def test_an_authored_in_chinese_skill_really_is_chinese(skill_id: str):
    """`zh-native.txt` is a claim that the skill was written in Chinese, so it needs a density check.

    Found: `build-ontology-from-db` was listed as "authored in Chinese" while holding 502 CJK characters
    against 5 481 English words (ratio 0.09) — a 45 KB English document with Chinese headings. The old check
    only asked for "more than 200 CJK characters", which any long English file passes by accident.
    """
    body = _body(BUILTIN / skill_id / "SKILL.md")
    cjk = _cjk(body)
    latin = len(re.findall(r"\b[A-Za-z]{3,}\b", body))
    assert cjk > 200, f"{skill_id} is listed in zh-native.txt but has only {cjk} CJK characters"
    assert cjk >= latin * 0.15, (
        f"{skill_id} is listed as authored in Chinese but runs {latin} English words against {cjk} CJK "
        "characters — if it is a translation, it belongs in pending-zh.txt until it is translated")


@pytest.mark.parametrize("skill_id", sorted(_pending()))
def test_a_pending_skill_really_is_english(skill_id: str):
    """Pending means "what agents read is English" — the same density test the other two states get.

    A flat `< 200 CJK characters` was the wrong shape: `build-ontology-from-db` is a 45 KB English document
    that happens to carry 502 CJK characters in its headings, and the old rule therefore called it
    "translated". Density is what matters: prose that is mostly Chinese is Chinese, whatever its length.
    """
    body = _body(BUILTIN / skill_id / "SKILL.md")
    cjk = _cjk(body)
    latin = len(re.findall(r"\b[A-Za-z]{3,}\b", body))
    assert cjk < 200 or cjk < latin * 0.15, (
        f"{skill_id} reads as Chinese ({cjk} CJK against {latin} English words) but is listed as pending — "
        "move it out of pending-zh.txt so the structure and parity checks start applying to it")


@pytest.mark.parametrize("skill_id", sorted(_archived()), ids=str)
def test_the_frontmatter_keeps_every_key_the_original_had(skill_id: str):
    """A translation may rewrite prose; it may not drop a field other code reads.

    Found by an independent reviewer, in five skills: the hand-translated frontmatters kept only
    `name`/`lang`/`translated`/`source`/`description`. What went missing was `tags` (the taxonomy),
    `triggers` (the discovery cues the matcher reads), `allowed_tools` (the `**Allowed Tools:**` line in the
    agent prompt), `author`/`version` (the MIT attribution), and `params` — and `params` is not decorative:
    `core/skills/params.py` binds its values and renders "these are the values your skills are pointed at, do
    not re-derive them". `to-tickets` was telling the reader to read `spec_path` while nothing declared it, so
    the one input the whole skill gates on had no value and no default.

    The three keys a translation adds are excluded from the comparison.
    """
    added = {"lang", "translated", "source"}
    en = _frontmatter(ARCHIVE / skill_id / "SKILL.md")
    zh = _frontmatter(BUILTIN / skill_id / "SKILL.md")
    missing = sorted(set(en) - set(zh) - added)
    assert not missing, (
        f"{skill_id}: the original frontmatter has {missing} and the Chinese does not — those fields are read "
        "by code (tags by the taxonomy, triggers by the matcher, allowed_tools by the prompt, params by "
        "core/skills/params.py), not by readers")
