#!/usr/bin/env python3
"""Move skills from English to Chinese without letting the move be a guess.

The model (2026-11-09): **Chinese is the loaded language.** `backend/skills/builtin/<id>/SKILL.md` holds
Chinese text; the English it came from is archived to `backend/skills/en-originals/<id>/SKILL.md`, which
lives outside both skill roots so nothing stages or indexes it. `backend/skills/pending-zh.txt` names the
skills still in English.

That leaves a gap between "someone produced Chinese text" and "the library now serves Chinese text", and
this script is the only way across it. A translation is written to
`backend/skills/.zh-staging/<id>.md`, checked against its archived English original, and only then
promoted. The checks are the ones `tests/test_skill_translations.py` enforces, run *before* the file can
become the version agents read:

  * structure parity — same number of `##` headings, same number of code fences. A translation that
    dropped a step is a different procedure under the same name, and no loader can see it.
  * the loader delimiters — `## Instructions` / `## Examples` stay recognisable to a prefix match, because
    `SkillLoader._parse_body_sections` and `skill_row_to_markdown` both key off those words. Translating
    them does not raise; it silently reinterprets the whole body as instructions.
  * CJK density — "ran it through a translator that gave up" is caught here.
  * frontmatter — `lang: zh`, `translated: human|machine`, and `source:` pointing at the archived English,
    so a reader can always find what this text came from.
  * `SkillLoader` itself parses the staged file.

Usage::

    python scripts/skill_zh.py archive <id> [<id> ...]   # stage the English original (idempotent)
    python scripts/skill_zh.py check   <id> [<id> ...]   # validate staged translations, change nothing
    python scripts/skill_zh.py promote <id> [<id> ...]   # check, install, drop from pending-zh.txt
    python scripts/skill_zh.py status                    # how many skills are in which language

Every write is a whole-file write of validated text; nothing here edits a body.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
BUILTIN = BACKEND / "skills" / "builtin"
ARCHIVE = BACKEND / "skills" / "en-originals"
STAGING = BACKEND / "skills" / ".zh-staging"
PENDING = BACKEND / "skills" / "pending-zh.txt"
ZH_NATIVE = BACKEND / "skills" / "zh-native.txt"

DELIMITERS = ("## Instructions", "## Examples")
# Measured across the first five hand translations: 1.14-1.91 CJK characters per English word. The floor
# scales with the original because a translation cannot be larger than its source — a fixed floor of 200
# failed honest translations of the two-line demo skills, which is the wrong direction for a guard to fail.
CJK_PER_EN_WORD_MIN = 0.6
# Density inside the Chinese file: tool names, code and identifiers stay English, but the prose must not.
CJK_VS_LATIN_MIN = 0.15


class Rejected(Exception):
    """A staged translation that must not become the version agents read."""


# ---------------------------------------------------------------------------
# text helpers (kept in step with tests/test_skill_translations.py)
# ---------------------------------------------------------------------------
def body_of(text: str) -> str:
    end = text.find("\n---", 3)
    return text[end + 4:] if text.startswith("---") and end != -1 else text


def frontmatter_of(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    fields: dict[str, str] = {}
    key = None
    for line in (text[3:end] if end != -1 else "").splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip().strip('"')
        elif key and line.strip():
            fields[key] += " " + line.strip().strip('"')
    return fields


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def latin_words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z]{3,}\b", text))


def shape(text: str) -> tuple[int, int]:
    lines = text.splitlines()
    headings = sum(1 for ln in lines if re.match(r"^##\s+", ln))
    fences = sum(1 for ln in lines if ln.startswith("```"))
    return headings, fences


def list_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", line):
            out.append(line)
    return out


def write_list_file(path: Path, ids: list[str], header: str) -> None:
    body = "\n".join(header.splitlines()) + "\n\n" + "\n".join(sorted(ids)) + "\n"
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def archive(ids: list[str]) -> int:
    """Copy the English SKILL.md into en-originals/ so the translation has a fixed source."""
    rc = 0
    for skill_id in ids:
        live, kept = BUILTIN / skill_id / "SKILL.md", ARCHIVE / skill_id / "SKILL.md"
        if not live.is_file():
            print(f"  REFUSE  {skill_id}: {live} does not exist", file=sys.stderr)
            rc = 1
            continue
        if kept.is_file():
            print(f"  exists  {skill_id}: already archived, left alone")
            continue
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(live, kept)
        print(f"  archived {skill_id}: {cjk_count(body_of(kept.read_text()))} CJK chars in the original "
              f"(0 expected — it is the English)")
    return rc


def check(ids: list[str]) -> int:
    """Validate staged translations. Returns 1 if anything was rejected."""
    rc = 0
    for skill_id in ids:
        try:
            validate(skill_id)
            print(f"  ok      {skill_id}")
        except Rejected as exc:
            print(f"  REJECT  {skill_id}: {exc}", file=sys.stderr)
            rc = 1
    return rc


def english_source(skill_id: str) -> Path:
    """Where the English is: the archive once translated, else the live file.

    Before promotion the live `builtin/<id>/SKILL.md` *is* the English, so translating from it and
    archiving it at promotion time keeps the repo consistent at every intermediate moment — no window
    where an archive sits beside an English body, which the test rightly calls a lie.
    """
    kept = ARCHIVE / skill_id / "SKILL.md"
    return kept if kept.is_file() else BUILTIN / skill_id / "SKILL.md"


def validate(skill_id: str) -> str:
    """Return the validated staged text or raise Rejected with the reason."""
    staged = STAGING / f"{skill_id}.md"
    if not staged.is_file():
        raise Rejected(f"nothing staged at {staged.relative_to(REPO)}")
    kept = english_source(skill_id)
    if not kept.is_file():
        raise Rejected(f"no English original to compare against ({kept.relative_to(REPO)} missing)")
    if cjk_count(body_of(kept.read_text(encoding="utf-8"))) > 200:
        raise Rejected(f"{kept.relative_to(REPO)} is already Chinese — this skill was promoted already, "
                       "or its English original was overwritten; restore the English first")

    zh_text, en_text = staged.read_text(encoding="utf-8"), kept.read_text(encoding="utf-8")
    zh_body, en_body = body_of(zh_text), body_of(en_text)

    fm = frontmatter_of(zh_text)
    if fm.get("lang") != "zh":
        raise Rejected("frontmatter must say `lang: zh`")
    if fm.get("translated") not in {"human", "machine"}:
        raise Rejected("frontmatter must say `translated: human` or `translated: machine`")
    if not fm.get("source", "").endswith(f"en-originals/{skill_id}/SKILL.md"):
        raise Rejected(f"frontmatter `source:` must end with en-originals/{skill_id}/SKILL.md, "
                       f"got {fm.get('source')!r}")
    for field in ("name", "description"):
        if not fm.get(field):
            raise Rejected(f"frontmatter lost `{field}`")

    zh_shape, en_shape = shape(zh_body), shape(en_body)
    if zh_shape[0] != en_shape[0]:
        raise Rejected(f"{zh_shape[0]} `##` headings against {en_shape[0]} in the English — a dropped step "
                       "is a different procedure under the same name")
    if zh_shape[1] != en_shape[1]:
        raise Rejected(f"{zh_shape[1]} code fences against {en_shape[1]} — the commands are the part that "
                       "gets executed")

    cjk, latin = cjk_count(zh_body), latin_words(zh_body)
    floor = max(3, round(latin_words(en_body) * CJK_PER_EN_WORD_MIN))
    if cjk < floor:
        raise Rejected(f"{cjk} CJK characters against {latin_words(en_body)} English words in the original "
                       f"(floor {floor}) — agents would still be reading English")
    if cjk < latin * CJK_VS_LATIN_MIN:
        raise Rejected(f"{latin} English words against {cjk} CJK characters — mostly untranslated")

    for delimiter in DELIMITERS:
        en_has = any(ln.startswith(delimiter) for ln in en_body.splitlines())
        zh_has = any(ln.startswith(delimiter) for ln in zh_body.splitlines())
        if en_has and not zh_has:
            raise Rejected(f"the English has a `{delimiter}` line and the Chinese does not — keep that word "
                           f"and add the Chinese in parentheses: `{delimiter}（…）`")

    # The real loader, on a real directory: frontmatter plus sections must survive.
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / skill_id
        probe.mkdir()
        (probe / "SKILL.md").write_text(zh_text, encoding="utf-8")
        sys.path.insert(0, str(BACKEND))
        from core.skills.loader import SkillLoader

        parsed = SkillLoader().load_skill(str(probe))
    if parsed is None:
        raise Rejected("SkillLoader refused the staged file")
    if cjk_count(parsed.instructions) < floor:
        raise Rejected(f"the parsed instructions hold {cjk_count(parsed.instructions)} CJK characters (floor "
                       f"{floor}) — check the `## Instructions` line, it may have been translated")
    if parsed.examples is not None and cjk_count(parsed.examples) == 0:
        raise Rejected("`## Examples` section parsed but is not Chinese")
    return zh_text


def promote(ids: list[str]) -> int:
    """Install validated translations and drop them from the pending list."""
    pending = list_file(PENDING)
    zh_native = set(list_file(ZH_NATIVE))
    rc = 0
    installed = []
    for skill_id in ids:
        try:
            zh_text = validate(skill_id)
        except Rejected as exc:
            print(f"  REJECT  {skill_id}: {exc}", file=sys.stderr)
            rc = 1
            continue
        if skill_id in zh_native:
            print(f"  REFUSE  {skill_id}: listed in zh-native.txt (authored in Chinese), not a translation",
                  file=sys.stderr)
            rc = 1
            continue
        if not (ARCHIVE / skill_id / "SKILL.md").is_file():
            # Freeze the English in the same breath as installing the Chinese: an archive that exists
            # beside an English body is a claim the test rejects, so the two writes belong together.
            kept = ARCHIVE / skill_id / "SKILL.md"
            english = english_source(skill_id)
            if cjk_count(body_of(english.read_text(encoding="utf-8"))) > 200:
                print(f"  REFUSE  {skill_id}: the live file is not English, so there is nothing to archive",
                      file=sys.stderr)
                rc = 1
                continue
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(english, kept)
            print(f"  archived {skill_id} → {kept.relative_to(REPO)}")
        (BUILTIN / skill_id / "SKILL.md").write_text(zh_text, encoding="utf-8")
        (STAGING / f"{skill_id}.md").unlink()
        installed.append(skill_id)
        print(f"  promoted {skill_id}")

    if installed:
        remaining = [pid for pid in pending if pid not in set(installed)]
        write_list_file(PENDING, remaining, PENDING_HEADER)
        print(f"\n  pending-zh.txt: {len(pending)} → {len(remaining)}")
    if installed:
        print("\n  Next: restart the backend (or POST /api/skills/reload-all) so the DB serves the new text,\n"
              "  then: cd backend && .venv/bin/python -m pytest tests/test_skill_translations.py -q")
    return rc


PENDING_HEADER = """# Skills still waiting for Chinese text.
#
# `backend/skills/builtin/<id>/SKILL.md` is the text an agent reads. It is Chinese for every skill that has
# an English original under `backend/skills/en-originals/<id>/`; the list below is the rest — still English,
# and nobody should pretend otherwise.
#
# The test asserts this file matches reality in BOTH directions: a translated skill must leave the list, and
# a listed skill must actually still be English. That is what stops the backlog from becoming decoration.
#
# States: translated (archived original) · authored in Chinese (zh-native.txt) · still English (here).
#
# Move a skill with `python scripts/skill_zh.py promote <id>`, never by hand: promote refuses a translation
# whose structure or frontmatter disagrees with the archived English."""


def status() -> int:
    ids = sorted(d.name for d in BUILTIN.iterdir() if (d / "SKILL.md").is_file())
    archived = {d.name for d in ARCHIVE.iterdir() if (d / "SKILL.md").is_file()} if ARCHIVE.is_dir() else set()
    zh_native, pending = set(list_file(ZH_NATIVE)), set(list_file(PENDING))
    staged = {p.stem for p in STAGING.glob("*.md")} if STAGING.is_dir() else set()
    print(f"  skills           {len(ids)}")
    print(f"  translated       {len(archived & set(ids))}")
    print(f"  authored in zh   {len(zh_native)}")
    print(f"  pending English  {len(pending)}")
    print(f"  staged, checked  {len(staged)}")
    total = sum((BUILTIN / i / 'SKILL.md').stat().st_size for i in pending)
    print(f"  English left     {total/1024:.0f} KB across {len(pending)} skills")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["archive", "check", "promote", "status"])
    parser.add_argument("skills", nargs="*", help="skill ids (folder names under backend/skills/builtin)")
    args = parser.parse_args(argv)
    if args.command == "status":
        return status()
    if not args.skills:
        parser.error("name at least one skill id")
    ids = []
    for skill_id in args.skills:
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
            ids.append(skill_id)
        else:
            # `.zh-staging/` also holds the translation brief; a shell glob over it must not abort the run
            # with "not a kebab-case skill id" half way through a batch.
            print(f"  ignore  {skill_id}: not a skill id", file=sys.stderr)
    if not ids:
        parser.error("none of the given names is a skill id")
    return {"archive": archive, "check": check, "promote": promote}[args.command](ids)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
