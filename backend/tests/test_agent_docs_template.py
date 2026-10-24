"""The default AGENTS.md / CLAUDE.md a new agent inherits.

These guard a specific, expensive bug: the template used to tell every agent
that skills live in the workspace `skills/` folder and that it must NEVER run
ls/glob/grep to discover paths. In database storage mode the workspace
`skills/` folder is empty (the real catalogue is served from the virtual
`/skills/...` paths in the prompt), and the no-discovery rule forbade the
`glob("**/SKILL.md")` step that lets an agent find the right skill by
description.

Net effect: every agent created from the UI reported "skills/ not staged" and
never used a skill, until its prompt was patched by hand.
"""

from types import SimpleNamespace

import pytest

from core.agents.identity import default_agent_docs


@pytest.fixture
def docs():
    agent = SimpleNamespace(id=999, name="demo_agent", description="A demo agent.")
    return default_agent_docs(agent, "/tmp/ws/demo_agent")


def test_agents_md_points_skills_at_the_virtual_catalogue(docs):
    text = docs["AGENTS.md"]
    assert "/skills/" in text
    # the old template claimed the catalogue lives in the workspace folder
    assert "staged into `skills/`" not in text
    assert "NOT inside this workspace" in text or "NOT the workspace" in text


def test_claude_md_does_not_claim_workspace_skills(docs):
    text = docs["CLAUDE.md"]
    assert "/skills/" in text
    assert "skills: `skills/`" not in text


def test_template_states_the_generic_skill_rule(docs):
    """Without this rule a cheap model never opens the SKILL.md body."""
    text = docs["AGENTS.md"]
    assert "## Skills — use the catalogue" in text
    assert "read that skill's SKILL.md" in text.replace("  ", " ")
    assert "Never answer from memory when a matching skill exists" in text


def test_discovery_is_not_banned_outright(docs):
    """The blanket ban is what made skill discovery impossible."""
    text = docs["AGENTS.md"]
    assert "NEVER run ls/glob/grep just to discover paths" not in text
    assert "do NOT explore" not in text
    # uploads/deliverables keep their deterministic-path rule
    assert "do NOT run ls/glob/grep to discover those paths" in text


def test_workspace_scaffolding_still_documented(docs):
    """The fix must not have dropped the parts agents rely on."""
    text = docs["AGENTS.md"]
    for fragment in ("upload/", "generated/", "other/", "AGENTS.md", "CLAUDE.md"):
        assert fragment in text
    assert "/tmp/ws/demo_agent" in text
    assert "999" in text


# ── the template is a reviewable file, not a Python f-string ───────────────

def test_templates_are_repo_files():
    from pathlib import Path
    import core.agents.identity as identity

    tpl = Path(identity.__file__).resolve().parent / "templates"
    assert (tpl / "AGENTS.default.md").is_file()
    assert (tpl / "CLAUDE.default.md").is_file()


def test_placeholders_are_substituted(docs):
    for name, text in docs.items():
        assert "{{" not in text, f"{name} kept an unsubstituted placeholder"
        assert "}}" not in text, f"{name} kept an unsubstituted placeholder"


def test_rendering_uses_the_agent_values():
    agent = SimpleNamespace(id=4242, name="weather_bot", description="Says hi warmly.")
    docs = default_agent_docs(agent, "/tmp/ws/weather_bot")
    text = docs["AGENTS.md"]
    assert "weather_bot" in text
    assert "Says hi warmly." in text
    assert "4242" in text
    assert "/tmp/ws/weather_bot" in text


def test_missing_template_degrades_to_a_stub(monkeypatch):
    """A packaged install without package-data must not break agent creation."""
    import core.agents.identity as identity

    monkeypatch.setattr(identity, "_TEMPLATE_DIR", identity.Path("/nonexistent/templates"))
    agent = SimpleNamespace(id=7, name="stub_agent", description="stub")
    docs = identity.default_agent_docs(agent, "/tmp/ws/stub")
    assert "stub_agent" in docs["AGENTS.md"]
    assert "/tmp/ws/stub" in docs["AGENTS.md"]


# ── CLAUDE.md is a mirror: stored + materialised, NOT embedded in the prompt ─

def test_prompt_embeds_agents_md_but_not_claude_md(docs):
    from core.agents.identity import build_identity_system_prompt

    prompt = build_identity_system_prompt(
        "You are a helpful AI assistant.", 999, "/tmp/ws/demo_agent", docs
    )
    assert "## AGENTS.md (embedded)" in prompt
    assert "## CLAUDE.md (embedded)" not in prompt
    # the mirror is still produced and stored — it reaches the workspace as a file
    assert docs["CLAUDE.md"]


def test_prompt_stays_under_the_old_size(docs):
    """Embedding only AGENTS.md must make the prompt smaller, not larger."""
    from core.agents.identity import build_identity_system_prompt

    prompt = build_identity_system_prompt("You are a helpful AI assistant.", 999,
                                          "/tmp/ws/demo_agent", docs)
    inline_docs = len(docs["AGENTS.md"]) + len(docs["CLAUDE.md"])
    assert len(prompt) < inline_docs + 1000      # old shape was docs + identity + base
