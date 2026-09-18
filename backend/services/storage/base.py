# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Storage backend abstraction (docs/system-architecture.md §15).

One object-addressed interface for every durable artifact writer:
FileStorage, WorkspaceManager, skills. Implementations:

- ``LocalStorageBackend`` - disk (personal / dev default)
- ``DbStorageBackend``   - Postgres BYTEA (enterprise, small payloads)
- ``ObjectStorageBackend`` - S3 / COS / OSS (enterprise, large blobs; future)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class StorageStat:
    """Size + type info for a stored object."""
    size_bytes: int
    mime_type: Optional[str] = None
    updated_at: Optional[datetime] = None


class StorageBackend(ABC):
    """Object-addressed durable storage.

    Keys are POSIX-like (``skills/foo/SKILL.md``). Implementations decide
    where the bytes physically live.
    """

    @abstractmethod
    def save(self, key: str, content: bytes, mime_type: Optional[str] = None) -> str:
        """Persist content under key (upsert). Returns the key."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Return content bytes. Raises KeyError if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether key has content."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove key. Returns True if something was removed."""

    @abstractmethod
    def list(self, prefix: str = "") -> List[str]:
        """List stored keys under an optional prefix."""

    @abstractmethod
    def stat(self, key: str) -> Optional[StorageStat]:
        """Return stat info for key, or None if missing."""
