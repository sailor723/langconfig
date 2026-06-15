"""
Unified Model Database Model.

Stores both cloud and local LLM models in a single table.
Replaces constants/models.py (hardcoded enum) and models/local_model.py.

source field distinguishes: 'cloud' (managed by LangConfig) vs 'local' (user-configured).
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime
from db.database import Base
import datetime


class Model(Base):
    """
    Unified model storage for cloud and local LLMs.

    Cloud models are seeded from code (one-time migration) and managed via the `models` table.
    Local models are added by users via Settings > Local Models.
    """
    __tablename__ = 'models'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Identification ────────────────────────────────────────────────
    model_id = Column(String, unique=True, nullable=False, index=True)
    # Cloud: "deepseek-chat", "gpt-4o", "claude-sonnet-4-5", etc.
    # Local: "local-ollama-llama3"  (prefixed with "local-")

    display_name = Column(String, nullable=False)
    # Cloud: "DeepSeek Chat", "GPT-4o", "Claude Sonnet 4.5"
    # Local: "My Llama 3.2 (Ollama)"

    provider = Column(String, nullable=False, index=True)
    # Cloud: "deepseek", "openai", "anthropic", "google", "glm", "minimax"
    # Local: "ollama", "lmstudio", "vllm", "litellm", "custom"

    source = Column(String, nullable=False, default='cloud')
    # "cloud" or "local"

    # ── Capabilities ──────────────────────────────────────────────────
    capabilities = Column(JSON, default=dict)
    # {"streaming": true, "tools": true, "max_context": 128000}

    is_active = Column(Boolean, default=True, nullable=False)
    # Soft delete / disable

    # ── Local-specific fields (null for cloud models) ─────────────────
    base_url = Column(String, nullable=True)
    # "http://localhost:11434/v1"

    api_model_name = Column(String, nullable=True)
    # Provider's internal model name (e.g. "llama3.2:latest")

    api_key = Column(String, nullable=True)
    # Optional, encrypted at application layer

    is_validated = Column(Boolean, default=False, nullable=False)
    # True if connection test passed (local models only)

    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    validation_error = Column(String, nullable=True)

    # ── Usage ─────────────────────────────────────────────────────────
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # ── Categorization ────────────────────────────────────────────────
    tags = Column(JSON, default=list)
    # ["coding", "fast", "7b"]

    # ── Timestamps ────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True),
                       default=datetime.datetime.utcnow,
                       onupdate=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Model(id={self.id}, model_id='{self.model_id}', provider='{self.provider}', source='{self.source}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "provider": self.provider,
            "source": self.source,
            "capabilities": self.capabilities,
            "is_active": self.is_active,
            "base_url": self.base_url,
            "api_model_name": self.api_model_name,
            "is_validated": self.is_validated,
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "validation_error": self.validation_error,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
