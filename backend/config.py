"""
LangConfig Configuration
Reads all API keys and infrastructure settings from .env (pydantic-settings).
Database settings table is used only for user preferences (theme, language, etc.).
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os
from dotenv import load_dotenv

# Load .env file from project root
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)

# Compose DATABASE_URL from the POSTGRES_* parts when not set explicitly, so
# Settings.database_url always agrees with db.database and docker-compose.
# db.db_url is dependency-free (no SQLAlchemy), so importing config stays light.
if not os.getenv("DATABASE_URL"):
    from db.db_url import compose_db_url
    os.environ["DATABASE_URL"] = compose_db_url()


class Settings(BaseSettings):
    """Application settings — all API keys and infrastructure config from .env"""

    # ── Environment ──
    environment: str = "development"
    debug: bool = True

    # ── Secrets at rest (Fernet key seed — read by services/encryption.py) ──
    api_key_encryption_key: Optional[str] = None

    # ── Database ──
    database_url: str = "postgresql://langconfig:langconfig_dev@localhost:5432/langconfig"
    database_url_async: Optional[str] = None

    # ── LLM API Keys (directly from .env, no DB fallback) ──
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_api_base: str = "https://api.deepseek.com"
    agnes_api_key: Optional[str] = None
    agnes_base_url: str = "https://apihub.agnes-ai.com/v1"
    minimax_api_key: Optional[str] = None
    minimax_api_base: str = "https://api.minimax.chat/v1"
    kimi_api_key: Optional[str] = None
    kimi_api_base: Optional[str] = None
    qwen_api_key: Optional[str] = None
    qwen_api_base: Optional[str] = None
    glm_api_key: Optional[str] = None
    glm_api_base: Optional[str] = None
    tavily_api_key: Optional[str] = None
    serper_api_key: Optional[str] = None

    # ── Ollama Embedding ──
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text:latest"

    # ── LangSmith (optional) ──
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "langconfig"

    # ── Middleware ──
    enable_default_middleware: bool = True

    # ── Execution History ──
    max_execution_history_per_workflow: int = 100
    execution_history_retention_days: int = 90
    auto_cleanup_execution_history: bool = True

    # ── Analysis Agent ──
    # Max recursion depth for the analysis deep agent (dashboard gen + chat).
    # Read by api/analysis/routes.py and skills/sql-analyst/9_erp_dashboard.py.
    analysis_recursion_limit: int = 1000

    # Wall-clock timeout (seconds) for dashboard auto-generation.
    # The agent may take 2-5 minutes on multi-table ERP DBs with full SKILL.md.
    # Read by api/analysis/routes.py:_auto_generate_dashboard.
    analysis_dashboard_timeout: int = 600

    # Chat timeout (seconds) — shorter than dashboard gen.
    analysis_chat_timeout: int = 120

    # ── Storage (docs/system-architecture.md §15) ──
    # Runtime storage backend: 'local' (disk, default) | 'db' (Postgres BYTEA).
    # The process-wide value is overridden at boot by the storage settings
    # document (Settings UI runtime switch) — .env STORAGE_MODE is only the
    # base default. The storage roots (base_dir/documents_base_dir) live in
    # the storage settings document (core/settings).
    storage_mode: str = "local"

    # ── Uppercase aliases for convenience ──
    # UI-editable providers: DB-first (DB keys are encrypted at rest, decrypted
    # transparently by _db_api_key_only below). .env is the fallback when no
    # DB key exists, so the system still works on a fresh install with only
    # .env. Keys are matched by snake_case; *_API_BASE properties use .env as
    # the source for now (TODO: extend APIKeySet to accept base_url overrides).
    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("openai_api_key") or self.openai_api_key

    @property
    def ANTHROPIC_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("anthropic_api_key") or self.anthropic_api_key

    @property
    def GOOGLE_API_KEY(self) -> Optional[str]:
        return (
            _db_api_key_only("google_api_key")
            or self.google_api_key
            or self.gemini_api_key
        )

    @property
    def DEEPSEEK_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("deepseek_api_key") or self.deepseek_api_key

    @property
    def DEEPSEEK_API_BASE(self) -> str:
        return _db_api_key_only("deepseek_api_base") or self.deepseek_api_base

    @property
    def SERPER_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("serper_api_key") or self.serper_api_key

    @property
    def TAVILY_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("tavily_api_key") or self.tavily_api_key

    @property
    def AGNES_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("agnes_api_key") or self.agnes_api_key

    @property
    def AGNES_BASE_URL(self) -> str:
        # AGNES_BASE_URL lives in DB under agnes_base_url; honor it when set.
        return _db_api_key_only("agnes_base_url") or self.agnes_base_url

    @property
    def MINIMAX_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("minimax_api_key") or self.minimax_api_key

    @property
    def MINIMAX_API_BASE(self) -> str:
        # TODO: wire through when APIKeySet accepts minimax_base_url
        return self.minimax_api_base

    @property
    def KIMI_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("kimi_api_key") or self.kimi_api_key

    @property
    def KIMI_API_BASE(self) -> Optional[str]:
        return self.kimi_api_base

    @property
    def QWEN_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("qwen_api_key") or self.qwen_api_key

    @property
    def QWEN_API_BASE(self) -> Optional[str]:
        return self.qwen_api_base

    @property
    def GLM_API_KEY(self) -> Optional[str]:
        return _db_api_key_only("glm_api_key") or self.glm_api_key

    @property
    def GLM_API_BASE(self) -> Optional[str]:
        return self.glm_api_base

    # ── Computed ──
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


# ── DB-first helpers ──
# Read UI-set keys from the DSH-style settings documents (models.api_keys,
# decrypted) and fall back to the .env value. Used by uppercase property
# aliases above so runtime resolution honors what the user saved in Settings.
def _db_api_key_only(key_name: str) -> Optional[str]:
    """Read just the DB value (decrypted). Returns None if absent.

    Phase 5: reads the ``models`` settings document (core/settings) — the
    legacy single-row ``settings.api_keys`` column is no longer written.
    Read-only: never creates the table; a missing table (pre-migration DB)
    resolves to None so the caller falls back to .env.
    """
    try:
        from core.settings import store
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            doc = store.get_document(db, "models")
            return (doc.get("api_keys") or {}).get(key_name) or None
        finally:
            db.close()
    except Exception:
        return None


# Global settings instance
settings = Settings()


def get_api_key_from_db(key_name: str) -> Optional[str]:
    """Read an API key from .env (pydantic-settings), falling back to the DB.

    Resolution order:
    1. .env file (via pydantic-settings) — canonical source of truth
    2. Settings documents (core/settings `models.api_keys`) — set via the
       Settings UI at runtime

    The DB fallback allows API keys to be configured through the Settings UI
    when .env is not available or incomplete. .env always takes precedence.
    """
    # Try .env first via settings
    try:
        val = getattr(settings, key_name, None) or getattr(settings, key_name.upper(), None)
        if val:
            return val
    except Exception:
        pass

    # Fallback: UI-set key from the settings documents (models.api_keys).
    try:
        db_val = _db_api_key_only(key_name)
        if db_val:
            return db_val
    except Exception:
        pass

    return None