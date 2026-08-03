# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
StorageObject Model - durable artifact blobs for the StorageBackend seam.

Part of the "DB as the permanent store" strategy
(docs/system-architecture.md §15). Small payloads (skills, configs,
text outputs) live here as BYTEA; the ``key`` doubles as the object key
when an object store (S3 / COS / OSS) is used instead.
"""
import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, LargeBinary, String, func

from db.database import Base


def _utcnow() -> datetime.datetime:
    """Timezone-aware UTC now (datetime.utcnow is deprecated since Python 3.12)."""
    return datetime.datetime.now(datetime.timezone.utc)


class StorageObject(Base):
    """Object-addressed blob row: unique key -> content bytes."""
    __tablename__ = "storage_objects"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(500), nullable=False, unique=True)
    content = Column(LargeBinary, nullable=False)  # BYTEA in Postgres
    size_bytes = Column(BigInteger, nullable=False, default=0)
    mime_type = Column(String(100), nullable=True)
    # server_default matches migration 018; Python-side onupdate keeps
    # updated_at fresh on ORM writes (Postgres has no server ON UPDATE clause).
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=_utcnow,
    )
