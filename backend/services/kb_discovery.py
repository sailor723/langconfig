# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""The knowledge base as it exists on disk — the single source of truth for it.

Three rules, and this module is where they are enforced so that the API and the maintenance
scripts cannot drift apart:

1. **The root comes from the filesystem side, never the settings registry.** ``kb_root()`` reads
   environment configuration only. No database read decides where the knowledge base lives, so a
   knowledge base can be found and read with the database unreachable, and nothing in the
   settings documents can silently repoint it.
2. **Discovery is done by looking at the disk.** A folder is a project if it is named
   ``project_<id>`` and has a ``.kvmeta/project_<id>.json`` catalog beside it. That pairing is
   deliberate: it is what the panel lists documents from, and it excludes
   ``project_chat_sessions``, which is the chat attachment container keyed by session id rather
   than a project.
3. **A discovered project is reachable.** Copied folders have no ``projects`` row — the panel
   lists projects from the database, so such a knowledge base is present but invisible. Rather
   than requiring an operator to run a script, ``register_missing()`` materialises the rows, and
   the projects endpoint calls it before listing.

A row needs more than ``id`` and ``name``: ``ProjectResponse`` requires ``status``,
``configuration`` and ``indexing_status``, and a partial row makes ``GET /api/projects/`` return
500 for *every* project. Explicit ids also do not advance ``projects_id_seq``, so the sequence is
moved past the highest registered id or the next project created in the UI collides.
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Historical default, kept because every install has used it: relative to the backend CWD.
DEFAULT_KB_ROOT = "./data/documents"

# Written into every auto-registered row. `adopt_orphan_projects.py --undo` refuses to delete a
# row that no longer carries it, so a project a human has since described is never removed.
AUTO_DESC = "Adopted from data/documents — rename me in the UI"

_PROJECT_DIR = re.compile(r"project_(\d+)$")


def kb_root(instance_default: Optional[str] = None) -> Path:
    """Where the knowledge base lives: environment configuration, and nothing else.

    Order: ``KB_ROOT`` → ``DOCUMENTS_BASE_DIR`` (the original name) → the caller's default →
    ``./data/documents``. Relative paths resolve against the process CWD, which for the backend
    is ``backend/``.
    """
    for value in (os.getenv("KB_ROOT"), os.getenv("DOCUMENTS_BASE_DIR"), instance_default, DEFAULT_KB_ROOT):
        if value:
            return Path(value)
    return Path(DEFAULT_KB_ROOT)


def kv_dir(root: Optional[Path] = None) -> Path:
    return (root or kb_root()) / ".kvmeta"


@dataclass(frozen=True)
class DiscoveredProject:
    project_id: int
    kv_file: Path
    document_count: int

    @property
    def folder(self) -> Path:
        return self.kv_file.parent.parent / f"project_{self.project_id}"


def discover(root: Optional[Path] = None) -> list[DiscoveredProject]:
    """Every project the disk says exists, newest catalog first. Reads only the filesystem."""
    root = root or kb_root()
    catalogs = kv_dir(root)
    found = []
    for path in sorted(glob.glob(str(root / "project_*"))):
        match = _PROJECT_DIR.fullmatch(os.path.basename(path))
        if not match or not os.path.isdir(path):
            continue
        pid = int(match.group(1))
        kv_file = catalogs / f"project_{pid}.json"
        if not kv_file.exists():
            continue                      # no catalog: nothing would list it, so it is not a project
        try:
            count = len(json.loads(kv_file.read_text()))
        except Exception:                 # noqa: BLE001 — a corrupt catalog is still a project
            count = 0
        found.append(DiscoveredProject(project_id=pid, kv_file=kv_file, document_count=count))
    return found


def uncatalogued(root: Optional[Path] = None) -> list[tuple[str, int]]:
    """Folders holding files that cannot be discovered: no catalog, or not a project at all."""
    root = root or kb_root()
    catalogs = kv_dir(root)
    found = []
    for path in sorted(glob.glob(str(root / "project_*"))):
        if not os.path.isdir(path):
            continue
        name = os.path.basename(path)
        files = sum(len(fs) for _, _, fs in os.walk(path))
        if not files:
            continue
        if not _PROJECT_DIR.fullmatch(name):
            found.append((name, files))                                   # not a project
        elif not (catalogs / f"{name}.json").exists():
            found.append((name, files))                                   # a project nothing lists
    return found


def register_missing(db, names: Optional[dict] = None,
                     only: Optional[Iterable[int]] = None) -> list[int]:
    """Create the rows for on-disk projects that have none. Returns the ids it created.

    ``db`` is a SQLAlchemy Session. Idempotent: ``ON CONFLICT DO NOTHING`` means a project that
    already exists is left exactly as it is, including a human's name for it.
    """
    from sqlalchemy import text

    names = names or {}
    wanted = set(only) if only is not None else None
    candidates = [p for p in discover() if wanted is None or p.project_id in wanted]
    if not candidates:
        return []

    existing = {row[0] for row in db.execute(text("SELECT id FROM projects")).fetchall()}
    missing = [p for p in candidates if p.project_id not in existing]
    if not missing:
        return []

    created: list[int] = []
    for project in missing:
        row = db.execute(text("""
            INSERT INTO projects (id, name, description, status, configuration,
                                  indexing_status, created_at, updated_at)
            VALUES (:id, :name, :desc, 'active', '{}'::json, 'not_indexed', now(), now())
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """), {"id": project.project_id,
               "name": names.get(project.project_id) or f"project {project.project_id}",
               "desc": AUTO_DESC}).scalar()
        if row is not None:
            created.append(project.project_id)

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
