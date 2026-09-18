# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the skill-review path-traversal fix.

csv_stem arrives from the URL and was interpolated into sandbox file paths
with no sanitization, allowing ``..`` traversal to read/rename/write files
outside the sandbox (arbitrary read via GET, arbitrary write via POST).
"""
import pytest
from fastapi import HTTPException

from api.chat import skill_review
from api.chat.skill_review import _sanitize_csv_stem


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the skill-review sandbox at a temp dir."""
    monkeypatch.setattr(skill_review, "_get_sandbox_dir", lambda: tmp_path)
    return tmp_path


# ── sanitizer unit tests ─────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "../etc/passwd",
    "..%2Fetc%2Fpasswd",
    "a/b",
    "a\\b",
    "dir/../x",
    ".",
    "..",
    "",
    "   ",
])
def test_sanitize_rejects_traversal(bad):
    with pytest.raises(HTTPException) as exc:
        _sanitize_csv_stem(bad)
    assert exc.value.status_code == 400


def test_sanitize_accepts_plain_stem():
    assert _sanitize_csv_stem("orders_2026") == "orders_2026"
    assert _sanitize_csv_stem("orders.report.v2") == "orders.report.v2"


# ── endpoint tests ───────────────────────────────────────────────────

async def test_get_rejects_traversal_stem(sandbox):
    with pytest.raises(HTTPException) as exc:
        await skill_review.get_pending_skill("session-1", "../outside")
    assert exc.value.status_code == 400


async def test_post_rejects_traversal_stem(sandbox):
    with pytest.raises(HTTPException) as exc:
        await skill_review.review_pending_skill(
            "session-1", "../../etc/x", skill_review.SkillReviewAction(action="approve")
        )
    assert exc.value.status_code == 400


async def test_get_returns_pending_content(sandbox):
    pending = sandbox / "orders.skill.md.pending"
    pending.write_text("# Pending skill body", encoding="utf-8")
    result = await skill_review.get_pending_skill("session-1", "orders")
    assert result["status"] == "pending"
    assert "Pending skill body" in result["content"]


async def test_approve_renames_pending_to_active(sandbox):
    (sandbox / "orders.skill.md.pending").write_text("body", encoding="utf-8")
    result = await skill_review.review_pending_skill(
        "session-1", "orders", skill_review.SkillReviewAction(action="approve")
    )
    assert result["status"] == "approved"
    assert (sandbox / "orders.skill.md").exists()
    assert not (sandbox / "orders.skill.md.pending").exists()


async def test_get_missing_stem_404(sandbox):
    with pytest.raises(HTTPException) as exc:
        await skill_review.get_pending_skill("session-1", "does-not-exist")
    assert exc.value.status_code == 404
