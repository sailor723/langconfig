# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Centralized connection configuration for the langgraph/ runners.

Both SQL and Neo4j connection parameters are read here from the
project-root .env (loaded once via config.py at process startup) and
re-exported as plain Python constants. Hardcoded literals are banned
from the rest of the codebase — every caller goes through this module
so that changing a port, password, or host is a single-file edit.

Why a module instead of just `os.getenv()` scattered through the code:
  - One place to grep for "neo4j" / "postgres" defaults.
  - One place to validate env values at runtime (e.g. parse a port).
  - One place to surface a friendly error if required env is missing.

The defaults match the docker-compose.yml in the repo root, so a
fresh checkout works without any .env edits.
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Postgres (shared by SQL agent / Chinook data + the main app database)
# ---------------------------------------------------------------------------
# These compose() helpers are the canonical source of truth. The
# SQL setup script reads the same env vars directly via os.getenv,
# so the two paths stay in sync.

POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5433"))
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "langconfig")
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "langconfig")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "langconfig_dev")


def compose_postgres_url(
    driver: str = "postgresql",
    *,
    host: str | None = None,
    port: int | None = None,
    dbname: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> str:
    """Build a Postgres connection URL from env (or override args).

    The PROJECT_ROOT .env is the single source of truth for connection
    details. Hardcoded literals are banned — every consumer in this
    package should compose its URL from these env vars.
    """
    h = host or POSTGRES_HOST
    p = port or POSTGRES_PORT
    d = dbname or POSTGRES_DB
    u = user or POSTGRES_USER
    pw = password or POSTGRES_PASSWORD
    return f"{driver}://{u}:{pw}@{h}:{p}/{d}"


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------
# Same idea: every consumer (graph_studio routes, langgraph/neo4j_setup_db,
# the chat-time tools) reads from these constants. No port/credentials
# literals elsewhere.
#
# Two endpoints are exposed because Neo4j serves two protocols:
#   - Bolt (port 7687) — used by the official neo4j-python-driver for the
#     chat-time and graph-studio queries. Cached in `langgraph/neo4j_setup_db.py`.
#   - HTTP/REST (port 7474) — used by the document-index/vector-store helpers
#     in `tools/native_impl.py` and `api/knowledge/rag/*`. These are the
#     drivers that wrap the older Neo4jDocumentIndex API.
# Both are typically hosted on the same Neo4j container, just different ports.

NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_ENCRYPTED: bool = os.getenv("NEO4J_ENCRYPTED", "false").lower() in (
    "true", "1", "yes",
)

# HTTP REST endpoint — used by Neo4jDocumentIndex helpers.
NEO4J_HTTP_URL: str = os.getenv("NEO4J_URL", "http://localhost:7474")
NEO4J_HTTP_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_HTTP_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")


# ---------------------------------------------------------------------------
# Local LLM (Ollama)
# ---------------------------------------------------------------------------
# Same single-source-of-truth pattern. Used by the langgraph/llm.py
# runtime + the local-model settings UI in core/settings/.

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LOCAL_LLM_BASE_URL: str = os.getenv(
    "LOCAL_LLM_BASE_URL", OLLAMA_BASE_URL
)  # legacy alias


# ---------------------------------------------------------------------------
# Redis (workflow cache)
# ---------------------------------------------------------------------------

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")


# ---------------------------------------------------------------------------
# Active-target overrides (set by the studio UI at runtime)
# ---------------------------------------------------------------------------
# These are intentionally NOT read from env — they're in-memory overrides
# controlled by the studio's API endpoints. Other code can read them via
# the get_target_database() helpers in sql_setup_db / neo4j_setup_db.
# ---------------------------------------------------------------------------
