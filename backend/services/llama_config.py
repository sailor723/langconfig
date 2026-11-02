# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
LlamaIndex Configuration Service

This module provides centralized configuration for LlamaIndex integration,
including global settings initialization and multi-tenant PGVector store setup.
"""

import logging
import os
from typing import Optional, Union
from urllib.parse import urlparse

from config import settings as app_settings

logger = logging.getLogger(__name__)

# Try to import LlamaIndex - it's optional
try:
    from llama_index.core import Settings
    from llama_index.embeddings.openai import OpenAIEmbedding
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.llms.openai import OpenAI
    from llama_index.vector_stores.postgres import PGVectorStore
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    logger.warning("LlamaIndex not available. Vector store features will be disabled.")
    LLAMAINDEX_AVAILABLE = False
    Settings = None
    OpenAIEmbedding = None
    OllamaEmbedding = None
    OpenAI = None
    PGVectorStore = None

# HuggingFace embedding is optional (requires torch/sentence-transformers)
try:
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
except ImportError:
    HuggingFaceEmbedding = None

# Global flag to track initialization
_initialized = False
_multimodal_enabled = False
# Set when the embedding model could not be built (no Ollama, no OpenAI key, and
# sentence-transformers not installed). Vector/RAG features degrade to "off";
# nothing else in the app may fail because of it.
_embeddings_unavailable_reason: Optional[str] = None


def embeddings_available() -> bool:
    """Whether a real embedding model is configured.

    Callers that need vectors (RAG retrieval, document indexing) must check this
    instead of assuming Settings.embed_model exists: on a machine with no Ollama,
    no OpenAI key and no sentence-transformers, there is no embedding model at
    all, and that is a *feature switch*, not an error.
    """
    return _initialized and _embeddings_unavailable_reason is None


def embeddings_unavailable_reason() -> Optional[str]:
    return _embeddings_unavailable_reason


def initialize_llama_index_settings(
    litellm_proxy_url: Optional[str] = None, 
    litellm_api_key: Optional[str] = None,
    enable_multimodal: bool = True
):
    """
    Initialize the global LlamaIndex Settings object with optional multimodal support.
    
    Args:
        litellm_proxy_url: URL for the LiteLLM proxy service
        litellm_api_key: API key for LiteLLM proxy authentication
        enable_multimodal: Whether to use multimodal embeddings (requires OpenAI API key)
    """
    global _initialized, _multimodal_enabled, _embeddings_unavailable_reason

    if _initialized:
        logger.info("LlamaIndex settings already initialized")
        return
    
    try:
        # Priority: Ollama > OpenAI > HuggingFace (local fallback)
        # Single source of truth: OLLAMA_BASE_URL / OLLAMA_EMBED_MODEL in .env.
        from langgraph.connection import OLLAMA_BASE_URL
        ollama_base_url = os.getenv("OLLAMA_BASE_URL") or OLLAMA_BASE_URL
        ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")

        # Check if Ollama is available
        import httpx
        ollama_available = False
        try:
            resp = httpx.get(f"{ollama_base_url}/api/tags", timeout=2.0)
            ollama_available = resp.status_code == 200
        except Exception:
            pass

        if ollama_available:
            logger.info(f"Initializing Ollama embedding model: {ollama_embed_model}")
            Settings.embed_model = OllamaEmbedding(
                model_name=ollama_embed_model,
                base_url=ollama_base_url,
            )
            # nomic-embed-text has 768 dimensions
            _multimodal_enabled = False
            logger.info(f"Ollama embeddings enabled with {ollama_embed_model}")
        else:
            # OPENAI_API_KEY is a DB-backed property (config.py); the env
            # fallback that used to sit here is gone — no path reads a
            # credential from .env.
            openai_api_key = app_settings.OPENAI_API_KEY
            if enable_multimodal and openai_api_key:
                logger.info("Initializing OpenAI multimodal embedding model")
                Settings.embed_model = OpenAIEmbedding(
                    model="text-embedding-3-large",
                    dimensions=1024,
                    api_key=openai_api_key
                )
                _multimodal_enabled = True
                logger.info("Multimodal embeddings enabled with OpenAI text-embedding-3-large")
            elif HuggingFaceEmbedding is not None:
                if enable_multimodal:
                    logger.warning("Multimodal requested but OpenAI API key not available, falling back to text-only")
                logger.info("Initializing HuggingFace text-only embedding model")
                Settings.embed_model = HuggingFaceEmbedding(
                    model_name="sentence-transformers/all-MiniLM-L6-v2"
                )
                _multimodal_enabled = False
            else:
                # No Ollama (not installed / not reachable), no OpenAI key, and
                # `llama_index.embeddings.huggingface` failed to import because
                # sentence-transformers (or torch) is missing. This used to call
                # `HuggingFaceEmbedding(...)` where the name was None, which
                # raised `'NoneType' object is not callable` — and because
                # ensure_initialized() is reached from the chat path, EVERY
                # message in a project died with that message instead of simply
                # answering without retrieval. Measured on a fresh install.
                _embeddings_unavailable_reason = (
                    "no embedding model available: Ollama is not reachable at "
                    f"{ollama_base_url}, no OpenAI API key is configured, and "
                    "sentence-transformers is not installed "
                    "(pip install sentence-transformers, or set an embedding "
                    "provider key in Settings → Models)"
                )
                logger.error("RAG is disabled — %s", _embeddings_unavailable_reason)
                Settings.embed_model = None
                _multimodal_enabled = False
        
        # Configure LLM for HyDE if proxy details are provided
        if litellm_proxy_url and litellm_api_key:
            logger.info(f"Configuring LLM with LiteLLM proxy: {litellm_proxy_url}")
            # Use the app-wide default model (settings documents) instead
            # of a hardcoded one.
            try:
                from core.settings import runtime_get
                llm_model = runtime_get("models", "default_model") or "gpt-4o-mini"
            except Exception:
                llm_model = "gpt-4o-mini"
            Settings.llm = OpenAI(
                model=llm_model,
                api_base=f"{litellm_proxy_url}/v1",
                api_key=litellm_api_key
            )
        else:
            logger.warning("LiteLLM proxy URL or API key not provided. LLM will not be configured for HyDE.")
        
        _initialized = True
        logger.info("LlamaIndex settings initialized successfully")
        
    except Exception as e:
        # Never propagate: initialization is reached from the chat path, and a
        # broken/absent embedding provider must cost retrieval, not the reply.
        _embeddings_unavailable_reason = f"LlamaIndex initialization failed: {e}"
        logger.error("RAG is disabled — %s", _embeddings_unavailable_reason)
        _initialized = True


def get_vector_store(project_id: int, embed_dim: Optional[int] = None) -> PGVectorStore:
    """
    Initialize and return a PGVectorStore for the specified project.
    
    This implements multi-tenancy by using project-specific table names,
    ensuring strict data isolation between different projects.
    
    Args:
        project_id: The project identifier for multi-tenant isolation
        embed_dim: Embedding dimension (default: auto-detect based on current model)
        
    Returns:
        PGVectorStore: Configured vector store instance
        
    Raises:
        ValueError: If database URL is invalid or missing
        Exception: If vector store initialization fails
    """
    if not app_settings.database_url:
        raise ValueError("database_url is required but not configured")

    # Auto-detect embedding dimension if not provided
    if embed_dim is None:
        embed_dim = get_embedding_dimension()

    # Parse the database URL to extract connection parameters
    parsed_url = urlparse(app_settings.database_url)
    
    # Ensure we have proper connection details (port defaults to 5432 for PostgreSQL)
    port = parsed_url.port or 5432
    if not all([parsed_url.hostname, parsed_url.username,
                parsed_url.password, parsed_url.path]):
        raise ValueError("Invalid database_url format. Missing required connection parameters.")
    
    # Extract database name (remove leading '/')
    database_name = parsed_url.path.lstrip('/')
    
    # Create project-specific table name for multi-tenancy
    table_name = f"data_project_index_{project_id}"
    
    logger.info(f"Initializing PGVectorStore for project {project_id} with table '{table_name}'")
    
    try:
        vector_store = PGVectorStore.from_params(
            database=database_name,
            host=parsed_url.hostname,
            port=port,
            user=parsed_url.username,
            password=parsed_url.password,
            table_name=table_name,
            embed_dim=embed_dim,
            # Additional configuration for robustness
            hnsw_kwargs={
                "hnsw_m": 16,
                "hnsw_ef_construction": 64,
                "hnsw_ef_search": 40,
            }
        )
        
        logger.info(f"PGVectorStore initialized successfully for project {project_id}")
        return vector_store
        
    except Exception as e:
        logger.error(f"Failed to initialize PGVectorStore for project {project_id}: {e}")
        raise


def ensure_initialized():
    """
    Ensure LlamaIndex settings are initialized before use.

    This is a convenience function that can be called to guarantee
    initialization has occurred before using LlamaIndex components.
    """
    if not _initialized:
        logger.info("LlamaIndex not yet initialized, initializing with default settings")
        # Configure LiteLLM proxy for HyDE support
        litellm_url = os.getenv("LITELLM_PROXY_URL", "http://litellm-proxy:4000")
        # No literal default: "sk-proxy-master-key" in the source tree is a
        # credential, and the old os.getenv() read made .env a second source.
        # The LiteLLM proxy is optional; when configured, its key belongs in the
        # settings document like every other secret (None/empty = no auth).
        from config import get_api_key_from_db

        litellm_key = get_api_key_from_db("litellm_api_key") or ""
        initialize_llama_index_settings(
            litellm_proxy_url=litellm_url,
            litellm_api_key=litellm_key,
            enable_multimodal=True
        )


def get_embedding_dimension() -> int:
    """
    Get the embedding dimension used by the configured embedding model.

    Returns:
        int: Embedding dimension (1024 for OpenAI, 768 for Ollama nomic-embed-text, 384 for text-only)
    """
    global _multimodal_enabled
    if _multimodal_enabled:
        return 1024
    # Check if Ollama is being used (nomic-embed-text = 768 dimensions)
    ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
    if "nomic" in ollama_embed_model.lower():
        return 768
    return 384


def is_multimodal_enabled() -> bool:
    """
    Check if multimodal embeddings are currently enabled.
    
    Returns:
        bool: True if multimodal embeddings are active
    """
    global _multimodal_enabled
    return _multimodal_enabled


def get_table_name(project_id: int) -> str:
    """
    Generate the table name for a given project ID.
    
    This follows the multi-tenant naming convention used by the vector store.
    
    Args:
        project_id: The project identifier
        
    Returns:
        str: The table name for the project's vector data
    """
    return f"data_project_index_{project_id}"