"""Contract tests for ``scripts/prune_chat_checkpoints.py``.

The dangerous part of pruning checkpoints is *what it selects*, not the delete
itself. Chat and workflow runs share one LangGraph checkpointer, and a workflow
run that is paused for human approval is resumable state — deleting it would
break a run in flight. The selection is therefore defined as "threads that join
to a chat session with an empty transcript", and these tests pin that down:

* an empty chat session is selected;
* a session that has any message is never selected;
* a workflow thread (`task_*` / `run_*` / `workflow_*_node_*`) is never selected,
  even when it is huge and old, because it has no `chat_sessions` row;
* the age filter is honoured;
* the delete set only touches tables that actually carry `thread_id`
  (`checkpoint_migrations` records schema versions and must stay out).

These run against the live database (the checkpoint tables only exist there),
using a `test-prune-` prefix and cleaning up after themselves.
"""

import datetime
import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

# scripts/ is not a package; load the module by path.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prune_chat_checkpoints.py"
_spec = importlib.util.spec_from_file_location("prune_chat_checkpoints", _SCRIPT)
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)


PREFIX = "test-prune-"


def _agent_id(db) -> int:
    aid = db.execute(text("select min(id) from deep_agent_templates")).scalar()
    if aid is None:
        pytest.skip("no agent templates in this database")
    return int(aid)


def _add_session(db, sid: str, messages: str, days_old: int = 30) -> None:
    db.execute(
        text(
            """
            insert into chat_sessions
                (agent_id, session_id, messages, total_cost_usd, rag_context_tokens,
                 is_active, created_at, updated_at, is_favorite)
            values
                (:agent_id, :sid, cast(:msgs as json), 0, 0, true,
                 now() - make_interval(days => :age), now() - make_interval(days => :age), false)
            """
        ),
        {"agent_id": _agent_id(db), "sid": sid, "msgs": messages, "age": days_old},
    )


def _add_checkpoint(db, thread_id: str, blob: bytes = b"x" * 64) -> None:
    db.execute(
        text(
            """
            insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint)
            values (:t, '', :ck, 'msgpack', '{}'::jsonb)
            """
        ),
        {"t": thread_id, "ck": f"ck-{uuid.uuid4().hex[:8]}"},
    )
    db.execute(
        text(
            """
            insert into checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob)
            values (:t, '', 'messages', '1', 'msgpack', :blob)
            """
        ),
        {"t": thread_id, "blob": blob},
    )


@pytest.fixture
def db(db_session):
    """Rows created with the test prefix are removed whichever way the test ends.

    A failing assertion can leave the session mid-aborted-transaction, so roll
    back first — otherwise the cleanup itself raises and masks the real failure.
    """
    yield db_session
    try:
        db_session.rollback()
    except Exception:
        pass
    for stmt in (
        f"delete from checkpoint_blobs where thread_id like '{PREFIX}%'",
        f"delete from checkpoint_writes where thread_id like '{PREFIX}%'",
        f"delete from checkpoints where thread_id like '{PREFIX}%'",
        f"delete from chat_sessions where session_id like '{PREFIX}%'",
    ):
        try:
            db_session.execute(text(stmt))
            db_session.commit()
        except Exception:
            db_session.rollback()


# ── what gets selected ──────────────────────────────────────────────────────

def test_empty_chat_session_is_selected(db):
    sid = f"{PREFIX}empty-{uuid.uuid4().hex[:8]}"
    _add_session(db, sid, "[]")
    _add_checkpoint(db, sid)
    db.commit()

    targets = prune.find_targets(db, older_than_days=0)
    ids = {t["session_id"] for t in targets}
    assert sid in ids
    assert next(t for t in targets if t["session_id"] == sid)["ckpt_rows"] >= 1


def test_session_with_messages_is_never_selected(db):
    sid = f"{PREFIX}used-{uuid.uuid4().hex[:8]}"
    _add_session(db, sid, '[{"role": "user", "content": "hi"}]')
    _add_checkpoint(db, sid)
    db.commit()

    assert sid not in {t["session_id"] for t in prune.find_targets(db, 0)}


def test_null_messages_counts_as_empty(db):
    sid = f"{PREFIX}null-{uuid.uuid4().hex[:8]}"
    _add_session(db, sid, "null")
    db.commit()
    assert sid in {t["session_id"] for t in prune.find_targets(db, 0)}


def test_workflow_thread_is_never_selected(db):
    """A resumable HITL run shares the checkpointer but has no chat_sessions row."""
    thread = f"{PREFIX}workflow-task_999_node_1"
    _add_checkpoint(db, thread, blob=b"y" * 4096)
    db.commit()

    targets = prune.find_targets(db, older_than_days=0)
    assert thread not in {t["session_id"] for t in targets}
    # and it is still in the database — selection must not have touched it
    still_there = db.execute(
        text("select count(*) from checkpoints where thread_id = :t"), {"t": thread}
    ).scalar()
    assert still_there >= 1


def test_age_filter_is_honoured(db):
    recent = f"{PREFIX}recent-{uuid.uuid4().hex[:8]}"
    old = f"{PREFIX}old-{uuid.uuid4().hex[:8]}"
    _add_session(db, recent, "[]", days_old=1)
    _add_session(db, old, "[]", days_old=120)
    db.commit()

    older = {t["session_id"] for t in prune.find_targets(db, older_than_days=90)}
    assert old in older
    assert recent not in older


# ── the delete set ─────────────────────────────────────────────────────────

def test_delete_tables_all_carry_thread_id(db):
    """`checkpoint_migrations` must stay out: it stores schema versions, not rows
    per thread, and including it aborted a real run with "column thread_id does
    not exist"."""
    assert "checkpoint_migrations" not in prune.CHECKPOINT_TABLES
    for table in prune.CHECKPOINT_TABLES:
        has_col = db.execute(
            text(
                "select count(*) from information_schema.columns "
                "where table_name = :t and column_name = 'thread_id'"
            ),
            {"t": table},
        ).scalar()
        assert has_col == 1, f"{table} has no thread_id column"


def test_prune_deletes_only_the_given_threads(db):
    victim = f"{PREFIX}victim-{uuid.uuid4().hex[:8]}"
    keeper = f"{PREFIX}keeper-{uuid.uuid4().hex[:8]}"
    _add_session(db, victim, "[]")
    _add_session(db, keeper, '[{"role": "user", "content": "keep me"}]')
    _add_checkpoint(db, victim)
    _add_checkpoint(db, keeper)
    db.commit()

    counts = prune.prune(db, [victim])
    assert counts["checkpoints"] >= 1
    assert counts["checkpoint_blobs"] >= 1

    remaining = {
        r[0]
        for r in db.execute(
            text("select distinct thread_id from checkpoints where thread_id like :p"),
            {"p": f"{PREFIX}%"},
        ).all()
    }
    assert victim not in remaining
    assert keeper in remaining


def test_dry_run_selection_is_read_only(db):
    sid = f"{PREFIX}readonly-{uuid.uuid4().hex[:8]}"
    _add_session(db, sid, "[]")
    _add_checkpoint(db, sid)
    db.commit()

    before = db.execute(text("select count(*) from checkpoints")).scalar()
    prune.find_targets(db, older_than_days=0)          # what --dry-run does
    after = db.execute(text("select count(*) from checkpoints")).scalar()
    assert before == after


# ── helpers ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "n, expected",
    [(0, "0.0 B"), (512, "512.0 B"), (2048, "2.0 KB"), (5 * 1024**3, "5.0 GB")],
)
def test_human_sizes(n, expected):
    assert prune._human(n) == expected
