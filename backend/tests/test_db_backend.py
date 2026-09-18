"""Unit tests for DbBackend — the deepagents BackendProtocol adapter (Phase 3).

Backed by an in-memory SQLite DbStorageBackend so no live Postgres is needed.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.storage_object import StorageObject
from services.storage.db import DbStorageBackend
from services.storage.db_backend import DbBackend


@pytest.fixture
def db_backend():
    """A DbBackend over an in-memory SQLite storage backend."""
    engine = create_engine("sqlite:///:memory:")
    StorageObject.__table__.create(engine)
    storage = DbStorageBackend(session_factory=sessionmaker(bind=engine))
    return DbBackend(storage)


@pytest.fixture
def seeded(db_backend):
    """Seed a small skills tree so ls/read/download have something to list."""
    for skill in ("hello", "web-search"):
        db_backend.write(
            f"/skills/builtin/{skill}/SKILL.md",
            f"---\nname: {skill}\n---\n## Instructions\n\nHow to use {skill}\n",
        )
    return db_backend


def _paths(ls_result):
    assert ls_result.error is None
    return [e["path"] for e in ls_result.entries]


def test_ls_discovers_nested_dirs(seeded):
    """ls derives virtual directories from the nested storage keys."""
    assert _paths(seeded.ls("/skills")) == ["/skills/builtin/"]
    assert _paths(seeded.ls("/skills/builtin")) == [
        "/skills/builtin/hello/",
        "/skills/builtin/web-search/",
    ]
    assert _paths(seeded.ls("/skills/builtin/hello")) == ["/skills/builtin/hello/SKILL.md"]


def test_ls_root_lists_namespaces(seeded):
    assert "/skills/" in _paths(seeded.ls("/"))


def test_read_roundtrip_and_missing(seeded):
    result = seeded.read("/skills/builtin/hello/SKILL.md", limit=1000)
    assert result.error is None
    assert "How to use hello" in result.file_data["content"]

    missing = seeded.read("/skills/nope/SKILL.md")
    assert missing.error is not None


def test_download_files(seeded):
    from deepagents.backends.protocol import FILE_NOT_FOUND

    responses = seeded.download_files([
        "/skills/builtin/hello/SKILL.md",
        "/skills/missing/SKILL.md",
    ])
    assert responses[0].error is None
    assert b"How to use hello" in responses[0].content
    assert responses[1].error == FILE_NOT_FOUND


def test_write_edit_delete_recursive(db_backend):
    assert db_backend.write("/out/a.txt", "one").error is None
    assert db_backend.write("/out/sub/b.txt", "two").error is None

    # Recursive delete of the /out directory removes every key beneath it.
    result = db_backend.delete("/out")
    assert result.error is None
    assert db_backend.ls("/out").entries == []


def test_edit_string_replacement(db_backend):
    db_backend.write("/out/a.txt", "hello world")
    edited = db_backend.edit("/out/a.txt", "world", "there")
    assert edited.error is None and edited.occurrences == 1
    assert "hello there" in db_backend.read("/out/a.txt", limit=1000).file_data["content"]

    # Unknown file surfaces a structured error, not a crash.
    assert db_backend.edit("/out/nope.txt", "x", "y").error is not None


def test_glob_supports_double_star(seeded):
    result = seeded.glob("**/SKILL.md")
    assert result.error is None
    assert len(result.matches) == 2
    assert all(m["path"].startswith("/skills/") for m in result.matches)


def test_grep_literal_with_max_count(seeded):
    result = seeded.grep("How to use", path="/skills", max_count=1)
    assert len(result.matches) == 1
    assert result.truncated is True


def test_path_traversal_rejected(db_backend):
    assert db_backend.ls("/../etc").error is not None
    assert db_backend.read("/skills/../secret").error is not None
    assert db_backend.write("/~/evil", "x").error is not None
    assert db_backend.delete("/..").error is not None


def test_storage_prefix_maps_composite_routed_paths():
    """DbBackend(storage_prefix='skills') re-attaches the namespace that
    CompositeBackend strips, so /skills/builtin/... keys round-trip."""
    engine = create_engine("sqlite:///:memory:")
    StorageObject.__table__.create(engine)
    storage = DbStorageBackend(session_factory=sessionmaker(bind=engine))
    backend = DbBackend(storage, storage_prefix="skills")

    assert backend.write("/builtin/hello/SKILL.md", "hi").error is None
    assert storage.read("skills/builtin/hello/SKILL.md") == b"hi"

    # ls returns paths without the prefix; the composite re-adds it.
    assert _paths(backend.ls("/builtin")) == ["/builtin/hello/"]
    assert backend.download_files(["/builtin/hello/SKILL.md"])[0].content == b"hi"
