# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the DSH-style settings wire API (api/system/settings_documents.py).

The router is mounted on a minimal TestClient app with ``get_db`` overridden
to the PostgreSQL test database (langconfig_test) — the dev database is never
touched. The settings_documents table is created/truncated by the fixtures.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from api.system.settings_documents import router as settings_documents_router
from core import settings as cs
from db.database import get_db

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test",
)
SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

Session = sessionmaker(
    bind=create_engine(SYNC_URL, pool_pre_ping=True),
    autoflush=False,
    expire_on_commit=False,
)


def _override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(settings_documents_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_documents():
    cs._reset_table_ensure()  # noqa: SLF001 — test hook
    db = Session()
    try:
        cs.ensure_table(db)
        cs.reset_documents(db)
        # The test DB is create_all-only (migrations not replayable), so the
        # legacy settings table may predate the setup_complete column — bring
        # it in line with the ORM model exactly as alembic 026 does.
        db.execute(text(
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
            "setup_complete BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        db.commit()
    finally:
        db.close()
    yield
    db = Session()
    try:
        cs.reset_documents(db)
    finally:
        db.close()


# ── describe ─────────────────────────────────────────────────────────────────

def test_describe_returns_all_namespaces(client):
    res = client.get("/api/settings/describe")
    assert res.status_code == 200
    body = res.json()
    assert body["writable"] is True
    namespaces = body["namespaces"]
    assert [ns["ns"] for ns in namespaces] == cs.namespaces()
    for ns in namespaces:
        assert "schema" in ns and "properties" in ns["schema"]
        assert "value" in ns and isinstance(ns["value"], dict)
        assert "user" in ns and isinstance(ns["user"], dict)
        assert ns["revision"] == 0
        assert "secrets" in ns and isinstance(ns["secrets"], list)


def test_describe_redacts_secrets_even_when_unset(client):
    body = client.get("/api/settings/describe").json()
    models = next(ns for ns in body["namespaces"] if ns["ns"] == "models")
    assert "openai_api_key" not in models["value"]["api_keys"]
    paths = {tuple(s["path"]) for s in models["secrets"]}
    assert ("api_keys", "openai_api_key") in paths
    assert ("local_api_key") in {p[-1] if len(p) == 1 else None for p in paths}


# ── mutate ───────────────────────────────────────────────────────────────────

def test_mutate_set_and_describe_reflects(client):
    res = client.post("/api/settings/mutate", json={
        "ns": "models",
        "ops": [{"op": "set", "path": ["default_model"], "value": "gpt-4o"}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["revision"] == 1
    assert body["value"]["default_model"] == "gpt-4o"

    described = client.get("/api/settings/describe").json()
    models = next(ns for ns in described["namespaces"] if ns["ns"] == "models")
    assert models["revision"] == 1
    assert models["value"]["default_model"] == "gpt-4o"
    assert models["user"] == {"default_model": "gpt-4o"}


def test_mutate_conflict_returns_409(client):
    first = client.post("/api/settings/mutate", json={
        "ns": "models", "ops": [{"op": "set", "path": ["max_tokens"], "value": 1000}],
    })
    assert first.status_code == 200
    assert first.json()["revision"] == 1

    stale = client.post("/api/settings/mutate", json={
        "ns": "models",
        "ops": [{"op": "set", "path": ["max_tokens"], "value": 2000}],
        "expected_revision": 0,
    })
    assert stale.status_code == 409
    assert "revision" in stale.json()["detail"]

    fresh = client.post("/api/settings/mutate", json={
        "ns": "models",
        "ops": [{"op": "set", "path": ["max_tokens"], "value": 2000}],
        "expected_revision": 1,
    })
    assert fresh.status_code == 200
    assert fresh.json()["revision"] == 2


def test_mutate_unset(client):
    client.post("/api/settings/mutate", json={
        "ns": "workspace", "ops": [{"op": "set", "path": ["workspace_path"], "value": "/tmp/x"}],
    })
    res = client.post("/api/settings/mutate", json={
        "ns": "workspace", "ops": [{"op": "unset", "path": ["workspace_path"]}],
    })
    assert res.status_code == 200
    assert res.json()["value"] == {}  # sparse stored section
    # resolved view restores the schema default
    described = client.get("/api/settings/describe").json()
    workspace = next(ns for ns in described["namespaces"] if ns["ns"] == "workspace")
    assert workspace["value"]["workspace_path"] == ""


def test_mutate_unknown_namespace_404(client):
    res = client.post("/api/settings/mutate", json={
        "ns": "no-such-ns", "ops": [{"op": "set", "path": ["x"], "value": 1}],
    })
    assert res.status_code == 404


def test_doc_chat_limits_round_trip_over_the_wire(client):
    """The Doc Chat limits are settable through the API the Settings panel calls.

    This is the layer the UI actually uses (`mutateSettings({ns:'knowledge', ops})`), so a field
    that the schema knows but the wire API rejects would only surface when someone pressed Save.
    """
    res = client.post("/api/settings/mutate", json={
        "ns": "knowledge",
        "ops": [
            {"op": "set", "path": ["doc_chat_max_files"], "value": 40},
            {"op": "set", "path": ["doc_chat_max_context_chars"], "value": 400_000},
        ],
    })
    assert res.status_code == 200, res.text

    described = client.get("/api/settings/describe").json()
    knowledge = next(ns for ns in described["namespaces"] if ns["ns"] == "knowledge")
    assert knowledge["value"]["doc_chat_max_files"] == 40
    assert knowledge["value"]["doc_chat_max_context_chars"] == 400_000

    # Unset returns each field to the built-in default doc chat falls back to.
    res = client.post("/api/settings/mutate", json={
        "ns": "knowledge",
        "ops": [
            {"op": "unset", "path": ["doc_chat_max_files"]},
            {"op": "unset", "path": ["doc_chat_max_context_chars"]},
        ],
    })
    assert res.status_code == 200, res.text
    described = client.get("/api/settings/describe").json()
    knowledge = next(ns for ns in described["namespaces"] if ns["ns"] == "knowledge")
    assert knowledge["value"]["doc_chat_max_files"] is None
    assert knowledge["value"]["doc_chat_max_context_chars"] is None


def test_doc_chat_limits_reject_out_of_range_values_over_the_wire(client):
    """`0 files per answer` must be refused at the API, not stored and acted on."""
    for field, bad in (("doc_chat_max_files", 0), ("doc_chat_max_context_chars", 5)):
        res = client.post("/api/settings/mutate", json={
            "ns": "knowledge", "ops": [{"op": "set", "path": [field], "value": bad}],
        })
        assert res.status_code == 422, f"{field}={bad} should be refused, got {res.status_code}"


def test_mutate_schema_invalid_422(client):
    res = client.post("/api/settings/mutate", json={
        "ns": "general", "ops": [{"op": "set", "path": ["no_such_field"], "value": 1}],
    })
    assert res.status_code == 422


def test_mutate_bad_op_shape_422(client):
    res = client.post("/api/settings/mutate", json={
        "ns": "models", "ops": [{"op": "explode", "path": ["x"]}],
    })
    assert res.status_code == 422  # Literal['set','unset'] rejects at request schema


def test_mutate_secret_redacted_in_response(client):
    res = client.post("/api/settings/mutate", json={
        "ns": "models",
        "ops": [{"op": "set", "path": ["api_keys", "openai_api_key"], "value": "sk-wire-secret"}],
    })
    assert res.status_code == 200
    body = res.json()
    assert "openai_api_key" not in body["value"]["api_keys"]
    secret = next(s for s in body["secrets"] if s["path"] == ["api_keys", "openai_api_key"])
    assert secret["set"] is True
    # stored at rest encrypted, readable back decrypted by the engine
    db = Session()
    try:
        assert cs.get_document(db, "models")["api_keys"]["openai_api_key"] == "sk-wire-secret"
        raw = db.get(cs.SettingsDocument, "models").document["api_keys"]["openai_api_key"]
        assert raw.startswith("gAAAA")
    finally:
        db.close()


# ── Phase 5: legacy row is no longer written by the new API ──────────────────

def test_mutate_does_not_write_legacy_settings_row(client):
    """After Phase 5 the settings documents are the only write target — the
    legacy single-row settings table stays inert (its api_keys/workspace
    columns are not updated by mutate)."""
    from models.settings import Settings as SettingsModel

    db = Session()
    try:
        row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
        before = dict(row.api_keys or {}) if row else {}
    finally:
        db.close()

    res = client.post("/api/settings/mutate", json={
        "ns": "models",
        "ops": [{"op": "set", "path": ["api_keys", "openai_api_key"], "value": "sk-nomirror"},
                {"op": "set", "path": ["default_model"], "value": "gpt-4o"}],
    })
    assert res.status_code == 200

    db = Session()
    try:
        row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
        after = dict(row.api_keys or {}) if row else {}
        assert after == before  # no mirror write to the legacy column
        # document holds the key (encrypted at rest, decrypted on read)
        assert cs.get_document(db, "models")["api_keys"]["openai_api_key"] == "sk-nomirror"
    finally:
        db.close()


def test_mutate_workspace_does_not_write_legacy_settings_row(client):
    from models.settings import Settings as SettingsModel

    db = Session()
    try:
        row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
        before_ws = row.workspace_path if row else None
    finally:
        db.close()

    res = client.post("/api/settings/mutate", json={
        "ns": "workspace",
        "ops": [{"op": "set", "path": ["workspace_path"], "value": "/tmp/nows-legacy"}],
    })
    assert res.status_code == 200

    db = Session()
    try:
        row = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
        assert (row.workspace_path if row else None) == before_ws  # legacy column untouched
        assert cs.resolve_value(db, "workspace")["workspace_path"] == "/tmp/nows-legacy"
    finally:
        db.close()
