"""The `skill` tool must return a body — and that had never been tested.

Measured 2026-11-09, while adding the `lang` argument: `skill("grilling")` answered
"Error loading skill 'grilling': 'StructuredTool' object is not callable" for EVERY skill. The internal
helper `_skill_support_files` had been decorated `@tool`, which turns a function into a StructuredTool, and
the tool body called it as a function. Progressive disclosure — the whole point of the skill system — was
returning an error string, and nothing failed, because no test ever called the tool.

So this file does three things:

1. calls the tool for a real skill and asserts it returns the body (the coverage that was missing);
2. asserts no private helper in `tools/native_impl.py` is decorated as a tool again (the bug's shape);
3. pins the language contract: Chinese by default, the archived English on `lang="en"`, and a skill with no
   archive still Chinese-or-English but never an error.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
NATIVE = REPO / "backend" / "tools" / "native_impl.py"
BUILTIN = REPO / "backend" / "skills" / "builtin"


def _call(**kwargs) -> str:
    from tools.native_impl import skill

    return asyncio.run(skill(**kwargs))


def _any_skill() -> str:
    """A skill every install has, translated or not."""
    for candidate in ("grilling", "to-spec", "tdd", "web-search"):
        if (BUILTIN / candidate / "SKILL.md").is_file():
            return candidate
    first = sorted(d.name for d in BUILTIN.iterdir() if (d / "SKILL.md").is_file())[0]
    return first


def test_the_tool_returns_a_body():
    body = _call(skill_id=_any_skill())
    assert not body.startswith("Error loading skill"), body[:200]
    assert len(body) > 500, f"a skill body of {len(body)} chars is not instructions: {body[:200]!r}"
    assert body.lstrip().startswith("# Skill:"), body[:80]


def test_no_private_helper_is_decorated_as_a_tool():
    src = NATIVE.read_text(encoding="utf-8")
    offenders = [m.group(1) for m in
                 re.finditer(r"@tool\s*\n(?:@[^\n]*\n)*def (_[A-Za-z0-9_]+)", src)]
    assert not offenders, (
        f"these private helpers are decorated @tool, so calling them as functions raises "
        f"'StructuredTool' object is not callable: {offenders}")


def test_the_default_language_is_chinese():
    translated = [d.name for d in (REPO / "backend" / "skills" / "en-originals").iterdir()
                  if d.is_dir()] if (REPO / "backend" / "skills" / "en-originals").is_dir() else []
    if not translated:
        pytest.skip("no translated skill yet")
    body = _call(skill_id=sorted(translated)[0])
    assert len(re.findall(r"[\u4e00-\u9fff]", body)) > 200, (
        "the default body must be the Chinese working text — that is the decision this repository made")


@pytest.mark.parametrize("skill_id", ["grilling"])
def test_english_is_available_on_request_only(skill_id: str):
    archived = REPO / "backend" / "skills" / "en-originals" / skill_id / "SKILL.md"
    if not archived.is_file():
        pytest.skip(f"{skill_id} has no archived English")
    english = _call(skill_id=skill_id, lang="en")
    assert "(instructions: en)" in english.splitlines()[0]
    assert len(re.findall(r"[\u4e00-\u9fff]", english)) < 200, "lang='en' must serve the English original"


def test_an_unknown_language_falls_back_to_the_canonical_file():
    body = _call(skill_id=_any_skill(), lang="fr")
    assert not body.startswith("Error loading skill")
    assert len(body) > 500
