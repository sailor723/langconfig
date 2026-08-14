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
                config.documents_base_dir (DOCUMENTS_BASE_DIR in the root
                .env, else ./data/documents); a DB settings.storage_path
                override wins at runtime.
        """
        if base_dir is None:
            try:
                from config import settings
                base_dir = getattr(settings, "documents_base_dir", None) or "./data/documents"
            except Exception:
                base_dir = "./data/documents"
        self._default_base_dir = base_dir
        self._base_dir = None
        self._init_storage()
    
    def _init_storage(self):
        """Initialize storage directory from settings."""
        try:
            from api.system.settings import _settings
            base_dir = _settings.get("storage_path", self._default_base_dir)
        except:
            base_dir = self._default_base_dir
        
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"File storage initialized at {self._base_dir.absolute()}")
    
    @property
    def base_dir(self) -> Path:
        """Get current base directory, refreshing from settings if needed."""
        try:
            from api.system.settings import _settings
            current_path = _settings.get("storage_path", self._default_base_dir)
            if str(self._base_dir) != current_path:
                self._base_dir = Path(current_path)
                self._base_dir.mkdir(parents=True, exist_ok=True)
        except:
            pass
        return self._base_dir

    # ------------------------------------------------------------------
    # Phase 2 write-through (docs/system-architecture.md §15):
    # when STORAGE_MODE=db each uploaded document is also persisted to
    # the storage backend (storage_objects) under `documents/<rel-path>`.
    # The on-disk copy stays the operational store for the RAG pipeline,
    # so local mode (default) is a no-op and behavior is unchanged.
    # ------------------------------------------------------------------
    def _storage_key(self, file_path: Path) -> Optional[str]:
        """Map an on-disk document path to its storage key, or None if the
        file lives outside the documents base dir."""
        try:
            rel = Path(file_path).resolve().relative_to(self.base_dir.resolve())
        except ValueError:
            return None
        return f"documents/{rel.as_posix()}"

    def _persist(self, file_path: Path, content: bytes) -> None:
        """Write-through: store a durable copy in storage when STORAGE_MODE=db."""
        from config import settings
        if settings.storage_mode != "db":
            return
        key = self._storage_key(file_path)
        if key is None:
            return
        try:
            from services.storage import get_storage
            mime, _ = mimetypes.guess_type(file_path.name)
            get_storage().save(key, content, mime)
        except Exception as e:
            logger.warning(f"Failed to persist storage copy {key}: {e}")

    def _unpersist(self, file_path: Path) -> None:
        """Best-effort delete of the durable storage copy when STORAGE_MODE=db."""
        from config import settings
        if settings.storage_mode != "db":
            return
        key = self._storage_key(file_path)
        if key is None:
            return
        try:
            from services.storage import get_storage
            get_storage().delete(key)
        except Exception as e:
            logger.warning(f"Failed to delete storage copy {key}: {e}")

    # ------------------------------------------------------------------
    # Phase 3 read-through: in STORAGE_MODE=db the durable copy in
    # storage_objects is authoritative and the on-disk copy is only a
    # fallback, so documents survive even if the filesystem copy is lost.
    # Local mode (default) stays a plain disk read.
    # ------------------------------------------------------------------
    def read_bytes(self, file_path: Path) -> Optional[bytes]:
        """Read a document's bytes: storage-first in db mode, disk fallback.

        Returns None if the document exists in neither place.
        """
        from config import settings
        if settings.storage_mode == "db":
            key = self._storage_key(file_path)
            if key is not None:
                try:
                    from services.storage import get_storage
                    return get_storage().read(key)
                except KeyError:
                    pass  # not in storage yet — fall back to the disk copy
                except Exception as e:
                    logger.warning(f"Failed to read storage copy {key}: {e}")
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

        # Write file
        file_path.write_bytes(content)
        # Phase 2: durable copy in storage_objects when STORAGE_MODE=db.
        self._persist(file_path, content)
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
            # Phase 3: drop the durable storage copy even when the disk copy
            # is already gone (read-through survival case) — best-effort.
            self._unpersist(path)
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
