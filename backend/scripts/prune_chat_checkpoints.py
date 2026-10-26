#!/usr/bin/env python
"""Prune LangGraph checkpoints for chat sessions that hold no conversation.

Why this exists
---------------
Chat is the biggest writer to the checkpoint tables: every graph step stores a
snapshot, and a runaway agent loop can produce tens of thousands of them for a
single session. On the reference install one such session accounted for ~5.4 GB
of `checkpoint_blobs` while holding **zero** messages — nothing a user can see,
nothing a report would miss.

Two facts make a safe pruning possible:

* **The transcript is stored separately.** `chat_sessions.messages` and
  `conversation_archives` are the record; the checkpoint is the *agent's memory*.
  Deleting a checkpoint never deletes the conversation a user can read.
* **Chat threads and workflow threads are distinguishable.** A chat thread is the
  session's UUID and always has a `chat_sessions` row; workflow threads are named
  `task_*`, `run_*`, `workflow_*_node_*`. This script only ever deletes threads
  that match a chat session, so a workflow's resumable (HITL) run can never be
  touched.

The cost, stated plainly: a pruned session that is continued later starts with
**empty** agent state. The UI still shows its history (that lives in the
database), but the model no longer remembers it. There is currently no
`chat_sessions.messages -> checkpoint` rehydration path.

Usage
-----
    # what would be deleted (no writes)
    .venv/bin/python scripts/prune_chat_checkpoints.py --dry-run

    # delete checkpoints of sessions with no messages, older than 7 days,
    # taking a pg_dump of the four checkpoint tables first
    .venv/bin/python scripts/prune_chat_checkpoints.py --apply --older-than-days 7

    # additionally drop the now-empty session rows themselves
    .venv/bin/python scripts/prune_chat_checkpoints.py --apply --delete-empty-sessions
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "pyproject.toml").exists():
        sys.path.insert(0, str(_p))
        break

from sqlalchemy import bindparam, text  # noqa: E402

from db.database import SessionLocal, engine  # noqa: E402

# Tables that carry a `thread_id`. `checkpoint_migrations` is deliberately NOT
# here: it only records the checkpointer's own schema version (single column
# `v`), so there is nothing per-thread to delete — trying to would fail the whole
# transaction.
CHECKPOINT_TABLES = (
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoints",
)


def find_targets(db, older_than_days: int) -> list[dict]:
    """Chat sessions whose transcript is empty (optionally also old enough)."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=older_than_days
    )
    rows = db.execute(
        text(
            """
            select s.session_id,
                   s.agent_id,
                   s.title,
                   s.created_at,
                   s.updated_at,
                   case
                     when s.messages is null or json_typeof(s.messages) <> 'array' then 0
                     else json_array_length(s.messages)
                   end as msg_count,
                   (select count(*) from checkpoints c
                     where c.thread_id = s.session_id) as ckpt_rows,
                   (select coalesce(sum(pg_column_size(b.blob)), 0)
                      from checkpoint_blobs b
                     where b.thread_id = s.session_id) as blob_bytes
              from chat_sessions s
             -- A transcript that is not a non-empty array holds no messages:
             -- SQL NULL, JSON null, a scalar or an object all mean "empty".
             -- CASE, not OR, so json_array_length is only evaluated for arrays.
             where case
                     when s.messages is null or json_typeof(s.messages) <> 'array' then true
                     else json_array_length(s.messages) = 0
                   end
               and coalesce(s.updated_at, s.created_at) < :cutoff
             order by blob_bytes desc
            """
        ),
        {"cutoff": cutoff},
    ).all()
    return [dict(r._mapping) for r in rows]


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def backup(db_url, out_dir: Path) -> Path | None:
    """pg_dump the checkpoint tables so a wrong call is recoverable."""
    url = engine.url
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"checkpoints-{stamp}.dump"
    cmd = [
        "pg_dump",
        "-h", url.host or "localhost",
        "-p", str(url.port or 5432),
        "-U", url.username or "postgres",
        "-d", url.database,
        "-Fc",
    ]
    for table in (*CHECKPOINT_TABLES, "checkpoint_migrations"):
        cmd += ["-t", f"public.{table}"]
    cmd += ["-f", str(target)]

    env = {"PGPASSWORD": url.password or ""}
    import os

    full_env = {**os.environ, **env}
    try:
        subprocess.run(cmd, check=True, env=full_env, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        print(f"  ✗ pg_dump failed: {exc} {detail.decode(errors='replace')[:200]}")
        return None
    return target


def prune(db, session_ids: list[str]) -> dict:
    """Delete one thread's rows from every checkpoint table."""
    counts: dict[str, int] = {}
    if not session_ids:
        return counts
    for table in CHECKPOINT_TABLES:
        result = db.execute(
            text(f"delete from {table} where thread_id in :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": session_ids},
        )
        counts[table] = result.rowcount or 0
    db.commit()
    return counts


def drop_empty_sessions(db, session_ids: list[str]) -> int:
    if not session_ids:
        return 0
    result = db.execute(
        text(
            "delete from chat_sessions where session_id in :ids "
            "and (messages is null or json_typeof(messages) <> 'array' "
            "     or json_array_length(messages) = 0)"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": session_ids},
    )
    db.commit()
    return result.rowcount or 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report only (default behaviour)")
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--older-than-days", type=int, default=0,
                    help="only touch sessions whose last update is older than this (default 0)")
    ap.add_argument("--delete-empty-sessions", action="store_true",
                    help="also delete the empty chat_sessions rows (their transcript is empty)")
    ap.add_argument("--limit", type=int, default=0, help="max sessions to process (0 = all)")
    ap.add_argument("--backup-dir", default="/tmp/langconfig-checkpoint-backup",
                    help="where pg_dump writes the rollback archive")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip pg_dump (use when an archive for these tables already exists)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        targets = find_targets(db, args.older_than_days)
        if args.limit:
            targets = targets[: args.limit]

        total_blobs = sum(t["blob_bytes"] or 0 for t in targets)
        total_ckpts = sum(t["ckpt_rows"] or 0 for t in targets)

        print("Chat sessions with an EMPTY transcript"
              + (f" older than {args.older_than_days}d" if args.older_than_days else "")
              + ":")
        print(f"  sessions            : {len(targets)}")
        print(f"  checkpoint rows     : {total_ckpts}")
        print(f"  blob bytes (on disk): {_human(total_blobs)}")
        if targets:
            print("\n  largest 5:")
            for t in targets[:5]:
                print(f"    {t['session_id'][:8]}…  agent {t['agent_id']:<4} "
                      f"msgs=0  blobs={_human(t['blob_bytes'] or 0):>9}  "
                      f"updated={str(t['updated_at'])[:10]}")
        print("\n  workflow threads (task_*/run_*/workflow_*_node_*) are NOT touched — "
              "this script only deletes threads that have a chat_sessions row.")

        if not args.apply:
            print("\nDRY RUN — nothing deleted. Re-run with --apply to execute.")
            return 0

        ids = [t["session_id"] for t in targets]
        if not ids:
            print("\nNothing to do.")
            return 0

        if args.no_backup:
            print("\n  --no-backup: relying on an existing archive for these tables")
        else:
            archive = backup(engine.url, Path(args.backup_dir))
            if archive:
                print(f"\n  rollback archive: {archive}")
            else:
                print("\n  ⚠️  no archive written — aborting (use --backup-dir, or --no-backup)")
                return 1

        counts = prune(db, ids)
        print("\n  deleted:")
        for table, n in counts.items():
            print(f"    {table:22} {n}")

        if args.delete_empty_sessions:
            dropped = drop_empty_sessions(db, ids)
            print(f"    chat_sessions (empty)   {dropped}")

        print("\nDone. Re-run --dry-run to confirm the remaining footprint.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
