"""create settings_documents — DSH-style namespace documents (+ one-time backfill)

Creates the ``settings_documents`` table that backs the DSH-style settings
engine (``core/settings/store.py``): one row per namespace with the user-layer
document (secrets Fernet-encrypted at rest) and a monotonic revision.

Backfills the documents **once** from the legacy single-row ``settings`` table
+ the root ``.env`` (the pre-refactor sources of truth), so existing installs
keep their effective values. The legacy row is left untouched — it stays as a
shim for the old endpoints and is dropped in a later migration.

Safety properties:
- ADDITIVE: only creates a new table and inserts into it; nothing is dropped,
  altered, or overwritten on the legacy ``settings`` row or any other table.
- IDEMPOTENT: rows are inserted with ON CONFLICT DO NOTHING, so re-running is
  a no-op and user edits made after the first backfill are preserved.
- GUARDED: when the legacy ``settings`` table does not exist (create_all-only
  installs, which use ``alembic stamp head`` and never replay migrations), the
  backfill is skipped entirely — fresh installs get defaults from
  ``seed_settings.py`` / the boot auto-seed instead.

Revision ID: 028_create_settings_documents
Revises: 027_clear_settings_model_params
Create Date: 2026-08-15 00:00:00.000000
"""
import json
import os
from pathlib import Path

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '028_create_settings_documents'
down_revision = '027_clear_settings_model_params'
branch_labels = None
depends_on = None

# env.py loads the root .env via db.database; be explicit anyway so this
# migration stays self-contained when invoked directly.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _first(*values):
    """First non-empty value (empty string treated as unset)."""
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar() is not None


_CHAT_KEY_FIELDS = (
    "openai_api_key", "openai_base_url",
    "anthropic_api_key", "anthropic_base_url",
    "google_api_key", "google_base_url",
    "cohere_api_key", "cohere_base_url",
    "replicate_api_key", "replicate_base_url",
    "deepseek_api_key", "deepseek_api_base",
    "glm_api_key", "glm_api_base",
    "minimax_api_key", "minimax_api_base",
    "qwen_api_key", "qwen_api_base",
    "kimi_api_key", "kimi_api_base",
    "agnes_api_key", "agnes_base_url",
)
_SEARCH_KEY_FIELDS = ("tavily_api_key", "serper_api_key")


def _models_document(row: dict | None) -> dict:
    env = os.getenv
    doc: dict = {}
    if row is not None:
        api_keys = row.get("api_keys") or {}
        chat = {k: v for k, v in api_keys.items() if k in _CHAT_KEY_FIELDS and v}
        if chat:
            doc["api_keys"] = chat
        # Model defaults (legacy columns were NULLed by 027). Fallbacks mirror
        # core/settings/defaults.py (the old .env values) so backfill and
        # boot-seed agree when DEFAULT_MODEL & co are gone from .env.
        doc["default_model"] = _first(
            row.get("default_model"), row.get("primary_model"),
            env("DEFAULT_MODEL"), "deepseek-chat",
        )
        doc["default_temperature"] = _first(
            row.get("default_temperature"), row.get("temperature"),
            env("DEFAULT_TEMPERATURE"), "0",
        )
        doc["max_tokens"] = _first(
            row.get("max_tokens"), row.get("max_tokens_default"),
            env("MAX_TOKENS"), "256000",
        )
        fallback = row.get("fallback_models") or []
        if not fallback and env("FALLBACK_MODELS"):
            fallback = [m.strip() for m in env("FALLBACK_MODELS").split(",") if m.strip()]
        if not fallback:
            fallback = ["local-ollama-qwen25-14b"]
        doc["fallback_models"] = fallback
        for field in ("top_p", "routing_strategy", "daily_token_limit",
                      "monthly_token_limit", "alert_threshold"):
            value = row.get(field)
            if value is not None:
                doc[field] = value
        # Local models
        for legacy, new in (("local_provider", "local_provider"),
                            ("local_base_url", "local_base_url"),
                            ("local_model_name", "local_model_name"),
                            ("local_api_key", "local_api_key")):
            value = row.get(legacy)
            if value:
                doc[new] = value
    else:
        doc["default_model"] = _first(env("DEFAULT_MODEL"), "deepseek-chat")
        doc["default_temperature"] = _first(env("DEFAULT_TEMPERATURE"), "0")
        doc["max_tokens"] = _first(env("MAX_TOKENS"), "256000")
        fallback = [m.strip() for m in (env("FALLBACK_MODELS") or "").split(",") if m.strip()]
        doc["fallback_models"] = fallback or ["local-ollama-qwen25-14b"]
    return doc


def _general_document(row: dict | None) -> dict:
    if row is None:
        return {}
    doc = {}
    for field in ("app_name", "language", "auto_save", "auto_save_interval",
                  "confirm_before_delete", "show_notifications", "check_updates",
                  "telemetry", "log_level", "theme"):
        value = row.get(field)
        if value is not None:
            doc[field] = value
    return doc


def _workspace_document(row: dict | None) -> dict:
    doc = {}
    if row is not None:
        for legacy, new in (("workspace_path", "workspace_path"),
                            ("workspace_allow_read", "allow_read"),
                            ("workspace_allow_write", "allow_write"),
                            ("workspace_require_approval", "require_approval"),
                            ("workspace_auto_detect_git", "auto_detect_git"),
                            ("workspace_backup_before_edit", "backup_before_edit")):
            value = row.get(legacy)
            if value is not None:
                doc[new] = value
    base_dir = os.getenv("WORKSPACE_BASE_DIR", "backend/outputs")
    if base_dir:
        doc["base_dir"] = base_dir
    return doc


def _storage_document(row: dict | None) -> dict:
    doc = {}
    mode = _first(row.get("storage_mode") if row else None, os.getenv("STORAGE_MODE"), "local")
    doc["mode"] = mode
    base_dir = os.getenv("STORAGE_BASE_DIR", "./data/storage")
    if base_dir:
        doc["base_dir"] = base_dir
    documents_dir = os.getenv("DOCUMENTS_BASE_DIR", "./data/documents")
    if documents_dir:
        doc["documents_base_dir"] = documents_dir
    return doc


def _rag_document(row: dict | None) -> dict:
    doc = {}
    if row is not None:
        # Fallback mirrors core/settings/defaults.py (the old .env value)
        # so backfill and boot-seed agree when DEFAULT_EMBEDDING_MODEL is gone.
        embedding = _first(row.get("embedding_model"), os.getenv("DEFAULT_EMBEDDING_MODEL"),
                           "ollama-nomic-embed-text:latest")
        doc["embedding_model"] = embedding
        for field in ("chunk_size", "chunk_overlap"):
            value = row.get(field)
            if value is not None:
                doc[field] = value
    return doc


def _search_document(row: dict | None) -> dict:
    if row is None:
        return {}
    api_keys = row.get("api_keys") or {}
    search = {k: v for k, v in api_keys.items() if k in _SEARCH_KEY_FIELDS and v}
    return search


def _onboarding_document(row: dict | None) -> dict:
    if row is None:
        return {}
    setup_complete = row.get("setup_complete")
    if setup_complete is None:
        return {}
    return {"setup_complete": bool(setup_complete)}


def upgrade() -> None:
    """Create settings_documents and backfill from the legacy settings row + .env."""
    op.execute(
        "CREATE TABLE IF NOT EXISTS settings_documents ("
        " ns VARCHAR(64) PRIMARY KEY,"
        " document JSON NOT NULL,"
        " revision INTEGER NOT NULL,"
        " updated_at TIMESTAMPTZ NOT NULL)"
    )

    conn = op.get_bind()
    if not _table_exists(conn, "settings"):
        # create_all-only installs (stamp head, never replay) — fresh installs
        # get defaults from seed_settings.py / boot auto-seed.
        return

    row = conn.execute(text("SELECT * FROM settings WHERE id = 1")).mappings().first()
    documents = {
        "models": _models_document(row),
        "general": _general_document(row),
        "workspace": _workspace_document(row),
        "storage": _storage_document(row),
        "rag": _rag_document(row),
        "search": _search_document(row),
        "onboarding": _onboarding_document(row),
    }
    now = "now()"
    for ns, doc in documents.items():
        if not doc:
            continue
        op.execute(
            text(
                "INSERT INTO settings_documents (ns, document, revision, updated_at) "
                "VALUES (:ns, CAST(:doc AS JSON), 1, " + now + ") "
                "ON CONFLICT (ns) DO NOTHING"
            ),
            {"ns": ns, "doc": json.dumps(doc)},
        )


def downgrade() -> None:
    """Drop the settings_documents table (legacy settings row untouched)."""
    op.execute("DROP TABLE IF EXISTS settings_documents")
