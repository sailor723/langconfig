# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DbStorageBackend - Postgres-backed implementation of StorageBackend.

Enterprise mode (STORAGE_MODE=db): blobs live in the ``storage_objects``
table (BYTEA). Skills, configs, and text outputs are the sweet spot;
large blobs should use object storage (S3 / COS / OSS) instead.
"""
import logging
from typing import Callable, List, Optional

from .base import StorageBackend, StorageStat

logger = logging.getLogger(__name__)


class DbStorageBackend(StorageBackend):
    """Object-addressed blobs in Postgres (storage_objects table)."""

    def __init__(self, session_factory: Optional[Callable] = None):
        # Lazy import so the package can be imported without a live DB.
        from db.database import SessionLocal
        self._session_factory = session_factory or SessionLocal

    def _session(self):
        return self._session_factory()

    def save(self, key: str, content: bytes, mime_type: Optional[str] = None) -> str:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            obj = db.query(StorageObject).filter(StorageObject.key == key).first()
            if obj is None:
                obj = StorageObject(key=key)
                db.add(obj)
            obj.content = content
            obj.size_bytes = len(content)
            if mime_type is not None:
                obj.mime_type = mime_type
            db.commit()
            return key
        finally:
            db.close()

    def read(self, key: str) -> bytes:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            obj = db.query(StorageObject).filter(StorageObject.key == key).first()
            if obj is None:
                raise KeyError(key)
            return bytes(obj.content)
        finally:
            db.close()

    def exists(self, key: str) -> bool:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            return db.query(StorageObject.id).filter(StorageObject.key == key).first() is not None
        finally:
            db.close()

    def delete(self, key: str) -> bool:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            obj = db.query(StorageObject).filter(StorageObject.key == key).first()
            if obj is None:
                return False
            db.delete(obj)
            db.commit()
            return True
        finally:
            db.close()

    def list(self, prefix: str = "") -> List[str]:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            q = db.query(StorageObject.key)
            if prefix:
                q = q.filter(StorageObject.key.like(f"{prefix}%"))
            return [row[0] for row in q.all()]
        finally:
            db.close()

    def stat(self, key: str) -> Optional[StorageStat]:
        from models.storage_object import StorageObject
        db = self._session()
        try:
            obj = db.query(StorageObject).filter(StorageObject.key == key).first()
            if obj is None:
                return None
            return StorageStat(
                size_bytes=obj.size_bytes,
                mime_type=obj.mime_type,
                updated_at=obj.updated_at,
            )
        finally:
            db.close()
