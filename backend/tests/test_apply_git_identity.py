"""An apply must be able to commit without a person's git identity on the checkout.

Measured on a fresh ECS deployment (2026-11-13): applying a staged meeting_v1 publish installed every
file and set the row to `applied`, yet the journal said `git commit for meeting_v1 failed: Author
identity unknown` — the repo had no user.name/user.email, so the commit never happened, the files sat
STAGED, and the UI reported an error for work that had already landed. The applier is the committer;
it supplies its own identity for that one commit.
"""
import pathlib

PUBLISH = pathlib.Path(__file__).resolve().parents[1] / "services" / "ontology_publish.py"


def test_the_apply_commit_carries_a_platform_identity():
    text = PUBLISH.read_text(encoding="utf-8")
    start = text.index("def _git(")
    body = text[start:text.index("# ─────────────────────────────────────────────────────────────── stage")]
    assert '"-c", "user.name=' in body, "the commit still relies on the checkout's git identity"
    assert '"-c", "user.email=' in body
    assert '"commit", "-m", message' in body


def test_the_identity_is_per_commit_not_a_global_side_effect():
    text = PUBLISH.read_text(encoding="utf-8")
    assert '"config", "user.name"' not in text, \
        "the applier must not rewrite the checkout's git config"
