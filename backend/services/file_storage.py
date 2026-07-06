# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
File Storage Service

Handles persistence of uploaded documents to disk.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileStorage:
    """Manages file storage for uploaded documents."""
    
    def __init__(self, base_dir: str = "./data/documents"):
        """
        Initialize file storage.
        
        Args:
            base_dir: Base directory for document storage
        """
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
                    project_dir = project_dir / str(segment)
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
            if path.exists():
                path.unlink()
                logger.info(f"Deleted file {file_path}")
                return True
            return False
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
