"""
Simple key-value document store — no Neo4j, no vector DB, no PostgreSQL.

Stores documents on disk via `file_storage` and tracks metadata in an
in-memory dict (persisted to a JSON file on the KV_DATA_DIR path).

Follows the same zero-dependency pattern as `doc_chat.py`.

Endpoints:
  GET    /api/kv/bases              — the knowledge bases under the knowledge root
  GET    /api/kv/tree               — every folder and file under the knowledge root
  GET    /api/kv/documents          — list a knowledge base's documents
  POST   /api/kv/upload             — upload a single file
  POST   /api/kv/upload-bulk        — upload multiple files (folder)
  POST   /api/kv/link               — record a file that stays where it is
  POST   /api/kv/ingest-folder      — server-side folder walk
  DELETE /api/kv/documents/{id}     — delete a document
  GET    /api/kv/documents/{id}/file — serve raw file bytes
  GET    /api/kv/documents/{id}/content — extracted text (docx/pptx/xlsx/...)

Every one of them names the knowledge base by its FOLDER NAME — `knowledge=<folder>`, the same
value `/api/kv/bases` reports as `key`. There is no project id, and no `kb_<key>` folder
convention: a knowledge base is a folder with a catalog beside it, and `documents_dir()` resolves
it for this module and for doc chat alike, so the folder a document is uploaded into is the folder
it is read back from.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# The hierarchy a knowledge base files documents under, outermost first. `save_file` writes them
# in this order and `_parse_hierarchy_from_path` reads them back by position, so anything that
# names them has to use the same sequence.
_HIERARCHY = ("industry", "player", "sub_category", "sub_department")

# The 8-hex collision prefix `FileStorage.save_file` puts on every filename it writes. It is a
# storage detail; the document's own name is what follows it.
_ON_DISK_PREFIX = re.compile(r"^[0-9a-f]{8}_")

from core.utils.http import content_disposition

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.file_storage import file_storage

logger = logging.getLogger(__name__)

# Office/document MIME types vary across OS mimetypes databases — register
# them explicitly so docx/pptx/xlsx uploads and serving are consistent.
for _ext, _mime in (
    (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    (".doc", "application/msword"),
    (".xls", "application/vnd.ms-excel"),
    (".ppt", "application/vnd.ms-powerpoint"),
):
    mimetypes.add_type(_mime, _ext)

router = APIRouter(prefix="/api/kv", tags=["kv"])

# ── Where knowledge lives ──────────────────────────────────────────
# `data/knowledge`, its own directory: knowledge only, so copying it copies exactly the knowledge.
# It is deliberately NOT `file_storage.base_dir` (`data/documents`), which is shared with chat
# attachments (530 MB of this install's 695 MB) and RAG uploads. The root comes from environment
# configuration, never from a settings document, so a copied settings row cannot repoint it.
from services.kb_discovery import catalog_path, documents_dir, kb_root  # noqa: E402

KV_DATA_DIR = kb_root() / ".kvmeta"    # kept for callers that import it; the store
#                                        creates directories only when it writes


# ── In-memory KV store with JSON file persistence ─────────────────

class DocRecord(BaseModel):
    """A document record stored in the KV store.

    There is no `project_id` here, not even a legacy one. A knowledge base is named by the folder
    it lives in, which is also the name of its catalog, so a record has nothing to gain from
    repeating a project id — and when it did repeat one, it was a second copy of the catalog's own
    name that could drift from it. Catalogs written before the change still load: pydantic ignores
    the unknown field, and `put_doc()` does not write it back.
    """
    id: str
    filename: str
    original_filename: str
    size: int
    mime_type: Optional[str] = None
    storage_path: str  # absolute path on disk
    # The document's path INSIDE its knowledge base, and the source of truth for where it is.
    # `storage_path` above is the absolute path of whichever machine wrote the record, which makes
    # a catalog un-portable: copy the folder to another machine and every record still names the
    # old one. `key` resolves against the root the catalog is read from, so a copied knowledge base
    # works. Both are written; `_record_file` prefers this one.
    key: Optional[str] = None
    # Content hash, so a re-ingest can skip what is already here. Absent on records written before
    # hashing existed, which is why dedup also asks the disk.
    sha256: Optional[str] = None
    industry: Optional[str] = None
    player: Optional[str] = None
    sub_category: Optional[str] = None
    sub_department: Optional[str] = None
    created_at: float = Field(default_factory=time.time)  # epoch seconds
    # The knowledge base this document belongs to — the folder name, not a foreign key.
    kb: Optional[str] = None
    # Added by LINK rather than by upload: `storage_path` names a file that lives wherever it
    # already lived, nothing was copied into the knowledge store, and deleting the record must
    # never delete that file.
    linked: bool = False


class KVStore:
    """
    One knowledge base: a JSON catalog of documents plus the directory holding them.

    Constructed with the knowledge base's folder name. Thread-safe for single-writer deployments.
    For multi-process, consider replacing with Redis or a file lock.
    """

    def __init__(self, knowledge: str):
        self.knowledge = knowledge
        # Where this knowledge base currently lives: the current root, or the legacy one if it
        # has not been renamed yet. Reading and writing stay together, so a KB is never split
        # across two catalogs; the rename is what moves it.
        self._file = catalog_path(self.knowledge, create=True)
        self._data: Dict[str, Any] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────

    def _load(self) -> None:
        """Load metadata from JSON file if it exists.

        A catalog written before the change has `project_id` in every record and may lack `kb`;
        pydantic ignores the field it no longer knows and this fills in the one it needs, so the
        rest of the module never has to care which shape it is looking at.
        """
        if self._file.exists():
            try:
                raw = self._file.read_text(encoding="utf-8")
                self._data = json.loads(raw)
                for record in self._data.values():
                    if isinstance(record, dict):
                        record.setdefault("kb", self.knowledge)
            except Exception as e:
                logger.warning(f"Failed to load KV store from {self._file}: {e}")
                self._data = {}

    def _save(self) -> None:
        """Persist metadata to JSON file, creating the knowledge root if it is not there yet.

        Nothing creates this directory at import time, so a write to a knowledge base that has
        never been written before is what brings `.kvmeta` into existence. Without this the write
        raised FileNotFoundError, was swallowed by the handler below, and the record quietly
        disappeared.
        """
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save KV store to {self._file}: {e}")

    # ── CRUD ───────────────────────────────────────────────────

    def list_docs(self) -> List[DocRecord]:
        """Return all documents in this knowledge base."""
        return [DocRecord(**v) for v in self._data.values()]

    def get_doc(self, doc_id: str) -> Optional[DocRecord]:
        """Get a single document by id."""
        raw = self._data.get(doc_id)
        if raw is None:
            return None
        return DocRecord(**raw)

    def put_doc(self, doc: DocRecord) -> None:
        """Insert or update a document."""
        self._data[doc.id] = doc.model_dump()
        self._save()

    def put_docs(self, docs: List["DocRecord"]) -> int:
        """Insert or update several documents, writing the catalog ONCE.

        `put_doc` re-serialises the whole catalog per document, which is fine for one upload and
        quadratic for a sweep: indexing 171 files would rewrite a 580 KB catalog 171 times. The
        result is identical, the writes are not.
        """
        for doc in docs:
            self._data[doc.id] = doc.model_dump()
        if docs:
            self._save()
        return len(docs)

    def delete_doc(self, doc_id: str) -> bool:
        """Delete a document. Returns True if it existed."""
        existed = doc_id in self._data
        self._data.pop(doc_id, None)
        if existed:
            self._save()
        return existed

    def next_id(self) -> str:
        """Generate a unique document id."""
        return uuid.uuid4().hex[:16]


# ── Helpers ────────────────────────────────────────────────────────

def _record_file(doc, knowledge: Optional[str] = None) -> Path:
    """Where a record's file actually is, as an ABSOLUTE path.

    `key` first, because it is relative to the knowledge base and therefore survives the folder
    being copied to another machine or the root being moved. `storage_path` is the fallback for
    records written before `key` existed, and for `linked` documents, whose path is by definition
    wherever the user's own file lives.

    Resolved, and that is load-bearing rather than tidy. `documents_dir()` is configured relative
    (`./data/knowledge`) while every caller that compares this against something walked from disk
    holds an absolute path. Returning the relative form made `index-missing` match nothing, so it
    wrote a second record for all 441 files of a knowledge base that was already fully indexed —
    the same relative-versus-absolute trap the neighbours of this function warn about, and it cost
    a real cleanup to undo.
    """
    kb = knowledge or getattr(doc, "kb", None)
    key = getattr(doc, "key", None)
    if kb and key and not getattr(doc, "linked", False):
        candidate = documents_dir(kb) / key
        if candidate.is_file():
            return candidate.resolve()
    return Path(doc.storage_path).resolve()


def _doc_type_from_ext(filename: str) -> str:
    """Map file extension to a human-readable type string."""
    ext = Path(filename).suffix.lower()
    type_map = {
        ".txt": "text", ".md": "markdown", ".pdf": "pdf",
        ".json": "json", ".csv": "csv", ".yaml": "yaml", ".yml": "yaml",
        ".html": "html", ".htm": "html", ".xml": "xml",
        ".py": "code", ".js": "code", ".ts": "code", ".jsx": "code",
        ".tsx": "code", ".java": "code", ".cpp": "code", ".c": "code",
        ".h": "code", ".hpp": "code", ".rb": "code", ".go": "code",
        ".rs": "code", ".swift": "code", ".kt": "code",
        ".sh": "code", ".bash": "code", ".sql": "code",
        ".doc": "docx", ".docx": "docx",
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".gif": "image", ".webp": "image",
    }
    return type_map.get(ext, "text")


def _parse_hierarchy_from_metadata(metadata: dict) -> dict:
    """Extract hierarchy fields from uploaded metadata."""
    return {
        "industry": metadata.get("industry") if isinstance(metadata, dict) else None,
        "player": metadata.get("player") if isinstance(metadata, dict) else None,
        "sub_category": metadata.get("sub_category") if isinstance(metadata, dict) else None,
        "sub_department": metadata.get("sub_department") if isinstance(metadata, dict) else None,
    }


# ── File serving (encoding & media types) ────────────────────────────────
# Formats the browser can render inline; everything else (docx/pptx/zip/...)
# is sent as `attachment` so it downloads with the correct filename instead of
# rendering as garbage.
_VIEWABLE_EXTENSIONS = {
    ".pdf", ".html", ".htm",
    ".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".xml",
    ".css", ".sql", ".sh", ".bash", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}


def _serve_file_bytes(
    content: bytes,
    filename: str,
    stored_mime: Optional[str],
    range_header: Optional[str] = None,
) -> Response:
    """Build the document response: correct media type (re-guessing when the
    stored MIME is missing/unknown), a properly encoded disposition, and
    single-range support so Safari's PDF viewer can probe/seek (it errors out
    when a Range request is answered with a plain 200)."""
    ext = Path(filename).suffix.lower()
    mime = stored_mime or "application/octet-stream"
    if mime == "application/octet-stream":
        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"
    headers = {
        "Content-Disposition": content_disposition(
            filename, inline=ext in _VIEWABLE_EXTENSIONS
        ),
        "Accept-Ranges": "bytes",
    }
    total = len(content)

    # Browsers' PDF viewers issue a single range (e.g. "bytes=0-1" probe,
    # "bytes=100-200" seek, "bytes=-500" suffix) — handle just that.
    if range_header and total > 0:
        m = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
        if m:
            start_s, end_s = m.groups()
            if start_s == "" and end_s:  # suffix range: last N bytes
                start = max(0, total - int(end_s))
                end = total - 1
            else:
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total - 1
            if start < total and start <= end:
                end = min(end, total - 1)
                headers["Content-Range"] = f"bytes {start}-{end}/{total}"
                return Response(
                    content=content[start : end + 1],
                    media_type=mime,
                    status_code=206,
                    headers=headers,
                )
        # Un-satisfiable range
        headers["Content-Range"] = f"bytes */{total}"
        return Response(content=b"", media_type=mime, status_code=416, headers=headers)

    return Response(content=content, media_type=mime, headers=headers)


# ── Response schemas ──────────────────────────────────────────────

class KVDocumentResponse(BaseModel):
    id: str
    name: str
    original_filename: str
    document_type: str
    size: int
    mime_type: Optional[str] = None
    industry: Optional[str] = None
    player: Optional[str] = None
    sub_category: Optional[str] = None
    sub_department: Optional[str] = None
    created_at: float
    linked: bool = False
    # The knowledge base this document is in — the folder name, which is what the caller passed.
    knowledge: Optional[str] = None


class KVUploadResponse(BaseModel):
    id: str
    name: str
    size: int
    message: str


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/tree")
async def knowledge_tree(depth: int = 16):
    """Every folder and file under the knowledge root, exactly as it is on disk.

    Not documents-of-a-project, and not only what a catalog happens to list: this is the
    filesystem. A folder copied under the knowledge root shows up here before anything has
    registered it, which is the point — knowledge is the files, and the panel shows them.

    `depth` is a guard against a pathological tree, not a display choice, and it has to sit well
    past anything real: at the old default of 4, a knowledge base organised
    `industry/player/topic/section/team/` had its deepest folders — and every file in them — cut
    off silently, so the tree under-reported what was on disk (346 files against 952 records).
    """
    from services.kb_discovery import kb_root

    root = Path(kb_root()).resolve()

    def walk(directory: Path, level: int) -> list:
        if level > depth:
            return []
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except OSError:
            return []
        out = []
        for entry in entries:
            if entry.name == ".DS_Store" or entry.name == ".kvmeta":
                continue
            try:
                rel = str(entry.relative_to(root))
                if entry.is_dir():
                    out.append({"name": entry.name, "path": rel, "type": "dir",
                                "children": walk(entry, level + 1)})
                else:
                    out.append({"name": entry.name, "path": rel, "type": "file",
                                "size": entry.stat().st_size})
            except OSError:
                continue
        return out

    return {"root": str(root), "entries": walk(root, 1)}


@router.get("/bases")
async def list_knowledge_bases():
    """The knowledge bases this install holds, read from the filesystem.

    The Knowledge view uses this instead of asking which project to scope to. A knowledge base
    exists because its folder and catalog exist, so the list comes from the disk and works with
    the database unreachable. `key` is the folder name — pass it back as `knowledge=`.
    """
    from services.kb_discovery import discover, kb_root

    # No database read: a knowledge base's name lives with the knowledge base, in its own
    # `kb.json`. Listing and naming therefore work with Postgres unreachable, and copying the
    # folder to another machine carries the name with it.
    out = []
    for kb in discover():
        # Size comes from the catalog's own `size` fields, not a walk of the folder. Two reasons:
        # the catalog is already being read for the count, so this costs nothing extra; and it
        # reports the size of what is INDEXED, which is what the count next to it means. A folder
        # holding unindexed files would otherwise show a size that does not match its count, and
        # the difference is exactly what "Scan and index" exists to fix.
        size_bytes = 0
        try:
            catalog = json.loads(Path(kb.catalog).read_text(encoding="utf-8"))
            size_bytes = sum(int(r.get("size") or 0) for r in catalog.values()
                             if isinstance(r, dict))
        except Exception:  # noqa: BLE001 — a listing must not fail over one unreadable catalog
            size_bytes = 0
        out.append({
            "key": kb.key,
            "name": kb.display_name,
            "document_count": kb.document_count,
            "size_bytes": size_bytes,
            "folder": str(kb.folder),
            "root": str(kb.folder.parent),
        })
    return {"root": str(kb_root()), "bases": out}


@router.get("/documents")
async def list_documents(knowledge: str):
    """List a knowledge base's documents, from the filesystem catalog.

    This used to switch on STORAGE_MODE: in `db` mode it listed from `storage_objects` in
    Postgres instead, which made the database an alternative catalog — a documents folder copied
    onto the machine was then present and invisible. Knowledge is filesystem-only now, so the
    `.kvmeta` catalog is the only index, whatever the storage mode says.
    """
    store = KVStore(knowledge)
    docs = store.list_docs()
    # Sort newest first
    docs.sort(key=lambda d: d.created_at, reverse=True)
    return [
        KVDocumentResponse(
            id=d.id,
            name=d.original_filename,
            original_filename=d.original_filename,
            document_type=_doc_type_from_ext(d.original_filename),
            size=d.size,
            mime_type=d.mime_type,
            industry=d.industry,
            player=d.player,
            sub_category=d.sub_category,
            sub_department=d.sub_department,
            created_at=d.created_at,
            linked=d.linked,
            knowledge=d.kb or knowledge,
        )
        for d in docs
    ]


@router.post("/index-missing")
async def index_missing_files(knowledge: Optional[str] = None):
    """Give a record to every file already on disk under the knowledge root that has none.

    The catalog is the index and the folder is the content, so a file dropped in by hand — copied,
    restored, written by a script — is real and readable but unlisted: the document list is built
    from the catalog, so it cannot show what the catalog has never heard of. Measured on this
    install, that was 320 files against 1993 records, 55 MB of them with no indexed counterpart.

    Records are written IN PLACE. Nothing is copied and nothing is moved — `ingest-folder` calls
    `save_file()`, which would write a second, uuid-prefixed copy of every one of those files
    beside the original. This is the equivalent of `link` for files that are already inside the
    knowledge base.

    Deliberately NOT `linked`. These files live inside the knowledge base, so the knowledge base
    owns them and deleting one from the panel deletes it, exactly as for an uploaded document. A
    linked record would mean "the file is not ours, leave it alone", which is for paths outside
    the root.

    Idempotent: a file that already has a record is left alone, and running it twice adds nothing.
    `knowledge` may be omitted to sweep every knowledge base.
    """
    from services.kb_discovery import MANIFEST_NAME, discover, documents_dir, kv_dir

    targets = [knowledge] if knowledge else [kb.key for kb in discover()]
    reports = []
    for name in targets:
        # RESOLVED, because a record stores an ABSOLUTE storage_path while `documents_dir()` is
        # built from `kb_root()`, which is configured relative — "data/knowledge". Comparing a
        # relative walk path against absolute records never matches, so the "already has a record"
        # check silently fails and every file is indexed a second time, doubling the catalog.
        base = documents_dir(name).resolve()
        if not base.is_dir():
            reports.append({"knowledge": name, "indexed": 0, "already_indexed": 0,
                            "note": "no such folder"})
            continue

        store = KVStore(name)
        # Resolved through `_record_file`, so a record whose `key` is set matches the file it
        # actually refers to even if this root is not the one the record was written on. Matched on
        # the path rather than the name, because matching on the name would miss a file that was
        # renamed on disk and re-add its neighbour.
        known = {str(_record_file(d, name)) for d in store.list_docs()}

        fresh: List[DocRecord] = []
        already = 0
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.startswith(".") or path.name == MANIFEST_NAME:
                continue                       # the manifest is the base's own name, not a document
            if str(path) in known:
                already += 1
                continue

            # The folder a file sits in IS its hierarchy, positionally — the same shape the upload
            # paths write, so a swept file groups exactly like an uploaded one.
            parts = list(path.relative_to(base).parts[:-1])
            hierarchy = {key: (parts[i] if len(parts) > i else None)
                         for i, key in enumerate(_HIERARCHY)}
            try:
                stat = path.stat()
            except OSError:
                continue
            fresh.append(DocRecord(
                id=store.next_id(),
                kb=name,
                filename=path.name,
                # The writer's 8-hex collision prefix is a storage detail; the document's name is
                # what follows it.
                original_filename=_ON_DISK_PREFIX.sub("", path.name),
                size=stat.st_size,
                mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                storage_path=str(path),
                created_at=stat.st_mtime,
                **hierarchy,
            ))

        added = store.put_docs(fresh)

        # Empty folders, which this sweep is uniquely placed to notice: it has just walked every
        # one, so it knows which hold nothing. Deepest first, so a parent that becomes empty once
        # its children go is removed in the same pass rather than surviving to the next one.
        pruned: List[str] = []
        for path in sorted((p for p in base.rglob("*") if p.is_dir()),
                           key=lambda p: len(p.parts), reverse=True):
            if path.name.startswith("."):
                continue
            try:
                if not any(path.iterdir()):
                    path.rmdir()
                    pruned.append(str(path.relative_to(base)))
            except OSError:
                continue

        # A knowledge base whose folder holds nothing but its own manifest is an empty knowledge
        # base: it lists no documents and never will, because there is nothing to list. Removed
        # with its folder and catalog together — leaving either behind would strand it, and the
        # next discovery pass would see a catalog with no folder.
        documents_left = [p for p in base.rglob("*")
                          if p.is_file() and p.name != MANIFEST_NAME]
        if not documents_left:
            catalog = kv_dir(kb_root()) / f"{name}.json"
            try:
                if catalog.exists():
                    catalog.unlink()
                for leftover in base.rglob("*"):
                    if leftover.is_file():
                        leftover.unlink()
                base.rmdir()
            except OSError as exc:
                logger.warning("could not remove empty knowledge base %s: %s", name, exc)
            else:
                reports.append({"knowledge": name, "indexed": added, "already_indexed": already,
                                "removed": True,
                                "note": "empty knowledge base — folder and catalog removed"})
                logger.info("removed empty knowledge base %s", name)
                continue

        reports.append({"knowledge": name, "indexed": added, "already_indexed": already,
                        "empty_folders_removed": pruned})

    total = sum(r["indexed"] for r in reports)
    removed_bases = [r["knowledge"] for r in reports if r.get("removed")]
    removed_folders = sum(len(r.get("empty_folders_removed") or []) for r in reports)
    # Genuinely different outcomes, which one message would blur: files added, files all present
    # already, and a knowledge base with nothing in it. "No files on disk" is not "everything is
    # already indexed" — the first means the folder is empty, and saying otherwise sends someone
    # looking for a problem that is not there.
    seen = sum(r["indexed"] + r["already_indexed"] for r in reports)
    if total:
        message = f"Indexed {total} file(s) in place."
    elif seen:
        message = f"Nothing to do — all {seen} file(s) on disk already have a record."
    else:
        message = "No files on disk to index."
    if removed_folders:
        message += f" Removed {removed_folders} empty folder(s)."
    if removed_bases:
        message += f" Removed empty knowledge base(s): {', '.join(removed_bases)}."
    return {
        "success": True,
        "indexed": total,
        "scanned": seen,
        "removed_folders": removed_folders,
        "removed_bases": removed_bases,
        "bases": reports,
        "message": message,
    }


@router.post("/link", response_model=KVUploadResponse)
async def link_document(
    knowledge: str = Form(...),
    path: str = Form(...),
    metadata: Optional[str] = Form(None),
):
    """Add a document that stays where it is: record a path, copy nothing.

    The other way to add knowledge is `POST /upload`, which copies the file into this knowledge
    base so it travels with the folder. Linking is for documents that already live somewhere
    useful — a shared drive, a project directory, a data volume — and that would be wasteful or
    wrong to duplicate. The trade is that the knowledge base is no longer self-contained: if the
    file moves or the mount goes away, the record dangles, which is exactly what
    `doctor.sh` reports and `relocate_knowledge_paths.py` repairs.
    """
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="A file path is required")

    target = Path(os.path.expanduser(path.strip()))
    if not target.is_absolute():
        raise HTTPException(status_code=400,
                            detail="Use an absolute path — a relative one would mean different "
                                   "files depending on where the backend was started")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No such file: {target}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {target}")

    # Linking a file that is already inside this knowledge base would create a second record for
    # one document; upload is the honest way to add something the knowledge base already holds.
    store = KVStore(knowledge)
    docs_dir = documents_dir(knowledge)
    try:
        target.resolve().relative_to(docs_dir.resolve())
    except ValueError:
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail=f"That file is already inside this knowledge base ({docs_dir}). "
                   "Use upload for files here, or link a path outside it.",
        )

    for existing in store.list_docs():
        if not existing.linked and Path(existing.storage_path) == target:
            raise HTTPException(status_code=409, detail="That path is already linked here")

    doc_metadata: dict = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="metadata must be valid JSON")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot read {target}: {exc}")

    doc_id = store.next_id()
    store.put_doc(DocRecord(
        id=doc_id,
        kb=knowledge,
        filename=target.name,
        original_filename=target.name,
        size=size,
        mime_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        storage_path=str(target),
        linked=True,
        **_parse_hierarchy_from_metadata(doc_metadata),
    ))

    logger.info(f"Linked {target} into knowledge base {knowledge} as {doc_id}")
    return KVUploadResponse(
        id=doc_id,
        name=target.name,
        size=size,
        message="Linked. The file was not copied and will not be deleted with this record.",
    )


@router.post("/upload", response_model=KVUploadResponse)
async def upload_document(
    knowledge: str = Form(...),
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
):
    """Upload a single document into a knowledge base.

    The knowledge base is named by `knowledge` — its folder name under the knowledge root, which
    is what `GET /api/kv/bases` reports as `key`. Nothing here is looked up in a database: the
    name is a folder, and `documents_dir()` is the same resolver doc chat reads through, so the
    file lands exactly where a chat about this knowledge base will look for it.

    Metadata is optional JSON with hierarchy fields: industry, player, sub_category,
    sub_department.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    knowledge = (knowledge or "").strip()
    if not knowledge:
        raise HTTPException(
            status_code=400,
            detail="A knowledge base is required: pass knowledge=<folder name>",
        )

    # Parse optional metadata
    doc_metadata: dict = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning(f"Invalid metadata JSON: {metadata}")

    hierarchy = _parse_hierarchy_from_metadata(doc_metadata)
    content = await file.read()

    # Save to disk via file_storage (preserves hierarchy path). The id argument is unused because
    # a knowledge base supplies its own target directory: knowledge is not scoped to a project, so
    # there is no id to derive a default path from.
    storage_path = file_storage.save_file(
        None, file.filename, content,
        target_dir=documents_dir(knowledge),
        hierarchy={
            "industry": hierarchy["industry"],
            "player": hierarchy["player"],
            "sub_category": hierarchy["sub_category"],
            "sub_department": hierarchy["sub_department"],
        },
    )

    store = KVStore(knowledge)
    doc_id = store.next_id()
    doc = DocRecord(
        id=doc_id,
        kb=knowledge,
        filename=Path(file.filename).name,
        original_filename=file.filename,
        size=len(content),
        mime_type=mimetypes.guess_type(file.filename)[0] or "application/octet-stream",
        storage_path=storage_path,
        **hierarchy,  # industry, player, sub_category, sub_department
    )
    store.put_doc(doc)

    return KVUploadResponse(
        id=doc_id,
        name=file.filename,
        size=len(content),
        message="Uploaded successfully.",
    )


@router.post("/upload-bulk", response_model=List[KVUploadResponse])
async def upload_documents_bulk(
    knowledge: str = Form(...),
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    file_metadata: Optional[str] = Form(None),
):
    """Upload multiple files (supports folder upload with hierarchy).

    - `knowledge`: the knowledge base's folder name, resolved by `documents_dir()`.
    - `metadata`: shared JSON metadata for all files.
    - `file_metadata`: per-file JSON list matching `files` order. Each
      entry may contain: industry, player, sub_category, sub_department.
    """
    knowledge = (knowledge or "").strip()
    if not knowledge:
        raise HTTPException(
            status_code=400,
            detail="A knowledge base is required: pass knowledge=<folder name>",
        )

    # Parse metadata
    doc_metadata: dict = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning(f"Invalid metadata JSON: {metadata}")

    # Parse per-file metadata
    per_file_metadata: List[dict] = []
    if file_metadata:
        try:
            parsed = json.loads(file_metadata)
            if isinstance(parsed, list):
                per_file_metadata = [m if isinstance(m, dict) else {} for m in parsed]
        except json.JSONDecodeError:
            logger.warning(f"Invalid file_metadata JSON: {file_metadata}")

    store = KVStore(knowledge)
    results: List[KVUploadResponse] = []

    for idx, file in enumerate(files):
        try:
            if not file.filename:
                continue

            # Pick metadata for this file
            effective_meta = (
                per_file_metadata[idx]
                if idx < len(per_file_metadata)
                else doc_metadata
            )
            hierarchy = _parse_hierarchy_from_metadata(effective_meta)
            content = await file.read()

            # Save to disk
            storage_path = file_storage.save_file(
                None, file.filename, content,
                target_dir=documents_dir(knowledge),
                hierarchy={
                    "industry": hierarchy["industry"],
                    "player": hierarchy["player"],
                    "sub_category": hierarchy["sub_category"],
                    "sub_department": hierarchy["sub_department"],
                },
            )

            doc_id = store.next_id()
            doc = DocRecord(
                id=doc_id,
                kb=knowledge,
                filename=Path(file.filename).name,
                original_filename=file.filename,
                size=len(content),
                mime_type=mimetypes.guess_type(file.filename)[0] or "application/octet-stream",
                storage_path=storage_path,
                **hierarchy,
            )
            store.put_doc(doc)

            results.append(KVUploadResponse(
                id=doc_id,
                name=file.filename,
                size=len(content),
                message="Uploaded successfully.",
            ))
            logger.info(f"Uploaded {file.filename} -> {doc_id}")

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            results.append(KVUploadResponse(
                id="",
                name=file.filename or "unknown",
                size=0,
                message=f"Failed: {e}",
            ))

    return results


@router.post("/ingest-folder")
async def ingest_folder_from_path(request: Request):
    """Walk a folder on the server's disk and ingest all supported files.

    Body (JSON):
      {
        "knowledge":   str,   # knowledge base folder name to ingest into
        "folder_path": absolute path on the server
      }

    Returns counts of files ingested.
    """
    from datetime import datetime

    body = await request.json()
    knowledge = (body.get("knowledge") or "").strip()
    folder_path = body.get("folder_path")

    if not knowledge or not folder_path:
        raise HTTPException(
            status_code=400,
            detail="Both 'knowledge' and 'folder_path' are required",
        )

    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Folder not found on disk: {folder}",
        )

    # Supported extensions (mirrors doc_chat.py)
    text_exts = {
        ".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".xml",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css",
        ".sql", ".sh", ".bash", ".rb", ".go", ".rs", ".java", ".kt",
        ".swift", ".r", ".c", ".cpp", ".h", ".hpp",
    }

    store = KVStore(knowledge)
    ingested = 0
    failed = 0
    skipped = 0

    for fp in sorted(folder.rglob("*")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        if fp.suffix.lower() not in text_exts:
            skipped += 1
            continue

        try:
            content = fp.read_bytes()

            # Derive hierarchy from relative path inside folder
            rel = fp.relative_to(folder)
            parts = list(rel.parts[:-1])  # exclude filename
            hierarchy = {
                "industry": parts[0] if len(parts) >= 1 else None,
                "player": parts[1] if len(parts) >= 2 else None,
                "sub_category": parts[2] if len(parts) >= 3 else None,
                "sub_department": parts[3] if len(parts) >= 4 else None,
            }

            storage_path = file_storage.save_file(
                None, fp.name, content,
                target_dir=documents_dir(knowledge),
                hierarchy=hierarchy,
            )

            doc_id = store.next_id()
            doc = DocRecord(
                id=doc_id,
                kb=knowledge,
                filename=fp.name,
                original_filename=fp.name,
                size=len(content),
                mime_type=mimetypes.guess_type(str(fp))[0] or "text/plain",
                storage_path=storage_path,
                **hierarchy,
            )
            store.put_doc(doc)
            ingested += 1

        except Exception as e:
            logger.error(f"Failed to ingest {fp}: {e}")
            failed += 1

    return {
        "success": failed == 0,
        "knowledge": knowledge,
        "folder": str(folder),
        "files_ingested": ingested,
        "files_skipped": skipped,
        "files_failed": failed,
        "message": f"Ingested {ingested} file(s), skipped {skipped}, failed {failed}.",
    }


@router.post("/import")
async def import_folder_from_path(request: Request):
    """Make a folder already on this machine into a knowledge base under a chosen name.

    Body: ``{"path": "/abs/path/to/folder", "knowledge": "EBL_OS_docs", "dry_run": false}``

    The counterpart to uploading a folder from the browser: nothing is transferred, which is the
    point when the folder is already here. Files are COPIED into the knowledge root, so the source
    is untouched, and content already present is skipped by hash, so a repeat run adds nothing. A
    path inside the knowledge root is refused with the alternative named.
    """
    from services.kv_ingest import import_directory

    body = await request.json()
    source = (body.get("path") or "").strip()
    knowledge = (body.get("knowledge") or "").strip()
    if not source or not knowledge:
        raise HTTPException(status_code=400, detail="Both 'path' and 'knowledge' are required")

    report = await asyncio.to_thread(
        import_directory, source, knowledge, apply=not bool(body.get("dry_run")))
    return {
        "knowledge": report.knowledge,
        "ok": report.ok,
        "created": report.created_kb,
        "merged_into": report.merged_into,
        "written": len(report.written),
        "duplicates": len(report.duplicates),
        "unrecognised": list(report.unknown_types),
        "refused": [{"name": n, "reason": r} for n, r in report.refused],
        "warnings": list(report.warnings),
    }


@router.get("/legacy")
async def list_legacy_knowledge(path: Optional[str] = None):
    """Folders available to migrate, from the legacy root or from a path the user names.

    Reads the disk only. Nothing is moved, renamed or registered by looking. With no `path` this is
    the old per-project layout; with one it is whatever directory the user pointed at, which is what
    makes old data on another disk or in an unzipped archive reachable instead of invisible.

    Each candidate reports the absolute directory it came from, and whether a knowledge base already
    recorded it — so the panel can stop offering work that is done.
    """
    from services.kv_ingest import scan_source

    projects = await asyncio.to_thread(scan_source, path)
    # Reported so the panel can tell "you named a folder that is not there" from "there is nothing
    # left to migrate". Both come back as an empty list, and telling a user their migration is
    # complete when they mistyped a path is worse than saying nothing.
    path_ok = True
    if path:
        candidate = Path(path).expanduser()
        path_ok = candidate.is_dir()
    return {
        "projects": projects,
        "total_folders": sum(len(p["folders"]) for p in projects),
        "path": path or None,
        "path_ok": path_ok,
    }


@router.post("/migrate")
async def migrate_legacy_folders(request: Request):
    """Copy chosen folders into knowledge bases, under the names the user typed.

    Body: ``{"selections": [{"source": "/abs/dir", "knowledge": "华阳招聘"}]}``

    Each selection is one folder becoming one knowledge base. It copies, so the source is left
    exactly as it was; running it twice adds nothing, because content already present is skipped by
    hash. The group a folder belongs to is taken from its parent directory, which is what the
    provenance record keys on — so a folder migrated from anywhere is recognised again next time,
    and is not offered twice.
    """
    from services.kv_ingest import folder_fingerprint, import_directory, record_migration

    body = await request.json()
    selections = body.get("selections") or []
    if not selections:
        raise HTTPException(status_code=400, detail="No folders selected")

    results = []
    for item in selections:
        source = (item.get("source") or "").strip()
        folder = (item.get("folder") or Path(source).name).strip()
        group = (item.get("group") or Path(source).parent.name).strip()
        knowledge = (item.get("knowledge") or folder).strip()
        if not source or not knowledge:
            results.append({"source": source, "folder": folder, "knowledge": knowledge,
                            "ok": False, "error": "source and knowledge are required"})
            continue
        try:
            # In a thread: this reads and writes whole files, and a folder can hold a thousand.
            report = await asyncio.to_thread(import_directory, source, knowledge, apply=True)
        except (ValueError, OSError) as exc:
            results.append({"source": source, "folder": folder, "knowledge": knowledge,
                            "ok": False, "error": str(exc)})
            continue

        if report.ok:
            count, fingerprint = await asyncio.to_thread(folder_fingerprint, Path(source))
            await asyncio.to_thread(record_migration, report.knowledge, group, folder,
                                    count, fingerprint)

        results.append({
            "source": source, "folder": folder, "group": group,
            "knowledge": report.knowledge,
            "ok": report.ok,
            "created": report.created_kb,
            "merged_into": report.merged_into,
            "written": len(report.written),
            "duplicates": len(report.duplicates),
            "unrecognised": list(report.unknown_types),
            "refused": [{"name": n, "reason": r} for n, r in report.refused],
            "warnings": list(report.warnings),
        })

    return {
        "results": results,
        "written": sum(r.get("written", 0) for r in results),
        "duplicates": sum(r.get("duplicates", 0) for r in results),
    }


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, knowledge: str):
    """Delete a document from the KV store and its file from disk."""
    store = KVStore(knowledge)
    doc = store.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.linked:
        # The file is not ours. It was linked in place, so removing the knowledge record must
        # leave it exactly where it is — deleting it would destroy the user's own document.
        store.delete_doc(doc_id)
        logger.info(f"Unlinked document {doc_id}; file left in place: {_record_file(doc, knowledge)}")
        return {"message": "Unlinked. The file itself was left where it is."}

    # Delete file from disk
    try:
        file_storage.delete_file(str(_record_file(doc, knowledge)))
    except Exception as e:
        logger.warning(f"Failed to delete file from disk: {e}")

    store.delete_doc(doc_id)
    return {"message": "Document deleted."}


@router.get("/file")
async def get_file_by_path(knowledge: str, path: str, request: Request):
    """Serve a file under a knowledge base by its PATH, catalogued or not.

    The panel's folder tree is the filesystem, and a knowledge base can hold files nothing has
    indexed: a folder copied in by hand, a report written straight to disk. Opening one cannot go
    through the catalog, because the catalog is an index and this is the thing being indexed —
    `/documents/{id}/file` has no id to offer for a file that was never added. Measured here, that
    is most of them: 508 files on disk across the root against 238 with a record.

    `path` is relative to the knowledge base and is confined to it, so it cannot reach the rest of
    the disk.
    """
    root = documents_dir(knowledge).resolve()
    target = (root / path).resolve()
    try:
        # resolve() first, so a symlink pointing out of the knowledge base is refused too rather
        # than followed — the check has to be on where the path lands, not on how it is spelled.
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Path is outside the knowledge base")

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"No such file: {path}")

    try:
        content = target.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot read {path}: {exc}")

    mime, _ = mimetypes.guess_type(target.name)
    return _serve_file_bytes(content, target.name, mime, request.headers.get("range"))


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: str, knowledge: str, request: Request):
    """Serve the raw document file for inline viewing or download."""
    store = KVStore(knowledge)
    doc = store.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = _record_file(doc, knowledge)
    content = file_storage.read_bytes(file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found on disk")

    return _serve_file_bytes(content, doc.original_filename, doc.mime_type, request.headers.get("range"))


@router.get("/documents/{doc_id}/content")
async def get_document_content(doc_id: str, knowledge: str):
    """Return extracted text/markdown for inline viewing.

    Mirrors the RAG content endpoint (`/api/rag/documents/{id}/content`) for
    KV-store documents: binary Office formats (.docx via python-docx, .pptx
    via python-pptx, .xlsx via openpyxl) are parsed into text on the server
    so the Knowledge panel can render them inline instead of downloading.

    The response matches `DocumentContentResponse` (rag/schemas.py):
    {kind, content, rows, sheet_names, sheet_rows, truncated}.
    """
    from api.knowledge.rag.helpers import _extract_text_for_viewer

    store = KVStore(knowledge)
    doc = store.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = _record_file(doc, knowledge)
    content = file_storage.read_bytes(file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found on disk")
    ext = file_path.suffix.lower() or Path(doc.original_filename).suffix.lower()
    # The extractor reads from disk; a linked document may point at a path that has since gone
    # away, so materialise what we did manage to read when the original is not there.
    if file_path.exists():
        return _extract_text_for_viewer(file_path, ext)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return _extract_text_for_viewer(tmp_path, ext)
    finally:
        tmp_path.unlink(missing_ok=True)
