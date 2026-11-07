"""Gates: logics_query answers questions and CANNOT change the ontology it answers from."""
import pytest


def _agent():
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    db = SessionLocal()
    try:
        row = (db.query(DeepAgentTemplate)
               .filter(DeepAgentTemplate.name == "logics_query")
               .order_by(DeepAgentTemplate.id.desc()).first())
        if row is None:
            pytest.skip("NOT RUN: no logics_query agent in this install "
                        "(seed_logics_query_agent.py)")
        return row
    finally:
        db.close()


def test_the_query_agent_exists_and_is_visible():
    """An agent that answers numbers but cannot be found is missing (that is how 349 vanished:
    is_public=false and the list endpoint defaults to public_only)."""
    assert _agent().is_public is True


def test_it_holds_the_ask_tool_and_no_way_to_change_the_ontology():
    """Two guarantees, and the SECOND one is not a property of native_tools.

    deepagents injects its own FilesystemMiddleware (ls / read_file / write_file / edit_file / glob /
    grep / execute) and cannot be told not to, so asserting `write_file not in native_tools` (the first
    version of this test) measured the config, not the agent — the model could still write and, worse,
    still had `execute`, i.e. a shell in which psql answers the question without the ontology at all.
    `use_local_sandbox = False` is what actually removes `execute` (capability-gated on a disk backend);
    the remaining file tools are confined to the agent's own workspace.
    """
    cfg = _agent().config or {}
    tools = cfg.get("native_tools") or []
    assert "ontology_ask" in tools, tools
    # the one tool that could change the ontology
    assert "ontology_publish" not in tools, tools
    # …and the mechanism that keeps an ad-hoc SQL path out of the model's schema
    assert cfg.get("use_local_sandbox") is False, cfg.get("use_local_sandbox")


def test_its_ontology_comes_from_skill_parameters_not_from_prose():
    cfg = _agent().config or {}
    assert cfg.get("skills") == ["answer-ontology-question"], cfg.get("skills")
    params = (cfg.get("skill_params") or {}).get("answer-ontology-question") or {}
    assert params.get("ontology_key"), params
    assert params.get("workbench", "").startswith("http"), params


def test_the_answer_skill_declares_the_parameters_the_agent_supplies():
    import pathlib
    from core.skills import params as sp
    base = pathlib.Path(__file__).resolve().parents[1] / "skills" / "builtin"
    declared = sp.declared(base / "answer-ontology-question" / "SKILL.md")
    assert "ontology_key" in declared
    cfg = _agent().config or {}
    values, problems = sp.resolve(None, cfg.get("skills") or [], cfg.get("skill_params") or {},
                                 cfg)
    assert problems == [], problems
    assert values["answer-ontology-question"]["ontology_key"] == params_key(cfg)


def params_key(cfg):
    return (cfg.get("skill_params") or {}).get("answer-ontology-question", {}).get("ontology_key")
