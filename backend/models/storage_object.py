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
from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, BigInteger
from db.database import Base
import datetime


class StorageObject(Base):
    """Object-addressed blob row: unique key -> content bytes."""
    __tablename__ = "storage_objects"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(500), nullable=False, unique=True)
    content = Column(LargeBinary, nullable=False)  # BYTEA in Postgres
    size_bytes = Column(BigInteger, nullable=False, default=0)
    mime_type = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
