"""Promote a folder inside a knowledge base to a knowledge base of its own.

    cd backend
    .venv/bin/python scripts/promote_subfolder_to_kb.py --knowledge knowledge-4242 \\
        --folder business_model                  # dry run
    .venv/bin/python scripts/promote_subfolder_to_kb.py --knowledge knowledge-4242 \\
        --folder business_model --apply

Why this exists
---------------
Folders used to be uploaded *into* a knowledge base, with the folder's own name becoming a
subfolder inside it (an `industry` level). So a folder called `business_model` landed at
`data/knowledge/<some base>/business_model/` instead of being a knowledge base called
`business_model`. Uploads now name the knowledge base after the folder, but folders that already
went in the old way are nested where they should not be.

This moves the contents up: `<base>/<folder>/**` becomes `<new base>/**`, the records move with
them, and the directory they were in is removed once it is empty. The old base keeps everything
else and its own records for the moved files are dropped.

The hierarchy fields shift up by one to match, because the folder that is being promoted was
itself the outermost level: what was `player` becomes `industry`, and so on. Getting this wrong
would leave documents claiming a path they are no longer at.

Reversible: journalled into `.kvmeta/.promote-journal-<utc>.json`, and `--undo` replays it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)                     # the knowledge root is resolved relative to the CWD

from services.kb_discovery import MANIFEST_NAME, kb_root, kv_dir, write_manifest  # noqa: E402

JOURNAL_VERSION = 1
JOURNAL_PREFIX = ".promote-journal-"
HIERARCHY = ("industry", "player", "sub_category", "sub_department")


def shift_hierarchy(record: dict) -> None:
    """Drop the outermost hierarchy level, in place.

    The promoted folder WAS the outermost level (it is why the documents were a subfolder at all),
    so everything below it moves up one and the last slot empties.
    """
    values = [record.get(k) for k in HIERARCHY]
    shifted = values[1:] + [None]
    for key, value in zip(HIERARCHY, shifted):
        record[key] = value


def plan(root: Path, knowledge: str, folder: str) -> dict:
    base_dir = root / knowledge
    source = base_dir / folder
    target = root / folder

    if not base_dir.is_dir():
        raise SystemExit(f"no knowledge base at {base_dir}")
    if not source.is_dir():
        raise SystemExit(f"no folder {folder!r} inside {knowledge} ({source})")
    if target.exists():
        raise SystemExit(f"{target} already exists — refusing to merge two knowledge bases")

    catalog = kv_dir(root) / f"{knowledge}.json"
    if not catalog.exists():
        raise SystemExit(f"no catalog for {knowledge} ({catalog})")
    records = json.loads(catalog.read_text(encoding="utf-8"))

    prefix = str(source) + os.sep
    moving = {k: v for k, v in records.items()
              if isinstance(v, dict) and str(v.get("storage_path", "")).startswith(prefix)}
    if not moving:
        raise SystemExit(f"no records in {knowledge} point into {folder!r}")

    files = [p for p in sorted(source.rglob("*")) if p.is_file()]
    return {"base_dir": base_dir, "source": source, "target": target,
            "records": records, "moving": moving, "files": files,
            "catalog": catalog, "name": folder}


def show(p: dict, root: Path, apply: bool) -> None:
    print(f"knowledge root : {root.resolve()}")
    print(f"promote        : {p['source'].relative_to(root)}  ->  {p['target'].relative_to(root)}")
    print(f"files          : {len(p['files'])}")
    for f in p["files"][:8]:
        print(f"    {f.relative_to(p['source'])}")
    if len(p["files"]) > 8:
        print(f"    … and {len(p['files']) - 8} more")
    print(f"records        : {len(p['moving'])} move to {p['name']}, "
          f"{len(p['records']) - len(p['moving'])} stay in {p['source'].parent.name}")
    print("APPLYING" if apply else "DRY RUN — nothing was changed. Pass --apply to do it.")


def apply_run(root: Path, p: dict) -> Path:
    journals = kv_dir(root)
    journal_path = journals / f"{JOURNAL_PREFIX}{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    journal = {
        "version": JOURNAL_VERSION,
        "started_at": time.time(),
        "root": str(root.resolve()),
        "knowledge": p["source"].parent.name,
        "folder": p["name"],
        "published": False,
        "records_moved": sorted(p["moving"]),
        "files_moved": [str(f.relative_to(p["source"])) for f in p["files"]],
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")

    # 1. The files. `shutil.move` into a fresh directory preserves the structure below the folder.
    p["target"].mkdir(parents=True, exist_ok=True)
    for entry in sorted(p["source"].iterdir()):
        shutil.move(str(entry), str(p["target"] / entry.name))
    journal["moved"] = True
    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2. The new catalog: the moved records, rewritten to their new absolute paths.
    new_records = {}
    old_prefix, new_prefix = str(p["source"]), str(p["target"])
    for doc_id, record in p["moving"].items():
        record = dict(record)
        record["storage_path"] = new_prefix + record["storage_path"][len(old_prefix):]
        record["kb"] = p["name"]
        shift_hierarchy(record)
        new_records[doc_id] = record
    new_catalog = kv_dir(root) / f"{p['name']}.json"
    new_catalog.write_text(json.dumps(new_records, indent=2, ensure_ascii=False), encoding="utf-8")
    journal["published"] = True
    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. The old catalog loses exactly those records, and nothing else.
    remaining = {k: v for k, v in p["records"].items() if k not in p["moving"]}
    p["catalog"].write_text(json.dumps(remaining, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. The knowledge base's own name, and the now-empty directory it came out of.
    write_manifest(p["target"], p["name"], p["name"])
    if not any(p["source"].iterdir()):
        p["source"].rmdir()

    broken = [r["storage_path"] for r in new_records.values() if not Path(r["storage_path"]).exists()]
    if broken:
        for path in broken[:3]:
            print(f"  !! {path}")
        raise SystemExit(f"{len(broken)} moved record(s) point at a missing file — "
                         f"reverse with --undo {journal_path}")
    return journal_path


def undo_run(journal_path: Path) -> None:
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    root = Path(journal["root"])
    knowledge, folder = journal["knowledge"], journal["folder"]
    target, source = root / folder, root / knowledge / folder
    new_catalog = kv_dir(root) / f"{folder}.json"
    old_catalog = kv_dir(root) / f"{knowledge}.json"

    print(f"undoing {journal_path.name}: {folder} -> {knowledge}/{folder}")
    if (new_catalog.exists() and old_catalog.exists()):
        moved = set(journal["records_moved"])
        back = json.loads(old_catalog.read_text(encoding="utf-8"))
        for doc_id, record in json.loads(new_catalog.read_text(encoding="utf-8")).items():
            record = dict(record)
            record["storage_path"] = str(source) + record["storage_path"][len(str(target)):]
            record["kb"] = knowledge
            # Undo the shift: the highest level is restored from the record's own kb.
            values = [None] + [record.get(k) for k in HIERARCHY[:3]]
            for key, value in zip(HIERARCHY, values):
                record[key] = value
            back[doc_id] = record
        old_catalog.write_text(json.dumps(back, indent=2, ensure_ascii=False), encoding="utf-8")
        new_catalog.unlink()
    if journal.get("moved") and target.is_dir() and not source.exists():
        source.mkdir(parents=True)
        for entry in sorted(target.iterdir()):
            shutil.move(str(entry), str(source / entry.name))
        (target / MANIFEST_NAME).unlink(missing_ok=True)
        if not any(target.iterdir()):
            target.rmdir()
    print("undo complete")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--knowledge", required=False, help="the knowledge base holding the folder")
    ap.add_argument("--folder", required=False, help="the folder to promote")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", metavar="JOURNAL")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    if args.undo:
        undo_run(Path(args.undo))
        return 0
    if not args.knowledge or not args.folder:
        raise SystemExit("--knowledge and --folder are both required")
    # Resolved, because records store ABSOLUTE storage_paths while `kb_root()` is configured
    # relative. Building the folder paths relatively means nothing ever matches them, and the
    # failure is silent: the promotion finds "no records" in a folder that is full of them.
    root = (Path(args.root) if args.root else kb_root()).resolve()
    p = plan(root, args.knowledge, args.folder)
    show(p, root, args.apply)
    if not args.apply:
        return 0
    journal = apply_run(root, p)
    print(f"\njournal: {journal}")
    print(f"to reverse:  .venv/bin/python scripts/promote_subfolder_to_kb.py --undo {journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
