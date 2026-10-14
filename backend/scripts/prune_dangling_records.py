"""Drop catalog records whose file is no longer on disk.

    cd backend
    .venv/bin/python scripts/prune_dangling_records.py                 # report only
    .venv/bin/python scripts/prune_dangling_records.py --apply
    .venv/bin/python scripts/prune_dangling_records.py --knowledge langconfig-test --apply

A catalog is the index and the files are the truth, so a record whose file has gone is a document
that does not exist — but it still appears in the Knowledge panel, and opening it fails. Deleting
a folder by hand is the usual cause: `rm -rf` on a subfolder leaves every record in it pointing at
nothing, and nothing else in the codebase notices.

Records added by LINK are exempt. A linked record names a file that lives somewhere else on
purpose, and a link whose target is unreachable is a *reported* condition (`doctor.sh` says
DANGLING, `relocate_knowledge_paths.py` repairs a moved root) rather than a record to delete —
removing it would discard the knowledge that the document was ever added.

Dry run by default, and `--apply` writes a journal beside the catalogs recording exactly which
records were dropped, so a prune done by mistake can be reversed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from services.kb_discovery import kb_root, kv_dir, read_manifest  # noqa: E402

JOURNAL_PREFIX = ".prune-journal-"


def find(root: Path, only: str | None) -> list[dict]:
    """Every catalog, with the records in it whose file has gone."""
    out = []
    for catalog in sorted(kv_dir(root).glob("[!.]*.json")):
        name = catalog.stem
        if only and name != only:
            continue
        try:
            records = json.loads(catalog.read_text(encoding="utf-8"))
        except Exception as exc:                          # noqa: BLE001
            print(f"  ! {catalog.name}: unreadable ({exc})")
            continue
        dangling = {doc_id: record for doc_id, record in records.items()
                    if isinstance(record, dict)
                    and not record.get("linked")
                    and not Path(str(record.get("storage_path") or "")).exists()}
        if dangling:
            out.append({"catalog": catalog, "knowledge": name, "records": records,
                        "dangling": dangling})
    return out


def show(found: list[dict], root: Path, apply: bool) -> None:
    print(f"knowledge root: {root.resolve()}")
    total = sum(len(f["dangling"]) for f in found)
    for f in found:
        orphaned_folder = not (root / f["knowledge"]).is_dir()
        note = "  (its folder is gone too)" if orphaned_folder else ""
        print(f"\n  {f['knowledge']}: {len(f['dangling'])} of {len(f['records'])} "
              f"record(s) point at a missing file{note}")
        for record in list(f["dangling"].values())[:6]:
            print(f"    - {record.get('original_filename')}")
        if len(f["dangling"]) > 6:
            print(f"    … and {len(f['dangling']) - 6} more")
    print(f"\n{total} dangling record(s) in {len(found)} catalog(s)")
    print("APPLYING" if apply else "DRY RUN — nothing was changed. Pass --apply to do it.")


def apply_run(found: list[dict], root: Path) -> Path:
    journal_path = kv_dir(root) / f"{JOURNAL_PREFIX}{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    journal = {"started_at": time.time(), "root": str(root.resolve()), "dropped": {}}
    for f in found:
        keep = {k: v for k, v in f["records"].items() if k not in f["dangling"]}
        f["catalog"].write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
        # Journalled with the full record, so `--restore` can put it back exactly as it was.
        journal["dropped"][f["knowledge"]] = f["dangling"]
        journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {f['knowledge']}: dropped {len(f['dangling'])}, kept {len(keep)}")
    return journal_path


def restore(journal_path: Path) -> None:
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    root = Path(journal["root"])
    for knowledge, dropped in journal["dropped"].items():
        catalog = kv_dir(root) / f"{knowledge}.json"
        records = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else {}
        records.update(dropped)
        catalog.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {knowledge}: restored {len(dropped)} record(s)")
    print("restore complete — the files themselves are not restored, only the records")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--knowledge", help="only this knowledge base")
    ap.add_argument("--restore", metavar="JOURNAL", help="put a pruned journal's records back")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    root = (Path(args.root) if args.root else kb_root()).resolve()

    if args.restore:
        restore(Path(args.restore))
        return 0

    found = find(root, args.knowledge)
    if not found:
        print(f"no dangling records under {root.resolve()}")
        return 0
    show(found, root, args.apply)
    if not args.apply:
        return 0
    journal = apply_run(found, root)
    print(f"\njournal: {journal}")
    print(f"to reverse:  .venv/bin/python scripts/prune_dangling_records.py "
          f"--restore {journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
