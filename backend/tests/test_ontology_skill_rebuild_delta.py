"""A rebuild must MEASURE the database before it claims the structure did not change.

The failure this guards (2026-11-11, reviewing a 2026-11-08 build): the delta ledger said

    {"step": "S1", "why": "结构未变（无新增/删除对象与列）"}

while `check_structure` against the same database reported nine tables the ontology never modelled. The
first build enters at S0 and reads the database; a rebuild enters at S-1 and reads the documents — so the
one path that claims to be cheaper was blind to a database that grew, and it published.

The skill now says S-1 opens with the structure gate. These tests hold that in place: the prose, the
numbered rule, the recorded pitfall, and the skill's own linter.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO / "backend" / "skills" / "builtin" / "build-ontology-from-db"
SKILL = SKILL_DIR / "SKILL.md"
RULES = SKILL_DIR / "references" / "rules.md"
PITFALLS = SKILL_DIR / "references" / "pitfalls.md"
LINTER = REPO / "backend" / "scripts" / "check_skill.py"


@pytest.fixture(scope="module")
def skill_text():
    if not SKILL.is_file():
        pytest.skip("the ontology build skill is not installed in this checkout")
    return SKILL.read_text(encoding="utf-8")


def _s1_section(text: str) -> str:
    start = text.index("## S-1.")
    end = text.index("## S0.")
    return text[start:end]


# ── the prose ───────────────────────────────────────────────────────────────

def test_s1_starts_by_measuring_the_database(skill_text):
    """The gate comes before the delta items are written, not as an afterthought further down."""
    s1 = _s1_section(skill_text)
    gate = s1.index("check_structure.py")
    delta_block = s1.index("delta.json` 必须能解析") if "delta.json` 必须能解析" in s1 else None
    assert gate < s1.index("规则，按顺序"), \
        "the structure gate must be introduced before the delta rules, not inside them"
    assert delta_block is None or gate < delta_block


def test_s1_names_the_database_as_a_fourth_input(skill_text):
    s1 = _s1_section(skill_text)
    assert "库的当下 schema 是第四份输入" in s1
    assert "首建从 S0 进" in s1 and "重建从 S-1 进" in s1, \
        "the section must state the blind spot it closes (first build reads the DB, rebuild read documents)"


def test_skipping_s1_without_the_gate_is_called_out(skill_text):
    """`skip: S1` is legal only with the gate's own line as evidence."""
    s1 = _s1_section(skill_text)
    assert "跳过 S1 而没有 `check_structure` 的绿行" in s1
    assert "规则 27" in s1, "the prose must point at the numbered rule that carries the gate"


def test_s1_reports_this_rounds_failure_with_its_numbers(skill_text):
    """The scoreboard earns its authority from being the actual failure, not a general warning."""
    assert "9 uncovered" in skill_text
    assert "driver_schedule" in skill_text, "the failing tables must be named, not summarised"
    assert "结构未变" in skill_text


# ── the numbered rule ───────────────────────────────────────────────────────

def test_rule_27_exists_and_names_the_structure_gate():
    text = RULES.read_text(encoding="utf-8")
    block = text.split("## 27.", 1)
    assert len(block) == 2, "rule 27 is missing"
    body = block[1]
    assert "check_structure.py" in body.split("## ")[0]
    assert "ontology_open" in body.split("## ")[0], \
        "a rebuild gets a copy with ontology_open, never `cp -r` of the repo"
    assert "**Gate:**" in body.split("## ")[0]


def test_the_rule_count_in_prose_matches_the_rules_defined():
    """The linter only understands number-words up to twenty; the hyphenated counts are on us."""
    text = RULES.read_text(encoding="utf-8")
    defined = re.findall(r"^##\s+(\d+[a-z]?)\.\s+", text, re.M)
    header = re.search(r"^(Twenty[-a-z]*|Thirty[-a-z]*|[A-Z][a-z]+)\s+rules", text, re.M)
    assert header, "rules.md no longer states how many rules it holds"
    words = {"Twenty-four": 24, "Twenty-five": 25, "Twenty-six": 26, "Twenty-seven": 27,
             "Twenty-eight": 28, "Twenty-nine": 29, "Thirty": 30}
    assert header.group(1) in words, f"unmapped count word {header.group(1)!r}"
    assert words[header.group(1)] == len(defined), \
        f"rules.md claims {header.group(1)} but defines {len(defined)} rules"


def test_the_pitfall_is_recorded_with_the_gate_output():
    text = PITFALLS.read_text(encoding="utf-8")
    assert "结构未变" in text
    assert "9 uncovered" in text and "212 checks" in text, \
        "the pitfall must carry the gate's own output, not a retelling"
    assert "rule 27" in text, "a pitfall that does not say what changed will be re-learned"


# ── the skill's own version and linter ──────────────────────────────────────

def test_the_version_was_bumped_for_a_base_skill_change(skill_text):
    """Changing this skill is changing every future build, so it carries a datable version."""
    version = re.search(r"^version:\s*\"?([0-9.]+)\"?\s*$", skill_text, re.M)
    assert version, "no version in the front matter"
    major, minor = (int(x) for x in version.group(1).split(".")[:2])
    assert (major, minor) >= (3, 2), f"S-1 changed but the skill still says {version.group(1)}"


def test_the_skill_lints_itself():
    """`check_skill.py` is the repo's own gate on this file: it must stay at zero problems."""
    if not LINTER.is_file():
        pytest.skip("scripts/check_skill.py is not present")
    proc = subprocess.run([sys.executable, str(LINTER), "--skill", "build-ontology-from-db"],
                          capture_output=True, text=True, timeout=120, cwd=str(REPO / "backend"))
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "0 problem(s)" in proc.stdout, proc.stdout
