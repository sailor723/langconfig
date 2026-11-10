#!/usr/bin/env python3
"""Translated-skill fidelity: what a translator must not lose, measured instead of believed.

The other checks prove a translation is *shaped* like its original — same `##` headings, same fences, dense
enough Chinese, frontmatter pointing at the archive, the loader parses it. None of them look at whether the
words survived. This does, mechanically, on the two things a machine can compare:

  1. **Tokens.** Every backticked identifier, number, URL and path in the English prose must appear in the
     Chinese prose. A dropped `pg_query`, a rounded `0.94596`, a vanished `docs/tickets/NNN-<slug>.md` is a
     procedure that quietly does something else.
  2. **Fenced blocks.** Code must be byte-identical. A block that changed is either a document template (fine —
     that is the fence rule) or a mangled command (not fine), so every changed block is listed with its info
     string for a reader to judge.

What it cannot measure is meaning: a translation can keep every token and still lose the argument. That is what
a reviewer reads for, and why this report says "no token was lost" and never "the translation is good".

Usage::

    python scripts/skill_translation_fidelity.py             # all translated skills
    python scripts/skill_translation_fidelity.py code-review grilling
    python scripts/skill_translation_fidelity.py --fences    # also list every changed fence
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILTIN = REPO / "backend" / "skills" / "builtin"
ARCHIVE = REPO / "backend" / "skills" / "en-originals"

TOKEN = re.compile(r"`([^`\n]{2,})`")
URL = re.compile(r"https?://[^\s)`>\"']+")
PATHISH = re.compile(r"(?<![\w`])(?:[\w.<>-]+/)+[\w.<>-]+")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:%|ms|s|x)?(?![\w])")
FENCE = re.compile(r"^\s*```(\S*)")


def body_of(text: str) -> str:
    end = text.find("\n---", 3)
    return text[end + 4:] if text.startswith("---") and end != -1 else text


def split_fences(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (prose with fenced blocks removed, [(info, block_text), …])."""
    prose, blocks, current = [], [], None
    for line in text.splitlines():
        m = FENCE.match(line)
        if m:
            if current is None:
                current = [m.group(1).strip(), []]
            else:
                blocks.append((current[0], "\n".join(current[1])))
                current = None
            continue
        (current[1] if current is not None else prose).append(line)
    if current is not None:                      # unterminated fence: keep what there is
        blocks.append((current[0], "\n".join(current[1])))
    return "\n".join(prose), blocks


CODE_EXT = (".py", ".md", ".json", ".yml", ".yaml", ".txt", ".ts", ".tsx", ".toml", ".sh", ".sql", ".html")


def severity(token: str) -> str:
    """How much a missing token matters.

    `hard` is data: a URL, a code filename, or a token with a digit, an underscore, an inner capital or an
    ALLCAPS acronym — anything a reader would type, or a number whose value is the point.

    `soft` is English that sat in backticks because of how the source was written: slash-joined word pairs
    (`back/forward`, `async/sync`, `FX/commodity`, `IEA/IRENA-class`), phrases with spaces, and an English plural
    (`404s`). A translator rendering those as 前进/后退, 外汇/大宗商品 or 五个 404 is doing the job, not losing it —
    and calling that a defect would bury the real ones. Two rules matter more than they look: a **single** word in
    capitals is hard (`PASS`, `REFUSED` are contract values), and a single camelCase word is hard
    (`atRiskDrivers` was the real find) — only a *slash-joined* letter group counts as prose.
    """
    stripped = token.rstrip(".,;:）) ")
    if "://" in stripped:
        return "hard"
    if stripped.endswith(CODE_EXT):
        return "hard"
    if " " in stripped:                     # a phrase, not an identifier
        return "soft"
    if "/" in stripped:
        segments = [s for s in stripped.split("/") if s]
        if any(any(ch.isdigit() for ch in s) for s in segments):
            return "hard"
        if all(re.fullmatch(r"[A-Za-z][A-Za-z-]*", s) for s in segments):
            return "soft"
        return "hard"
    if any(ch.isdigit() for ch in stripped) or "_" in stripped:
        return "hard"
    if re.search(r"[a-z][A-Z]", stripped):  # camelCase
        return "hard"
    if re.fullmatch(r"[A-Z]{2,}", stripped):  # a bare acronym: PASS, REFUSED, ADMITTED
        return "hard"
    return "soft"


def normalise(text: str) -> str:
    """Credit the two renderings that are translations of a token rather than losses of one.

    `8x` becomes 8 倍 — same claim, Chinese unit. `404s` becomes 五个 404 — same code, English plural dropped.
    """
    text = re.sub(r"(\d+(?:[.,]\d+)?)\s*倍", r"\1x", text)
    text = re.sub(r"(\d+)s\b", r"\1", text)
    return text


def tokens_in(prose: str) -> set[str]:
    found = {m.group(1).strip() for m in TOKEN.finditer(prose)}
    found |= {m.group(0) for m in URL.finditer(prose)}
    found |= {m.group(0) for m in PATHISH.finditer(prose)}
    found |= {m.group(0) for m in NUMBER.finditer(prose)}
    return {t for t in found if len(t) >= 2}


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def check(skill_id: str, show_fences: bool) -> tuple[list[str], list[str], list[str]]:
    zh_path, en_path = BUILTIN / skill_id / "SKILL.md", ARCHIVE / skill_id / "SKILL.md"
    if not (zh_path.is_file() and en_path.is_file()):
        return [], [], [f"{skill_id}: no archive — not a translation"]
    zh_prose, zh_blocks = split_fences(body_of(zh_path.read_text(encoding="utf-8")))
    en_prose, en_blocks = split_fences(body_of(en_path.read_text(encoding="utf-8")))

    zh_squashed = squash(normalise(zh_prose))
    missing = sorted((t for t in tokens_in(en_prose) if squash(normalise(t)) not in zh_squashed),
                     key=lambda tok: (severity(tok) != "hard", tok))

    changed = [(info, block) for (info, block), (zh_info, zh_block)
               in zip(en_blocks, zh_blocks) if block.strip() != zh_block.strip()]
    fence_notes = []
    if changed:
        for info, block in changed:
            first = block.strip().splitlines()[0][:60] if block.strip() else "(empty)"
            kind = "template" if info.lower() in {"markdown", "md", "text", ""} else "CODE CHANGED"
            fence_notes.append(f"{kind}: ```{info} … {first}")
    missing_blocks = len(en_blocks) - len(zh_blocks)
    if missing_blocks:
        fence_notes.append(f"{missing_blocks} fenced block(s) fewer than the original")
    return missing, fence_notes, []


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skills", nargs="*")
    ap.add_argument("--fences", action="store_true", help="list every fenced block that changed")
    ap.add_argument("--verbose", action="store_true", help="also list English phrases that were translated")
    args = ap.parse_args(argv)

    if args.skills:
        ids = args.skills
    else:
        ids = sorted(d.name for d in ARCHIVE.iterdir()
                     if (d / "SKILL.md").is_file() and (BUILTIN / d.name / "SKILL.md").is_file())

    clean, lossy, code_changed, skipped = [], [], [], []
    for skill_id in ids:
        missing, fences, errs = check(skill_id, args.fences)
        if errs:
            skipped.extend(errs)
            continue
        hard = [f for f in fences if f.startswith("CODE CHANGED")]
        if [tok for tok in missing if severity(tok) == "hard"] or hard:
            lossy.append((skill_id, missing, fences))
        else:
            clean.append(skill_id)
        if hard:
            code_changed.append(skill_id)

    for skill_id, missing, fences in lossy:
        print(f"\n{skill_id}")
        hard = [tok for tok in missing if severity(tok) == "hard"]
        soft = [tok for tok in missing if severity(tok) != "hard"]
        if hard:
            print(f"  LOSES {len(hard)} hard token(s) — data a reader would type or rely on:")
            for token in hard[:12]:
                print(f"    - {token}")
            if len(hard) > 12:
                print(f"    … and {len(hard) - 12} more")
        if soft and args.verbose:
            print(f"  {len(soft)} English phrase(s) rendered in Chinese (expected): {soft[:6]}")
        for note in fences:
            if args.fences or note.startswith("CODE CHANGED"):
                print(f"  fence {note}")

    print(f"\n{len(clean)} skill(s) keep every prose token and every code block")
    print(f"{len(lossy)} skill(s) lost a token or changed a code block"
          f"  ({len(code_changed)} changed a block whose info string says it is code)")
    for err in skipped:
        print(f"  skip: {err}")
    return 1 if lossy else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
