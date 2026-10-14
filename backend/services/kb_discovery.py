# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""The knowledge base as it exists on disk — the single source of truth for it.

A knowledge base is a namespace directory plus its own catalog, and it exists because those files
exist. Nothing here reads a settings document or asks the `projects` table whether a knowledge
base may exist.

**The new layout** (what everything is moving to)::

    data/knowledge/                 <- the knowledge root, knowledge only
        kb_16/07b030a7_report.docx
        .kvmeta/kb_16.json          <- records carry "kb": "16"

**The legacy layout** (still read, so nothing breaks mid-migration)::

    data/documents/                 <- shared with chat attachments and RAG uploads
        project_16/07b030a7_report.docx
        .kvmeta/project_16.json     <- records also carried "project_id"

Both are discovered, the new one first. `scripts/migrate_kb_layout.py` moves one to the other,
and only the knowledge part moves: `project_chat_sessions` and the RAG uploads deliberately stay
in `data/documents`, which is 530 MB of the 695 MB there and is not knowledge.

Three rules this module enforces so the API and the maintenance scripts cannot drift apart:

1. **The root comes from environment configuration, never the settings registry.** A knowledge
   base can be found and read with the database unreachable, and no settings row can repoint it.
2. **Discovery is done by looking at the disk.** A folder is a knowledge base if it is named
   ``kb_<key>`` (or a legacy ``project_<id>``) and has a matching catalog beside it. A folder
   without a catalog is not one: nothing could list it.
3. **A discovered knowledge base is reachable.** The Knowledge panel lists projects, so
   ``register_missing()`` materialises a row per knowledge base, and `GET /api/projects/` calls it
   before answering. A row needs more than ``id`` and ``name`` — ``ProjectResponse`` requires
   ``status``, ``configuration`` and ``indexing_status``, and a partial row makes the endpoint
   return 500 for *every* project — and the id sequence is advanced past the highest registered id
   because explicit ids do not advance it.
"""
from __future__ import annotations

import glob
import json
import os
import re
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

_KB_DIR = re.compile(r"kb_([A-Za-z0-9._-]+)$")
_LEGACY_DIR = re.compile(r"project_(\d+)$")


def kb_root(instance_default: Optional[str] = None) -> Path:
    """The knowledge root: environment configuration, and nothing else."""
    for value in (os.getenv(KB_ROOT_ENV), instance_default, DEFAULT_KB_ROOT):
        if value:
            return Path(value)
    return Path(DEFAULT_KB_ROOT)


def legacy_root() -> Path:
    return Path(os.getenv(LEGACY_ROOT_ENV) or LEGACY_KB_ROOT)


def kb_roots() -> list[Path]:
    """Every root to read from, the current one first. Duplicates removed, order kept."""
    roots, seen = [], set()
    for root in (kb_root(), legacy_root()):
        if str(root) not in seen:
            seen.add(str(root))
            roots.append(root)
    return roots


def kv_dir(root: Optional[Path] = None) -> Path:
    return (root or kb_root()) / ".kvmeta"


# ── per-knowledge-base paths ────────────────────────────────────────────────

def kb_dir(key: str, root: Optional[Path] = None) -> Path:
    """Where a knowledge base's documents live. Always the current root: writes go here."""
    return (root or kb_root()) / f"kb_{key}"


def legacy_kb_dir(key: str, root: Optional[Path] = None) -> Path:
    return (root or legacy_root()) / f"project_{key}"


def catalog_path(key: str, create: bool = False) -> Optional[Path]:
    """The catalog holding this knowledge base, wherever it currently lives.

    New location first, then the legacy one, so an install being migrated keeps working until the
    migration runs. With ``create=True`` the current root's path is returned even when nothing
    exists yet — that is where a new knowledge base is written.
    """
    candidates = [kv_dir(kb_root()) / f"kb_{key}.json",
                  kv_dir(legacy_root()) / f"project_{key}.json"]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if create else None


def documents_dir(key: str) -> Path:
    """The documents directory to use for a knowledge base, preferring a migrated one."""
    current = kb_dir(key)
    if current.is_dir():
        return current
    legacy = legacy_kb_dir(key)
    if legacy.is_dir():
        return legacy
    return current


# ── discovery ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiscoveredProject:
    """One knowledge base found on disk. `key` is its identity; `legacy` says where it lives."""

    key: str
    catalog: Path
    document_count: int
    legacy: bool

    @property
    def project_id(self) -> Optional[int]:
        """The numeric handle the projects table and the API still use, when there is one."""
        return int(self.key) if self.key.isdigit() else None

    @property
    def folder(self) -> Path:
        parent = self.catalog.parent.parent
        return parent / (f"project_{self.key}" if self.legacy else f"kb_{self.key}")


def _scan(root: Path) -> list[DiscoveredProject]:
    catalogs = kv_dir(root)
    found = []
    for path in sorted(glob.glob(str(root / "*"))):
        if not os.path.isdir(path):
            continue
        name = os.path.basename(path)
        match = _KB_DIR.fullmatch(name)
        legacy = False
        if not match:
            match = _LEGACY_DIR.fullmatch(name)
            legacy = True
        if not match:
            continue                       # project_chat_sessions and friends are not knowledge
        key = match.group(1)
        catalog = catalogs / (f"project_{key}.json" if legacy else f"kb_{key}.json")
        if not catalog.exists():
            continue                       # no catalog: nothing would list it
        try:
            count = len(json.loads(catalog.read_text()))
        except Exception:                  # noqa: BLE001 — a corrupt catalog is still a KB
            count = 0
        found.append(DiscoveredProject(key=key, catalog=catalog,
                                       document_count=count, legacy=legacy))
    return found


def discover(root: Optional[Path] = None) -> list[DiscoveredProject]:
    """Every knowledge base on disk. Reads only the filesystem; no database, no settings."""
    if root is not None:
        return _scan(root)
    found, seen = [], set()
    for candidate in kb_roots():
        for kb in _scan(candidate):
            if kb.key in seen:
                continue                   # migrated or duplicated: the current root wins
            seen.add(kb.key)
            found.append(kb)
    return found


def uncatalogued(root: Optional[Path] = None) -> list[tuple[str, int]]:
    """Folders holding files that cannot be discovered: no catalog, or not a knowledge base."""
    found = []
    for candidate in ([root] if root is not None else kb_roots()):
        catalogs = kv_dir(candidate)
        for path in sorted(glob.glob(str(candidate / "*"))):
            if not os.path.isdir(path):
                continue
            name = os.path.basename(path)
            files = sum(len(fs) for _, _, fs in os.walk(path))
            if not files:
                continue
            match = _KB_DIR.fullmatch(name) or _LEGACY_DIR.fullmatch(name)
            if not match:
                found.append((name, files))                        # not a knowledge base
            elif not (catalogs / f"{'kb' if _KB_DIR.fullmatch(name) else 'project'}_"
                      f"{match.group(1)}.json").exists():
                found.append((name, files))                        # nothing could list it
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
    candidates = [p for p in discover() if wanted is None or p.key in wanted]
    if not candidates:
        return []

    existing = {str(row[0]) for row in db.execute(text("SELECT id FROM projects")).fetchall()}
    created: list[int] = []
    for kb in candidates:
        if kb.key in existing or kb.project_id is None:
            continue
        row = db.execute(text("""
            INSERT INTO projects (id, name, description, status, configuration,
                                  indexing_status, created_at, updated_at)
            VALUES (:id, :name, :desc, 'active', '{}'::json, 'not_indexed', now(), now())
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """), {"id": kb.project_id,
               "name": names.get(kb.project_id) or names.get(kb.key) or f"knowledge {kb.key}",
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
