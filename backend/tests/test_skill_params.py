"""Gates: a skill declares the parameters it needs; the agent supplies the values; nothing is guessed."""
import pathlib
import pytest
from core.skills import params as sp

BUILTIN = pathlib.Path(__file__).resolve().parents[1] / "skills" / "builtin"


def test_the_three_ontology_skills_declare_their_parameters():
    for skill, expected in (("build-ontology-from-db", {"datasource", "ontology_key"}),
                            ("edit-ontology-metrics", {"ontology_key"}),
                            ("answer-ontology-question", {"ontology_key"})):
        declared = sp.declared(BUILTIN / skill / "SKILL.md")
        assert expected <= set(declared), (skill, declared)


def test_a_required_parameter_with_no_value_fails_by_name():
    values, problems = sp.resolve(350, ["edit-ontology-metrics"], {}, {"skills": ["edit-ontology-metrics"]})
    assert values == {}
    assert problems and "ontology_key" in problems[0] and "edit-ontology-metrics" in problems[0]


def test_a_parameter_can_default_from_the_agent_config():
    values, problems = sp.resolve(
        349, ["build-ontology-from-db"],
        {"build-ontology-from-db": {"ontology_key": "logistics"}},
        {"datasource": "logistics"})
    assert problems == [], problems
    assert values["build-ontology-from-db"] == {
        "datasource": "logistics", "ontology_key": "logistics",
        "profile_file": "logistics_settings.json"}      # the {ontology_key} default was expanded


def test_a_skill_without_parameters_is_untouched():
    values, problems = sp.resolve(1, ["code-review"], {"code-review": {"x": 1}}, {})
    assert values == {} and problems == []


def test_the_prompt_block_states_the_values_once():
    block = sp.render_block({"answer-ontology-question": {"ontology_key": "logistics",
                                                          "workbench": "http://127.0.0.1:8098"}})
    assert "# Skill parameters" in block
    assert "`ontology_key` = `logistics`" in block
    assert "params.json" in block


def test_params_json_is_written_next_to_the_skill(tmp_path):
    target = sp.write_params(tmp_path, "edit-ontology-metrics", {"ontology_key": "logistics"})
    assert target is not None and target.name == "params.json"
    assert '"ontology_key": "logistics"' in target.read_text(encoding="utf-8")
