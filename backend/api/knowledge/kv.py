"""
Simple key-value document store — no Neo4j, no vector DB, no PostgreSQL.

Stores documents on disk via `file_storage` and tracks metadata in an
in-memory dict (persisted to a JSON file on the KV_DATA_DIR path).

Follows the same zero-dependency pattern as `doc_chat.py`.

Endpoints:
  GET    /api/kv/documents          — list documents for a project
  POST   /api/kv/upload             — upload a single file
  POST   /api/kv/upload-bulk        — upload multiple files (folder)
  POST   /api/kv/ingest-folder      — server-side folder walk
  DELETE /api/kv/documents/{id}     — delete a document
  GET    /api/kv/documents/{id}/file — serve raw file bytes
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.file_storage import file_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kv", tags=["kv"])

# ── KV data directory — where the metadata JSON lives ──────────────
KV_DATA_DIR = Path(file_storage.base_dir) / ".kvmeta"
KV_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── In-memory KV store with JSON file persistence ─────────────────

class DocRecord(BaseModel):
    """Minimal document record stored in the KV store."""
    id: str
    project_id: int
    filename: str
    original_filename: str
    size: int
    mime_type: Optional[str] = None
    storage_path: str  # absolute path on disk
    industry: Optional[str] = None
    player: Optional[str] = None
    sub_category: Optional[str] = None
    sub_department: Optional[str] = None
    created_at: float = Field(default_factory=time.time)  # epoch seconds


class KVStore:
    """
    Simple key-value store backed by a JSON file.

    Thread-safe for single-writer deployments. For multi-process,
    consider replacing with Redis or a file lock.
    """

    def __init__(self, project_id: int):
        self.project_id = project_id
        self._file = KV_DATA_DIR / f"project_{project_id}.json"
        self._data: Dict[str, Any] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────

    def _load(self) -> None:
        """Load metadata from JSON file if it exists."""
        if self._file.exists():
            try:
                raw = self._file.read_text(encoding="utf-8")
                self._data = json.loads(raw)
            except Exception as e:
                logger.warning(f"Failed to load KV store from {self._file}: {e}")
                self._data = {}

    def _save(self) -> None:
        """Persist metadata to JSON file."""
        try:
            self._file.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save KV store to {self._file}: {e}")

    # ── CRUD ───────────────────────────────────────────────────

    def list_docs(self) -> List[DocRecord]:
        """Return all documents for this project."""
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


# ── Response schemas ──────────────────────────────────────────────

class KVDocumentResponse(BaseModel):
    id: str
    project_id: int
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


class KVUploadResponse(BaseModel):
    id: str
    name: str
    size: int
    message: str


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/documents")
async def list_documents(project_id: int):
    """List all documents for a project."""
    store = KVStore(project_id)
    docs = store.list_docs()
    # Sort newest first
    docs.sort(key=lambda d: d.created_at, reverse=True)
    return [
        KVDocumentResponse(
            id=d.id,
            project_id=d.project_id,
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
        )
        for d in docs
    ]


@router.post("/upload", response_model=KVUploadResponse)
async def upload_document(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
):
    """Upload a single document. Metadata is optional JSON with
    hierarchy fields: industry, player, sub_category, sub_department."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Parse optional metadata
    doc_metadata: dict = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning(f"Invalid metadata JSON: {metadata}")

    hierarchy = _parse_hierarchy_from_metadata(doc_metadata)
    content = await file.read()

    # Save to disk via file_storage (preserves hierarchy path)
    storage_path = file_storage.save_file(
        project_id, file.filename, content,
        hierarchy={
            "industry": hierarchy["industry"],
            "player": hierarchy["player"],
            "sub_category": hierarchy["sub_category"],
            "sub_department": hierarchy["sub_department"],
        },
    )

    store = KVStore(project_id)
    doc_id = store.next_id()
    doc = DocRecord(
        id=doc_id,
        project_id=project_id,
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
    project_id: int = Form(...),
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    file_metadata: Optional[str] = Form(None),
):
    """Upload multiple files (supports folder upload with hierarchy).

    - `metadata`: shared JSON metadata for all files.
    - `file_metadata`: per-file JSON list matching `files` order. Each
      entry may contain: industry, player, sub_category, sub_department.
    """
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

    store = KVStore(project_id)
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
                project_id, file.filename, content,
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
                project_id=project_id,
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
        "project_id":  int,
        "folder_path": absolute path on the server
      }

    Returns counts of files ingested.
    """
    from datetime import datetime

    body = await request.json()
    project_id = body.get("project_id")
    folder_path = body.get("folder_path")

    if not project_id or not folder_path:
        raise HTTPException(
            status_code=400,
            detail="Both 'project_id' and 'folder_path' are required",
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

    store = KVStore(project_id)
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
                project_id, fp.name, content,
                hierarchy=hierarchy,
            )

            doc_id = store.next_id()
            doc = DocRecord(
                id=doc_id,
                project_id=project_id,
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
        "project_id": project_id,
        "folder": str(folder),
        "files_ingested": ingested,
        "files_skipped": skipped,
        "files_failed": failed,
        "message": f"Ingested {ingested} file(s), skipped {skipped}, failed {failed}.",
    }


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, project_id: int):
    """Delete a document from the KV store and its file from disk."""
    store = KVStore(project_id)
    doc = store.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file from disk
    try:
        file_storage.delete_file(doc.storage_path)
    except Exception as e:
        logger.warning(f"Failed to delete file from disk: {e}")

    store.delete_doc(doc_id)
    return {"message": "Document deleted."}


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: str, project_id: int):
    """Serve the raw document file for inline viewing or download."""
    store = KVStore(project_id)
    doc = store.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = Path(doc.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type = doc.mime_type or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=doc.original_filename,
        content_disposition_type="inline",
    )
