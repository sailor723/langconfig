"""Gates for `scope: conversation` skill parameters.

One ontology builder now serves every ontology (`docs/system-architecture/ontology-agents.md`), which
means the two values that used to be baked into each builder row — the ontology key and the database
behind it — are answered per conversation instead. That only works if the platform:

* builds a keyless agent at all (`ontology_key: required` used to fail the build by name — the agent
  never started, so "ask the user for the key" could not happen);
* does not invent a `datasource` for it out of `config.database` (one agent can sit on the ontology
  server, whose `dbname` is `postgres`, and `postgres` is not the skill's database);
* still renders a value that a per-key agent DOES supply, unchanged — the six per-key builder rows must
  keep behaving exactly as before this existed;
* still fails a build by name for a genuinely required parameter, so the escape hatch did not turn the
  guard off everywhere.

Run: cd backend && .venv/bin/python -m pytest tests/test_skill_params_scope.py -v
"""
from __future__ import annotations

from core.skills import params as P

BUILDER = "db-ontology-build"
#: a skill with a plain `required: true` param, used to prove the guard still bites
STRICT = "db-ontology-ask"


def _spec(skill: str):
    return P.declared(P.BUILTIN_ROOT / skill / "SKILL.md")


def test_the_builder_declares_its_key_and_database_as_conversation_scoped():
    spec = _spec(BUILDER)
    assert spec["ontology_key"]["scope"] == "conversation"
    assert spec["datasource"]["scope"] == "conversation"
    # the old per-agent default is gone: `default_from: agent.datasource` was a second place to
    # configure the connection, and it disagreed with `config.database` on a keyless builder
    assert "default_from" not in spec["datasource"]


def test_a_keyless_builder_builds_with_no_problems_and_no_invented_values():
    values, problems = P.resolve(1, [BUILDER], {}, {})
    assert problems == []
    assert values == {BUILDER: {}}


def test_a_database_binding_does_not_masquerade_as_the_ontologys_database():
    """The ontology server's default `postgres` database is not what the skill builds from."""
    cfg = {"database": {"mode": "custom", "host": "127.0.0.1", "port": 5433,
                        "dbname": "postgres", "user": "langconfig", "password_set": True}}
    values, problems = P.resolve(1, [BUILDER], {}, cfg)
    assert problems == []
    assert "datasource" not in values[BUILDER]


def test_a_per_key_agent_keeps_its_values_and_derives_the_profile_file():
    values, problems = P.resolve(1, [BUILDER],
                                 {BUILDER: {"datasource": "sunhing", "ontology_key": "sunhing_v1"}},
                                 {})
    assert problems == []
    assert values[BUILDER]["datasource"] == "sunhing"
    assert values[BUILDER]["ontology_key"] == "sunhing_v1"
    assert values[BUILDER]["profile_file"] == "sunhing_v1_settings.json"


def test_a_required_parameter_is_still_fatal_by_name():
    """The escape hatch must not disarm the guard for skills that never opted in."""
    assert _spec(STRICT)["ontology_key"].get("required") is True
    assert "scope" not in _spec(STRICT)["ontology_key"]
    values, problems = P.resolve(7, [STRICT], {}, {})
    assert values == {}
    assert problems and "ontology_key" in problems[0] and "agent 7" in problems[0]
