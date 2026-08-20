"""
LangConfig Configuration
Reads all API keys and infrastructure settings from .env (pydantic-settings).
Database settings table is used only for user preferences (theme, language, etc.).
"""
from pydantic_settings import BaseSettings
from pydantic import model_validator
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
    # No hardcoded URL: the only legitimate defaults are the parts
    # (host/port/user/password/dbname) read from the POSTGRES_* env
    # block by compose_db_url() above. If those env vars are also
    # missing, raise so the operator notices instead of silently
    # connecting to localhost:5432.
    database_url: str = ""
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
    # Source of truth: OLLAMA_BASE_URL / OLLAMA_EMBED_MODEL in .env.
    # Defer to runtime resolution so the value reflects the latest .env
    # at request time (and so we don't ship a hardcoded default).
    ollama_base_url: str = ""
    ollama_embed_model: str = ""

    # ── LangSmith (optional) ──
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "langconfig"

    # ── Middleware ──
    enable_default_middleware: bool = True

    # ── Execution History ──
    max_execution_history_per_workflow: int = 100
    execution_history_retention_days: int = 90
    auto_cleanup_execution_history: bool = True

    # ── Agent recursion limit (shared) ──
    # Max recursion depth for deep-agent graph execution. Used by:
    #  - api/analysis/routes.py (dashboard generation)
    #  - api/chat/messages.py (both streaming and non-streaming chat paths)
    # Override via .env's ANALYSIS_RECURSION_LIMIT=N if your team needs
    # longer pipelines. The SDK default of 9,999 is usually too high for
    # our deployment profile.
    analysis_recursion_limit: int = 1000

    # Wall-clock timeout (seconds) for dashboard auto-generation.
    # The agent may take 2-5 minutes on multi-table ERP DBs with full SKILL.md.
    # Read by api/analysis/routes.py:_auto_generate_dashboard.
    analysis_dashboard_timeout: int = 600

    # Chat timeout (seconds) — shorter than dashboard gen.
    analysis_chat_timeout: int = 120

    # ── Runtime settings (user-adjustable via Settings panel) ──
    # These are loaded from .env on cold start (bootstrap default). The
    # _apply_runtime_overrides model_validator below reads the `runtime`
    # settings document and overrides each field with the DB value, so the
    # Settings panel always wins once the team changes a value.
    # Workspace / backups
    langconfig_workspace_root: str = "backend/.workspace_data"
    backup_dir: str = "./backups"
    storage_mode: str = "local"
    # Local embeddings
    ollama_embed_model: str = "nomic-embed-text:latest"
    # Tracing
    langsmith_tracing: bool = False
    langsmith_project: str = "langconfig"
    # DB pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 1000
    # Performance
    performance_monitoring_enabled: bool = True
    slow_request_threshold_ms: int = 1000
    log_slow_queries: bool = True
    slow_query_threshold: float = 1.0
    log_all_requests: bool = False
    # Execution history
    max_execution_history_per_workflow: int = 100
    execution_history_retention_days: int = 90
    auto_cleanup_execution_history: bool = True

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

    def _runtime_override(self):
        """Read the `runtime` settings document; values in DB override .env
        (which only acts as the bootstrap default on first boot).

        Called once via a model_validator after .env is loaded. Pydantic's
        env_file is still required to handle secrets and operator-only
        settings; this only layers DB-first on top of the runtime fields.
        """
        try:
            from core.settings.runtime import runtime_value
            values = runtime_value("runtime")
            for field in (
                "langconfig_workspace_root", "backup_dir",
                "storage_mode",
                "ollama_embed_model",
                "langsmith_tracing", "langsmith_project",
                "db_pool_size", "db_max_overflow",
                "analysis_recursion_limit", "analysis_dashboard_timeout", "analysis_chat_timeout",
                "rate_limit_enabled", "rate_limit_requests_per_minute",
                "performance_monitoring_enabled", "slow_request_threshold_ms",
                "log_slow_queries", "slow_query_threshold", "log_all_requests",
                "max_execution_history_per_workflow", "execution_history_retention_days",
                "auto_cleanup_execution_history",
            ):
                v = values.get(field)
                if v is not None:
                    setattr(self, field, v)
        except Exception:
            # Pre-migration DB or transient error — keep env-loaded values.
            pass

    @model_validator(mode="after")
    def _apply_runtime_overrides(self):
        # If .env didn't provide DATABASE_URL, fall back to a URL
        # composed from the POSTGRES_* env parts (single source of truth).
        # No hardcoded localhost:5432 fallback — if those env vars are
        # also missing, the operator sees a clear error from DB-side
        # connection failures, not a silent localhost connection.
        if not self.database_url:
            from db.db_url import compose_db_url
            self.database_url = compose_db_url()
        # Same idea for the local LLM endpoints: read once from .env at
        # model-load time. Operators edit .env, not this file.
        if not self.ollama_base_url:
            self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "")
        if not self.ollama_embed_model:
            self.ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "")
        self._runtime_override()
        return self

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

    Resolution order (SINGLE api-key table):
    1. .env file (via pydantic-settings) — canonical source of truth
    2. The ``models`` settings document's ``api_keys`` field
       (core/settings — the one table every API key lives in, set via the
       Settings UI; secrets encrypted at rest)

    The legacy ``settings.api_keys`` JSONB column was migrated into the
    models document and is no longer read.
    """
    # Try .env first via settings
    try:
        val = getattr(settings, key_name, None) or getattr(settings, key_name.upper(), None)
        if val:
            return val
    except Exception:
        pass

    # Fallback: UI-set key from the single models.api_keys document.
    try:
        db_val = _db_api_key_only(key_name)
        if db_val:
            return db_val
    except Exception:
        pass

    return None