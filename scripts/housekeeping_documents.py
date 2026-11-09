#!/usr/bin/env python3
"""Documents housekeeping — find (and, on request, quarantine) files nothing points at.

Measured on this checkout (2026-11-09):

    1 491 files / 643 MB on disk under backend/data/documents
    1 847 distinct paths referenced by the KV catalog (.kvmeta/*.json) or the DB
      459 files / 535 MB orbiting with no reference at all        ← the biggest single waste
      815 references pointing at a file that is gone (44 %)      ← the UI can still offer them

Two different problems, two different actions. Neither is destructive here:

  --report (default)   print both sides, change nothing
  --quarantine         MOVE the unreferenced files into data/documents/.quarantine/<ts>/
                       (a move, not a delete: `mv` back and they are where they were)
  --prune-refs         drop catalog entries whose file is gone, after backing the catalog up
                       to the same quarantine folder

Usage:

    cd backend
    .venv/bin/python ../scripts/housekeeping_documents.py                    # look
    .venv/bin/python ../scripts/housekeeping_documents.py --db               # also cross-check the DB
    .venv/bin/python ../scripts/housekeeping_documents.py --quarantine --apply
    .venv/bin/python ../scripts/housekeeping_documents.py --prune-refs --apply

Tests: backend/tests/test_housekeeping_documents.py (classification logic, on a temp tree).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time
from dataclasses import dataclass, field

#: The store lives under the BACKEND directory: `backend/data/documents` (the root `data/` folder is
#: agent-generated analysis output and holds no documents). Resolved by probing, because the same
#: script is used from the repository root and against a temp tree in the tests.
DOCUMENTS = pathlib.Path("data") / "documents"
CATALOG = DOCUMENTS / ".kvmeta"
QUARANTINE = DOCUMENTS / ".quarantine"


def docs_root(root: pathlib.Path) -> pathlib.Path:
    """The directory that CONTAINS `data/documents`: `<root>/backend` if it exists, else `<root>`."""
    for candidate in (root / "backend", root):
        if (candidate / DOCUMENTS).is_dir():
            return candidate
    return root


@dataclass
class Verdict:
    """What the scan found. Pure data — the tests build one of these directly."""
    files: set[str] = field(default_factory=set)          # paths on disk, repository-relative
    refs: set[str] = field(default_factory=set)           # paths the catalog/DB point at
    catalog_problems: list[str] = field(default_factory=list)

    @property
    def orphans(self) -> list[str]:
        """On disk, referenced by nothing — the app cannot show these."""
        return sorted(self.files - self.refs)

    @property
    def dangling(self) -> list[str]:
        """Referenced, but the file is gone — the app offers a document it cannot open."""
        return sorted(self.refs - self.files)

    @property
    def healthy(self) -> int:
        return len(self.files & self.refs)


def _rel(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def collect_files(root: pathlib.Path) -> set[str]:
    """Every regular file under the documents directory, minus the catalog and quarantine."""
    root = docs_root(root)
    out: set[str] = set()
    base = root / DOCUMENTS
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = _rel(p, root)
        parts = p.relative_to(base).parts
        if parts and parts[0] in (".kvmeta", ".quarantine"):
            continue                       # the catalog is metadata, the quarantine is where we park
        if p.name == ".gitkeep":
            continue
        out.add(rel)
    return out


def collect_catalog_refs(root: pathlib.Path) -> tuple[set[str], list[str]]:
    """`storage_path` from every per-project catalog file. Paths are absolute in the catalog."""
    root = docs_root(root)
    refs: set[str] = set()
    problems: list[str] = []
    catalog = root / CATALOG
    if not catalog.is_dir():
        return refs, problems
    for f in sorted(catalog.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:                                    # noqa: BLE001
            problems.append(f"{f.name}: not readable as JSON ({exc})")
            continue
        records = doc.values() if isinstance(doc, dict) else doc
        if isinstance(doc, dict) and "documents" in doc:            # tolerate a wrapped shape
            records = doc["documents"].values() if isinstance(doc["documents"], dict) else doc["documents"]
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            path = rec.get("storage_path") or rec.get("file_path") or rec.get("path")
            if not path:
                continue
            p = pathlib.Path(str(path))
            # the catalog stores absolute paths; re-anchor whatever prefix onto this checkout
            marker = "/data/documents/"
            s = str(p).replace("\\", "/")
            if marker in s:
                rel = s.split(marker, 1)[1]
            else:
                try:
                    rel = _rel(p, docs_root(root))
                except ValueError:
                    problems.append(f"{f.name}: path outside the repository: {path}")
                    continue
            refs.add(f"{DOCUMENTS.as_posix()}/{rel}")
    return refs, problems


def collect_db_refs(root: pathlib.Path) -> tuple[set[str], list[str]]:
    """Paths recorded in the two DB tables that hold documents. Optional: needs the app's DB."""
    refs: set[str] = set()
    problems: list[str] = []
    try:
        sys.path.insert(0, str(docs_root(root)))
        from db.database import SessionLocal                        # noqa: PLC0415
        from sqlalchemy import text                                 # noqa: PLC0415

        db = SessionLocal()
        try:
            for sql in ("select file_path from context_documents",
                        "select file_path from session_documents",
                        "select file_path from workspace_files"):
                try:
                    rows = db.execute(text(sql)).fetchall()
                except Exception:                                   # noqa: BLE001
                    continue
                for (path,) in rows:
                    if not path:
                        continue
                    s = str(path).replace("\\", "/")
                    marker = "/data/documents/"
                    if marker in s:
                        refs.add(f"{DOCUMENTS.as_posix()}/{s.split(marker, 1)[1]}")
        finally:
            db.close()
    except Exception as exc:                                        # noqa: BLE001
        problems.append(f"DB not consulted ({exc})")
    return refs, problems


def scan(root: pathlib.Path, with_db: bool = False) -> Verdict:
    files = collect_files(root)
    refs, problems = collect_catalog_refs(root)
    if with_db:
        db_refs, db_problems = collect_db_refs(root)
        refs |= db_refs
        problems += db_problems
    # a reference may name a file that exists but was never catalogued by BASENAME (older entries used
    # a different prefix); keep those as references so nothing live is quarantined by mistake.
    by_name = {pathlib.Path(f).name: f for f in files}
    for r in list(refs):
        if r in files:
            continue
        twin = by_name.get(pathlib.Path(r).name)
        if twin:
            refs.add(twin)
    return Verdict(files=files, refs=refs, catalog_problems=problems)


def _size(root: pathlib.Path, paths: list[str]) -> float:
    root = docs_root(root)
    total = 0
    for rel in paths:
        try:
            p = root / rel
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total / 1048576


def quarantine_orphans(root: pathlib.Path, orphans: list[str], stamp: str) -> dict:
    """MOVE the unreferenced files under `.quarantine/<stamp>/`, keeping their relative paths."""
    root = docs_root(root)
    dest_root = root / QUARANTINE / stamp
    moved, failed = [], []
    for rel in orphans:
        src = root / rel
        rel_to_docs = pathlib.Path(rel).relative_to(DOCUMENTS)
        dst = dest_root / rel_to_docs
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(rel)
        except Exception as exc:                                    # noqa: BLE001
            failed.append(f"{rel}: {exc}")
    if moved:
        (dest_root / "MANIFEST.txt").write_text(
            "moved from backend/data/documents (unreferenced by the KV catalog or the DB)\n"
            + "\n".join(moved) + "\n", encoding="utf-8")
    return {"dest": str(dest_root), "moved": moved, "failed": failed}


def prune_dangling_refs(root: pathlib.Path, dangling: list[str], stamp: str) -> dict:
    """Drop catalog entries whose file is gone, after copying the catalog aside."""
    root = docs_root(root)
    catalog = root / CATALOG
    if not catalog.is_dir():
        return {"changed": 0, "backup": None, "removed": []}
    backup = root / QUARANTINE / stamp / "kvmeta-backup"
    backup.mkdir(parents=True, exist_ok=True)
    missing = {pathlib.Path(d).name for d in dangling}
    changed, removed = 0, []
    for f in sorted(catalog.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                           # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        keep = {}
        for key, rec in doc.items():
            path = ""
            if isinstance(rec, dict):
                path = str(rec.get("storage_path") or rec.get("file_path") or rec.get("path") or "")
            name = pathlib.Path(path).name if path else ""
            exists = False
            if path:
                marker = "/data/documents/"
                s = path.replace("\\", "/")
                rel = s.split(marker, 1)[1] if marker in s else None
                exists = bool(rel) and (root / DOCUMENTS / rel).is_file()
            if exists or not name:
                keep[key] = rec
            else:
                removed.append(f"{f.name}: {name}")
        if len(keep) != len(doc):
            shutil.copy2(f, backup / f.name)
            f.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
            changed += 1
    _ = missing
    return {"changed": changed, "backup": str(backup), "removed": removed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Find unreferenced / dangling document records.")
    ap.add_argument("--root", default=None, help="repository root (default: the script's parent)")
    ap.add_argument("--db", action="store_true", help="also treat the DB tables as references")
    ap.add_argument("--quarantine", action="store_true", help="move unreferenced files aside")
    ap.add_argument("--prune-refs", action="store_true", help="drop catalog entries whose file is gone")
    ap.add_argument("--apply", action="store_true", help="actually do it (otherwise: report only)")
    ap.add_argument("--limit", type=int, default=12, help="how many paths to print per list")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parents[1]
    verdict = scan(root, with_db=args.db)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    print(f"root: {root}")
    print(f"files on disk          : {len(verdict.files)}")
    print(f"distinct references    : {len(verdict.refs)}")
    print(f"healthy (file + cat)   : {verdict.healthy}")
    print(f"UNREFERENCED files     : {len(verdict.orphans)}  ({_size(root, verdict.orphans):.1f} MB)")
    print(f"DANGLING references    : {len(verdict.dangling)}")
    for problem in verdict.catalog_problems[:5]:
        print(f"  ! {problem}")

    for title, items in (("unreferenced (first %d)" % args.limit, verdict.orphans),
                         ("dangling refs (first %d)" % args.limit, verdict.dangling)):
        if items:
            print(f"\n{title}:")
            for rel in items[:args.limit]:
                print(f"  {rel}")

    if not args.apply:
        print("\nreport only — nothing changed. Re-run with --quarantine and/or --prune-refs plus "
              "--apply to act.")
        return 0

    if args.quarantine and verdict.orphans:
        res = quarantine_orphans(root, verdict.orphans, stamp)
        print(f"\nquarantined {len(res['moved'])} file(s) -> {res['dest']}")
        for f in res["failed"][:5]:
            print(f"  ! {f}")
    if args.prune_refs and verdict.dangling:
        res = prune_dangling_refs(root, verdict.dangling, stamp)
        print(f"\npruned {len(res['removed'])} catalog entr(ies) across {res['changed']} file(s); "
              f"backup -> {res['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
