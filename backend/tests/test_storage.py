"""Unit tests for the StorageBackend implementations (Phase 1).

Both backends are exercised against a clean backend; the DB variant uses
an in-memory SQLite engine so no live Postgres is required.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.storage.local import LocalStorageBackend
from services.storage.db import DbStorageBackend
from models.storage_object import StorageObject


@pytest.fixture
def local_backend(tmp_path):
    return LocalStorageBackend(str(tmp_path / "storage"))


@pytest.fixture
def db_backend():
    engine = create_engine("sqlite:///:memory:")
    # Only the storage_objects table is needed for these tests.
    StorageObject.__table__.create(engine)
    return DbStorageBackend(session_factory=sessionmaker(bind=engine))


def _roundtrip(backend):
    key = "skills/foo/SKILL.md"
    assert not backend.exists(key)
    backend.save(key, b"# Foo skill")
    assert backend.exists(key)
    assert backend.read(key) == b"# Foo skill"
    stat = backend.stat(key)
    assert stat is not None and stat.size_bytes == len(b"# Foo skill")
    assert key in backend.list("skills")
    assert backend.delete(key)
    assert not backend.exists(key)


def test_local_roundtrip(local_backend):
    _roundtrip(local_backend)


def test_db_roundtrip(db_backend):
    _roundtrip(db_backend)


def test_local_unsafe_key_rejected(local_backend):
    with pytest.raises(ValueError):
        local_backend.save("../escape.md", b"x")


def test_db_missing_key_raises(db_backend):
    with pytest.raises(KeyError):
        db_backend.read("nope.md")


def test_db_overwrite_keeps_single_row(db_backend):
    db_backend.save("a.md", b"v1")
    db_backend.save("a.md", b"v2")
    assert db_backend.read("a.md") == b"v2"
    assert db_backend.list() == ["a.md"]
