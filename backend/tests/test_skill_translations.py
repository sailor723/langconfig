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
    body = _body(BUILTIN / skill_id / "SKILL.md")
    cjk = _cjk(body)
    latin = len(re.findall(r"\b[A-Za-z]{3,}\b", body))
    assert cjk > 200, f"{skill_id}: SKILL.md has only {cjk} CJK characters — agents are reading English"
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
    body = _body(BUILTIN / skill_id / "SKILL.md")
    assert _cjk(body) > 200, (
        f"{skill_id} is listed in zh-native.txt but {_cjk(body)} CJK characters is not Chinese text")


@pytest.mark.parametrize("skill_id", sorted(_pending()))
def test_a_pending_skill_really_is_english(skill_id: str):
    body = _body(BUILTIN / skill_id / "SKILL.md")
    assert _cjk(body) < 200, (
        f"{skill_id} looks translated but is listed as pending — move it out of pending-zh.txt so the "
        "structure checks start applying to it")
