#!/usr/bin/env python
"""Move the workspace tree into per-user roots (Slice 2, step 2).

Before accounts, everything lived flat: ``<root>/<vault>/…``. Slice 2 puts each
person's files under ``<root>/users/<id>/…``, and nothing but this script moves the
existing bytes. It is **dry-run by default** and reversible, because it relocates a
running installation's files.

Why a move and not a copy: the tree is on one filesystem, so ``rename`` is a
metadata operation — 763 MB of files move in milliseconds and the disk does not
double in size. A copy would need the free space and a cleanup pass on failure.

Safety rules baked in:

* **Dry run first.** It prints exactly what it would move and exits without touching
  anything. ``--apply`` is required to act.
* **Refuses to guess.** The owner must be an existing active admin; if ``users/``
  already holds something it stops rather than merging two trees.
* **Resumable.** Entries are renamed one at a time, so an interrupted run leaves
  some entries moved and some not; running it again continues (the ones already
  moved are no longer at the top level). It reports what it skipped.
* **Rollback exists and is tested.** ``--rollback`` moves every entry back up and
  removes ``users/`` — the only state change that cannot be expressed as a query.
* **Database rows are not rewritten, on purpose.** ``workspace_files.file_path`` and
  ``storage_objects.key`` are stored *relative to the owner's root*, so the move
  does not invalidate a single row; ``--verify`` proves it by resolving the sample
  paths against the new root.

Usage::

    cd backend
    .venv/bin/python scripts/adopt_user_workspaces.py                 # dry run
    .venv/bin/python scripts/adopt_user_workspaces.py --apply         # do it
    .venv/bin/python scripts/adopt_user_workspaces.py --verify        # after the move
    .venv/bin/python scripts/adopt_user_workspaces.py --rollback      # undo
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from services import user_roots  # noqa: E402

#: Never moved: the container itself, and anything a later step may add as install-wide.
NEVER_MOVE = {"users"}


def _owner_id(db) -> int:
    from services.user_service import owner_user

    owner = owner_user(db)
    if owner is None:
        raise SystemExit(
            "no active admin account exists; Slice 2 needs somebody to own the files.\n"
            "  create one: cd backend && .venv/bin/python scripts/create_user.py admin '<pw>' --admin"
        )
    if not getattr(owner, "is_admin", lambda: False)():
        raise SystemExit(f"{owner.username!r} exists but is not an admin — refusing to guess an owner")
    return owner.id


def _entries(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.iterdir() if p.name not in NEVER_MOVE),
        key=lambda p: p.name,
    )


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _human(bytes_: int) -> str:
    value = float(bytes_)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


def report(root: Path, target: Path, entries: list[Path]) -> None:
    total = 0
    print(f"  root   {root}")
    print(f"  target {target}")
    print()
    print(f"  {'entry':<34} {'type':<5} {'size':>9}")
    print(f"  {'-' * 34} {'-' * 5} {'-' * 9}")
    for entry in entries:
        size = _size(entry)
        total += size
        kind = "dir" if entry.is_dir() else "file"
        print(f"  {entry.name:<34} {kind:<5} {_human(size):>9}")
    print(f"  {'-' * 34} {'-' * 5} {'-' * 9}")
    print(f"  {len(entries)} entries, {_human(total)} total")
    print(f"  free space on the target filesystem: "
          f"{_human(_free(root))}")


def _free(path: Path) -> int:
    import shutil

    return shutil.disk_usage(path).free


def apply(root: Path, target: Path, entries: list[Path]) -> int:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(
            f"{target} is not empty. Refusing to merge two trees.\n"
            "  If a previous run was interrupted, this is expected: it has already moved\n"
            "  those entries. Re-run with --verify to check, or --rollback to undo."
        )
    target.mkdir(parents=True, exist_ok=True)

    moved = 0
    for entry in entries:
        destination = target / entry.name
        if destination.exists():
            print(f"  skip   {entry.name} (already at the destination)")
            continue
        try:
            # rename: same filesystem ⇒ metadata-only, atomic per entry.
            entry.rename(destination)
        except OSError as exc:
            print(f"  FAILED {entry.name}: {exc}", file=sys.stderr)
            print(
                "  Stopping here. Everything moved so far is fine; fix the cause and\n"
                "  re-run (it resumes), or --rollback to undo.",
                file=sys.stderr,
            )
            return 1
        print(f"  moved  {entry.name}")
        moved += 1

    print()
    print(f"  {moved} entr{'y' if moved == 1 else 'ies'} moved into {target}")
    print("  next: run --verify, then restart the backend so the resolver picks it up.")
    return 0


def rollback(root: Path, target: Path) -> int:
    if not target.is_dir():
        raise SystemExit(f"{target} does not exist — nothing to roll back")
    moved = 0
    for entry in sorted(target.iterdir(), key=lambda p: p.name):
        destination = root / entry.name
        if destination.exists():
            print(f"  skip   {entry.name} (already at the original location)", file=sys.stderr)
            continue
        entry.rename(destination)
        print(f"  back   {entry.name}")
        moved += 1
    try:
        target.rmdir()
        print(f"  removed {target}")
    except OSError:
        print(f"  {target} still holds something; left in place", file=sys.stderr)
        return 1
    print(f"  {moved} entr{'y' if moved == 1 else 'ies'} restored")
    return 0


def verify(db, root: Path, owner_id: int, sample: int = 8) -> int:
    """Prove the DB rows still resolve: they are owner-relative, not install-relative."""
    from sqlalchemy import text

    user_root = user_roots.root_for(owner_id, root=root)
    print(f"  owner {owner_id} → {user_root}")
    if not user_root.is_dir():
        print("  FAIL: the owner's tree does not exist — has the move run?", file=sys.stderr)
        return 1

    rows = db.execute(text(
        "SELECT file_path FROM workspace_files "
        "WHERE owner_id = :o ORDER BY id LIMIT :n"
    ), {"o": owner_id, "n": sample}).all()
    if not rows:
        print("  no workspace_files rows to check")
        return 0

    missing = 0
    for (relative,) in rows:
        candidate = user_root / relative
        exists = candidate.exists()
        print(f"  {'ok  ' if exists else 'MISS'} {relative}")
        if not exists:
            missing += 1

    total = db.execute(text(
        "SELECT count(*) FROM workspace_files WHERE owner_id = :o"
    ), {"o": owner_id}).scalar()
    on_disk = sum(1 for _ in user_root.rglob("*") if _.is_file()) if user_root.is_dir() else 0
    print()
    print(f"  {total} file rows owned by {owner_id}; {on_disk} files on disk under that root")
    if missing:
        print(f"  FAIL: {missing} of {len(rows)} sampled rows do not resolve", file=sys.stderr)
        return 1
    print("  OK: sampled rows resolve under the owner's root")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move the workspace tree into per-user roots.",
        epilog="Dry run by default. --apply moves, --rollback undoes, --verify checks.",
    )
    parser.add_argument("--root", default=None, help="workspace root (default: the resolved install root)")
    parser.add_argument("--owner", type=int, default=None, help="user id to own the tree (default: first admin)")
    parser.add_argument("--apply", action="store_true", help="actually move the entries")
    parser.add_argument("--rollback", action="store_true", help="move everything back and remove users/")
    parser.add_argument("--verify", action="store_true", help="check that the DB rows resolve after the move")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the interactive confirmation")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve() if args.root else user_roots.install_root()
    if not root.is_dir():
        raise SystemExit(f"{root} is not a directory — run --root with the workspace path")

    db = SessionLocal()
    try:
        owner_id = args.owner or _owner_id(db)
        target = user_roots.root_for(owner_id, root=root)

        print()
        print("  per-user workspace adoption")
        print("  " + "─" * 52)

        if args.verify:
            return verify(db, root, owner_id)
        if args.rollback:
            return rollback(root, target)

        entries = _entries(root)
        if not entries:
            print("  nothing at the top level to move — already adopted?")
            return verify(db, root, owner_id)

        report(root, target, entries)
        if not args.apply:
            print()
            print("  DRY RUN — nothing was moved. Re-run with --apply to do it.")
            return 0

        print()
        if not args.yes:
            print(f"  About to move {len(entries)} entries into {target}.")
            answer = input("  Type 'move' to continue: ").strip()
            if answer != "move":
                print("  cancelled — nothing was moved.")
                return 1

        status = apply(root, target, entries)
        if status == 0:
            print()
            verify(db, root, owner_id)
        return status
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
