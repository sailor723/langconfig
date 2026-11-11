"""`scripts/agent_train.py` — the spec has to be able to say no.

Training an agent by spec is only better than a one-off script if the spec is validated and the
stored row can be compared against it. Both halves are tested here without writing to the database:
the loader's rules, the config/doc compilation, and the validation that separates "this name is not
supplied at all" (an error) from "the SDK may supply it, depending on the backend" (a warning).

The live round trip is evidence, not a unit test: `--check` said OK for agent 375, a copy of the spec
with `temperature: 0.21` was applied, `--check` then reported `DRIFT: temperature: 0.21 -> 0.2`, and
re-applying the real spec printed `OK` again.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "agent_train.py"
SPEC = REPO / "backend" / "agents" / "table-builder.yaml"


@pytest.fixture(scope="module")
def trainer():
    if not SCRIPT.is_file():
        pytest.skip("agent_train.py not present")
    spec = importlib.util.spec_from_file_location("agent_train", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── the spec loader ─────────────────────────────────────────────────────────

def _write(tmp_path, text, name="spec.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_prompt_file_is_read_relative_to_the_spec(trainer, tmp_path):
    (tmp_path / "p.md").write_text("你是测试 agent。", encoding="utf-8")
    spec = trainer.load_spec(_write(tmp_path, "name: t\nprompt_file: p.md\n"))
    assert spec["prompt"] == "你是测试 agent。"


def test_a_missing_prompt_file_is_refused(trainer, tmp_path):
    with pytest.raises(SystemExit) as exc:
        trainer.load_spec(_write(tmp_path, "name: t\nprompt_file: nope.md\n"))
    assert "does not exist" in str(exc.value)


def test_inline_and_file_together_are_refused(trainer, tmp_path):
    (tmp_path / "p.md").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        trainer.load_spec(_write(tmp_path, "name: t\nprompt: x\nprompt_file: p.md\n"))
    assert "not both" in str(exc.value)


def test_an_unknown_key_is_refused_rather_than_silently_ignored(trainer, tmp_path):
    """A typo like `nativ_tools:` would otherwise produce an agent with no tools and no error."""
    with pytest.raises(SystemExit) as exc:
        trainer.load_spec(_write(tmp_path, "name: t\nprompt: x\nnativ_tools: [bash]\n"))
    assert "unknown spec keys" in str(exc.value)


def test_a_hand_written_identity_tail_is_refused(trainer):
    spec = {"name": "t", "prompt": "正文\n\n## Identity\n- Agent ID: 1"}
    problems, _ = trainer.validate_against_platform(_FakeDB(), spec)
    assert any("Identity" in p for p in problems)


# ── what is an error, and what is only a warning ────────────────────────────

def test_a_tool_that_nothing_supplies_is_an_error(trainer):
    problems, _ = trainer.validate_against_platform(_FakeDB(), {"name": "t", "native_tools": ["no_such_tool"]})
    assert problems and "no_such_tool" in problems[0]


def test_an_sdk_filesystem_tool_is_a_warning_not_a_pass(trainer):
    """`glob` was accepted by the row and never bound — the validator must say so out loud."""
    problems, warnings = trainer.validate_against_platform(_FakeDB(), {"name": "t", "native_tools": ["glob"]})
    assert problems == []
    assert warnings and "SDK" in warnings[0]


def test_a_catalogued_tool_is_silent(trainer):
    problems, warnings = trainer.validate_against_platform(
        _FakeDB(tools=["list_files"]), {"name": "t", "native_tools": ["list_files"]})
    assert problems == [] and warnings == []


def test_a_skill_with_no_skill_md_is_an_error(trainer):
    problems, _ = trainer.validate_against_platform(_FakeDB(), {"name": "t", "skills": ["no-such-skill"]})
    assert problems and "no-such-skill" in problems[0]


# ── compilation ─────────────────────────────────────────────────────────────

def test_config_compiles_interrupts_and_defaults(trainer):
    config = trainer.build_config({
        "name": "t", "native_tools": ["list_files"], "skills": ["sql-analyst"],
        "interrupts": {"db_build_from_file": {"allowed_decisions": ["approve", "reject"]}},
        "use_local_sandbox": False,
    })
    assert config["native_tools"] == ["list_files"]
    assert config["skills"] == ["sql-analyst"]
    assert config["guardrails"]["interrupts"]["db_build_from_file"]["allowed_decisions"] == ["approve", "reject"]
    assert config["use_local_sandbox"] is False
    assert config["temperature"] == 0.2 and config["recursion_limit"] == 60


def test_the_diff_names_every_changed_field(trainer):
    previous = {"model": "a", "native_tools": ["x"], "skills": []}
    config = {"model": "b", "native_tools": ["x", "list_files"], "skills": ["sql-analyst"],
              "guardrails": {"interrupts": {}}}
    lines = "\n".join(trainer.summarise(config, previous))
    assert "model" in lines and "native_tools" in lines and "skills" in lines


def test_an_unchanged_agent_produces_no_diff(trainer):
    config = trainer.build_config({"name": "t", "native_tools": [], "skills": []})
    assert trainer.summarise(config, config) == []


# ── the shipped spec ────────────────────────────────────────────────────────

def test_the_table_builder_spec_is_structurally_sound():
    """Catches a broken spec without needing a database: names, files and the confirmation gate."""
    import yaml

    if not SPEC.is_file():
        pytest.skip("spec not present")
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["prompt_file"].endswith(".md")
    assert "list_files" in spec["native_tools"], "the agent that could not list its own upload"
    assert "db_plan_from_file" in spec["native_tools"] and "db_build_from_file" in spec["native_tools"]
    assert "db_build_from_file" in spec["interrupts"], "building must stay behind an approval"
    assert spec["use_local_sandbox"] is False, "this agent should not need a shell"


class _FakeDB:
    """Just enough session for the validator: it queries CustomTool rows."""

    def __init__(self, tools=()):
        self._tools = [type("Row", (), {"tool_id": t})() for t in tools]

    def query(self, _model):
        return self

    def all(self):
        return self._tools


# ── a prompt-only edit is a change ──────────────────────────────────────────

def test_a_prompt_edit_is_not_reported_as_nothing_to_change(trainer):
    """The first version compared only config keys, so `--dry-run` said "nothing to change" for the
    one edit a training session usually makes."""
    lines = trainer.text_differs("old body", "a longer new body", {"AGENTS.md": "x"}, {"AGENTS.md": "x"})
    assert lines and "prompt:" in lines[0]


def test_a_docs_edit_is_a_change_and_trailing_newlines_are_not(trainer):
    assert trainer.text_differs("same", "same", {"AGENTS.md": "a"}, {"AGENTS.md": "a\n"}) == []
    assert trainer.text_differs("same", "same", {"AGENTS.md": "a"}, {"AGENTS.md": "b"})
