# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
File Storage Service

Handles persistence of uploaded documents to disk.
"""
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileStorage:
    """Manages file storage for uploaded documents."""

    def __init__(self, base_dir: str = None):
        """
        Initialize file storage.

        Args:
            base_dir: Base directory for document storage. Defaults to
                ./data/documents; the storage settings document
                (documents_base_dir, seeded from the old DOCUMENTS_BASE_DIR)
                wins at runtime via ``_resolve_documents_base_dir``.
        """
        if base_dir is None:
            base_dir = "./data/documents"
        self._default_base_dir = base_dir
        self._base_dir = None
        self._init_storage()
    
    def _init_storage(self):
        """Initialize storage directory from the settings documents (storage
        namespace → documents_base_dir; falls back to the .env default)."""
        base_dir = self._resolve_documents_base_dir()
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"File storage initialized at {self._base_dir.absolute()}")

    def _resolve_documents_base_dir(self) -> str:
        """Resolve the documents root from environment configuration — never from the database.

        This used to read `storage.documents_base_dir` out of the settings registry, on every
        access to `base_dir` (i.e. per request). Two consequences, both bad: the knowledge base
        could not be located with the database unreachable, and any settings document — inherited
        from a seed snapshot or a copied row — could silently repoint where documents are read
        from. The root is a filesystem fact, so it is resolved from the filesystem side.

        A divergence from the settings document is reported by `scripts/audit_local_data.py`
        rather than acted on here, so nothing in the request path reads the registry.
        """
        from services.kb_discovery import kb_root

        return str(kb_root(self._default_base_dir))

    @property
    def base_dir(self) -> Path:
        """Get current base directory, refreshing from settings if needed."""
        try:
            current_path = self._resolve_documents_base_dir()
            if str(self._base_dir) != current_path:
                self._base_dir = Path(current_path)
                self._base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return self._base_dir

    # ------------------------------------------------------------------
    # The knowledge base is filesystem-only, by decision.
    #
    # These two methods used to mirror every uploaded document into
    # `storage_objects` when STORAGE_MODE=db — a durable copy, but one that
    # made the database an alternative catalog: `api/knowledge/kv.py` then
    # LISTED from that table, so a documents folder copied onto the machine
    # was present and invisible. Knowledge now travels as files and nothing
    # else, and the storage mode cannot change that.
    #
    # `storage_objects` is still used for skills and agent outputs, which are
    # registry/workspace concerns rather than knowledge.
    # ------------------------------------------------------------------
    def _storage_key(self, file_path: Path) -> Optional[str]:
        """Unused for knowledge documents; kept for callers that still map a path to a key."""
        try:
            rel = Path(file_path).resolve().relative_to(self.base_dir.resolve())
        except ValueError:
            return None
        return f"documents/{rel.as_posix()}"

    # ------------------------------------------------------------------
    # Phase 3 read-through: in STORAGE_MODE=db the durable copy in
    # storage_objects is authoritative and the on-disk copy is only a
    # fallback, so documents survive even if the filesystem copy is lost.
    # Local mode (default) stays a plain disk read.
    # ------------------------------------------------------------------
    def read_bytes(self, file_path: Path) -> Optional[bytes]:
        """Read a document's bytes: storage-first in db mode, disk fallback.

        Returns None if the file is not on disk. There is no second place to look: knowledge
        documents are filesystem-only, so a copy of the documents directory is the whole knowledge
        base. (This used to prefer a `storage_objects` copy in db mode, which meant a mirror left
        over from an earlier mode could be served after the file itself was gone.)
        """
        try:
            return file_path.read_bytes()
        except FileNotFoundError:
            return None
    
    def save_file(self, project_id: int, filename: str, content: bytes,
                  hierarchy: dict = None) -> str:
        """
        Save uploaded file to disk.

        Args:
            project_id: Project identifier
            filename: Original filename — may be a relative path
                (e.g. "industry/player/file.md") when the browser sent
                a folder upload. Only the basename is used.
            content: File content bytes
            hierarchy: Optional {industry, player, sub_category,
                sub_department} dict. When provided, the file is
                written under
                project_<id>/<industry>/<player>/<sub_category>/
                <sub_department>/ so the on-disk path mirrors the
                source folder and the `_parse_hierarchy_from_path`
                fallback in rag.py can recover the bucket from disk.

        Returns:
            Absolute path to saved file
        """
        project_dir = self.base_dir / f"project_{project_id}"

        # Honor the hierarchy (when the UI / curl supplied it) by
        # mirroring the source folder layout on disk. This keeps the
        # the fallback _parse_hierarchy_from_path() in rag.py working
        # even if the form metadata was lost in transit.
        if hierarchy:
            for key in ("industry", "player", "sub_category", "sub_department"):
                segment = hierarchy.get(key)
                if segment and not str(segment).startswith("."):
                    # Each segment must be a single, safe path component:
                    # no separators, no traversal, no absolute paths.
                    # (a "../x" segment would start with "." and is already
                    # rejected above; a segment like "a/../../etc" or an
                    # absolute "/etc" would otherwise escape project_dir.)
                    segment = str(segment)
                    if (
                        "/" in segment
                        or "\\" in segment
                        or segment in (".", "..")
                        or segment != segment.strip()
                    ):
                        raise ValueError(
                            f"Unsafe hierarchy segment {segment!r} for {key!r}: "
                            "must be a plain folder name"
                        )
                    project_dir = project_dir / segment
        project_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename to avoid collisions. Use only the
        # basename — the directory part (if any) is encoded above in
        # the project_dir walk so we never end up with a path like
        # `<uuid>_<folder>/<file>` which pathlib would interpret as
        # `<uuid>_<folder>` being a directory.
        base = Path(filename).name
        # Skip hidden files (e.g. ".placeholder", ".DS_Store"). The
        # caller should filter these out, but this is a defensive
        # net so we never silently write a junk file.
        if base.startswith("."):
            raise ValueError(f"Refusing to save hidden file: {filename!r}")
        file_id = uuid.uuid4().hex[:8]
        safe_filename = f"{file_id}_{base}"
        file_path = project_dir / safe_filename

        # Write file. This is the only copy of it that exists: knowledge documents are
        # filesystem-only, deliberately, so a copy of the folder is a complete copy of the
        # knowledge base.
        file_path.write_bytes(content)
        logger.info(f"Saved file {base} to {file_path}")

        return str(file_path.absolute())
    
    def delete_file(self, file_path: str) -> bool:
        """
        Delete file from disk.
        
        Args:
            file_path: Path to file
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            path = Path(file_path)
            deleted = False
            if path.exists():
                path.unlink()
                deleted = True
            # Knowledge documents have no second copy to drop: the file was the only one.
            if deleted:
                logger.info(f"Deleted file {file_path}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False
    
    def get_project_storage_size(self, project_id: int) -> int:
        """
        Calculate total storage used by project.
        
        Args:
            project_id: Project identifier
            
        Returns:
            Total bytes used
        """
        project_dir = self.base_dir / f"project_{project_id}"
        if not project_dir.exists():
            return 0
        
        total_size = sum(f.stat().st_size for f in project_dir.rglob('*') if f.is_file())
        return total_size


# Global instance
file_storage = FileStorage()
