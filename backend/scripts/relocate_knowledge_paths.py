"""Rewrite document paths recorded against another machine's tree, so they resolve here.

    cd <tree>/backend
    .venv/bin/python scripts/relocate_knowledge_paths.py                  # report only
    .venv/bin/python scripts/relocate_knowledge_paths.py --apply

Copy `data/documents` from one machine to another — which is what moving a knowledge base between
installs amounts to — and the files arrive while every recorded path still names the machine they
came from:

    .kvmeta/project_1.json     storage_path: /Users/weiping/…/backend/data/documents/project_1/…
    context_documents.file_path: the same prefix
    session_documents.file_path: the same prefix

The panel lists documents from `.kvmeta`, so it *looks* right while opening any document fails, and
`doctor.sh` stops with DANGLING before it will adopt projects. That is this script's job.

Three things it does deliberately:

- **dry-run by default.** Rewriting recorded paths is the one operation here that changes data
  rather than adding to it, so it reports what it would touch and writes nothing until `--apply`.
- **prefix only, verified per file.** It rewrites the old root to the new one and keeps the rest of
  the path. A path that still does not exist afterwards is counted and listed, not silently
  rewritten into another dangling value.
- **a journal.** `--apply` writes `relocate-journal.json` in the documents root: every record and
  row changed, with its previous value, which is what makes `--rollback` possible.

Paths that already resolve are never touched, so this is a no-op on a machine that moved its tree
to the same path — the common case, where nothing needs doing at all.
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run from anywhere: take backend/ from this file's own location and work from there. The
# app resolves settings paths against the process CWD ("./data/documents"), so the CWD must be
# backend/ no matter where the script was invoked from.
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402

# file_path columns that hold document paths and live under the documents root
PATH_COLUMNS = [("context_documents", "file_path"), ("session_documents", "file_path")]


def documents_root() -> Path:
    try:
        from services.file_storage import file_storage
        return Path(file_storage.base_dir).resolve()
    except Exception:
        return (BACKEND / "data" / "documents").resolve()


def kv_jsons(root: Path) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(root / ".kvmeta" / "*.json")))


def dangling(paths: list[str]) -> list[str]:
    return [p for p in paths if p and not os.path.exists(p)]


# The segment that separates a tree from the documents inside it. Keying on this instead of on
# the whole tree path is what makes the tool work regardless of where either tree lives — a copy
# between machines changes both roots, and only the documents part is what we are fixing.
DOCS_MARKER = "/data/documents"


def split_docs_path(path: str) -> tuple[str, str] | None:
    """(the documents root recorded in this path, the rest of it) or None if unusable."""
    i = path.find(DOCS_MARKER)
    if i == -1:
        return None
    return path[: i + len(DOCS_MARKER)], path[i + len(DOCS_MARKER):]


def common_root(paths: list[str]) -> str | None:
    """The documents root the records were written against — the machine we came from."""
    counts: dict[str, int] = {}
    for path in paths:
        parts = split_docs_path(path)
        if parts:
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    return max(counts, key=counts.get) if counts else None


def collect(root: Path):
    """Every recorded path that does not resolve, from .kvmeta and from the database."""
    records = []                       # (file, doc_id, old_path)
    for f in kv_jsons(root):
        data = json.loads(f.read_text())
        for doc_id, rec in data.items():
            p = rec.get("storage_path") or ""
            if p and not os.path.exists(p):
                records.append((f, doc_id, p))

    rows = []                          # (table, column, id, old_path)
    with engine.connect() as conn:
        for table, column in PATH_COLUMNS:
            for row_id, value in conn.execute(
                text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} <> ''")
            ):
                if value and not os.path.exists(value):
                    rows.append((table, column, row_id, value))
    return records, rows


def rewrite(old: str, new_root: Path) -> str:
    parts = split_docs_path(old)
    return str(new_root) + parts[1] if parts else old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
    ap.add_argument("--from", dest="old_root", help="the old root to replace (inferred when omitted)")
    ap.add_argument("--to", dest="new_root", help="the new root (default: this install's documents root)")
    ap.add_argument("--rollback", action="store_true", help="undo a previous --apply using its journal")
    args = ap.parse_args()

    root = Path(args.new_root).resolve() if args.new_root else documents_root()
    journal_path = root / "relocate-journal.json"

    if args.rollback:
        if not journal_path.exists():
            print(f"  no journal at {journal_path} — nothing to roll back")
            return 1
        journal = json.loads(journal_path.read_text())
        for entry in journal["kvmeta"]:
            f = Path(entry["file"])
            data = json.loads(f.read_text())
            if entry["doc_id"] in data:
                data[entry["doc_id"]]["storage_path"] = entry["old"]
            f.write_text(json.dumps(data))
        with engine.begin() as conn:
            for entry in journal["rows"]:
                conn.execute(text(f"UPDATE {entry['table']} SET {entry['column']} = :v WHERE id = :i"),
                             {"v": entry["old"], "i": entry["id"]})
        print(f"  rolled back {len(journal['kvmeta'])} record(s) and {len(journal['rows'])} row(s)")
        journal_path.unlink()
        return 0

    print(f"  documents root : {root}")
    records, rows = collect(root)
    all_paths = [p for _, _, p in records] + [p for _, _, _, p in rows]

    if not all_paths:
        print("  every recorded path resolves — nothing to rewrite")
        return 0

    old_root = args.old_root or common_root(all_paths)
    print(f"  {len(records)} .kvmeta record(s) and {len(rows)} database row(s) point at missing files")
    print(f"  old root       : {old_root}")
    print(f"  would become   : {root}")
    if not old_root:
        print("\n  cannot infer a single old root — pass --from explicitly")
        return 1

    preview = [rewrite(p, root) for p in all_paths[:3]]
    for p in preview:
        print(f"    {p}   {'OK' if os.path.exists(p) else 'still missing'}")
    fixable = sum(1 for p in all_paths if os.path.exists(rewrite(p, root)))
    outside = [p for p in all_paths if split_docs_path(p) is None]
    print(f"\n  {fixable} of {len(all_paths)} would resolve after the rewrite")
    if outside:
        print(f"  {len(outside)} path(s) are not under any /data/documents root and stay untouched:")
        for p in outside[:3]:
            print(f"    {p}")

    if not args.apply:
        print("\n  report only. Re-run with --apply to write, then verify: bash doctor.sh")
        return 0

    journal = {"when": datetime.now(timezone.utc).isoformat(), "old_root": old_root,
               "new_root": str(root), "kvmeta": [], "rows": []}
    for f, doc_id, old in records:
        data = json.loads(f.read_text())
        data[doc_id]["storage_path"] = rewrite(old, root)
        f.write_text(json.dumps(data))
        journal["kvmeta"].append({"file": str(f), "doc_id": doc_id, "old": old})
    with engine.begin() as conn:
        for table, column, row_id, old in rows:
            conn.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),
                         {"v": rewrite(old, root), "i": row_id})
            journal["rows"].append({"table": table, "column": column, "id": row_id, "old": old})
    journal_path.write_text(json.dumps(journal, indent=2))

    _, still_broken = collect(root)
    print(f"\n  rewrote {len(journal['kvmeta'])} record(s) and {len(journal['rows'])} row(s)")
    print(f"  journal: {journal_path}   (undo with --rollback)")
    print(f"  paths still missing after the rewrite: {len(still_broken)}")
    print("\n  Next: bash doctor.sh   — DANGLING should now be 0, and it will report orphan projects.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
