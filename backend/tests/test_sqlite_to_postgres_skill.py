"""The sqlite-to-postgres skill must state the four things a migration silently gets wrong.

Why a skill and not just the script: `migrate_sqlite_to_postgres.py` moves the DATA and proves the copy.
What it cannot do is notice the four things that do not travel with data —

  * SQL stored as TEXT in a table (`dim_kpi.formula`) still says `?`, which PostgreSQL reads as nothing;
  * a dimension table and a fact table can spell the same id differently (`a/b` vs `a_b`), so a join drops
    rows without an error;
  * `REAL` → `numeric` stops the value drifting but says nothing about whether 0.9459 means "94.6 %";
  * `period` is a string, and a month after today that sits in an `actual` column is not an actual.

Measured on one 23-table / 2 361-row migration (2026-11-11): 25 stored formulas needed `?`→`%s` (all 25 then
agreed with the fact table), 3 of 28 KPIs never joined, and three months of `actual` were in the future.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO / "backend" / "skills" / "builtin" / "sqlite-to-postgres"
SKILL = SKILL_DIR / "SKILL.md"
RULES = SKILL_DIR / "references" / "rules.md"
TOOL = REPO / "backend" / "scripts" / "migrate_sqlite_to_postgres.py"
LINTER = REPO / "backend" / "scripts" / "check_skill.py"
ZH_NATIVE = REPO / "backend" / "skills" / "zh-native.txt"


@pytest.fixture(scope="module")
def text():
    if not SKILL.is_file():
        pytest.skip("the skill is not installed in this checkout")
    return SKILL.read_text(encoding="utf-8")


# ── the skill exists, and says what it is for ──────────────────────────────

def test_the_skill_and_its_tool_are_both_present(text):
    assert TOOL.is_file(), "the migration tool the skill drives is missing"
    assert "sqlite-to-postgres" in text
    assert "migrate_sqlite_to_postgres.py" in text, "the skill must name the tool it runs"


def test_the_four_post_migration_checks_are_written_down(text):
    for needed, why in [
        ("%s", "the `?` → `%s` placeholder difference has to be stated"),
        ("join", "orphan ids between dimension and fact have to be stated"),
        ("scale", "unit/scale has to be stated"),
        ("period", "the string-period / future-actual caveat has to be stated"),
    ]:
        assert needed in text, f"the skill does not mention {needed!r} ({why})"


def test_the_refusals_are_explicit(text):
    for forbidden in ("不在核对 PASS 之前宣布迁移完成", "不把 `REAL` 翻成 `float`",
                      "不隐藏孤儿 id", "不在交付物里写口令"):
        assert forbidden in text, f"missing refusal: {forbidden}"


def test_the_skill_forbids_a_password_on_the_command_line(text):
    """Measured on the agent's first real run: it exported PGPASSWORD in a shell command, which puts the
    credential in the transcript the tool log and the delivered report. The script reads the deployment's
    .env itself, so there is no reason to type one."""
    assert "export PGPASSWORD" in text, "the skill must name the exact command shape it forbids"
    assert "--password" in text
    assert "POSTGRES_PASSWORD" in text, "and it must say where the connection actually comes from"


def test_the_rules_file_is_scheduled_and_gated():
    text = SKILL.read_text(encoding="utf-8")
    assert "references/rules.md" in text, "a reference nothing links is a reference nobody reads"
    rules = RULES.read_text(encoding="utf-8")
    assert "**Gate:**" in rules
    assert "**Ungated (advisory)**" in rules, \
        "the rules with no gate must say so rather than pretend to be enforced"


def test_the_skill_is_recorded_as_zh_native():
    """It was written in Chinese; the archive list is what stops a later pass translating it again."""
    assert "sqlite-to-postgres" in ZH_NATIVE.read_text(encoding="utf-8").split("\n")


def test_the_skill_lints_itself():
    proc = subprocess.run([sys.executable, str(LINTER), "--skill", "sqlite-to-postgres"],
                          capture_output=True, text=True, timeout=180, cwd=str(REPO / "backend"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 problem(s)" in proc.stdout


# ── the linter's own version check (it was red for the majority of the library) ────────────

def test_the_linter_accepts_a_double_quoted_version():
    """52 of 88 skills write `version: "1.0"`; a lint that is always red is a lint nobody reads."""
    body = LINTER.read_text(encoding="utf-8")
    assert 'r"^version:\\s*[\\"\']?[0-9]"' in body, "L1 went back to accepting only the single quote"
