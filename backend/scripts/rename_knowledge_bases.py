"""Give every knowledge base the name it goes by, instead of the key it was created under.

    cd backend
    .venv/bin/python scripts/rename_knowledge_bases.py              # dry run, changes nothing
    .venv/bin/python scripts/rename_knowledge_bases.py --apply      # do it, journaling as it goes
    .venv/bin/python scripts/rename_knowledge_bases.py --undo <journal>

Why this is a two-file operation and not a migration
----------------------------------------------------
A knowledge base is a folder with a catalog beside it, under the folder's own name. So renaming
one is renaming the folder and renaming the catalog — there is no third place the name is
recorded. Before this, the folder was ``kb_<key>``, the catalog was ``kb_<key>.json``, every
record repeated ``"kb": "<key>"``, and every ``storage_path`` spelled the folder out again; that
is six places for one name, and they are all rewritten here.

The knowledge base's old key is deliberately KEPT, inside its own ``kb.json``. Discovery uses it
as the knowledge base's identity, which is what stops a renamed folder from reappearing as a
second entry beside the copy it came from (``langconfig-test`` carries ``"key": "1"`` and so
shadows ``data/documents/project_1``, exactly as ``kb_1`` did).

Order matters, and the order is: fix the code, then run this. The endpoints name a knowledge base
by folder name, so they follow the folder wherever it goes. Run this first and every knowledge
base disappears from the panel at once, because nothing would be looking for its new name yet.

Reversibility
-------------
Everything is journalled before it is done, into ``.kvmeta/.rename-journal-<utc>.json`` — a
hidden file inside ``.kvmeta``, which discovery ignores. ``--undo`` replays it backwards: folders
and catalogs move back, ``storage_path`` and ``kb`` are rewritten back, and manifests are restored
to exactly what they were, including removing the ones this script created for folders that had
no catalog to begin with. A run that dies half way can be undone from the journal it left.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)                     # the knowledge root is resolved relative to the CWD

from services.kb_discovery import (   # noqa: E402
    MANIFEST_NAME, kb_root, kv_dir, legacy_root, read_manifest, write_manifest,
)

JOURNAL_VERSION = 1
JOURNAL_PREFIX = ".rename-journal-"

# The 8-hex collision prefix `FileStorage.save_file` puts on every filename it writes.
_HASH_PREFIX_RE = re.compile(r"^[0-9a-f]{8}_")

# Hierarchy folder positions, mirroring `_parse_hierarchy_from_path` in rag/uploads.py. A file
# dropped straight into the knowledge base has no hierarchy, which is normal and not an error.
_HIERARCHY = ("industry", "player", "sub_category", "sub_department")


def slugify(name: str) -> str:
    """A display name as a folder name: 'project 15' -> 'project-15'.

    Spaces have to go — they are legal in a path and miserable everywhere else — and a leading dot
    has to go too, because discovery skips dotted folders and the knowledge base would vanish.
    """
    s = name.strip().lower()
    s = re.sub(r"[^\w\s.-]", "", s)          # drop anything exotic
    s = re.sub(r"[\s_]+", "-", s)            # spaces and underscores become hyphens
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s


def target_name(folder: Path, key: str) -> str:
    """What this knowledge base should be called.

    Its own `kb.json` name if it has one — that is the name a person gave it. Failing that, the
    name of the folder it was copied from in the legacy root, so a knowledge base that never got a
    manifest is still named after what it actually is rather than after its old file path. Note
    the legacy folder is only ever *read*: nothing in `data/documents` is renamed or moved.
    """
    manifest_name = (read_manifest(folder) or {}).get("name")
    if manifest_name:
        return slugify(str(manifest_name))

    legacy = legacy_root() / f"project_{key}"
    if legacy.is_dir():
        return slugify(f"project-{key}")
    return slugify(f"knowledge-{key}")


def synthesize_records(folder: Path, name: str) -> dict:
    """Build a catalog for a folder of documents that never had one.

    Two knowledge bases here hold files and no catalog at all: visible in the disk tree, invisible
    to every document list, which is the worst of both. The records are rebuilt from the files
    themselves — size, type and timestamp come from the file, and the hierarchy from the
    directories it sits in.

    The id is a fresh one, not the 8-hex prefix on the filename: that prefix is a collision
    counter, shorter than every other document id in this codebase, and reusing it would put ids
    of two different shapes in one catalog.
    """
    records: dict[str, dict] = {}
    for path in sorted(folder.rglob("*")):
        # `kb.json` is the knowledge base's own name, not a document in it, and would otherwise
        # be catalogued as one — a knowledge base that lists its own manifest as a file.
        if not path.is_file() or path.name.startswith(".") or path.name == MANIFEST_NAME:
            continue
        rel = path.relative_to(folder)
        parts = list(rel.parts[:-1])
        hierarchy = {k: (parts[i] if len(parts) > i else None)
                     for i, k in enumerate(_HIERARCHY)}
        original = _HASH_PREFIX_RE.sub("", path.name)
        try:
            stat = path.stat()
        except OSError:
            continue
        doc_id = uuid.uuid4().hex[:16]
        records[doc_id] = {
            "id": doc_id,
            "filename": path.name,
            "original_filename": original,
            "size": stat.st_size,
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "storage_path": str(path),
            "created_at": stat.st_mtime,
            "kb": name,
            "linked": False,
            **hierarchy,
        }
    return records


def _prefix_pairs(old_folder: Path, new_folder: Path) -> list[tuple[str, str]]:
    """The (old, new) path prefixes to try, in literal and fully-resolved form.

    `storage_path` is written ABSOLUTE by `FileStorage.save_file`, but the knowledge root arrives
    here however it is configured — and the default is the relative ``./data/knowledge``. Matching
    an absolute record path against a relative prefix matches nothing, which is not a visible
    failure: the folders get renamed, the records keep the old path, and every document in the
    knowledge base becomes unopenable while the folder itself looks perfectly fine.

    Both forms are tried, because on macOS a root under /tmp resolves through a symlink to
    /private/tmp and the two spellings of the same directory would otherwise disagree.
    """
    pairs = [(str(old_folder) + os.sep, str(new_folder) + os.sep)]
    try:
        resolved = (str(old_folder.resolve()) + os.sep, str(new_folder.resolve()) + os.sep)
    except OSError:
        return pairs
    if resolved[0] != pairs[0][0]:
        pairs.append(resolved)
    return pairs


def rewrite_records(raw: dict, old_folder: Path, new_folder: Path, new_name: str) -> tuple[dict, list]:
    """Point every record at the folder's new name and new path.

    `storage_path` is absolute, so it is not enough to rename the directory: every record that
    mentions it has to be moved too, or every document in the knowledge base becomes unopenable
    while the folder itself is perfectly fine. Returns the rewritten catalog and the list of
    paths that matched no prefix, so `--undo` is exact rather than approximate.
    """
    pairs = _prefix_pairs(old_folder, new_folder)
    unmatched: list[str] = []
    out = {}
    for doc_id, record in raw.items():
        if not isinstance(record, dict):
            out[doc_id] = record
            continue
        record = dict(record)
        record["kb"] = new_name
        path = record.get("storage_path")
        if isinstance(path, str):
            for old_prefix, new_prefix in pairs:
                if path.startswith(old_prefix):
                    record["storage_path"] = new_prefix + path[len(old_prefix):]
                    break
            else:
                # Linked documents point outside the knowledge base on purpose, and must not be
                # touched. Anything else that fails to match is recorded rather than forced.
                if not record.get("linked"):
                    unmatched.append(path)
        out[doc_id] = record
    return out, unmatched


def verify_paths(raw: dict, folder: Path) -> list[str]:
    """Records whose file is not where they say it is.

    The check that turns the silent failure above into a loud one: after a rewrite, every
    non-linked record must point at a file that exists. Nothing about a renamed folder looks
    wrong from the outside — it is the catalog that has quietly stopped working.
    """
    broken = []
    for record in raw.values():
        if not isinstance(record, dict) or record.get("linked"):
            continue
        path = record.get("storage_path")
        if isinstance(path, str) and not Path(path).exists():
            broken.append(path)
    return broken


def strip_project_ids(raw: dict) -> dict:
    """Remove the legacy `project_id` a record may still carry.

    Nine records in this install still have one, from when a knowledge base was scoped to a
    project. Pydantic ignores the field on load, so it is invisible and harmless — but it is also
    a name nothing reads, in a feature that no longer has the concept, and it would be dropped
    anyway the next time that catalog happened to be written. Removing it here makes the files
    say what the code believes.

    Returns ``{doc_id: original_record}``, but only for the records that actually changed, so
    `--undo` can put them back exactly rather than reconstructing them — the key's position in
    the record is part of what is being restored.
    """
    removed = {}
    for doc_id, record in raw.items():
        if isinstance(record, dict) and "project_id" in record:
            removed[doc_id] = dict(record)
            trimmed = dict(record)
            trimmed.pop("project_id")
            raw[doc_id] = trimmed
    return removed


def plan(root: Path) -> list[dict]:
    """What the run would do, decided entirely from what is on disk right now."""
    catalogs = kv_dir(root)
    entries = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        catalog = catalogs / f"{folder.name}.json"
        manifest = read_manifest(folder) or {}

        # The key is what the knowledge base was created under. It is in its manifest when the
        # folder predates the rename, and in the folder name when it does not.
        key = str(manifest.get("key") or "")
        if not key:
            match = re.fullmatch(r"kb_([A-Za-z0-9._-]+)", folder.name)
            key = match.group(1) if match else folder.name

        records, legacy = 0, 0
        if catalog.exists():
            existing = json.loads(catalog.read_text())
            records = len(existing)
            legacy = sum(1 for v in existing.values()
                         if isinstance(v, dict) and "project_id" in v)

        name = target_name(folder, key)
        if not name:
            raise SystemExit(f"cannot derive a name for {folder}")

        entries.append({
            "from_folder": folder.name,
            "to_folder": name,
            "key": key,
            "catalog_exists": catalog.exists(),
            "records": records,
            "legacy_project_ids": legacy,
            "has_manifest": bool(manifest),
            "unchanged": folder.name == name and catalog.exists(),
        })

    names = [e["to_folder"] for e in entries]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise SystemExit(f"two knowledge bases would be called the same thing: {sorted(duplicates)}")
    for entry in entries:
        if entry["to_folder"] != entry["from_folder"] and (root / entry["to_folder"]).exists():
            raise SystemExit(f"{entry['to_folder']} already exists under {root}")
    return entries


def show(entries: list[dict], root: Path, apply: bool) -> None:
    print(f"knowledge root: {root.resolve()}")
    print(f"{'':2}{'from':<16}{'to':<20}{'key':<8}{'records':>9}{'legacy':>8}  catalog")
    for e in entries:
        flag = "  " if not e["unchanged"] else "= "
        cat = "present" if e["catalog_exists"] else "SYNTHESIZING from files"
        print(f"{flag}{e['from_folder']:<16}{e['to_folder']:<20}{e['key']:<8}"
              f"{e['records']:>9}{e['legacy_project_ids']:>8}  {cat}")
    stripped = sum(e["legacy_project_ids"] for e in entries)
    print(f"\n{len(entries)} knowledge base(s); "
          f"{sum(1 for e in entries if not e['catalog_exists'])} without a catalog, "
          f"{sum(1 for e in entries if not e['unchanged'])} to rename")
    if stripped:
        print(f"{stripped} record(s) still carry a legacy project_id; it will be removed "
              f"(and restored by --undo)")
    print("APPLYING" if apply else "DRY RUN — nothing was changed. Pass --apply to do it.")


def apply_run(entries: list[dict], root: Path) -> Path:
    catalogs = kv_dir(root)
    journal_path = catalogs / f"{JOURNAL_PREFIX}{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    journal = {
        "version": JOURNAL_VERSION,
        "started_at": time.time(),
        "root": str(root.resolve()),
        # The same dicts the loop below mutates, so each `_flush` records how far it got.
        # Leaving this empty made `--undo` a silent no-op: it replayed nothing and reported
        # success, which is the worst possible failure mode for the way back.
        "entries": entries,
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    _flush(journal_path, journal)

    for entry in entries:
        entry.setdefault("done_moves", [])
        if entry["unchanged"] and entry["catalog_exists"]:
            entry["skipped"] = True
            _flush(journal_path, journal)
            print(f"  = {entry['to_folder']}  already named this way")
            continue

        old_folder = root / entry["from_folder"]
        new_folder = root / entry["to_folder"]
        old_catalog = catalogs / f"{entry['from_folder']}.json"
        new_catalog = catalogs / f"{entry['to_folder']}.json"

        entry["old_folder"], entry["new_folder"] = str(old_folder), str(new_folder)
        entry["old_catalog"], entry["new_catalog"] = str(old_catalog), str(new_catalog)
        entry["manifest_before"] = read_manifest(old_folder) or {}
        # The manifest's exact text, not a re-serialisation of it: restoring from the parsed dict
        # would reformat a file this run did not otherwise change, and "reversible" should mean
        # the file comes back as it was, not as an equivalent.
        raw_manifest = (old_folder / MANIFEST_NAME)
        entry["manifest_before_text"] = (raw_manifest.read_text(encoding="utf-8")
                                         if raw_manifest.exists() else None)
        entry["synthesized"] = not old_catalog.exists()
        _flush(journal_path, journal)

        # 1. The folder. Recorded before it happens, so a crash here is still undoable.
        if old_folder != new_folder:
            old_folder.rename(new_folder)
            entry["done_moves"].append("folder")
            _flush(journal_path, journal)

        # 2. The catalog, rewritten and re-named in one write.
        if entry["synthesized"]:
            # Built from files that are already in their final place, so the paths it computes
            # are the finished ones and there is nothing left to rewrite.
            raw = synthesize_records(new_folder, entry["to_folder"])
            unmatched = []
        else:
            raw = json.loads(old_catalog.read_text(encoding="utf-8"))
            # Strip BEFORE the rewrite. The journalled copy has to be the record exactly as it
            # was found — old paths and old `kb` included — or `--undo` would restore a record
            # that already says the new name, which is how this went wrong the first time.
            entry["records_with_project_id"] = strip_project_ids(raw)
            raw, unmatched = rewrite_records(raw, old_folder, new_folder, entry["to_folder"])
        entry["unmatched"] = unmatched
        new_catalog.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        # Fingerprint what this run wrote. Undoing is only safe against the state a journal
        # actually produced — two runs can name the same folders, so the paths alone cannot tell
        # one journal from another, and replaying the wrong one moves a knowledge base this run
        # never touched.
        entry["catalog_sha256"] = _sha256(new_catalog)
        if old_catalog.exists() and old_catalog != new_catalog:
            old_catalog.unlink()
        entry["done_moves"].append("catalog")
        _flush(journal_path, journal)

        # 3. The knowledge base's own name. The old key is kept as its identity, which is what
        #    keeps the folder this was migrated from shadowed instead of listed beside it.
        write_manifest(new_folder, entry["key"], entry["to_folder"])
        entry["done_moves"].append("manifest")
        entry["done"] = True
        _flush(journal_path, journal)

        note = " (catalog synthesized from its files)" if entry["synthesized"] else ""
        print(f"  -> {entry['from_folder']} => {entry['to_folder']}"
              f"  [{len(raw)} record(s), {len(unmatched)} path(s) untouched]{note}")
        if unmatched:
            for path in unmatched[:5]:
                print(f"       untouched: {path}")

        # Every non-linked record must now point at a file that exists. Checked per knowledge
        # base, before moving on, so a rewrite that matched nothing is caught here rather than
        # discovered later as an empty-looking knowledge base.
        broken = verify_paths(raw, new_folder)
        entry["broken_paths"] = broken[:50]
        entry["broken_count"] = len(broken)
        _flush(journal_path, journal)
        if broken:
            print(f"\n  !! {len(broken)} record(s) now point at a file that does not exist, e.g.")
            for path in broken[:3]:
                print(f"       {path}")
            print(f"\n  The folders were renamed but at least one catalog still refers to the old"
                  f"\n  paths. Reverse this run before doing anything else:"
                  f"\n    .venv/bin/python scripts/rename_knowledge_bases.py --undo {journal_path}")
            raise SystemExit(1)

    journal["finished_at"] = time.time()
    _flush(journal_path, journal)
    return journal_path


def undo_run(journal_path: Path) -> None:
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("version") != JOURNAL_VERSION:
        raise SystemExit(f"journal version {journal.get('version')} is not {JOURNAL_VERSION}")
    root = Path(journal["root"])
    entries = journal.get("entries") or []
    if not entries:
        raise SystemExit(f"{journal_path} records no knowledge bases — nothing to undo. "
                         "Refusing to report success for a journal that would reverse nothing.")
    print(f"undoing {journal_path.name} against {root} ({len(entries)} knowledge base(s))")

    reverted = 0
    already = 0
    for entry in reversed(entries):
        done = entry.get("done_moves", [])
        if entry.get("skipped") or not done:
            continue
        if entry.get("undone"):
            already += 1
            continue
        new_folder = Path(entry["new_folder"])
        old_folder = Path(entry["old_folder"])
        # A journal describes one particular transition. Applying it to a knowledge base that is
        # already back where it started would move it somewhere it never was, so this is checked
        # rather than assumed — there can be more than one journal in `.kvmeta`, and undoing the
        # wrong one is worse than refusing.
        if "folder" in done and not new_folder.exists() and old_folder.exists():
            print(f"  -- {entry['to_folder']}: already back at {entry['from_folder']}, skipping")
            already += 1
            continue
        reverted += 1
        new_catalog = Path(entry["new_catalog"])
        old_catalog = Path(entry["old_catalog"])

        # Refuse to replay a journal against a knowledge base it did not produce. The paths are
        # not enough to tell two runs apart — both name the same target folder — so the catalog
        # this run wrote is fingerprinted and checked. Undoing the wrong journal silently moves
        # knowledge bases that are none of its business.
        expected = entry.get("catalog_sha256")
        actual = _sha256(new_catalog)
        if expected and actual is not None and actual != expected:
            raise SystemExit(
                f"\n{new_catalog} is not the catalog this journal wrote.\n"
                f"  journal expects sha256 {expected}\n"
                f"  found                  {actual}\n"
                "This journal belongs to a different, earlier run. Replaying it would move "
                "knowledge bases it never touched, so it is being refused.\n"
                "Use the journal from the most recent --apply instead."
            )

        # Records first, while the catalog is still where this run left it.
        if "catalog" in done:
            if entry["synthesized"]:
                new_catalog.unlink(missing_ok=True)          # there was no catalog to restore
            else:
                raw = json.loads(new_catalog.read_text(encoding="utf-8"))
                raw, _ = rewrite_records(raw, new_folder, old_folder, entry["from_folder"])
                for doc_id, record in raw.items():
                    if isinstance(record, dict):
                        # `kb` goes back to the key, exactly as the old records spelled it.
                        record["kb"] = entry["key"]
                # Records whose legacy project_id this run removed go back exactly as they were
                # found, which also restores the field's original position in the record.
                for doc_id, original in (entry.get("records_with_project_id") or {}).items():
                    raw[doc_id] = original
                old_catalog.parent.mkdir(parents=True, exist_ok=True)
                old_catalog.write_text(json.dumps(raw, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
                if new_catalog != old_catalog:
                    new_catalog.unlink(missing_ok=True)

        if "manifest" in done:
            # Put back the bytes this run found, or remove the manifest entirely when the folder
            # had none — a knowledge base that never got a name must not gain one by being undone.
            target = new_folder / MANIFEST_NAME
            if "manifest_before_text" in entry:
                before_text = entry["manifest_before_text"]
                if before_text is not None:
                    target.write_text(before_text, encoding="utf-8")
                else:
                    target.unlink(missing_ok=True)
            else:
                # A journal written before the text was recorded. Falling back to the parsed
                # manifest re-serialises it — equivalent, not identical — but the alternative is
                # treating "no text recorded" as "there was no manifest" and deleting a name this
                # run did not create.
                before = entry.get("manifest_before") or {}
                if before:
                    target.write_text(json.dumps(before, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
                else:
                    target.unlink(missing_ok=True)

        if "folder" in done:
            if new_folder.exists() and not old_folder.exists():
                new_folder.rename(old_folder)

        entry["undone"] = True
        _flush(journal_path, journal)
        print(f"  <- {entry['to_folder']} => {entry['from_folder']}")

    if already and not reverted:
        print(f"nothing to undo: all {already} entr(y/ies) are already in their original state")
    print(f"undo complete ({reverted} reversed, {already} already back)")


def _sha256(path: Path) -> Optional[str]:
    """Fingerprint of a catalog, or None when it is not there. Used to tell journals apart."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _flush(path: Path, journal: dict) -> None:
    """Write the journal after every step, so a run that dies is still reversible."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually make the changes (without this, nothing is touched)")
    ap.add_argument("--undo", metavar="JOURNAL", help="reverse a previous run from its journal")
    ap.add_argument("--root", default=None, help="knowledge root (defaults to KB_ROOT)")
    args = ap.parse_args()

    if args.undo:
        undo_run(Path(args.undo))
        return 0

    root = Path(args.root) if args.root else kb_root()
    if not root.is_dir():
        raise SystemExit(f"no knowledge root at {root}")
    entries = plan(root)
    show(entries, root, args.apply)
    if not args.apply:
        return 0
    journal = apply_run(entries, root)
    print(f"\njournal: {journal}")
    print(f"to reverse:  .venv/bin/python scripts/rename_knowledge_bases.py --undo {journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
