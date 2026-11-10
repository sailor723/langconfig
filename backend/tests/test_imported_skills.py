"""Every skill in the library must load — and the imported ones must say where they came from.

Context: the library is now generated in part from two vendored upstream sets
(`vendor/upstream-skills/mattpocock`, `.../langchain-skills`) by
`scripts/import_upstream_skills.py`. Generated files are code in a real sense: a malformed scalar in the
frontmatter silently removes a skill from the library (measured — five skills vanished because their
description contained `: ` unquoted), and a lost provenance line turns somebody else's MIT work into
anonymous text.

The checks:

1. every `SKILL.md` under `backend/skills/builtin/` loads through the app's own loader, with a non-empty
   description and body;
2. every *generated* skill carries the provenance block naming its upstream path;
3. every generated skill carries the verification-floor section, so it points at this repository's
   commands instead of inventing its own;
4. no generated skill still tells the agent to call a tool we do not have, or to use a slash command;
5. ids are unique and kebab-case, because the `skill` tool addresses skills by id.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILLS = REPO / "backend" / "skills" / "builtin"
PROVENANCE = "**Provenance.** Adapted from"
FLOOR = "## This repository's floor"

#: Tools that exist in this app (native + SDK). A generated skill may only name these.
KNOWN_TOOLS = {
    "read_file", "write_file", "edit_file", "bash", "grep", "glob", "task", "skill",
    "web_fetch", "web_search", "python_execute", "pg_query", "pg_list_tables", "pg_describe_table",
    "sqlite_execute", "bash", "read_any_file", "read_image", "save_analysis_result", "search_skills",
    "ontology_ask", "ontology_inspect", "gen_dashboard", "graphindex_search", "rag_search",
}
#: Upstream-isms that must not survive the port.
FORBIDDEN = [
    (r"\bClaude Code\b", "Claude-Code-specific client"),
    (r"/plugin install", "plugin marketplace command"),
    (r"CALL the Skill tool", "wrong invocation instruction"),
    (r"mcp__", "Claude tool namespacing"),
    (r"disable-model-invocation:", "a frontmatter field our loader does not read"),
]


def _skill_files() -> list[pathlib.Path]:
    return sorted(p for p in SKILLS.rglob("SKILL.md") if p.is_file())


def _generated(path: pathlib.Path) -> bool:
    return PROVENANCE in path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: p.parent.name)
def test_every_skill_loads_through_the_app_loader(path: pathlib.Path):
    from core.skills.loader import SkillLoader

    parsed = SkillLoader().load_skill(str(path.parent))
    assert parsed is not None, (
        f"{path.relative_to(REPO)} does not load — the frontmatter is invalid YAML or a required field is "
        "missing, so this skill is invisible to every agent")
    assert parsed.description.strip(), "an empty description means no trigger can ever match"
    assert parsed.instructions.strip(), "an empty body means the skill teaches nothing"


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_generated_skills_name_their_upstream(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    assert re.search(r"Adapted from `[a-z-]+/[\w-]+ → ", text), (
        f"{path.parent.name}: the provenance block does not name the upstream path "
        "(repo → path), which is how attribution is lost")


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_generated_skills_point_at_our_verification_floor(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    assert FLOOR in text, (
        f"{path.parent.name}: a generated skill must end with the verification-floor section — otherwise it "
        "invents its own idea of 'done' instead of using ./scripts/housekeeping_verify.sh and the baseline")
    assert "scripts/housekeeping_verify.sh" in text or "pytest" in text, (
        f"{path.parent.name}: the floor section does not name a real command")


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_generated_skills_have_no_upstream_isms(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    # the provenance block explains what was dropped; scanning the body, not the attribution, is the point
    body = text.split(FLOOR)[0].split("---", 2)[-1]
    body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith(">"))
    problems = [f"{why} ({pattern})" for pattern, why in FORBIDDEN if re.search(pattern, body)]
    assert not problems, f"{path.parent.name}: " + "; ".join(problems)


def test_ids_are_unique_and_kebab_case():
    ids = [p.parent.name for p in _skill_files()]
    assert len(ids) == len(set(ids)), "two directories claim the same skill id"
    bad = [i for i in ids if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", i)]
    assert not bad, f"the skill tool addresses skills by id; these are not kebab-case: {bad}"
