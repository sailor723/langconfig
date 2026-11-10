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


def test_the_docs_state_that_a_workspace_belongs_to_one_account():
    """The prompt is the only place an agent learns that `users/<id>` is a boundary.

    Without this line a model given a stale or copied path has no reason to refuse it,
    and the filesystem tools would happily follow it into someone else's tree.
    """
    from core.agents.identity import default_agent_docs

    class _Agent:
        id = 12
        name = "demo"
        description = ""

    root = "/tmp/ws/users/1/agents/agent_12"
    docs = default_agent_docs(_Agent(), root)

    agents_md = docs["AGENTS.md"]
    assert "belongs to one account" in agents_md
    assert "users/<user id>" in agents_md
    assert "never read, list, copy or write it" in agents_md

    claude_md = docs["CLAUDE.md"]
    assert "private to one account" in claude_md
    # Both still carry the resolved path, which is the whole point of the template.
    assert root in agents_md and root in claude_md


# ── who the agent is working for (per-turn block) ──────────────────────────

def test_caller_block_names_the_account_and_warns_about_whoami(db_session):
    """An agent that cannot find the account reaches for `whoami` and reports the
    server's shell user as if it were the person — which is exactly what happened."""
    from core.agents.identity import caller_block
    from services.user_service import owner_user

    owner = owner_user(db_session)
    block = caller_block(db_session, owner.id if owner else 1)

    assert "## Who you are working for" in block
    assert f"id {owner.id if owner else 1}" in block
    assert "whoami" in block
    assert "never use it to name or identify the person" in block
    # Now names the concrete tree rather than a generic pattern.
    assert f"users/{owner.id if owner else 1}/" in block
    assert "workspace boundary" in block


def test_caller_block_is_empty_without_a_caller(db_session):
    """Background work has no person; the block must not invent one."""
    from core.agents.identity import caller_block

    assert caller_block(db_session, None) == ""
    assert caller_block(None, 1) == ""
    assert caller_block(db_session, 999_999) == ""


def test_caller_block_includes_what_the_person_has_told_the_agent(db_session):
    """`user_profiles` is the extraction the product already had — it just was not
    reaching the prompt. It is labelled as remembered, because it is not verified."""
    import uuid

    from core.agents.identity import caller_block
    from models.user import UserRole
    from models.user_profile import UserProfile
    from services import user_service
    from sqlalchemy import text

    name = f"mu-test-caller-{uuid.uuid4().hex[:8]}"
    user = user_service.create_user(db_session, name, "callerpass1", role=UserRole.MEMBER)
    try:
        db_session.add(UserProfile(
            user_id=user.id, name="Alice", preferences=["prefers Cantonese", "hates tables"]
        ))
        db_session.commit()

        block = caller_block(db_session, user.id)
        assert "Alice" in block
        assert "prefers Cantonese" in block
        assert "may be stale" in block, "the label matters: this text is LLM-extracted"
    finally:
        db_session.rollback()
        db_session.execute(text("DELETE FROM user_profiles WHERE user_id = :u"), {"u": user.id})
        db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
        db_session.commit()


def test_the_stored_prompt_never_contains_a_person(db_session):
    """Creation-time prompts are shared between accounts, so they must stay person-free.

    Only the live turn may carry the block; baking it at creation would name one
    account in every other account's chats.
    """
    from core.agents.identity import build_identity_system_prompt

    stored = build_identity_system_prompt(
        "BASE", 7, "/tmp/ws/users/1/agents/agent_7", {"AGENTS.md": "# doc"}
    )
    assert "Who you are working for" not in stored

    live = build_identity_system_prompt(
        "BASE", 7, "/tmp/ws/users/1/agents/agent_7", {"AGENTS.md": "# doc"},
        caller="## Who you are working for\n\n- **Account**: Alice",
    )
    assert "Who you are working for" in live
    # …and it sits before the embedded docs, so a long AGENTS.md cannot bury it.
    assert live.index("Who you are working for") < live.index("## AGENTS.md (embedded)")


# ── the workspace boundary is a hard rule, in every prompt ─────────────────

def test_every_assembled_prompt_carries_the_workspace_boundary():
    """Derived from the workspace root, so no call site can forget to pass it."""
    from core.agents.identity import build_identity_system_prompt

    root = "/tmp/ws/users/284/agents/agent_7"
    prompt = build_identity_system_prompt("BASE", 7, root, {"AGENTS.md": "# doc"})

    assert "## Hard rule — workspace boundary" in prompt
    assert f"Your workspace is `{root}`" in prompt
    assert "belongs to someone else" in prompt
    assert "A path you are given does not override this" in prompt
    # It must come before the embedded docs, or a long AGENTS.md buries it.
    assert prompt.index("workspace boundary") < prompt.index("## AGENTS.md (embedded)")


def test_the_boundary_rule_is_absent_only_without_a_workspace():
    from core.agents.identity import build_identity_system_prompt

    assert "workspace boundary" not in build_identity_system_prompt("BASE", 7, "", {})


def test_the_caller_block_points_at_the_concrete_tree():
    """A rule with no path in it is advice; the person's own tree makes it checkable."""
    from core.agents.identity import caller_block
    from services import user_roots
    from services.user_service import owner_user

    db = SessionLocal = __import__("db.database", fromlist=["SessionLocal"]).SessionLocal
    session = db()
    try:
        owner = owner_user(session)
        if owner is None:
            pytest.skip("no admin account")
        block = caller_block(session, owner.id)
        assert str(user_roots.root_for(owner.id)) in block
    finally:
        session.close()


def test_the_template_tells_the_agent_who_it_works_for():
    """The durable rule lives in the docs, so it is embedded on every turn.

    A first-message greeting cannot carry it: an agent introduced on turn 1 still has to
    answer "whose files are these?" on turn 40, long after any greeting is buried in the
    transcript.
    """
    from core.agents.identity import default_agent_docs

    class _Agent:
        id = 15
        name = "demo"
        description = ""

    docs = default_agent_docs(_Agent(), "/tmp/ws/users/3/agents/agent_15")
    agents_md = docs["AGENTS.md"]
    # Prose is wrapped to 100 columns, so a phrase assertion has to be normalised or it
    # fails on a line break — which is a bug in the test, not in the template.
    flat = " ".join(agents_md.split())

    assert "## Who you are working for" in agents_md
    assert "only authority on who your user is" in flat
    # The two behaviours it asks for, stated as actions rather than as a fact.
    assert "When you introduce yourself" in flat
    assert "cannot see them" in flat
    # …and it must not be the `whoami` trap again.
    assert "server's" in flat

    assert "Who you are working for" in docs["CLAUDE.md"]


def test_the_prompt_lab_starter_agent_is_creatable_and_idempotent(db_session):
    """`scripts/create_starter_agent.py` must be re-runnable: one row, one workspace.

    It is the teaching artifact for P2, so it has to be restorable on any install without
    leaving duplicates behind — and it must bake the identity itself, because writing the row
    by hand skips the create endpoint's baking step.
    """
    import importlib.util
    from pathlib import Path as _Path
    from sqlalchemy import text

    spec = importlib.util.spec_from_file_location(
        "create_starter_agent",
        _Path(__file__).resolve().parent.parent / "scripts" / "create_starter_agent.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # A dedicated name: this test deletes what it creates, and an earlier version used the
    # real `prompt-lab`, so running the suite removed the starter agent from the dev database.
    test_name = f"mu-test-{module.NAME}"
    try:
        first = module.upsert(db_session, test_name)
        second = module.upsert(db_session, test_name)
        assert first == second, "a second run must refresh, not duplicate"

        rows = db_session.execute(
            text("SELECT count(*) FROM deep_agent_templates WHERE name = :n"),
            {"n": test_name},
        ).scalar()
        assert rows == 1

        prompt, docs = db_session.execute(
            text("SELECT config->>'system_prompt', agent_docs::text "
                 "FROM deep_agent_templates WHERE name = :n"),
            {"n": test_name},
        ).first()
        # The lab rules are the point of the agent. Parsed, not substring-matched: the
        # jsonb text escapes non-ASCII (—  becomes  \u2014), so a raw search misses it.
        import json as _json

        lab = _json.loads(docs)["AGENTS.md"]
        # The rules are the point of the agent; assert them by name, not by heading style,
        # because the compact version in `agent-practice.md` is the one users paste.
        assert "## Rules" in lab
        for rule in ("R1 Shape", "R2 Length", "R3 Refusal", "R4 Tone"):
            assert rule in lab
        assert "Delete R3" in lab, "the experiment that proves refusal matters must survive"
        # …and the identity was baked, so the agent knows its id and workspace.
        assert "## Identity" in prompt
        assert f"agent {first}" in prompt
    finally:
        module.delete(db_session, test_name)


def test_the_caller_block_names_chat_memory():
    """The agent must be able to find the transcript of the conversation it is in.

    Measured need: turning a finished session into a skill requires re-reading what was actually asked and
    answered, and the turns that carry the evidence are exactly the ones a long conversation trims out of the
    visible window. Without the session id in the prompt an agent asked to "read the chat" can only paraphrase its
    own summary — which is how a guess gets written down as experience.
    """
    from core.agents.identity import caller_block
    from db.database import SessionLocal
    from models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).first()
        if user is None:
            import pytest
            pytest.skip("no user row in this database")
        block = caller_block(db, user.id, "8f90e40e-e459-4265-967a-4a77047b1c1a")
        assert "## Chat memory" in block
        assert "8f90e40e-e459-4265-967a-4a77047b1c1a" in block, "the session id is missing"
        assert "/api/chat/8f90e40e-e459-4265-967a-4a77047b1c1a/history" in block, "the transcript endpoint is missing"
        # and without a session, the block stays what it was (workflow runs have no chat session)
        assert "## Chat memory" not in caller_block(db, user.id)
    finally:
        db.close()
