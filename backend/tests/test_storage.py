"""Unit tests for the StorageBackend implementations (Phase 1).

Both backends are exercised against a clean backend; the DB variant uses
an in-memory SQLite engine so no live Postgres is required.
"""
import pytest
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Phase 2 write-through (docs/system-architecture.md §15)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_mode(monkeypatch):
    """Force STORAGE_MODE=db and inject a sqlite-backed DbStorageBackend.

    Uses a StaticPool so the in-memory DB is shared across threads — the
    TestClient endpoint test runs the ASGI app in a worker thread.
    """
    from sqlalchemy.pool import StaticPool

    from config import settings
    from services import storage as storage_mod

    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    StorageObject.__table__.create(engine)
    backend = DbStorageBackend(session_factory=sessionmaker(bind=engine))

    monkeypatch.setattr(storage_mod, "_storage", backend)
    monkeypatch.setattr(settings, "storage_mode", "db")
    return backend


def test_filestorage_write_through_db_mode(db_mode, tmp_path):
    """FileStorage.save_file/delete_file mirror content to storage in db mode."""
    from services.file_storage import FileStorage

    fs = FileStorage(str(tmp_path / "documents"))
    saved = fs.save_file(1, "report.md", b"hello", hierarchy={"industry": "fin"})

    # On-disk copy still exists (operational store unchanged)...
    assert Path(saved).exists()
    # ...and the durable copy landed in storage_objects.
    keys = db_mode.list("documents/")
    assert len(keys) == 1
    assert keys[0].startswith("documents/project_1/fin/")
    assert keys[0].endswith("_report.md")
    assert db_mode.read(keys[0]) == b"hello"

    # Deleting the document also drops the storage copy.
    assert fs.delete_file(saved)
    assert db_mode.list("documents/") == []


def test_filestorage_read_through_db_mode(db_mode, tmp_path):
    """read_bytes serves storage_objects first in db mode, so documents
    survive even when the on-disk copy is lost (read-through survival)."""
    from services.file_storage import FileStorage

    fs = FileStorage(str(tmp_path / "documents"))
    saved = fs.save_file(1, "report.md", b"hello", hierarchy={"industry": "fin"})
    key = db_mode.list("documents/")[0]
    assert db_mode.read(key) == b"hello"

    # Disk copy disappears (e.g. evicted / never written)...
    Path(saved).unlink()
    assert not Path(saved).exists()

    # ...but the bytes still resolve from the durable storage copy.
    assert fs.read_bytes(Path(saved)) == b"hello"

    # delete_file cleans up the storage row even when the disk file is gone,
    # returning whether a disk file existed (False here).
    assert fs.delete_file(saved) is False
    assert db_mode.list("documents/") == []


def test_kv_endpoint_read_through_db_mode(db_mode, tmp_path, monkeypatch):
    """GET /api/kv/documents/{id}/file serves from storage_objects in db mode
    when the disk copy is missing (the Knowledge sidebar read path)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.knowledge import kv as kv_module
    from services.file_storage import FileStorage

    # Redirect the KV metadata dir and document base dir away from the repo.
    kv_meta = tmp_path / ".kvmeta"
    kv_meta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(kv_module, "KV_DATA_DIR", kv_meta)
    monkeypatch.setattr(FileStorage, "base_dir", property(lambda self: tmp_path))

    app = FastAPI()
    app.include_router(kv_module.router)
    client = TestClient(app)

    # Upload a document -> durable row created (write-through).
    resp = client.post(
        "/api/kv/upload",
        data={"project_id": "1"},
        files={"file": ("report.md", b"hello world", "text/markdown")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    keys = db_mode.list("documents/")
    assert len(keys) == 1
    assert db_mode.read(keys[0]) == b"hello world"

    # Lose the on-disk copy, as if the filesystem was evicted.
    doc = kv_module.KVStore(1).get_doc(doc_id)
    Path(doc.storage_path).unlink()
    assert not Path(doc.storage_path).exists()

    # The file endpoint still serves the bytes from storage_objects.
    resp = client.get(f"/api/kv/documents/{doc_id}/file", params={"project_id": 1})
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert "report.md" in resp.headers["content-disposition"]

    # Deleting the document drops the storage row too (no orphaned data).
    resp = client.delete(f"/api/kv/documents/{doc_id}", params={"project_id": 1})
    assert resp.status_code == 200
    assert db_mode.list("documents/") == []
    assert kv_module.KVStore(1).get_doc(doc_id) is None


def test_filestorage_local_mode_is_noop(db_mode, tmp_path, monkeypatch):
    """Default local mode keeps the old behavior: disk write, no storage row."""
    from config import settings
    from services.file_storage import FileStorage

    monkeypatch.setattr(settings, "storage_mode", "local")

    fs = FileStorage(str(tmp_path / "documents"))
    saved = fs.save_file(1, "report.md", b"hello")
    assert Path(saved).exists()
    assert db_mode.list("documents/") == []


def test_workspace_persist_output_db_mode(db_mode, tmp_path, monkeypatch):
    """WorkspaceManager.persist_output routes to storage in db mode, no-op in local."""
    from config import settings
    from services.workspace_manager import WorkspaceManager

    wm = WorkspaceManager(str(tmp_path / "outputs"))
    out = wm.get_task_workspace(1, 2, 3) / "report.txt"

    key = wm.persist_output(out, b"data")
    assert key == "outputs/project_1/workflow_2/task_3/report.txt"
    assert db_mode.read(key) == b"data"

    # Local mode: no-op, storage untouched.
    monkeypatch.setattr(settings, "storage_mode", "local")
    assert wm.persist_output(out, b"data") is None
    assert len(db_mode.list("outputs/")) == 1


def test_db_row_to_fs_write_through_db_mode(db_mode, tmp_path):
    """db_row_to_fs persists the SKILL.md body to storage in db mode."""
    from types import SimpleNamespace

    from core.skills.sync import db_row_to_fs

    row = SimpleNamespace(
        skill_id="hello", name="Hello", description="Demo",
        version="1.0.0", author="tester", tags=["x"], triggers=[],
        allowed_tools=[], required_context=None, examples=None,
        instructions="Say hi", source_path=None, source_type="builtin",
    )
    md = db_row_to_fs(row, skills_root=tmp_path / "skills")

    assert md.exists()
    content = db_mode.read("skills/builtin/hello/SKILL.md")
    assert content.startswith(b"---")
    assert b"Say hi" in content


def test_skill_storage_key_normalizes_source_type():
    """skill_storage_key canonicalizes str-mixin enums and dot paths."""
    from types import SimpleNamespace

    from core.skills.sync import skill_storage_key
    from models.skill import SkillSourceType

    row = lambda source_type: SimpleNamespace(skill_id="x", source_type=source_type)  # noqa: E731

    assert skill_storage_key(row("builtin")) == "skills/builtin/x/SKILL.md"
    assert skill_storage_key(row(SkillSourceType.PERSONAL)) == "skills/personal/x/SKILL.md"
    assert skill_storage_key(row("learning.phase5")) == "skills/phase5/x/SKILL.md"
    assert skill_storage_key(row(None)) == "skills/builtin/x/SKILL.md"
