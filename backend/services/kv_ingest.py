"""The ingest core: the one place a file becomes a knowledge document.

    from services.kv_ingest import ingest_directory, recategorize, NamingPolicy

Why this exists
---------------
"Put these files into a knowledge base" was implemented five times — `kv.upload`,
`kv.upload_bulk`, `kv.ingest_folder`, `kv.index_missing`, and
the migration script since removed — each with its own idea of what a document is
(`ingest_folder` skipped PDFs entirely, the single most likely file a teammate has), its own
`created_at` rule, and its own record shape. Moving data between them changed the outcome.

This module is the single implementation. Front doors are adapters:

    CLI directory  ─┐
    zip / transfer ─┼─►  ingest_directory()  ─►  file on disk + record in .kvmeta/<kb>.json
    browser upload ─┘

The unit is ``(relative_path, bytes)``, which is what every one of those sources can produce
cheaply, and what the browser already sends.

Catalog-aware by construction
-----------------------------
Nothing here moves a file without updating `.kvmeta/<kb>.json` in the same operation, because a
catalog that disagrees with the disk is the failure this whole exercise is about: it produces
documents that list but do not open, or files that exist but cannot be seen.

Two rules differ from the scripts this replaces:

1. **It copies, it does not move.** `ingest` leaves the source untouched, so there is nothing to
   reverse: undo is "delete the target". Every bug found in the migration script this replaced
   (removed 2026-10-15) lived in the move machinery — journal collisions, an inverse hierarchy
   shift writing `industry=None`, a manifest carried back into the parent — and none of them can
   occur here.
2. **Collisions merge.** The root-level knowledge base IS the one consistent knowledge base, so a
   second `semiconduct_industry` merges into the first rather than being refused. Files whose
   content already exists are skipped by hash, which is what makes re-running safe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional

from services.kb_discovery import (
    MANIFEST_NAME, catalog_path, documents_dir, kb_root, legacy_root, manifest_path,
    read_manifest, write_manifest,
)

logger = logging.getLogger(__name__)

# ── what is a document ─────────────────────────────────────────────────────
# Defined once. `api/knowledge/doc_chat.py` imports these rather than keeping its own copy, so
# the read side and the write side cannot disagree about what is readable.

TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".xml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css",
    ".sql", ".sh", ".bash", ".rb", ".go", ".rs", ".java", ".kt",
    ".swift", ".r", ".c", ".cpp", ".h", ".hpp",
}
PDF_EXTENSIONS = {".pdf"}
# Deferred by decision (2026-10-15): office formats are stored and listed but doc chat cannot
# inline them, so admitting them now would create documents that list and cannot be read.
OFFICE_EXTENSIONS: set[str] = set()

DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | OFFICE_EXTENSIONS

HIERARCHY = ("industry", "player", "sub_category", "sub_department")


class NamingPolicy(str, Enum):
    """How a knowledge base's folder name is derived.

    PRESERVE is the default because the folder's own name is the knowledge base's name — the rule
    this whole layout rests on — and because a name somebody chose (`Carrier-Researcher
    SS-Search L&T India`) is not improved by being rewritten.

    CANONICAL additionally folds a name into `snake_case`: lowercase, separators collapsed to
    underscores. It is opt-in, and it never touches non-ASCII, so `惠州华阳医疗器械有限公司` stays
    intact under either policy.
    """

    PRESERVE = "preserve"
    CANONICAL = "canonical"


# ── naming ─────────────────────────────────────────────────────────────────

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")


def equivalence_key(name: str) -> str:
    """Two names that differ only by case or separator are the same knowledge base.

    `business_model`, `business-model` and `Business Model` are one knowledge base, and creating a
    second one is the duplication this module exists to prevent. Only *provable* equivalence
    collapses; a judgement call such as `semiconduct_industry` vs `semiconductor_industry` is
    reported and left alone, because merging on a fuzzy guess is how the mess being cleaned up was
    made.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def canonical_name(name: str) -> str:
    """Fold a name into `snake_case`, or raise if it cannot be a folder name.

    Non-ASCII is kept: `惠州华阳医疗器械有限公司` is a perfectly good folder name, and collapsing a
    Chinese company name to an empty string would be a data-loss bug dressed as normalisation.
    """
    cleaned = _UNSAFE_NAME_CHARS.sub("_", name.strip())
    cleaned = re.sub(r"[\s.\-]+", "_", cleaned)
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    if not cleaned or cleaned in (".", "..") or set(cleaned) == {"."}:
        raise ValueError(f"{name!r} cannot be used as a knowledge base name")
    return cleaned.lower() if cleaned.isascii() else cleaned


def check_name(name: str, policy: NamingPolicy = NamingPolicy.PRESERVE) -> str:
    """The folder name a knowledge base will actually get, under a naming policy."""
    if policy is NamingPolicy.CANONICAL:
        return canonical_name(name)
    cleaned = _UNSAFE_NAME_CHARS.sub("_", name.strip()).strip(" .")
    if not cleaned or cleaned in (".", ".."):
        raise ValueError(f"{name!r} cannot be used as a knowledge base name")
    return cleaned


def find_knowledge_base(name: str) -> Optional[str]:
    """An existing knowledge base equivalent to `name`, or None.

    Compared on `equivalence_key`, so a folder named `Business-Model` resolves to the existing
    `business_model` instead of becoming a second knowledge base with the same documents in it.
    """
    from services.kb_discovery import discover

    wanted = equivalence_key(name)
    for kb in discover():
        if equivalence_key(kb.key) == wanted:
            return kb.key
    return None


def near_misses(name: str) -> list[str]:
    """Existing knowledge bases whose name is *close* but not provably equal.

    Reported, never acted on. `semiconduct_industry` vs `semiconductor_industry` is one edit apart
    and merging them automatically would be a guess.
    """
    from difflib import SequenceMatcher

    from services.kb_discovery import discover

    wanted = equivalence_key(name)
    out = []
    for kb in discover():
        other = equivalence_key(kb.key)
        if other == wanted or not other:
            continue
        ratio = SequenceMatcher(None, wanted, other).ratio()
        if ratio >= 0.85:
            out.append(kb.key)
    return sorted(out)


# ── hashing and records ────────────────────────────────────────────────────

def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_catalog(kb: str) -> dict:
    path = catalog_path(kb)
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a corrupt catalog must not stop an ingest
        logger.warning("could not read catalog for %s: %s", kb, exc)
        return {}


def save_catalog(kb: str, records: dict) -> None:
    """Write the catalog atomically.

    `tmp` + `replace`, because a half-written catalog is indistinguishable from a corrupt one and
    would take the listed documents with it.
    """
    path = catalog_path(kb, create=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def catalog_hashes(records: dict) -> dict[str, str]:
    """sha256 -> doc_id for every record that has one. Older records have no hash."""
    return {r["sha256"]: doc_id for doc_id, r in records.items()
            if isinstance(r, dict) and r.get("sha256")}


def disk_hashes(kb: str, records: dict) -> dict[str, str]:
    """sha256 -> key for the files this knowledge base actually holds.

    The disk is the source of truth, so dedup asks the files as well as the catalog: a record
    written before hashes existed, or a file copied in by hand, would otherwise be re-ingested as
    a new document.
    """
    out: dict[str, str] = {}
    base = documents_dir(kb)
    if not base.is_dir():
        return out
    for path in base.rglob("*"):
        if not path.is_file() or path.name == MANIFEST_NAME or path.name.startswith("."):
            continue
        out[sha256_of(path.read_bytes())] = str(path.relative_to(base).as_posix())
    return out


def _hierarchy_for(rel_key: str) -> dict:
    """`reports/2026/x.md` -> industry=reports, player=2026.

    Decorates the record only; nothing retrieves by these fields, and the path is what doc chat
    scopes by. Kept because the panel shows them and because dropping them would silently change
    an existing response shape.
    """
    parts = list(Path(rel_key).parts[:-1])
    return {key: (parts[i] if len(parts) > i else None) for i, key in enumerate(HIERARCHY)}


def _storage_name(filename: str) -> str:
    """Prefix the basename with 8 hex characters, the collision guard the writer has always used.

    Only the basename is prefixed — the directory part is carried by the record's `key`, so a name
    containing a slash can never be read as a path.
    """
    base = Path(filename).name
    if base.startswith("."):
        raise ValueError(f"refusing to store a hidden file: {filename!r}")
    return f"{uuid.uuid4().hex[:8]}_{base}"


def build_record(*, kb: str, key: str, filename: str, original_filename: str, data: bytes,
                 created_at: Optional[float]) -> dict:
    """A catalog record for one stored file.

    `key` is the KB-relative path and is the source of truth; `storage_path` is kept alongside it
    for readers that have not been switched over, and is derived rather than authoritative. That
    is what makes a copied catalog work on another machine — the absolute path of the machine it
    came from is no longer load-bearing.
    """
    return {
        "id": uuid.uuid4().hex[:16],
        "filename": filename,
        "original_filename": original_filename,
        "size": len(data),
        "mime_type": mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
        "key": key,
        "storage_path": str((documents_dir(kb) / key).resolve()),
        "sha256": sha256_of(data),
        # mtime when the source has one ("when was this collected"), ingest time otherwise.
        # The browser cannot supply a trustworthy mtime, so an upload gets the clock.
        "created_at": created_at if created_at is not None else time.time(),
        "kb": kb,
        "linked": False,
        **_hierarchy_for(key),
    }


# ── results ────────────────────────────────────────────────────────────────

@dataclass
class IngestReport:
    """What an ingest did, so a caller never has to guess from a count."""

    knowledge: str
    created_kb: bool = False
    merged_into: Optional[str] = None
    written: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    # Files left exactly where they are, with the reason. Deliberately NOT `refused`: a file that
    # arrived on its own has no folder to inherit a name from, and leaving it is a legitimate
    # outcome, not an error. The user can still upload it through the normal button.
    left_alone: list[tuple[str, str]] = field(default_factory=list)
    unknown_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refused

    def lines(self) -> list[str]:
        out = [f"  knowledge base : {self.knowledge}"
               + ("   (created)" if self.created_kb else "")
               + (f"   (merged into existing {self.merged_into!r})"
                  if self.merged_into and self.merged_into != self.knowledge else "")]
        out.append(f"  written        : {len(self.written)}")
        if self.duplicates:
            out.append(f"  duplicates     : {len(self.duplicates)} (content already present — skipped)")
        if self.left_alone:
            out.append(f"  left in place  : {len(self.left_alone)} "
                       f"(no folder to inherit a name from)")
            for name, _reason in self.left_alone[:5]:
                out.append(f"      {name}")
        if self.unknown_types:
            out.append(f"  unrecognised   : {len(self.unknown_types)} "
                       f"(ingested, but they may not open in chat)")
            for name in self.unknown_types[:5]:
                out.append(f"      {name}")
        if self.refused:
            out.append(f"  refused        : {len(self.refused)}")
            for name, reason in self.refused[:5]:
                out.append(f"      {name}: {reason}")
        for warning in self.warnings:
            out.append(f"  ! {warning}")
        return out


# ── sources ────────────────────────────────────────────────────────────────

def iter_directory(root: Path, *, skip_hidden: bool = True) -> Iterator[tuple[str, Path, float]]:
    """Walk a directory as `(relative_path, path, mtime)`.

    Yields paths rather than bytes so a caller can decide per file without holding a whole tree in
    memory; `ingest_from_directory` reads them one at a time for the same reason.
    """
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if skip_hidden and any(part.startswith(".") for part in Path(rel).parts):
            continue
        if path.name == MANIFEST_NAME:
            continue
        yield rel, path, path.stat().st_mtime


# ── the core ───────────────────────────────────────────────────────────────

def ingest_files(
    sources: list[tuple[str, bytes, Optional[float]]],
    knowledge: str,
    *,
    apply: bool = False,
    naming: NamingPolicy = NamingPolicy.PRESERVE,
    strip_prefix: int = 0,
) -> IngestReport:
    """Put `sources` into the knowledge base `knowledge`, merging if it already exists.

    `sources` is `(relative_path, data, mtime)`. `relative_path` is the path *inside the knowledge
    base* — its directory part sets the hierarchy, its basename names the file.

    Idempotent: a file whose content is already in the target is skipped, whether the catalog or
    the disk says so. Running twice adds nothing, which is what lets this replace a migration
    script that had to refuse on collision.
    """
    report = IngestReport(knowledge=knowledge)

    existing = find_knowledge_base(knowledge)
    resolved = existing or check_name(knowledge, naming)
    report.knowledge = resolved
    if existing and equivalence_key(existing) != equivalence_key(knowledge):
        report.merged_into = existing
    report.created_kb = existing is None

    known = dict(disk_hashes(resolved, load_catalog(resolved)))
    if not apply:
        # A dry run must not create anything, including the knowledge base folder.
        known = known or {}

    records = load_catalog(resolved)
    new_records: dict[str, dict] = {}

    for rel, data, mtime in sources:
        rel = rel.strip("/")
        if not rel:
            report.refused.append(("<empty path>", "no name inside the knowledge base"))
            continue
        parts = Path(rel).parts
        if any(p in ("..", "") for p in parts) or Path(rel).is_absolute():
            report.refused.append((rel, "path would leave the knowledge base"))
            continue
        name = parts[-1]
        if name.startswith("."):
            report.refused.append((rel, "hidden file"))
            continue

        # A re-ingested file may already carry the writer's 8-hex prefix; stripping it keeps names
        # from stacking (`b37a8720_3d136714_report.md`).
        display_name = name
        for _ in range(strip_prefix):
            head, sep, rest = display_name.partition("_")
            if len(head) == 8 and sep and all(c in "0123456789abcdef" for c in head):
                display_name = rest
            else:
                break

        digest = sha256_of(data)
        if digest in known:
            report.duplicates.append(rel)
            continue

        ext = Path(display_name).suffix.lower()
        if ext and ext not in DOCUMENT_EXTENSIONS:
            report.unknown_types.append(rel)

        if not apply:
            report.written.append(rel)
            known[digest] = rel          # a batch may hold the same content twice
            continue

        stored = _storage_name(display_name)
        key = (Path(*parts[:-1]) / stored).as_posix() if len(parts) > 1 else stored
        target = documents_dir(resolved) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        record = build_record(kb=resolved, key=key, filename=stored,
                              original_filename=rel, data=data, created_at=mtime)
        new_records[record["id"]] = record
        known[digest] = key
        report.written.append(rel)

    if apply and report.written:
        documents_dir(resolved).mkdir(parents=True, exist_ok=True)
        write_manifest(documents_dir(resolved), resolved, resolved)
        records.update(new_records)
        save_catalog(resolved, records)

    return report


def ingest_directory(
    root: Path,
    *,
    knowledge: Optional[str] = None,
    loose_name: Optional[str] = None,
    apply: bool = False,
    naming: NamingPolicy = NamingPolicy.PRESERVE,
    strip_prefix: int = 0,
) -> list[IngestReport]:
    """Ingest a directory.

    Two shapes, decided by whether the caller names a target:

    * `knowledge` given — the whole directory becomes that one knowledge base, and its subfolders
      become folders inside it. This is what an online folder upload does.
    * `knowledge` omitted — each immediate subfolder becomes a knowledge base named after itself,
      and files sitting at the root have no folder to inherit a name from. That is the legacy
      layout (`project_<id>/<folder>/**`), and it is the shape a teammate's tree arrives in.

    Files directly under `root` need `loose_name`: there is no folder to inherit a name from, so
    the caller supplies one or they are reported and left alone.
    """
    root = Path(root)
    if knowledge is not None:
        sources = [(rel, path.read_bytes(), mtime)
                   for rel, path, mtime in iter_directory(root)]
        return [ingest_files(sources, knowledge, apply=apply, naming=naming,
                             strip_prefix=strip_prefix)]

    reports: list[IngestReport] = []
    subfolders = sorted(p for p in root.iterdir()
                        if p.is_dir() and not p.name.startswith("."))
    loose = sorted(p for p in root.iterdir() if p.is_file() and not p.name.startswith("."))

    for folder in subfolders:
        sources = []
        for rel, path, mtime in iter_directory(folder):
            # `rel` is already relative to the folder, and the folder IS the knowledge base — so
            # this is the path inside the base as it stands. Prefixing it with the folder's own
            # name (as an earlier draft did) nests the knowledge base inside itself:
            # `EBL/EBL/cv/x.md`, with `industry=EBL, player=cv` instead of `industry=cv`.
            sources.append((rel, path.read_bytes(), mtime))
        reports.append(ingest_files(sources, folder.name, apply=apply, naming=naming,
                                    strip_prefix=strip_prefix))

    if loose:
        if loose_name:
            sources = [(p.name, p.read_bytes(), p.stat().st_mtime) for p in loose]
            reports.append(ingest_files(sources, loose_name, apply=apply, naming=naming,
                                        strip_prefix=strip_prefix))
        else:
            # Left exactly where they are. A file that arrived on its own has no folder to inherit
            # a name from, and inventing one is how `(ungrouped)` happened — a bucket whose
            # documented fate was documents the user cannot filter and the agent cannot route. The
            # user can upload it through the ordinary upload button, which is the flow they
            # already know.
            reports.append(IngestReport(
                knowledge="<left in place>",
                left_alone=[(p.name, "no folder to inherit a name from") for p in loose],
            ))
    return reports


# ── the legacy tree, as the UI sees it ─────────────────────────────────────

def folder_fingerprint(folder: Path) -> tuple[int, str]:
    """A folder's file count and a cheap fingerprint of its contents, in one walk.

    The fingerprint is over `(relative path, size, mtime)` — **stat only, no file reads** — because
    this runs every time the migration panel opens and the largest legacy folder holds 900 files.

    That choice is deliberate, and the asymmetry is what makes it safe:

    * A **false negative** (fingerprint differs, so an already-migrated folder is offered again) is
      harmless: migration is idempotent, so a repeat run writes nothing and reports the files as
      already present.
    * A **false positive** (folder hidden as done when it is not) would be the damaging direction,
      and it needs identical paths, sizes *and* mtimes with different bytes — which does not happen
      by accident.

    So the cheap signal errs in the harmless direction. Editing a file in place changes its mtime
    and re-offers the folder, which is the right answer anyway: the source changed.
    """
    count = 0
    digest = hashlib.sha256()
    for rel, path, _mtime in iter_directory(folder):
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        digest.update(f"{rel}|{stat.st_size}|{int(stat.st_mtime)}\n".encode())
    return count, digest.hexdigest()


def record_migration(knowledge: str, project: str, folder: str,
                     count: int, fingerprint: str) -> None:
    """Note, in the knowledge base's own manifest, which legacy folder it came from.

    Written into `kb.json` rather than a separate ledger for three reasons: the manifest already
    travels with the knowledge base, so the record cannot be separated from what it describes;
    `write_manifest` is additive by design, so a field this version does not know about survives;
    and if the knowledge base is deleted the record goes with it, which is exactly right — a
    ledger entry pointing at a missing knowledge base would hide a folder that needs migrating.
    """
    folder_dir = documents_dir(knowledge)
    folder_dir.mkdir(parents=True, exist_ok=True)
    data = read_manifest(folder_dir)
    sources = [s for s in (data.get("sources") or [])
               if not (s.get("project") == project and s.get("folder") == folder)]
    sources.append({
        "project": project,
        "folder": folder,
        "files": count,
        "fingerprint": fingerprint,
        "migrated_at": time.time(),
    })
    data["sources"] = sources
    path = manifest_path(folder_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def migrated_index() -> dict[tuple[str, str], dict]:
    """`(project, folder) -> what it became`, read from every knowledge base's manifest.

    This is what makes "already migrated" survive a page reload. The alternative — remembering it
    in the browser — forgets, and then the panel re-offers work that is done.
    """
    out: dict[tuple[str, str], dict] = {}
    root = Path(kb_root())
    if not root.is_dir():
        return out
    for kb in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        try:
            data = read_manifest(kb)
        except Exception:  # noqa: BLE001 — an unreadable manifest must not break the scan
            continue
        for source in data.get("sources") or []:
            if not isinstance(source, dict):
                continue
            project, folder = source.get("project"), source.get("folder")
            if project and folder:
                out[(project, folder)] = {
                    "knowledge": kb.name,
                    "fingerprint": source.get("fingerprint"),
                    "files": source.get("files"),
                    "migrated_at": source.get("migrated_at"),
                }
    return out


def adopt_existing_migrations(*, apply: bool = False) -> list[dict]:
    """Record provenance for folders that were migrated before provenance existed.

    The cheap fingerprint `scan_legacy` uses only works once a folder has been *recorded*. A folder
    migrated by an earlier version has no record, so it would be offered again forever. This does
    the expensive, exact check once — is every source file's content already in the knowledge base?
    — and writes the record, after which the cheap check takes over.

    Exact rather than heuristic, and deliberately so: it reads every file on both sides. It runs
    once per folder, as an explicit step, rather than on every panel open, because a read-only GET
    must not write and a full hash of both trees on every open would be felt.

    Only content is compared, not paths: a file that arrived under a different name still counts as
    present, because the question is whether this folder's documents are in the knowledge base, not
    whether they are laid out identically.
    """
    out: list[dict] = []
    known = migrated_index()
    root = Path(legacy_root())
    if not root.is_dir():
        return out

    for entry in sorted(p for p in root.iterdir() if p.is_dir()):
        if entry.name == "project_chat_sessions" or not entry.name.startswith("project_"):
            continue
        for child in sorted(entry.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            if (entry.name, child.name) in known:
                continue
            target = find_knowledge_base(child.name)
            if not target:
                continue
            count, fingerprint = folder_fingerprint(child)
            if not count:
                continue
            source_hashes = {sha256_of(p.read_bytes())
                             for _rel, p, _m in iter_directory(child)}
            present = set(disk_hashes(target, load_catalog(target)))
            missing = source_hashes - present
            record = {
                "project": entry.name,
                "folder": child.name,
                "knowledge": target,
                "files": count,
                "already_present": len(source_hashes & present),
                "distinct": len(source_hashes),
                "missing": len(missing),
                "adopted": not missing,
            }
            if record["adopted"] and apply:
                record_migration(target, entry.name, child.name, count, fingerprint)
            out.append(record)
    return out


def import_directory(source, knowledge: str, *, apply: bool = False,
                     naming: NamingPolicy = NamingPolicy.PRESERVE) -> IngestReport:
    """Take a folder on this machine and make it a knowledge base called `knowledge`.

    The counterpart to picking a folder in the browser: for material that is ALREADY on the machine
    running the backend — unzipped into a temp directory, copied from a share, restored from a
    backup — where sending the bytes through the browser would mean uploading a folder to the
    computer it is already on. Nothing is transferred here; the files are copied straight into the
    knowledge root.

    Refuses a path already inside the knowledge root, and not out of caution: those files are
    already in a knowledge base, so copying them would put a second copy beside the first under a
    new name. `Scan and index` is the operation for that, and it writes records without moving a
    byte. A refusal that names the button to press is worth more than a silent duplication.
    """
    src = Path(source).expanduser()
    if not src.exists() or not src.is_dir():
        return IngestReport(knowledge=knowledge,
                            refused=[(str(source), "not a folder on this machine")])

    try:
        inside = src.resolve().is_relative_to(Path(kb_root()).resolve())
    except (OSError, ValueError):
        inside = False
    if inside:
        return IngestReport(knowledge=knowledge, refused=[(
            str(source),
            "already inside the knowledge root — use 'Scan and index', which records those files "
            "where they are instead of copying them")])

    sources = [(rel, path.read_bytes(), mtime) for rel, path, mtime in iter_directory(src)]
    if not sources:
        return IngestReport(knowledge=knowledge,
                            refused=[(str(source), "that folder has no files in it")])
    return ingest_files(sources, knowledge, apply=apply, naming=naming)


def scan_source(root=None) -> list[dict]:
    """Folders that could become knowledge bases, under the legacy root or any path you name.

    Two shapes, decided by what is there rather than by a flag:

    * **A legacy root** — its children are `project_<id>` folders, so each project is a group and its
      subfolders are the candidates. This is the layout the old code produced and the one the
      default scan finds. A `project_chat_sessions` child is skipped: chat attachments, not
      knowledge.
    * **Any other path** — a folder a teammate handed over, an unzipped archive, an old disk. Its
      immediate subfolders are the candidates, grouped under the path's own name.

    Every candidate carries the absolute directory it came from, so the caller names a folder rather
    than reconstructing a path from parts — and so a folder outside the legacy root is reachable at
    all, which is the whole point of naming a path.
    """
    base = Path(root).expanduser() if root else Path(legacy_root())
    known = migrated_index()
    out: list[dict] = []
    if not base.is_dir():
        return out
    base_abs = base.resolve()

    children = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    projects = [c for c in children if c.name.startswith("project_")]
    if projects:
        groups = [(p.name, p) for p in projects if p.name != "project_chat_sessions"]
    else:
        groups = [(base_abs.name or str(base_abs), base_abs)]

    for label, group_dir in groups:
        folders = []
        for child in sorted(p for p in group_dir.iterdir()
                            if p.is_dir() and not p.name.startswith(".")):
            count, fingerprint = folder_fingerprint(child)
            if not count:
                continue
            record = known.get((label, child.name))
            item = {"folder": child.name, "files": count,
                    "group": label, "source": str(child.resolve())}
            if record:
                item["migrated_into"] = record["knowledge"]
                item["migrated"] = record.get("fingerprint") == fingerprint
                item["changed"] = not item["migrated"]
            else:
                item["migrated"] = False
                item["changed"] = False
            folders.append(item)
        if folders:
            out.append({"project": label, "path": str(group_dir.resolve()), "folders": folders})
    return out


def scan_legacy() -> list[dict]:
    """The legacy root, scanned. Kept so callers that mean that root do not have to pass it."""
    return scan_source(None)


# ── recategorize ───────────────────────────────────────────────────────────

def _strip_stored_prefix(name: str) -> str:
    """`b37a8720_report.md` -> `report.md`, repeatedly.

    Re-ingested files can carry two prefixes, and only the writer's own is ours to remove. A file
    genuinely called `deadbeef_notes.md` keeps its name, because the head must be exactly 8 hex
    characters with an underscore after it.
    """
    out = name
    while True:
        head, sep, rest = out.partition("_")
        if len(head) == 8 and sep and rest and all(c in "0123456789abcdef" for c in head):
            out = rest
        else:
            return out


def _names_for(record: dict) -> set[str]:
    """Every name a caller might reasonably use to refer to this document.

    `--path` should accept what the panel shows (`EBL OS Introduction.pdf`), not the prefixed name
    the writer put on disk (`cd55755f_EBL OS Introduction.pdf`) — a tool whose arguments only match
    internal identifiers is a tool people work around instead of with.
    """
    out: set[str] = set()
    for value in (record.get("key"), record.get("filename"), record.get("original_filename")):
        if not value:
            continue
        value = str(value)
        out.add(value)
        out.add(Path(value).name)
        out.add(_strip_stored_prefix(Path(value).name))
        out.add(_strip_stored_prefix(value))
    return {v for v in out if v}


def recategorize(
    source_kb: str,
    target_kb: str,
    *,
    paths: Optional[list[str]] = None,
    apply: bool = False,
    naming: NamingPolicy = NamingPolicy.PRESERVE,
) -> IngestReport:
    """Move documents out of one knowledge base and into another, updating both catalogs.

    This is what "re-categorise" means: the record leaves the source catalog in the same operation
    that the file leaves the source directory, so the two never disagree.

    No hierarchy *shift* is needed, unlike promoting a whole folder — a file moving from
    `ungrouped/x.pdf` to `EBL_OS_docs/x.pdf` simply has no parent folders, so its hierarchy is
    recomputed from its new key rather than shifted.
    """
    report = IngestReport(knowledge=target_kb)
    source_kb = find_knowledge_base(source_kb) or source_kb
    target = find_knowledge_base(target_kb)
    resolved_target = target or check_name(target_kb, naming)
    report.knowledge = resolved_target
    report.created_kb = target is None
    if target:
        report.merged_into = target

    source_records = load_catalog(source_kb)
    if not source_records:
        report.warnings.append(f"no catalog for {source_kb!r} — nothing to move")
        return report

    wanted = set(paths) if paths else None
    selected: list[tuple[str, dict]] = []
    for doc_id, record in source_records.items():
        if not isinstance(record, dict):
            continue
        if wanted is not None and not (_names_for(record) & wanted):
            continue
        selected.append((doc_id, record))

    if not selected:
        report.warnings.append(f"nothing in {source_kb!r} matched {sorted(wanted) if wanted else 'all'}")
        return report

    target_records = load_catalog(resolved_target) if report.created_kb is False else {}
    known = dict(disk_hashes(resolved_target, target_records)) if target_records else {}

    moved_ids: list[str] = []
    for doc_id, record in selected:
        source_path = documents_dir(source_kb) / (record.get("key") or "")
        if not record.get("key") or not source_path.is_file():
            report.refused.append((record.get("original_filename", doc_id),
                                   "file is not where the catalog says it is"))
            continue
        data = source_path.read_bytes()
        digest = sha256_of(data)
        if digest in known:
            report.duplicates.append(record.get("original_filename", doc_id))
            continue

        # Re-derive the on-disk name from the CLEAN display name, not `original_filename`: the
        # latter is the path it arrived by and still carries whatever prefix the legacy upload
        # gave it, so rebuilding from it stacks prefixes and yields
        # `fc03bfcb_3d136714_EBL OS Introduction.pdf`.
        base = _strip_stored_prefix(record.get("filename") or source_path.name)
        new_key = _storage_name(base)
        report.written.append(record.get("original_filename") or new_key)
        if not apply:
            known[digest] = new_key
            continue

        target_path = documents_dir(resolved_target) / new_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        source_path.unlink()

        updated = dict(record)
        updated.update({
            "key": new_key,
            "storage_path": str(target_path.resolve()),
            "filename": new_key,
            "kb": resolved_target,
            "sha256": digest,
            **_hierarchy_for(new_key),
        })
        target_records[doc_id] = updated
        source_records.pop(doc_id, None)
        moved_ids.append(doc_id)
        known[digest] = new_key

    if apply and moved_ids:
        documents_dir(resolved_target).mkdir(parents=True, exist_ok=True)
        write_manifest(documents_dir(resolved_target), resolved_target, resolved_target)
        save_catalog(resolved_target, target_records)
        save_catalog(source_kb, source_records)

    return report
