# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
LocalStorageBackend - disk-backed implementation of StorageBackend.

Personal / dev default (STORAGE_MODE=local). Objects are files under a
base directory, with the key mirrored as the relative path. Keys are
sanitized to prevent path traversal.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .base import StorageBackend, StorageStat

logger = logging.getLogger(__name__)


def _sanitize_key(key: str) -> str:
    """Normalize a storage key into a safe relative path.

    Strips a leading '/', normalizes backslashes, and rejects empty
    segments / '..' to guard against path traversal.
    """
    key = key.replace("\\", "/").lstrip("/")
    parts = key.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe storage key: {key!r}")
    return key


class LocalStorageBackend(StorageBackend):
    """Stores objects as files under ``base_dir``, key mirrored as the path."""

    def __init__(self, base_dir: str):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalStorageBackend initialized at {self._base_dir}")

    def _path(self, key: str) -> Path:
        return self._base_dir / _sanitize_key(key)

    def save(self, key: str, content: bytes, mime_type: Optional[str] = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list(self, prefix: str = "") -> List[str]:
        root = self._base_dir if not prefix else self._path(prefix)
        if not root.exists():
            return []
        return [
            str(p.relative_to(self._base_dir))
            for p in root.rglob("*")
            if p.is_file()
        ]

    def stat(self, key: str) -> Optional[StorageStat]:
        path = self._path(key)
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return StorageStat(size_bytes=path.stat().st_size, updated_at=mtime)
