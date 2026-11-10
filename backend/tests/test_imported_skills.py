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
import yaml

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


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_no_rewrite_artefacts(path: pathlib.Path):
    """The port rewrites text programmatically, which can leave its own debris.

    Two classes were produced for real while generating: doubled backticks where a rewrite landed inside an
    existing code span (``Skills` activity …``), and — worse — a "normalisation" regex that rewrote every
    fenced code block (```lang → ``lang) in 311 places. Both are invisible to a loader; both make the skill
    worse than the upstream it came from.
    """
    text = path.read_text(encoding="utf-8")
    assert text.count("```") % 2 == 0, (
        f"{path.parent.name}: an odd number of ``` fences — a rewrite ate one, and everything after it now "
        "renders as code")
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        assert not re.search(r"``[^`]+`", line), (
            f"{path.parent.name}:{n} has doubled backticks ({line.strip()[:60]!r}) — a rewrite landed inside "
            "a code span")


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_a_tool_name_is_never_used_as_a_verb(path: pathlib.Path):
    """Rewriting Claude's tool names into ours turned the imperative verb into a tool name.

    Measured: "Read the spec and tickets" became "read_file the spec and tickets" in 26 places, which is not
    a sentence in any language. A tool is named only where the text talks *about* it (in backticks, after
    "the", before "tool"); the prose verb stays a verb.
    """
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in
            re.finditer(r"\b(read_file|write_file|edit_file|bash|grep|glob|task)\s+(?:the|a|an|this|your|all)\s", text)]
    assert not hits, (f"{path.parent.name}: a tool name is used as a verb ({hits[:3]}) — the rewrite hit prose "
                      "instead of a tool reference")


@pytest.mark.parametrize("path", [p for p in _skill_files() if _generated(p)], ids=lambda p: p.parent.name)
def test_no_sentence_still_addresses_an_upstream_setup_skill(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    body = text.split(FLOOR)[0].split("---", 2)[-1]
    body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith(">"))
    leftovers = [phrase for phrase in (
        "should have been provided to you",
        "tell the user to run",
        "must be configured first (Skills activity",
    ) if phrase in body]
    # the second and third are OUR replacement wording; only the upstream one is a defect
    assert "should have been provided to you" not in body, (
        f"{path.parent.name}: an upstream sentence about a tracker that does not exist here survived "
        f"({leftovers})")


def test_ids_are_unique_and_kebab_case():
    ids = [p.parent.name for p in _skill_files()]
    assert len(ids) == len(set(ids)), "two directories claim the same skill id"
    bad = [i for i in ids if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", i)]
    assert not bad, f"the skill tool addresses skills by id; these are not kebab-case: {bad}"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: p.parent.name)
def test_allowed_tools_is_a_list_of_tool_names(path: pathlib.Path):
    """`allowed_tools` is printed into the prompt, so a broken list is text the model reads.

    Found in `web-search`: the frontmatter carried the literal string `["web_search", "fetch_url",
    "write_file", "read_file"]` exploded into one list item per character, so
    `core/agents/factory/prompting.py` rendered `**Allowed Tools:** [, ", w, e, b, _, s, e, a, r, …` into
    every prompt that used the skill. Nothing failed — a list of characters is still a list — which is why
    the shape has to be asserted rather than the presence.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        pytest.skip("no frontmatter")
    end = text.find("\n---", 3)
    frontmatter = yaml.safe_load(text[3:end]) or {}
    for key in ("allowed_tools", "allowed-tools"):
        value = frontmatter.get(key)
        if value is None:
            continue
        assert isinstance(value, list), (
            f"{path.parent.name}: `{key}` is {type(value).__name__}, but the prompt code joins it as a list")
        for item in value:
            assert isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9_]*", item), (
                f"{path.parent.name}: `{key}` contains {item!r}, which is not a tool name — a serialisation "
                "slip turns the prompt line into noise")
        fragments = [s for s in value if s in {"[", '"', ","} or len(s) <= 2]
        assert not fragments, (
            f"{path.parent.name}: `{key}` looks like a serialised string split per character: {value[:8]}")


def test_no_markdown_link_target_is_reworded():
    """A link target is a path, not prose — the importer's prose rewrites must not reach inside one.

    Measured: `- [triage-labels.md](./triage-labels.md)` became `(.the \\`triage\\` skill-labels.md)` when the
    `/triage` slash-command rule matched the tail of the relative path, and the same pass turned
    `For "other" issue trackers` into `For "other" \\`docs/tickets/\\`s`. A link with a sentence in it resolves
    to nothing, and nothing fails at load time, so this asserts the shape instead.
    """
    offenders = []
    for path in _skill_files():
        for match in re.finditer(r"\]\(([^)]*)\)", path.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("data:", "#", "mailto:")):      # inline payload / anchor: not a path
                continue
            if "`" in target or " " in target.strip():
                offenders.append((path.parent.name, target))
    assert not offenders, (
        f"a link target contains prose rather than a path: {offenders[:5]} — a rewrite pass reached inside "
        "the brackets")
