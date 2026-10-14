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


def test_filestorage_never_mirrors_to_storage(db_mode, tmp_path):
    """Even with STORAGE_MODE=db, a knowledge document is written ONLY to disk.

    This is the inverse of the write-through this file used to assert. The mirror made the
    database an alternative catalog, and `api/knowledge/kv.py` then listed from it — so a
    documents folder copied onto the machine was present and invisible. Knowledge is
    filesystem-only now: a copy of the directory is the whole knowledge base.
    """
    from services.file_storage import FileStorage

    fs = FileStorage(str(tmp_path / "documents"))
    saved = fs.save_file(1, "report.md", b"hello", hierarchy={"industry": "fin"})

    assert Path(saved).exists()
    assert Path(saved).read_bytes() == b"hello"
    assert db_mode.list("documents/") == []          # nothing was mirrored

    assert fs.delete_file(saved)
    assert db_mode.list("documents/") == []


def test_read_bytes_is_disk_only(db_mode, tmp_path):
    """A leftover storage_objects copy is never served, even in db mode.

    Documents written before this change may still have a mirror in Postgres. Reading it in
    preference to disk would serve a stale copy — including after the file itself was deleted —
    so the disk is the only place read_bytes looks.
    """
    from services.file_storage import FileStorage

    fs = FileStorage(str(tmp_path / "documents"))
    saved = fs.save_file(1, "report.md", b"hello", hierarchy={"industry": "fin"})
    key = fs._storage_key(Path(saved))

    # Simulate a mirror left behind by an older version of this codebase.
    db_mode.save(key, b"an older copy", "text/markdown")

    assert fs.read_bytes(Path(saved)) == b"hello"     # disk wins, not the mirror

    Path(saved).unlink()
    assert fs.read_bytes(Path(saved)) is None         # and a missing file is missing


def test_kv_endpoint_serves_from_disk_only(db_mode, tmp_path, monkeypatch):
    """GET /api/kv/documents/{id}/file serves the disk file, and a mirror is ignored."""
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

    resp = client.post(
        "/api/kv/upload",
        data={"project_id": "1"},
        files={"file": ("report.md", b"hello world", "text/markdown")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    assert db_mode.list("documents/") == []           # no durable row was created

    doc = kv_module.KVStore(1).get_doc(doc_id)
    assert Path(doc.storage_path).read_bytes() == b"hello world"

    resp = client.get(f"/api/kv/documents/{doc_id}/file", params={"project_id": 1})
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert "report.md" in resp.headers["content-disposition"]

    resp = client.delete(f"/api/kv/documents/{doc_id}", params={"project_id": 1})
    assert resp.status_code == 200
    assert kv_module.KVStore(1).get_doc(doc_id) is None
    assert not Path(doc.storage_path).exists()


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

    # Pin the project folder key so the assertion does not depend on live
    # project rows (slug logic is covered separately in test_vault_workspace.py).
    # get_task_workspace still exercises the real path-building flow:
    # outputs/<slug>/workflow_<id>/task_<id>/.
    monkeypatch.setattr(
        WorkspaceManager,
        "project_vault_key",
        staticmethod(lambda db, project_id: "my-project"),
    )

    wm = WorkspaceManager(str(tmp_path / "outputs"))
    out = wm.get_task_workspace(1, 2, 3) / "report.txt"

    key = wm.persist_output(out, b"data")
    # Key mirrors the on-disk path relative to the workspace base.
    assert key == "outputs/my-project/workflow_2/task_3/report.txt"
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


def test_kv_listing_is_filesystem_only_in_db_mode(db_mode, tmp_path, monkeypatch):
    """In db mode GET /api/kv/documents lists from .kvmeta, and storage_objects is ignored.

    Seeding the catalog from disk (rather than from Postgres keys) also exercises the media-type
    and RFC 5987 filename handling for non-ASCII names — the reported "garbled PDF" case — which
    must keep working now that the listing source has changed.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.knowledge import kv as kv_module
    from services.file_storage import FileStorage

    kv_meta = tmp_path / ".kvmeta"
    kv_meta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(kv_module, "KV_DATA_DIR", kv_meta)
    monkeypatch.setattr(FileStorage, "base_dir", property(lambda self: tmp_path))

    # A durable row with no file behind it. It must NOT appear in the listing: the filesystem is
    # the catalog, so a key in Postgres without a document on disk is not a document.
    db_mode.save("documents/project_1/orphan/no-file-anywhere.md", b"orphan", "text/markdown")

    app = FastAPI()
    app.include_router(kv_module.router)
    client = TestClient(app)

    # Upload through the real endpoint, then rename on disk to the non-ASCII names, keeping the
    # catalog in step: that is what a knowledge base on a real machine looks like.
    for name, body, mime in (
        ("report.md", b"hello world", "text/markdown"),
        ("\u62a5\u544a.pdf", b"%PDF-1.4 fake", "application/pdf"),
        ("\u6d4b\u8bd5.docx", b"PK fake", "application/octet-stream"),
    ):
        resp = client.post("/api/kv/upload", data={"project_id": "1"},
                           files={"file": (name, body, mime)})
        assert resp.status_code == 200

    resp = client.get("/api/kv/documents", params={"project_id": 1})
    assert resp.status_code == 200
    docs = {d["name"]: d for d in resp.json()}
    assert set(docs) == {"report.md", "\u62a5\u544a.pdf", "\u6d4b\u8bd5.docx"}
    assert "no-file-anywhere.md" not in docs
    assert docs["report.md"]["document_type"] == "markdown"
    assert docs["report.md"]["mime_type"] == "text/markdown"

    # PDF with non-ASCII name: proper content-type, inline disposition,
    # RFC 5987 encoded filename (no raw bytes in the header).
    pdf = docs["\u62a5\u544a.pdf"]
    resp = client.get(f"/api/kv/documents/{pdf['id']}/file", params={"project_id": 1})
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 fake"
    assert resp.headers["content-type"].startswith("application/pdf")
    cd = resp.headers["content-disposition"]
    assert "inline" in cd
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf" in cd

    # docx with non-ASCII name: correct office MIME, forced to attachment.
    docx = docs["\u6d4b\u8bd5.docx"]
    resp = client.get(f"/api/kv/documents/{docx['id']}/file", params={"project_id": 1})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in resp.headers["content-disposition"]

    # Deleting removes the disk file and the catalog entry, and leaves the orphan row alone.
    # (A fresh KVStore: the store caches its JSON file at construction.)
    pdf_path = Path(kv_module.KVStore(1).get_doc(pdf["id"]).storage_path)
    resp = client.delete(f"/api/kv/documents/{pdf['id']}", params={"project_id": 1})
    assert resp.status_code == 200
    assert not pdf_path.exists()
    assert db_mode.exists("documents/project_1/orphan/no-file-anywhere.md") is True


def test_kv_file_serves_range_requests(tmp_path, monkeypatch):
    """GET /api/kv/documents/{id}/file answers Range probes with 206 +
    Content-Range — Safari's PDF viewer requires this (it errors out when a
    Range request is answered with a plain 200 full-body response)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.knowledge import kv as kv_module
    from services.file_storage import FileStorage

    kv_meta = tmp_path / ".kvmeta"
    kv_meta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(kv_module, "KV_DATA_DIR", kv_meta)
    monkeypatch.setattr(FileStorage, "base_dir", property(lambda self: tmp_path))

    app = FastAPI()
    app.include_router(kv_module.router)
    client = TestClient(app)

    body = b"%PDF-1.4 fake body " * 40
    total = len(body)
    resp = client.post(
        "/api/kv/upload",
        data={"project_id": "1"},
        files={"file": ("report.pdf", body, "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    # Full response advertises range support.
    r = client.get(f"/api/kv/documents/{doc_id}/file", params={"project_id": 1})
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content == body

    # Safari-style probe range.
    r = client.get(
        f"/api/kv/documents/{doc_id}/file",
        params={"project_id": 1},
        headers={"Range": "bytes=0-1"},
    )
    assert r.status_code == 206
    assert r.content == b"%P"
    assert r.headers["content-range"] == f"bytes 0-1/{total}"

    # Suffix range (last N bytes).
    r = client.get(
        f"/api/kv/documents/{doc_id}/file",
        params={"project_id": 1},
        headers={"Range": "bytes=-8"},
    )
    assert r.status_code == 206
    assert r.content == body[-8:]
    assert r.headers["content-range"] == f"bytes {total - 8}-{total - 1}/{total}"

    # Un-satisfiable range -> 416 with an asterisk Content-Range.
    r = client.get(
        f"/api/kv/documents/{doc_id}/file",
        params={"project_id": 1},
        headers={"Range": "bytes=999999-"},
    )
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{total}"


def test_storage_mode_api_switches_and_persists(tmp_path, monkeypatch):
    """PUT /api/settings/storage-mode flips the runtime mode + resets the
    storage cache, and persists the choice; GET reports it."""
    from sqlalchemy.pool import StaticPool
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.system import settings as settings_api
    from config import settings as app_settings
    from db.database import get_db
    from models.settings import Settings as SettingsModel
    from services import storage as storage_mod

    # sqlite DB hosting the settings table + settings_documents, shared across
    # threads. The engine's ensure-table flag is process-global, so reset it and
    # create the documents table explicitly on this engine.
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SettingsModel.__table__.create(engine)
    from core.settings import SettingsDocument as _SettingsDocument
    from core import settings as _cs
    _cs._reset_table_ensure()  # noqa: SLF001 — test hook
    _SettingsDocument.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(settings_api.router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    # Normalize the ambient mode so assertions don't depend on .env.
    monkeypatch.setattr(app_settings, "storage_mode", "local")
    # Prove reset_storage() actually clears the cached backend.
    monkeypatch.setattr(storage_mod, "_storage", object())

    resp = client.get("/api/settings/storage-mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "local"
    assert body["source"] == "env"
    assert body["backend"] == "Local disk"

    resp = client.put("/api/settings/storage-mode", json={"mode": "db"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "db"
    assert body["source"] == "db"
    assert body["backend"] == "PostgreSQL (BYTEA)"
    # Runtime effects: process-wide setting mutated + cache cleared.
    assert app_settings.storage_mode == "db"
    assert storage_mod._storage is None
    # Persisted in the storage settings document (Phase 5 — no legacy column).
    from core.settings import get_document
    assert get_document(Session(), "storage")["mode"] == "db"

    resp = client.get("/api/settings/storage-mode")
    assert resp.json()["mode"] == "db"
    assert resp.json()["source"] == "db"

    # Invalid mode rejected.
    resp = client.put("/api/settings/storage-mode", json={"mode": "s3"})
    assert resp.status_code == 400
