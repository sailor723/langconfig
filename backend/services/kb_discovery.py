# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""The knowledge base as it exists on disk — the single source of truth for it.

A knowledge base is a namespace directory plus its own catalog, and it exists because those files
exist. Nothing here reads a settings document or asks the `projects` table whether a knowledge
base may exist.

**The layout**::

    data/knowledge/                      <- the knowledge root, knowledge only
        langconfig-test/                 <- the folder name IS the knowledge base's name
            business_model/07b030a7_report.docx
            kb.json                      <- { "name": "langconfig-test", "key": "1" }
        .kvmeta/langconfig-test.json     <- the catalog, named after the folder it describes

**The layouts this replaced** (still read, so nothing breaks mid-rename)::

    data/knowledge/kb_16/  +  .kvmeta/kb_16.json
    data/documents/project_16/  +  .kvmeta/project_16.json   <- also holds chat attachments

All of them are discovered, the current root first. `scripts/rename_knowledge_bases.py` moves the
old names onto the new ones, and only the knowledge part moves: `project_chat_sessions` and the
RAG uploads deliberately stay in `data/documents`, which is 530 MB of the 695 MB there and is not
knowledge.

Four rules this module enforces so the API and the maintenance scripts cannot drift apart:

1. **The root comes from environment configuration, never the settings registry.** A knowledge
   base can be found and read with the database unreachable, and no settings row can repoint it.
2. **Discovery is done by looking at the disk.** A folder is a knowledge base when its catalog
   sits beside it *under the folder's own name* (``.kvmeta/<folder>.json``) — whatever the folder
   is called. No prefix is assumed and no key is derived from a number, so renaming a folder and
   its catalog is the entire migration and a knowledge base may be named anything. A folder
   without a catalog is not one: nothing could list it.
3. **A discovered knowledge base is reachable.** The Knowledge panel lists projects, so
   ``register_missing()`` materialises a row per knowledge base, and `GET /api/projects/` calls it
   before answering. A row needs more than ``id`` and ``name`` — ``ProjectResponse`` requires
   ``status``, ``configuration`` and ``indexing_status``, and a partial row makes the endpoint
   return 500 for *every* project — and the id sequence is advanced past the highest registered id
   because explicit ids do not advance it.
4. **One resolver, so the two ends of the pipeline cannot disagree.** ``documents_dir()`` is where
   uploads are written and where doc chat reads. These used to be separate path expressions that
   disagreed on *both* the root (``data/knowledge`` vs ``data/documents``) and the folder name
   (``kb_16`` vs ``project_16``), so a document uploaded into a knowledge base was invisible to
   the chat that was supposed to answer from it — and silently, because the other copy was there
   and answered instead.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Where knowledge lives: its own directory, so copying it copies exactly the knowledge.
DEFAULT_KB_ROOT = "./data/knowledge"
# Where it used to live, shared with chat attachments and RAG uploads. Read-only now.
LEGACY_KB_ROOT = "./data/documents"
# Overrides stay supported: a deployment may keep its knowledge elsewhere.
KB_ROOT_ENV = "KB_ROOT"
LEGACY_ROOT_ENV = "DOCUMENTS_KB_ROOT"

# Written into every auto-registered row. `adopt_orphan_projects.py --undo` refuses to delete a
# row that no longer carries it, so a project a human has since described is never removed.
AUTO_DESC = "Adopted from a knowledge folder — rename me in the UI"

# Each knowledge base carries its own name, so a folder is complete in itself: copy it and the
# knowledge base arrives with its identity, needing no row in `projects` and no database at all.
MANIFEST_NAME = "kb.json"

# The old naming conventions. Nothing recognises a knowledge base by these any more — discovery
# reads the catalog beside the folder, whatever it is called. They survive in one place only:
# `DiscoveredProject.identity`, which strips the prefix so a folder that predates the rename still
# matches the folder it replaced, and so a renamed knowledge base does not list twice.
_KB_DIR = re.compile(r"kb_([A-Za-z0-9._-]+)$")
_LEGACY_DIR = re.compile(r"project_(\d+)$")


def kb_root(instance_default: Optional[str] = None) -> Path:
    """The knowledge root: environment configuration, and nothing else."""
    for value in (os.getenv(KB_ROOT_ENV), instance_default, DEFAULT_KB_ROOT):
        if value:
            return Path(value)
    return Path(DEFAULT_KB_ROOT)


def legacy_root() -> Path:
    """Where knowledge used to live, shared with chat attachments and RAG uploads.

    Nothing scans this any more. It is kept for the migration scripts, which needed to know where
    a knowledge base came from in order to name it, and for `adopt_orphan_projects`, which looks
    for a journal it may have written there. Reading it was the last thing tying discovery to the
    old layout, and it had a cost that was not obvious: a knowledge base deleted from the current
    root would RESURFACE as its legacy twin, because the copy that had been shadowing it was gone.
    """
    return Path(os.getenv(LEGACY_ROOT_ENV) or LEGACY_KB_ROOT)


def kb_roots() -> list[Path]:
    """Every root discovery reads: the knowledge root, and nothing else.

    This returned both roots once, current first, which made `data/documents` a second opinion
    about what knowledge exists. It is 695 MB of which 530 MB is chat attachments, it is not
    knowledge, and the fallback meant deleting a knowledge base could resurrect an older copy of
    it from there. Knowledge has one home; this is that home.
    """
    return [kb_root()]


def kv_dir(root: Optional[Path] = None) -> Path:
    return (root or kb_root()) / ".kvmeta"


# ── per-knowledge-base paths ────────────────────────────────────────────────
# A knowledge base's FOLDER NAME is its handle, everywhere. Nothing here prefixes it, nothing
# derives it from a number, and both ends of the document pipeline resolve through these
# functions — so the folder a document is written into is the folder it is read back from.

def kb_dir(name: str, root: Optional[Path] = None) -> Path:
    """Where a knowledge base's documents live. Always the current root: writes go here."""
    return (root or kb_root()) / name


def legacy_kb_dir(name: str, root: Optional[Path] = None) -> Path:
    """Where the same knowledge base lived before it had a root of its own."""
    return (root or legacy_root()) / name


def catalog_path(name: str, create: bool = False) -> Optional[Path]:
    """The catalog holding this knowledge base, named after the folder it describes.

    So the pairing is visible in a directory listing: `langconfig-test/` is indexed by
    `.kvmeta/langconfig-test.json`. Nothing is derived from a number and no prefix is assumed,
    which is what makes renaming a folder a two-file operation. One root, so there is one answer.
    """
    path = kv_dir(kb_root()) / f"{name}.json"
    return path if (path.exists() or create) else None


def documents_dir(name: str) -> Path:
    """The directory this knowledge base's documents are in — the single resolver for both ends.

    Uploads write here and doc chat reads here, so "upload a document, then ask about it" is the
    same directory by construction rather than by two path expressions that happen to agree.
    """
    return kb_dir(name)


# ── discovery ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiscoveredProject:
    """One knowledge base found on disk.

    `key` is the folder name — the handle every endpoint takes, and the name a person sees.
    `identity` is the separate question of what makes two folders the same knowledge base across
    layouts; see below for why they are not the same thing.
    """

    key: str
    catalog: Path
    document_count: int
    folder: Path
    legacy: bool = False
    name: Optional[str] = None
    # The key the knowledge base was created under, carried in its own `kb.json`. Kept through a
    # rename so the folder it replaced stays shadowed instead of reappearing as a second entry.
    manifest_key: Optional[str] = None

    @property
    def display_name(self) -> str:
        """What to show for this knowledge base. Never depends on a database."""
        return self.name or self.key

    @property
    def identity(self) -> str:
        """What makes two folders the same knowledge base, across layouts.

        The knowledge base's own key when its manifest carries one, otherwise the folder name with
        a conventional ``kb_``/``project_`` prefix stripped. This is what keeps a renamed knowledge
        base from surfacing twice: ``langconfig-test/`` carries ``"key": "1"`` and therefore
        shadows ``data/documents/project_1``, exactly as ``kb_1`` did before it was renamed.

        Note this is deliberately NOT the folder name. The folder name is the handle callers pass
        as ``knowledge=``; folding the two together would have made every renamed knowledge base
        appear a second time beside the copy it came from.
        """
        if self.manifest_key:
            return str(self.manifest_key)
        match = _KB_DIR.fullmatch(self.key) or _LEGACY_DIR.fullmatch(self.key)
        return match.group(1) if match else self.key

    @property
    def project_id(self) -> Optional[int]:
        """The numeric handle the projects table and the API still use, when there is one."""
        return int(self.identity) if self.identity.isdigit() else None


def manifest_path(folder) -> Path:
    # str is accepted deliberately: discovery walks glob results, which are strings, and
    # `"dir" / "kb.json"` raises TypeError — swallowed by read_manifest's except, which is how a
    # knowledge base's own name went missing while everything looked correct.
    return Path(folder) / MANIFEST_NAME


def read_manifest(folder: Path) -> dict:
    """A knowledge base's own metadata, or {} when it has none yet."""
    try:
        return json.loads(manifest_path(folder).read_text(encoding="utf-8"))
    except Exception:                       # noqa: BLE001 — absence is normal, not an error
        return {}


def write_manifest(folder: Path, key: str, name: Optional[str] = None) -> Path:
    """Record the knowledge base's identity beside its files.

    Deliberately additive and non-destructive: an existing manifest is updated, never replaced,
    so a field this version does not know about survives.
    """
    folder.mkdir(parents=True, exist_ok=True)
    data = read_manifest(folder)
    data["key"] = key
    if name:
        data["name"] = name
    data.setdefault("created_at", time.time())
    path = manifest_path(folder)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _scan(root: Path, legacy: bool = False) -> list[DiscoveredProject]:
    """Every knowledge base in one root: a folder with its catalog beside it, whatever it is named.

    The catalog is looked up under the folder's own name, which is the whole rule. It covers the
    name-based layout and both older ones unchanged — `kb_16/` is indexed by `.kvmeta/kb_16.json`
    and `project_16/` by `.kvmeta/project_16.json` — so this is not a second discovery path that
    has to be kept in step with the first, it is the same one with the prefix rule deleted.
    """
    catalogs = kv_dir(root)
    found = []
    for path in sorted(glob.glob(str(root / "*"))):
        if not os.path.isdir(path):
            continue
        name = os.path.basename(path)
        if name.startswith("."):
            continue                       # .kvmeta and friends are not knowledge bases
        catalog = catalogs / f"{name}.json"
        if not catalog.exists():
            continue                       # no catalog: nothing would list it
        try:
            count = len(json.loads(catalog.read_text()))
        except Exception:                  # noqa: BLE001 — a corrupt catalog is still a KB
            count = 0
        manifest = read_manifest(path)     # the KB's own name, not a project's
        found.append(DiscoveredProject(
            key=name, catalog=catalog, document_count=count,
            folder=Path(path), legacy=legacy,
            name=manifest.get("name"), manifest_key=manifest.get("key"),
        ))
    return found


def discover(root: Optional[Path] = None) -> list[DiscoveredProject]:
    """Every knowledge base on the knowledge root. Reads the filesystem; no database, no settings.

    One root, so there is no precedence question and no shadowing: a knowledge base is a folder
    under the knowledge root with a catalog beside it, or it does not exist. `identity` still
    earns its keep by deduplicating within a root — two folders carrying the same manifest key are
    one knowledge base — but it no longer decides which of two trees wins.
    """
    if root is not None:
        return _scan(root)
    found, seen = [], set()
    for kb in _scan(kb_root()):
        if kb.identity in seen:
            continue
        seen.add(kb.identity)
        found.append(kb)
    return found


def uncatalogued(root: Optional[Path] = None) -> list[tuple[str, int]]:
    """Folders holding files that cannot be discovered: nothing beside them could list them."""
    found = []
    for candidate in ([root] if root is not None else kb_roots()):
        catalogs = kv_dir(candidate)
        for path in sorted(glob.glob(str(candidate / "*"))):
            if not os.path.isdir(path):
                continue
            name = os.path.basename(path)
            if name.startswith("."):
                continue
            files = sum(len(fs) for _, _, fs in os.walk(path))
            if not files:
                continue
            if not (catalogs / f"{name}.json").exists():
                found.append((name, files))
    return found


# ── registration: the Knowledge panel lists projects, so a KB needs a row ───

def register_missing(db, names: Optional[dict] = None,
                     only: Optional[Iterable] = None) -> list[int]:
    """Create the rows for on-disk knowledge bases that have none. Returns the ids created.

    Idempotent: ``ON CONFLICT DO NOTHING`` leaves an existing row exactly as it is, including a
    name a human gave it.
    """
    from sqlalchemy import text

    names = names or {}
    wanted = {str(o) for o in only} if only is not None else None
    # Matched on identity, not folder name: `only` and `names` are keyed by the knowledge base's
    # numeric handle, which a renamed folder no longer spell out for itself.
    candidates = [p for p in discover() if wanted is None or p.identity in wanted]
    if not candidates:
        return []

    existing = {str(row[0]) for row in db.execute(text("SELECT id FROM projects")).fetchall()}
    created: list[int] = []
    for kb in candidates:
        if kb.identity in existing or kb.project_id is None:
            continue
        row = db.execute(text("""
            INSERT INTO projects (id, name, description, status, configuration,
                                  indexing_status, created_at, updated_at)
            VALUES (:id, :name, :desc, 'active', '{}'::json, 'not_indexed', now(), now())
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """), {"id": kb.project_id,
               "name": (names.get(kb.project_id) or names.get(kb.identity)
                        or kb.display_name),
               "desc": AUTO_DESC}).scalar()
        if row is not None:
            created.append(kb.project_id)

    if created:
        fix_sequence(db)
        db.commit()
    return created


def fix_sequence(db) -> tuple[int, int]:
    """Advance projects_id_seq past the highest id, or the next UI-created project collides."""
    from sqlalchemy import text

    before = db.execute(text("SELECT last_value FROM projects_id_seq")).scalar()
    highest = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM projects")).scalar()
    if highest is not None and before is not None and highest > before:
        db.execute(text("SELECT setval('projects_id_seq', :h)"), {"h": highest})
        db.commit()
    after = db.execute(text("SELECT last_value FROM projects_id_seq")).scalar()
    return before, after
