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


class Settings(BaseSettings):
    """Application settings — all API keys and infrastructure config from .env"""

    # ── Environment ──
    environment: str = "development"
    debug: bool = True

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

    # ── Default Model Settings ──
    default_llm_provider: str = "deepseek"
    default_model: str = "deepseek-chat"
    fallback_models: str = ""
    default_temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    default_embedding_model: str = "ollama-nomic-embed-text:latest"

    # ── Local LLM ──
    local_llm_provider: str = "ollama"
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "llama3.2:latest"
    local_llm_api_key: Optional[str] = None

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

    # ── RAG ──
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # ── Uppercase aliases for convenience ──
    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return self.openai_api_key

    @property
    def ANTHROPIC_API_KEY(self) -> Optional[str]:
        return self.anthropic_api_key

    @property
    def GOOGLE_API_KEY(self) -> Optional[str]:
        return self.google_api_key or self.gemini_api_key

    @property
    def DEEPSEEK_API_KEY(self) -> Optional[str]:
        return self.deepseek_api_key

    @property
    def DEEPSEEK_API_BASE(self) -> str:
        return self.deepseek_api_base

    @property
    def TAVILY_API_KEY(self) -> Optional[str]:
        return self.tavily_api_key

    @property
    def AGNES_API_KEY(self) -> Optional[str]:
        return self.agnes_api_key

    @property
    def AGNES_BASE_URL(self) -> str:
        return self.agnes_base_url

    @property
    def MINIMAX_API_KEY(self) -> Optional[str]:
        return self.minimax_api_key

    @property
    def MINIMAX_API_BASE(self) -> str:
        return self.minimax_api_base

    @property
    def KIMI_API_KEY(self) -> Optional[str]:
        return self.kimi_api_key

    @property
    def KIMI_API_BASE(self) -> Optional[str]:
        return self.kimi_api_base

    @property
    def QWEN_API_KEY(self) -> Optional[str]:
        return self.qwen_api_key

    @property
    def QWEN_API_BASE(self) -> Optional[str]:
        return self.qwen_api_base

    @property
    def GLM_API_KEY(self) -> Optional[str]:
        return self.glm_api_key

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


# Global settings instance
settings = Settings()


def get_api_key_from_db(key_name: str) -> Optional[str]:
    """Read an API key from .env (pydantic-settings), falling back to the DB.

    Resolution order:
    1. .env file (via pydantic-settings) — canonical source of truth
    2. DB settings.api_keys JSONB column — set via Settings UI at runtime

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

    # Fallback: try the database settings.api_keys JSONB column
    try:
        from db.database import SessionLocal
        from models.core import Setting
        db = SessionLocal()
        try:
            rec = db.query(Setting).filter(Setting.key == "api_keys").first()
            if rec and rec.value:
                import json
                keys = json.loads(rec.value) if isinstance(rec.value, str) else rec.value
                return keys.get(key_name)
        finally:
            db.close()
    except Exception:
        pass

    return None
