#!/usr/bin/env python3
"""Lint a skill as a BASE: are its rules gated, its files reachable, its numbers honest?

Why this exists. A builder was asked "are S1…S11 in the skill?" and spent 213 tool calls re-deriving its
own history, because the skill never said where the ladder stops. A second audit of the same build found
`:askedAs` on 0 of 43 metrics and `口径来自` on only 23 — while every gate stayed green, because those two
rules exist ONLY as prose. The rule that follows from both: **a rule with no gate is a rule that gets
skipped, and a file nothing links to is a file nobody reads.**

What it checks (each one is a finding, not a style note):

  L1  SKILL.md declares a `version:`                       (a base you cannot date is not a base)
  L2  every markdown link in SKILL.md resolves to a file   (dead link = missing instruction)
  L3  every file in the skill directory is REACHABLE       (from SKILL.md, or from a reference it links)
  L4  every rule in references/rules.md declares a GATE     (`**Gate:** …` or `**Ungated (advisory)**`)
  L5  the rule count the prose claims matches the rules     ("Fifteen rules" against nineteen `## N.`)
  L6  every gate named by a rule exists in gates/ or scripts/
  L7  the ladder mentions each reference at least once      (a reference nothing schedules is skipped)

    python backend/scripts/check_skill.py                       # every skill under backend/skills/builtin
    python backend/scripts/check_skill.py --skill build-ontology-from-db
    exit 0 when every check holds, 1 when any does not
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BUILTIN = BACKEND / "skills" / "builtin"
GATE_DIRS = [BACKEND / "features" / "ontology" / "gates", BACKEND / "scripts"]


def _gates_available() -> set[str]:
    names: set[str] = set()
    for d in GATE_DIRS:
        if d.is_dir():
            names |= {p.stem for p in d.glob("*.py")}
    return names


def lint(skill_dir: pathlib.Path, warns: list[str] | None = None) -> list[str]:
    problems: list[str] = []
    warns = warns if warns is not None else []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir.name}: no SKILL.md"]
    text = skill_md.read_text(encoding="utf-8")

    # L1 version
    # Either quote: 52 of the 88 skills in this library write `version: "1.0"`, so accepting only the
    # single quote made L1 red for the majority of a healthy library — and a lint that is always red is
    # a lint nobody reads.
    if not re.search(r"^version:\s*[\"']?[0-9]", text, re.M):
        problems.append("L1 SKILL.md declares no `version:`")

    # L2 links resolve (relative links only: references/…, scripts/…, examples/…)
    linked: set[str] = set()
    for target in re.findall(r"\]\(([^)#]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path = (skill_dir / target).resolve()
        linked.add(target)
        if not path.exists():
            problems.append(f"L2 dead link in SKILL.md: {target}")

    # L3 reachability: every file is named by SKILL.md, or by a reference SKILL.md links
    linked_texts = [text]
    for target in list(linked):
        p = (skill_dir / target).resolve()
        if p.is_file() and p.suffix == ".md":
            linked_texts.append(p.read_text(encoding="utf-8"))
    blob = "\n".join(linked_texts)
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        rel = path.relative_to(skill_dir).as_posix()
        if rel in blob or path.name in blob or rel.rsplit("/", 1)[0] in blob:
            continue
        problems.append(f"L3 unreachable file (nothing links it): {rel}")

    # L4/L5/L6 rules: an id, a gate, an honest count
    rules_md = skill_dir / "references" / "rules.md"
    if rules_md.is_file():
        rules_text = rules_md.read_text(encoding="utf-8")
        rules = re.findall(r"^##\s+(\d+[a-z]?)\.\s+(.+)$", rules_text, re.M)
        for rid, title in rules:
            block = rules_text.split(f"## {rid}.", 1)[1]
            block = block.split("\n## ", 1)[0]
            gate_line = re.search(r"\*\*Gate:\*\*(.+)", block)
            if gate_line is None and "**Ungated (advisory)**" not in block:
                problems.append(f"L4 rule {rid} ({title.strip()[:40]}) declares no gate and is not marked advisory")
            elif gate_line and "Ungated (MUST)" in gate_line.group(1):
                # A MUST rule with no gate is not a pass — it is a KNOWN DEBT, and it is printed on every run.
                # Measured: five rules were in exactly this state while every gate stayed green; hiding them
                # behind a green lint would repeat the mistake this lint exists to catch.
                warns.append(f"UNGATED MUST rule {rid} ({title.strip()[:44]}) — no gate yet")
            for gate in re.findall(r"`([a-z_]+\.py)`", block):
                if gate.split(".")[0] not in _gates_available():
                    problems.append(f"L6 rule {rid} names a gate that does not exist: {gate}")
        claimed = re.search(r"^(Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|Twenty)\s+rules", rules_text, re.M)
        words = {"Fifteen": 15, "Sixteen": 16, "Seventeen": 17, "Eighteen": 18, "Nineteen": 19, "Twenty": 20}
        if claimed and words[claimed.group(1)] != len(rules):
            problems.append(f"L5 rules.md claims {words[claimed.group(1)]} rules but defines {len(rules)}")
        # L7 each reference is scheduled somewhere in SKILL.md
        for ref in (skill_dir / "references").glob("*.md"):
            if ref.name not in text:
                problems.append(f"L7 references/{ref.name} is never mentioned in SKILL.md")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skill", default="", help="only this skill id (folder name)")
    args = ap.parse_args()

    dirs = [BUILTIN / args.skill] if args.skill else sorted(p for p in BUILTIN.iterdir() if (p / "SKILL.md").is_file())
    total = 0
    total_warns = 0
    for d in dirs:
        warns: list[str] = []
        problems = lint(d, warns)
        version = re.search(r"^version:\s*[\"']?([0-9.]+)[\"']?", (d / "SKILL.md").read_text(encoding="utf-8"), re.M)
        print(f"\n=== {d.name}  v{version.group(1) if version else '?'}")
        if not problems:
            print("  ok — every rule is gated or advisory, every file reachable, every reference scheduled")
        for p in problems:
            print(f"  [FAIL] {p}")
        for w in warns:
            print(f"  [WARN] {w}")
        total += len(problems)
        total_warns += len(warns)
    print(f"\n{total} problem(s), {total_warns} ungated-MUST warning(s) across {len(dirs)} skill(s).")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
