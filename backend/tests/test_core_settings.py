# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the DSH-style settings engine (backend/core/settings/).

Requires PostgreSQL (TEST_DATABASE_URL, default langconfig_test) — the same
environment the rest of the DB-backed suite needs. All tests run against the
settings_documents table only; it is created/truncated by the fixtures.
"""

import os

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import settings as cs

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://langconfig:langconfig_dev@localhost:5432/langconfig_test",
)
SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="module")
def db_session_factory():
    engine = create_engine(SYNC_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield Session
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_documents(db_session_factory):
    """Reset the ensure-table flag, create the table on the test DB, and
    truncate documents before each test."""
    cs._reset_table_ensure()  # noqa: SLF001 — test hook
    db = db_session_factory()
    try:
        cs.ensure_table(db)
        cs.reset_documents(db)
    finally:
        db.close()
    yield
    db = db_session_factory()
    try:
        cs.reset_documents(db)
    finally:
        db.close()


def _db(db_session_factory):
    db = db_session_factory()
    return db


# ── registry / schemas ───────────────────────────────────────────────────────

def test_v1_namespaces_registered():
    assert cs.namespaces() == [
        "general", "models", "workspace", "storage", "rag", "search", "onboarding", "runtime",
        "agents", "knowledge",
    ]
    for ns in cs.namespaces():
        assert cs.is_registered(ns)
        assert cs.get(ns).schema is cs.NAMESPACE_SCHEMAS[ns]


def test_knowledge_namespace_resolves_without_a_document_row(db_session_factory):
    """A new field needs NO reseed: schema defaults are the base layer of every resolution.

    `resolve()` merges `schema().model_dump()` under the DB document, so a namespace with no row at
    all — and a field no document mentions — still resolves. This is the property that makes adding
    a setting a code change rather than a migration.
    """
    value = cs.resolve_value(None, "knowledge")          # db=None: pure schema defaults
    assert value["doc_chat_model"] is None
    assert value["doc_chat_temperature"] is None
    assert value["doc_chat_max_files"] is None
    assert value["doc_chat_max_context_chars"] is None

    # And with a real, empty table the same thing holds.
    db = _db(db_session_factory)
    try:
        assert cs.store.get_document(db, "knowledge") == {}
        resolved = cs.resolve_value(db, "knowledge")
        assert resolved["doc_chat_max_files"] is None
        assert resolved["doc_chat_max_context_chars"] is None
    finally:
        db.close()


def test_knowledge_limits_are_optional_and_bounded(db_session_factory):
    """The two doc-chat limits are settable, unsettable, and refuse nonsense at write time."""
    db = _db(db_session_factory)
    try:
        cs.mutate(db, "knowledge", [
            {"op": "set", "path": ["doc_chat_max_files"], "value": 25},
            {"op": "set", "path": ["doc_chat_max_context_chars"], "value": 250_000},
        ])
        value = cs.resolve_value(db, "knowledge")
        assert value["doc_chat_max_files"] == 25
        assert value["doc_chat_max_context_chars"] == 250_000

        # A document written before the fields existed still resolves, with None for each.
        cs.mutate(db, "knowledge", [
            {"op": "unset", "path": ["doc_chat_max_files"]},
            {"op": "unset", "path": ["doc_chat_max_context_chars"]},
        ])
        value = cs.resolve_value(db, "knowledge")
        assert value["doc_chat_max_files"] is None
        assert value["doc_chat_max_context_chars"] is None

        # Out-of-range values are refused rather than stored, so `0 files` cannot reach doc chat.
        for field, bad in (("doc_chat_max_files", 0), ("doc_chat_max_context_chars", 5)):
            with pytest.raises(ValidationError):
                cs.mutate(db, "knowledge", [{"op": "set", "path": [field], "value": bad}])
    finally:
        db.close()


def test_agents_namespace_holds_create_time_limits():
    """Settings → Agents is the source of the create-time limits.

    The two kinds carry different step budgets on purpose: recursion_limit counts
    LangGraph supersteps, and one LLM turn costs ~13 steps for a standard agent
    but ~2 for a DeepAgent.
    """
    limits = cs.resolve_value(None, "agents")
    assert limits["agent"]["recursion_limit"] == 400
    assert limits["deepagent"]["recursion_limit"] == 150
    for kind in ("agent", "deepagent"):
        cfg = limits[kind]
        assert cfg["summarization_threshold"] < cfg["eviction_threshold"] < cfg["max_total_tokens"]
        assert cfg["keep_last_messages"] >= 1
        assert cfg["enable_summarization"] is True


def test_agents_namespace_rejects_bad_threshold_order():
    from core.settings.schemas import AgentLimits

    with pytest.raises(ValidationError):
        AgentLimits(
            recursion_limit=100,
            summarization_threshold=5000,
            eviction_threshold=4000,   # must be greater than summarization_threshold
            max_total_tokens=9000,
        )


def test_register_rejects_bad_namespace():
    with pytest.raises(TypeError):
        cs.register("Bad Name", cs.GeneralSettings)
    with pytest.raises(TypeError):
        cs.register("UPPER", cs.GeneralSettings)


def test_resolve_without_db_uses_schema_defaults():
    value = cs.resolve_value(None, "models")
    assert value["top_p"] == 1.0
    assert value["local_provider"] == "ollama"
    assert value["default_model"] is None  # absent doc -> no override


def test_every_schema_serializes_to_json_schema():
    for ns in cs.namespaces():
        schema = cs.get(ns).schema
        j = schema.model_json_schema()
        assert j["title"]
        assert "properties" in j


# ── store: mutate / put / get / revision ─────────────────────────────────────

def test_mutate_set_and_read(db_session_factory):
    db = _db(db_session_factory)
    try:
        doc, rev = cs.mutate(db, "models", [{"op": "set", "path": ["default_model"], "value": "gpt-4o"}])
        assert doc["default_model"] == "gpt-4o"
        assert rev == 1
        assert cs.get_revision(db, "models") == 1
        assert cs.get_document(db, "models")["default_model"] == "gpt-4o"
        # resolved value reflects the override
        assert cs.resolve_value(db, "models")["default_model"] == "gpt-4o"
    finally:
        db.close()


def test_mutate_unset_restores_defaults(db_session_factory):
    db = _db(db_session_factory)
    try:
        cs.mutate(db, "models", [{"op": "set", "path": ["default_model"], "value": "gpt-4o"}])
        cs.mutate(db, "models", [{"op": "unset", "path": ["default_model"]}])
        assert cs.get_document(db, "models") == {}
        assert cs.resolve_value(db, "models")["default_model"] is None
    finally:
        db.close()


def test_mutate_stale_revision_conflicts(db_session_factory):
    db = _db(db_session_factory)
    try:
        _, rev = cs.mutate(db, "models", [{"op": "set", "path": ["max_tokens"], "value": 1000}])
        assert rev == 1
        with pytest.raises(cs.SettingsConflict):
            cs.mutate(
                db, "models",
                [{"op": "set", "path": ["max_tokens"], "value": 2000}],
                expected_revision=0,
            )
        # matching revision succeeds
        doc, rev2 = cs.mutate(
            db, "models",
            [{"op": "set", "path": ["max_tokens"], "value": 2000}],
            expected_revision=rev,
        )
        assert doc["max_tokens"] == 2000
        assert rev2 == 2
    finally:
        db.close()


def test_mutate_rejects_unknown_field(db_session_factory):
    db = _db(db_session_factory)
    try:
        with pytest.raises(ValidationError):
            cs.mutate(db, "models", [{"op": "set", "path": ["no_such_field"], "value": 1}])
    finally:
        db.close()


def test_mutate_rejects_bad_op(db_session_factory):
    db = _db(db_session_factory)
    try:
        with pytest.raises(ValueError):
            cs.mutate(db, "models", [{"op": "explode", "path": ["x"]}])
        with pytest.raises(ValueError):
            cs.mutate(db, "models", [{"op": "set"}])
    finally:
        db.close()


def test_put_document_replaces_wholesale(db_session_factory):
    db = _db(db_session_factory)
    try:
        doc, rev = cs.put_document(db, "general", {"app_name": "Team", "theme": "dark"})
        assert doc == {"app_name": "Team", "theme": "dark"}
        assert rev == 1
        # replace drops the old fields (sparse stored section; resolved view
        # falls back to schema defaults)
        doc2, rev2 = cs.put_document(db, "general", {"language": "zh"})
        assert doc2 == {"language": "zh"}
        assert rev2 == 2
        resolved = cs.resolve_value(db, "general")
        assert resolved["app_name"] == "LangConfig"  # schema default again
        assert resolved["language"] == "zh"
    finally:
        db.close()


def test_put_document_expected_revision(db_session_factory):
    db = _db(db_session_factory)
    try:
        cs.put_document(db, "workspace", {"workspace_path": "/tmp/a"})
        with pytest.raises(cs.SettingsConflict):
            cs.put_document(db, "workspace", {"workspace_path": "/tmp/b"}, expected_revision=0)
    finally:
        db.close()


def test_delete_document(db_session_factory):
    db = _db(db_session_factory)
    try:
        cs.mutate(db, "rag", [{"op": "set", "path": ["chunk_size"], "value": 512}])
        assert cs.row_exists(db, "rag")
        assert cs.delete_document(db, "rag") is True
        assert not cs.row_exists(db, "rag")
        assert cs.delete_document(db, "rag") is False
    finally:
        db.close()


# ── secrets: at-rest encryption + wire redaction ─────────────────────────────

def test_secret_encrypted_at_rest(db_session_factory):
    db = _db(db_session_factory)
    try:
        doc, _ = cs.mutate(
            db, "models",
            [{"op": "set", "path": ["api_keys", "openai_api_key"], "value": "sk-test-secret"}],
        )
        # consumer-facing document is decrypted
        assert doc["api_keys"]["openai_api_key"] == "sk-test-secret"
        # the raw DB row holds ciphertext
        row = db.get(cs.SettingsDocument, "models")
        stored = row.document["api_keys"]["openai_api_key"]
        assert stored.startswith("gAAAA")  # Fernet prefix
        assert stored != "sk-test-secret"
        # read-back is decrypted again
        assert cs.get_document(db, "models")["api_keys"]["openai_api_key"] == "sk-test-secret"
    finally:
        db.close()


def test_wire_redacts_secrets(db_session_factory):
    db = _db(db_session_factory)
    try:
        cs.mutate(
            db, "models",
            [
                {"op": "set", "path": ["api_keys", "openai_api_key"], "value": "sk-wire"},
                {"op": "set", "path": ["default_model"], "value": "gpt-5"},
            ],
        )
        wire = cs.resolve(db, "models").wire()
        # secret value never leaves, position is enumerated as set
        assert "openai_api_key" not in wire["value"]["api_keys"]
        secret = next(s for s in wire["secrets"] if s["path"] == ["api_keys", "openai_api_key"])
        assert secret["set"] is True
        # non-secret fields flow through
        assert wire["value"]["default_model"] == "gpt-5"
        # unset secret positions are also enumerated (form slot exists)
        unset = next(s for s in wire["secrets"] if s["path"] == ["api_keys", "anthropic_api_key"])
        assert unset["set"] is False
    finally:
        db.close()


def test_secret_paths_recursive(db_session_factory):
    paths = cs.secret_paths(cs.ModelsSettings)
    assert ["api_keys", "openai_api_key"] in paths
    assert ["api_keys", "deepseek_api_key"] in paths
    assert ["local_api_key"] in paths
    assert ["api_keys", "openai_base_url"] not in paths  # base URLs are not secrets


# ── seed defaults ────────────────────────────────────────────────────────────

def test_seed_defaults_validate_and_persist(db_session_factory):
    db = _db(db_session_factory)
    try:
        defaults = cs.get_defaults()
        assert "models" in defaults
        for ns, doc in defaults.items():
            _, rev = cs.put_document(db, ns, doc)
            assert rev == 1
        # seeded values match the source (current .env via config.Settings)
        value = cs.resolve_value(db, "models")
        for key, expected in defaults["models"].items():
            assert value[key] == expected, key
        for ns in ("workspace", "storage", "rag"):
            resolved = cs.resolve_value(db, ns)
            for key, expected in defaults[ns].items():
                assert resolved[key] == expected, f"{ns}.{key}"
    finally:
        db.close()


def test_resolve_all_returns_every_namespace(db_session_factory):
    db = _db(db_session_factory)
    try:
        resolved = cs.resolve_all(db)
        assert [r.ns for r in resolved] == cs.namespaces()
        for r in resolved:
            assert isinstance(r.value, dict)
            assert r.revision == 0
    finally:
        db.close()


# ── seeding (ensure_settings_seeded / seed_settings.py) ──────────────────────

def test_ensure_seeded_writes_missing_namespaces(db_session_factory):
    db = _db(db_session_factory)
    try:
        written = cs.ensure_settings_seeded(db)
        assert written == len(cs.get_defaults())  # one doc per namespace with defaults
        assert cs.row_exists(db, "models")
        value = cs.resolve_value(db, "models")
        assert value["default_model"] == cs.get_defaults()["models"]["default_model"]
        # idempotent: second run writes nothing
        assert cs.ensure_settings_seeded(db) == 0
    finally:
        db.close()


def test_ensure_seeded_preserves_existing_rows(db_session_factory):
    db = _db(db_session_factory)
    try:
        cs.ensure_settings_seeded(db)  # seed everything first
        # user overrides a seeded value
        cs.mutate(db, "models", [{"op": "set", "path": ["default_model"], "value": "my-custom"}])
        assert cs.ensure_settings_seeded(db) == 0  # all rows exist -> untouched
        assert cs.resolve_value(db, "models")["default_model"] == "my-custom"
        assert cs.get_revision(db, "models") == 2  # seed(1) + mutate(2); no bump from re-seed
    finally:
        db.close()


def test_seed_script_module_runs(db_session_factory):
    """The seed script's main() is a thin wrapper — exercising the function it
    imports covers it; assert the script exists and is importable."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "seeds" / "in" / "seed_settings.py"
    assert script.exists()
    spec = importlib.util.spec_from_file_location("seed_settings_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # imports core.settings — must not raise
    assert callable(module.main)


# ── alembic 028 backfill helpers (DB-free) ───────────────────────────────────

def _load_migration_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "028_create_settings_documents.py"
    spec = importlib.util.spec_from_file_location("migration_028", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_ROW = {
    "default_model": None,  # NULLed by 027 — falls back to .env
    "default_temperature": None,
    "max_tokens": None,
    "primary_model": None,
    "temperature": 0.7,
    "max_tokens_default": 4096,
    "fallback_models": ["claude-sonnet-4-5"],
    "top_p": 0.9,
    "routing_strategy": "balanced",
    "daily_token_limit": 0,
    "monthly_token_limit": 0,
    "alert_threshold": 80,
    "api_keys": {
        "openai_api_key": "gAAAA-encrypted-openai",
        "openai_base_url": "https://api.openai.com/v1",
        "tavily_api_key": "gAAAA-encrypted-tavily",
    },
    "local_provider": "ollama",
    "local_base_url": "http://localhost:11434/v1",
    "local_model_name": "llama3.2:latest",
    "local_api_key": None,
    "app_name": "Team",
    "language": "zh",
    "theme": "dark",
    "auto_save": True,
    "workspace_path": "/tmp/ws",
    "workspace_allow_read": True,
    "workspace_allow_write": False,
    "workspace_require_approval": True,
    "workspace_auto_detect_git": True,
    "workspace_backup_before_edit": True,
    "storage_mode": None,
    "embedding_model": None,
    "chunk_size": 512,
    "chunk_overlap": 64,
    "setup_complete": True,
}


def test_migration_backfill_models_document():
    m = _load_migration_module()
    doc = m._models_document(LEGACY_ROW)
    # .env fallbacks fill the 027-NULLed columns
    assert doc["default_model"] == "deepseek-chat"
    assert doc["default_temperature"] == 0.7  # legacy temperature wins over .env 0
    assert doc["max_tokens"] == 4096  # legacy max_tokens_default wins over .env
    assert doc["fallback_models"] == ["claude-sonnet-4-5"]
    assert doc["top_p"] == 0.9
    # chat api keys copied raw (already encrypted at rest), base URLs included,
    # search keys NOT in the models namespace
    assert doc["api_keys"]["openai_api_key"] == "gAAAA-encrypted-openai"
    assert doc["api_keys"]["openai_base_url"] == "https://api.openai.com/v1"
    assert "tavily_api_key" not in doc["api_keys"]
    assert doc["local_provider"] == "ollama"


def test_migration_backfill_other_documents():
    m = _load_migration_module()
    assert m._general_document(LEGACY_ROW)["app_name"] == "Team"
    assert m._general_document(LEGACY_ROW)["language"] == "zh"
    ws = m._workspace_document(LEGACY_ROW)
    assert ws["workspace_path"] == "/tmp/ws"
    assert ws["allow_write"] is False
    assert ws["base_dir"] == "backend/outputs"  # from .env WORKSPACE_BASE_DIR
    st = m._storage_document(LEGACY_ROW)
    # legacy storage_mode NULL -> .env STORAGE_MODE (or schema default "local")
    assert st["mode"] == (os.getenv("STORAGE_MODE") or "local")
    assert st["documents_base_dir"] == "./data/documents"
    rag = m._rag_document(LEGACY_ROW)
    assert rag["chunk_size"] == 512
    # legacy embedding NULL -> .env DEFAULT_EMBEDDING_MODEL (or the seeded
    # default "ollama-nomic-embed-text:latest", matching defaults.py)
    assert rag["embedding_model"] == (os.getenv("DEFAULT_EMBEDDING_MODEL") or "ollama-nomic-embed-text:latest")
    search = m._search_document(LEGACY_ROW)
    assert search == {"tavily_api_key": "gAAAA-encrypted-tavily"}
    assert m._onboarding_document(LEGACY_ROW) == {"setup_complete": True}
    # empty row -> sparse/empty docs
    assert m._general_document(None) == {}
    assert m._search_document(None) == {}
