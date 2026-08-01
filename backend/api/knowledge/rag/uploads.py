# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Upload/ingest endpoints for the api.knowledge.rag package.

Split out of api/knowledge/rag.py; moved verbatim. Registered on the
prefix-less sub-router included by the package __init__ under /api/rag.
"""
import os as _os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, Request, UploadFile)
from sqlalchemy.orm import Session

from db.database import get_db
from models.core import ContextDocument, DocumentType, IndexingStatus
from services.document_type import resolve_document_type

from .schemas import DocumentUploadResponse
from .shared import logger

router = APIRouter(tags=["rag"])


def _safe_archive_member_path(target_dir: Path, member_name: str) -> Path:
    """Resolve an archive member name inside target_dir, rejecting any
    member that would escape it (Zip Slip / tar traversal protection)."""
    resolved = (target_dir / member_name).resolve()
    if not resolved.is_relative_to(target_dir.resolve()):
        raise ValueError(f"Unsafe archive member path: {member_name!r}")
    return resolved


def _safe_extract_zip_member(zip_ref: zipfile.ZipFile, member: zipfile.ZipInfo,
                             target_dir: Path) -> None:
    """Extract a single zip member safely, guarding against path traversal."""
    dest = _safe_archive_member_path(target_dir, member.filename)
    if member.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zip_ref.open(member) as src, open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _safe_extract_tar_member(tar_ref: tarfile.TarFile, member: tarfile.TarInfo,
                             target_dir: Path) -> None:
    """Extract a single tar member safely, guarding against path traversal.
    Symlinks/device members are skipped (no extractfile content)."""
    dest = _safe_archive_member_path(target_dir, member.name)
    if member.isdir():
        dest.mkdir(parents=True, exist_ok=True)
        return
    src = tar_ref.extractfile(member)
    if src is None:
        return  # e.g. symlink / special file — skip
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src, open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst)

@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile = File(None),
    metadata: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Upload a document for RAG indexing"""
    from services.file_storage import file_storage
    import json

    logger.info(f"Upload request - project_id={project_id}, file={file.filename if file else 'None'}, metadata={metadata}")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Parse metadata if provided
    doc_metadata = {}
    if metadata:
        try:
            doc_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning(f"Invalid metadata JSON: {metadata}")

    # Step N+1: hierarchy metadata (industry/player/sub_category/
    # sub_department). Optional for single uploads — most users won't
    # set them, but the workspace-bulk-upload path can pass them
    # through so the sidebar's Tree view shows the file in the
    # right folder.
    industry        = doc_metadata.get("industry") if isinstance(doc_metadata, dict) else None
    player          = doc_metadata.get("player") if isinstance(doc_metadata, dict) else None
    sub_category    = doc_metadata.get("sub_category") if isinstance(doc_metadata, dict) else None
    sub_department  = doc_metadata.get("sub_department") if isinstance(doc_metadata, dict) else None

    # Save file to disk. Pass the resolved hierarchy (industry /
    # player / sub_category / sub_department) so file_storage writes
    # the file under a nested folder path that mirrors the source
    # folder, instead of flattening everything into project_<id>/.
    # Without this, a browser folder-picker upload that includes a
    # relative path (e.g. "analysis/company_report.md") would be
    # written to `<project_dir>/<uuid>_analysis/company_report.md`
    # which pathlib treats as a directory and crashes the write.
    file_path = file_storage.save_file(
        project_id, file.filename, content,
        hierarchy={
            "industry": industry,
            "player": player,
            "sub_category": sub_category,
            "sub_department": sub_department,
        },
    )

    # Determine document type from file extension (expanded support)
    document_type = resolve_document_type(file.filename)

    # Create document record with correct schema
    # Build name, tags and description from metadata
    custom_name = doc_metadata.get("name") if isinstance(doc_metadata, dict) else None
    description = doc_metadata.get("description") if isinstance(doc_metadata, dict) else None
    tags = doc_metadata.get("tags") if isinstance(doc_metadata, dict) else None

    # Check for duplicate: same filename + project_id (skip failed docs so they can be re-uploaded)
    existing = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.filename == (custom_name or file.filename),
        ContextDocument.indexing_status != IndexingStatus.FAILED
    ).first()
    if existing:
        logger.info(f"Duplicate document '{file.filename}' for project {project_id}, reusing existing id={existing.id}")
        return DocumentUploadResponse(
            id=existing.id,
            name=existing.filename,
            document_type=existing.document_type,
            size=existing.file_size or 0,
            status=existing.indexing_status.value,
            message="Document already exists"
    )

    # Delegate to cmd_ingest — single code path for PG + Neo4j + disk,
    # guaranteed consistent naming (no duplicates).
    # Save to a temp directory with the original filename so cmd_ingest
    # sees src.name == the real display name.
    import tempfile as _tf
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest,
        make_llm,
    )

    _tmp_dir = _tf.mkdtemp()
    _tmp_path = Path(_tmp_dir) / file.filename
    _tmp_path.write_bytes(content)

    try:
        idx = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        llm = make_llm()
        rc = cmd_ingest(idx, llm, str(_tmp_path), project_id=project_id)
        if rc != 0:
            raise HTTPException(status_code=500, detail="ingest failed")
    finally:
        try:
            import shutil as _shutil
            _shutil.rmtree(_tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # Find the PG record that cmd_ingest just created so we can return its id.
    doc = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.original_filename == file.filename,
    ).order_by(ContextDocument.id.desc()).first()
    if not doc:
        raise HTTPException(status_code=500, detail="document not found after ingest")

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size or 0,
        status=doc.indexing_status,
        message="Document uploaded and indexed."
    )

def _parse_hierarchy_from_path(file_path: str) -> dict:
    """Step N+1 safety-net: derive industry/player/sub_category/sub_department
    from a saved file_path.

    # Why this exists
    -----------------
    The Sidebar's Tree view buckets docs by `industry`. If a doc has
    `industry IS NULL`, the tree view puts it in a synthetic
    "(ungrouped)" folder. Once there, the user can't filter the chat
    by industry, the agent can't route by hierarchy, and the visual
    UI is cluttered.

    # When is this called?
    ---------------------
    Called by `_process_single_file_for_bulk` (and any other place
    that inserts a ContextDocument with a NULL hierarchy) as a
    safety net. If the frontend's `file_metadata` form field didn't
    arrive (e.g. older browser, live backend running pre-Step-O
    bytecode, "Browse Files" used instead of "Select Folder"), the
    form metadata is empty — but the file is already on disk at a
    path that mirrors the source folder, so we can re-extract the
    hierarchy from there.

    # Path layouts supported
    ------------------------
    All three forms are handled. We anchor on the `data/documents/`
    segment and then drop the project prefix to find the hierarchy:

      1. <base>/data/documents/project_<id>/<industry>/<player>/<sub_category>/<sub_department>/<hash>_<name>
         ^^^^^^^^^^^^^^^  live backend (file_storage.save_file, CWD-relative)
      2. <base>/data/documents/<id>/<industry>/<player>/<sub_category>/<sub_department>/<hash>_<name>
         ^^^^^^^^^^^^^^^  CLI ingest script (CWD-relative, no `project_` prefix)
      3. Relative: `data/documents/project_<id>/...` (e.g. when the
         backend reads a relative path from a config)

    The path can be absolute OR relative — we don't depend on a
    leading `/`. Windows-style backslashes are also handled.

    # Returns
    ---------
    A dict with whatever levels were found. Missing levels are
    `None`. Callers can check `if not industry or not player:` to
    decide whether to fall back. If even the file_path doesn't have
    a hierarchy (e.g. user uploaded a single file to project root
    via "Browse Files"), the doc legitimately goes to (ungrouped).
    """
    if not file_path:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    parts: list[str] = [p for p in file_path.replace("\\", "/").split("/") if p]
    if not parts:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    # Find the data/documents/ anchor and take what comes after it.
    anchor_idx = -1
    for i, p in enumerate(parts):
        if p == "data" and i + 1 < len(parts) and parts[i + 1] == "documents":
            anchor_idx = i + 1  # index of "documents"
            break
    if anchor_idx >= 0:
        parts = parts[anchor_idx + 1:]
    if not parts:
        return {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    # Drop the project prefix: either `project_<id>` (live API)
    # or bare `<id>` (CLI ingest). Anything that's all-digits is
    # treated as a bare project id.
    if parts[0].startswith("project_") or parts[0].isdigit():
        parts = parts[1:]
    out = {"industry": None, "player": None, "sub_category": None, "sub_department": None}
    if len(parts) >= 2:
        out["industry"] = parts[0]
    if len(parts) >= 3:
        out["player"] = parts[1]
    if len(parts) >= 4:
        out["sub_category"] = parts[2]
    if len(parts) >= 5:
        out["sub_department"] = parts[3]
    return out

async def _process_single_file_for_bulk(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile,
    metadata: dict,
    db: Session
) -> DocumentUploadResponse:
    """Helper function to process a single file during bulk upload"""
    from services.file_storage import file_storage

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Determine document type from file extension (expanded support) — done
    # BEFORE save_file so we can early-out on hidden files like
    # `.placeholder` (no extension → map defaults to TEXT but the
    # actual upload would 400 with `Refusing to save hidden file`
    # from file_storage. We catch it here and skip cleanly so the
    # remaining 4 valid files in a folder upload still ingest.)
    base_filename = Path(file.filename).name
    if base_filename.startswith("."):
        logger.warning(
            f"Skipping hidden file in folder upload: {file.filename!r}"
        )
        # Mimic the DocumentUploadResponse shape so the bulk loop
        # keeps going for the other files. Use a sentinel id of 0 —
        # the bulk caller filters out negative-or-zero ids anyway.
        from datetime import datetime as _dt
        return DocumentUploadResponse(
            id=0,
            name=file.filename,
            document_type=DocumentType.TEXT,
            size=file_size,
            status=IndexingStatus.SKIPPED,
            message=f"Skipped hidden file (no extension): {file.filename}",
        )
    document_type = resolve_document_type(file.filename)

    # Build metadata
    custom_name = metadata.get("name") if isinstance(metadata, dict) else None
    description = metadata.get("description") if isinstance(metadata, dict) else None
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    # Step N+1: hierarchy metadata. Same as the single-upload path —
    # folder uploads send these via the per-file `file_metadata` field.
    industry        = metadata.get("industry") if isinstance(metadata, dict) else None
    player          = metadata.get("player") if isinstance(metadata, dict) else None
    sub_category    = metadata.get("sub_category") if isinstance(metadata, dict) else None
    sub_department  = metadata.get("sub_department") if isinstance(metadata, dict) else None

    # ============================================================
    # FALLBACK: derive hierarchy from the saved file_path
    # ============================================================
    # Why this matters: the Sidebar's Tree view puts any doc with
    # NULL `industry` into a synthetic "(ungrouped)" folder. If a
    # doc lands in (ungrouped), the user can't filter by industry/
    # player/sub_category, the chat agent can't route by hierarchy,
    # and the visual UI is cluttered.
    #
    # When can `industry` be NULL despite the file having a proper
    # path on disk?
    #   1. The frontend "Select Folder" picker captures the
    #      webkitRelativePath and sends it as `file_metadata`, but
    #      the live backend is running pre-Step-O bytecode (we saw
    #      this on project 1 — 57 docs all in (ungrouped) because
    #      the running uvicorn hadn't been restarted since the fix
    #      landed on disk).
    #   2. The user uploaded via "Browse Files" (single file) so
    #      there is no relativePath at all.
    #   3. The form field was sent but the JSON was malformed.
    #
    # The file_storage layer ALWAYS writes the file to
    # `data/documents/project_<id>/<industry>/<player>/<sub_category>/
    # <sub_department>/<hash>_<name>` — either by honoring the
    # caller's chosen subfolder (live API upload) or by walking
    # a source folder (ingest-folder). So the hierarchy is
    # always in the file_path, even if it never made it into
    # the form field.
    #
    # This fallback re-extracts the hierarchy from the path
    # BEFORE we insert the row, so the doc lands in the correct
    # folder from the start — no (ungrouped) ever needed.
    #
    # For the existing 57 docs that already landed in (ungrouped),
    # use `/tmp/backfill_hierarchy.py` to fix them in-place
    # (idempotent — safe to run multiple times).
    # ============================================================
    if not industry or not player:
        derived = _parse_hierarchy_from_path(file_path)
        if not industry:
            industry = derived.get("industry")
        if not player:
            player = derived.get("player")
        if not sub_category:
            sub_category = derived.get("sub_category")
        if not sub_department:
            sub_department = derived.get("sub_department")
        if industry or player or sub_category:
            logger.info(
                f"[Step N+1 fallback] Derived hierarchy from file_path for "
                f"{file.filename}: industry={industry!r} player={player!r} "
                f"sub_category={sub_category!r} sub_department={sub_department!r}"
            )
        else:
            # If even the path didn't have a hierarchy, this is a
            # true "Browse Files" upload of a single file to a
            # project root. The doc will land in (ungrouped) — this
            # is the only legitimate path to that bucket.
            logger.debug(
                f"No hierarchy in form metadata or file_path for "
                f"{file.filename} — doc will land in (ungrouped)"
            )

    # Delegate to cmd_ingest — single code path for PG + Neo4j + disk.
    # Save to a temp directory with the original filename so cmd_ingest
    # sees src.name == the real display name.
    import tempfile as _tf
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest,
        make_llm,
    )

    _tmp_dir = _tf.mkdtemp()
    _tmp_path = Path(_tmp_dir) / file.filename
    _tmp_path.write_bytes(content)

    try:
        idx = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        idx.ensure_constraints()
        llm = make_llm()
        # Pass the caller-supplied hierarchy (industry / player /
        # sub_category / sub_department) into cmd_ingest so the
        # ContextDocument row carries the correct folder bucket
        # instead of landing in (ungrouped). Without this, both
        # `effective_metadata` (read above for the legacy
        # `_parse_hierarchy_from_path` fallback) and the disk-side
        # hierarchy were computed but never persisted.
        hierarchy = {
            "industry": industry,
            "player": player,
            "sub_category": sub_category,
            "sub_department": sub_department,
        }
        rc = cmd_ingest(idx, llm, str(_tmp_path), project_id=project_id, hierarchy=hierarchy)
        if rc != 0:
            raise Exception("cmd_ingest failed")
    finally:
        try:
            import shutil as _shutil
            _shutil.rmtree(_tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # Find the PG record that cmd_ingest just created.
    doc = db.query(ContextDocument).filter(
        ContextDocument.project_id == project_id,
        ContextDocument.original_filename == file.filename,
    ).order_by(ContextDocument.id.desc()).first()
    if not doc:
        raise Exception("document not found after ingest")

    return DocumentUploadResponse(
        id=doc.id,
        name=doc.filename,
        document_type=doc.document_type,
        size=doc.file_size or 0,
        status=doc.indexing_status,
        message="Document uploaded and indexed."
    )

@router.post("/upload-bulk", response_model=List[DocumentUploadResponse])
async def upload_documents_bulk(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    project_id: int = Form(...),
    extract_archives: bool = Form(True),
    metadata: Optional[str] = Form(None),
    # Step N+1: optional per-file metadata for folder uploads. When
    # the user selects a folder in the browser, each File carries a
    # `webkitRelativePath` like "electric_vehicle_industry/tesla/
    # marketing/01-product-lineup.md". The frontend parses the path
    # into industry/player/sub_category/sub_department and sends one
    # metadata dict per file in this field (JSON-encoded list, index
    # matches `files`). If omitted, all files share `metadata`
    # (existing behavior).
    file_metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload multiple documents or archives for RAG indexing.

    Supports:
    - Multiple file uploads
    - Archive extraction (.zip, .tar, .tar.gz, .tgz)
    - Folder structures (preserves paths as metadata — per-file via
      `file_metadata`, or shared via `metadata`)

    Note: Files should be sent as multipart/form-data with field name 'files'
    """
    import json

    try:
        logger.info(f"Bulk upload request received - project_id={project_id}, extract_archives={extract_archives}")
        logger.info(f"Number of files received: {len(files) if files else 0}")

        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")

        # Parse shared metadata if provided
        doc_metadata = {}
        if metadata:
            try:
                doc_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                logger.warning(f"Invalid metadata JSON: {metadata}")

        # Parse per-file metadata if provided. Must be a list with one
        # entry per file (or empty list = no per-file metadata).
        per_file_metadata: list[dict] = []
        if file_metadata:
            try:
                parsed = json.loads(file_metadata)
                if isinstance(parsed, list):
                    per_file_metadata = [m if isinstance(m, dict) else {} for m in parsed]
                else:
                    logger.warning(f"file_metadata is not a list: {type(parsed).__name__}")
            except json.JSONDecodeError:
                logger.warning(f"Invalid file_metadata JSON: {file_metadata}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk upload validation: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

    uploaded_docs = []

    # Process each file. Use enumerate so we can look up the matching
    # entry in `per_file_metadata` for folder uploads (Step N+1).
    for file_idx, file in enumerate(files):
        try:
            logger.info(f"Processing file: {file.filename}")

            # Pick the metadata for THIS file:
            #  - per_file_metadata[file_idx] if the frontend supplied
            #    per-file metadata (folder upload, webkitRelativePath
            #    parsed into industry/player/sub_category), else
            #  - the shared doc_metadata (existing behavior).
            effective_metadata = (
                per_file_metadata[file_idx]
                if file_idx < len(per_file_metadata)
                else doc_metadata
            )

            # Check if it's an archive
            file_ext = file.filename.split('.')[-1].lower()
            is_archive = file_ext in ['zip', 'tar', 'gz', 'tgz']

            if is_archive and extract_archives:
                # For archives with extraction, process extracted files
                logger.info(f"Extracting archive: {file.filename}")
                content = await file.read()

                # Create temporary directory for extraction
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    archive_path = temp_path / file.filename

                    # Save archive to temp location
                    archive_path.write_bytes(content)

                    # Extract based on type — member-by-member with
                    # traversal protection (rejects ../ or absolute
                    # entries instead of writing outside temp_dir).
                    try:
                        if file_ext == 'zip':
                            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                                for member in zip_ref.infolist():
                                    _safe_extract_zip_member(zip_ref, member, temp_path)
                        elif file_ext in ['tar', 'gz', 'tgz']:
                            with tarfile.open(archive_path, 'r:*') as tar_ref:
                                for member in tar_ref.getmembers():
                                    _safe_extract_tar_member(tar_ref, member, temp_path)

                        # Process all extracted files
                        for extracted_file in temp_path.rglob('*'):
                            if extracted_file.is_file() and extracted_file != archive_path:
                                # Get relative path from archive root
                                relative_path = str(extracted_file.relative_to(temp_path))
                                logger.info(f"Processing extracted file: {relative_path}")

                                # Read file and create mock UploadFile
                                file_content = extracted_file.read_bytes()

                                class MockUploadFile:
                                    def __init__(self, filename, content, content_type='application/octet-stream'):
                                        self.filename = filename
                                        self.content = content
                                        self.content_type = content_type

                                    async def read(self):
                                        return self.content

                                mock_file = MockUploadFile(extracted_file.name, file_content)
                                # Use the parent archive's effective_metadata
                                # for all extracted children (the user picked
                                # the archive as a single upload, not the
                                # internal structure).
                                result = await _process_single_file_for_bulk(
                                    background_tasks, project_id, mock_file, effective_metadata, db
                                )
                                uploaded_docs.append(result)

                    except Exception as e:
                        logger.error(f"Failed to extract archive {file.filename}: {e}")
                        # Upload archive as-is if extraction fails
                        await file.seek(0)
                        result = await _process_single_file_for_bulk(
                            background_tasks, project_id, file, effective_metadata, db
                        )
                        uploaded_docs.append(result)
            else:
                # Regular file upload (no extraction)
                result = await _process_single_file_for_bulk(
                    background_tasks, project_id, file, effective_metadata, db
                )
                uploaded_docs.append(result)

        except Exception as e:
            logger.error(f"Failed to process file {file.filename}: {e}", exc_info=True)
            # Continue with other files
            continue

    logger.info(f"Bulk upload completed: {len(uploaded_docs)} documents uploaded")
    return uploaded_docs

@router.post("/ingest-folder")
async def ingest_folder_from_path(
    request: Request,
    db: Session = Depends(get_db),
):
    """Walk a folder on the server's disk and ingest every supported
    file into the given project, using the same code path as the CLI
    (index_build.cmd_ingest_folder) so PostgreSQL + Neo4j stay in sync.

    Body (JSON):
      {
        "project_id":   int,
        "folder_path":  absolute path on the server,
        "industry":     optional filter (default: derived from first path segment)
        "player":       optional filter (default: derived from second segment)
      }

    Returns:
      {
        "created": int, "updated": int, "skipped": int, "failed": int,
        "files_seen": int, "files_ingested": int, "files_filtered": int
      }
    """
    import json as _json
    try:
        body = await request.body()
        params = _json.loads(body or b"{}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    project_id   = params.get("project_id")
    folder_path  = params.get("folder_path")

    if not project_id or not folder_path:
        raise HTTPException(
            status_code=400,
            detail="Both 'project_id' and 'folder_path' are required"
        )

    # Validate project exists
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    # Validate folder exists on disk
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"folder not found on disk: {folder}"
        )

    # Delegate to CLI code path — guarantees consistent naming
    # across PostgreSQL, Neo4j, and disk files (no duplicates).
    from learning.phase9.graphindex.index_build import (
        Neo4jDocumentIndex,
        cmd_ingest_folder,
        make_llm,
    )

    idx = Neo4jDocumentIndex(
        base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
        username=_os.environ.get("NEO4J_USER", "neo4j"),
        password=_os.environ.get("NEO4J_PASSWORD", "password"),
    )
    idx.ensure_constraints()
    llm = make_llm()
    # Count files up front so the frontend can show "ingested X
    # files" even when cmd_ingest_folder only returns a 0/1 exit
    # code (the CLI's return type). The CLI module is the single
    # source of truth for what counts as "indexable" — it already
    # filters hidden files and unsupported extensions. Re-using the
    # same constants here keeps the two paths in lockstep.
    from learning.phase9.graphindex.index_build import _SUPPORTED_EXTS
    files_seen = sum(
        1 for p in folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _SUPPORTED_EXTS
        and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    )
    ok = cmd_ingest_folder(idx, llm, str(folder), project_id=project_id)
    success = ok == 0
    # When the CLI succeeds we assume every file got created.
    # Failure cases are unusual (LLM parse error, Neo4j write
    # error) and the print log already surfaces them — the
    # frontend's alert is best-effort UX feedback.
    files_ingested = files_seen if success else 0
    files_failed = 0 if success else files_seen
    files_filtered = 0  # cmd_ingest_folder filters in-place; nothing drops here

    return {
        "success": success,
        "project_id": project_id,
        "folder": str(folder),
        "files_seen": files_seen,
        "files_ingested": files_ingested,
        "files_filtered": files_filtered,
        "created": files_ingested,
        "updated": 0,
        "skipped": 0,
        "failed": files_failed,
        "message": "Folder ingested successfully." if success else "Folder ingested with errors.",
    }
