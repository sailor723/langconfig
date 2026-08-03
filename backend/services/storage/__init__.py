# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Storage backend factory (docs/system-architecture.md §15).

Selects the physical backend from STORAGE_MODE (root .env / config.py):

- ``local`` -> LocalStorageBackend (disk, personal default)
- ``db``    -> DbStorageBackend   (Postgres BYTEA, enterprise)
- ``s3``    -> ObjectStorageBackend (object store, future)
"""
import logging
from typing import Optional

from .base import StorageBackend, StorageStat  # noqa: F401
from .local import LocalStorageBackend
from .db import DbStorageBackend
from .db_backend import DbBackend  # noqa: F401 - deepagents BackendProtocol adapter

logger = logging.getLogger(__name__)

_storage: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """Return the configured StorageBackend singleton (cached)."""
    global _storage
    if _storage is None:
        from config import settings
        mode = (settings.storage_mode or "local").lower()
        if mode == "db":
            _storage = DbStorageBackend()
            logger.info("StorageBackend: db (Postgres BYTEA)")
        elif mode == "s3":
            raise NotImplementedError(
                "STORAGE_MODE=s3 requires ObjectStorageBackend (future phase)"
            )
        else:
            _storage = LocalStorageBackend(settings.storage_base_dir or "./data/storage")
            logger.info(f"StorageBackend: local ({settings.storage_base_dir})")
    return _storage


def reset_storage() -> None:
    """Clear the cached instance (used by tests)."""
    global _storage
    _storage = None
