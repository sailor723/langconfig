"""A skill's usage counter has to move when the skill is used — it never did.

Measured: `usage_count`, `last_used_at` and `avg_success_rate` were displayed in the skill list, the skill view and
the sidebar, and **nothing in the codebase ever wrote them**. `record_execution()` existed with the right logic and had
zero callers, so the library read "0 runs" for skills that agents had been served hundreds of times.

Two paths actually serve a skill, and both must count:

    skill("<id>")                        the progressive-disclosure tool
    read_file("skills/builtin/<id>/SKILL.md")   the staged sandbox mirror, which is how builtin skills are read

The `status` recorded per use means **the skill was served** (found, parsed, returned), not that the agent's task
succeeded — this platform has no signal for the latter, and the UI says which one it is.

Also asserted: an unknown skill id is a failed use, not a silent one, and the rate is seeded from the first real
outcome instead of from the column's `1.0` default (which read as "100 % success, never used").
"""
from __future__ import annotations

import pathlib

import pytest

from tools.native_impl import _skill_id_from_path

MESSAGES = pathlib.Path(__file__).resolve().parents[1] / "tools" / "native_impl.py"
REGISTRY = pathlib.Path(__file__).resolve().parents[1] / "core" / "skills" / "registry.py"


@pytest.mark.parametrize("path,expected", [
    ("/ws/skills/builtin/to-spec/SKILL.md", "to-spec"),
    ("skills/builtin/grilling/SKILL.md", "grilling"),
    ("/root/langconfig/skills/personal/1/erp-analyst/SKILL.md", "erp-analyst"),
    ("/root/langconfig/skills/builtin/to-spec/notes.md", None),
    ("/x/skills/whatever.md", None),
    ("/x/src/skills-report.md", None),
])
def test_only_a_skill_manifest_counts_as_a_skill_read(path: str, expected: str | None):
    assert _skill_id_from_path(path) == expected


def test_the_skill_tool_counts_its_uses():
    source = MESSAGES.read_text(encoding="utf-8")
    assert 'record_usage(found.skill_id, "explicit", "success"' in source, (
        "the skill tool serves a skill and does not count it — that is the bug this file exists for")
    assert 'record_usage(skill_id, "explicit", "failed"' in source, (
        "asking for a skill that does not exist is a failed use; it should not vanish")


def test_reading_a_skill_file_counts_its_use():
    source = MESSAGES.read_text(encoding="utf-8")
    assert "_skill_id_from_path(str(path))" in source, (
        "reading a staged SKILL.md is the common path for builtin skills and went uncounted")


def test_the_recorder_never_fails_the_call_it_measures():
    source = REGISTRY.read_text(encoding="utf-8")
    body = source.split("def record_usage(", 1)[1].split("\n    async def record_execution(", 1)[0]
    assert "except Exception:" in body, "a metrics write must not raise into the tool call"
    assert "usage_count = (skill_obj.usage_count or 0) + 1" in body
    assert "first_use" in body, "the first observation should seed the rate, not blend into the 1.0 default"


def test_the_counters_move(tmp_path):
    """One real use, measured end to end against the live database."""
    from db.database import SessionLocal
    from models.skill import Skill
    from sqlalchemy import select
    from core.skills.registry import get_skill_registry

    skill_id = "to-spec"
    with SessionLocal() as s:
        row = s.execute(select(Skill.usage_count).where(Skill.skill_id == skill_id)).scalar_one_or_none()
    if row is None:
        pytest.skip(f"{skill_id} is not in this database")

    registry = get_skill_registry()
    registry.record_usage(skill_id, "explicit", "success", source="test")

    with SessionLocal() as s:
        after = s.execute(
            select(Skill.usage_count, Skill.last_used_at).where(Skill.skill_id == skill_id)
        ).one()
    assert after[0] >= row + 1, "usage_count did not move"
    assert after[1] is not None, "last_used_at is still NULL"
