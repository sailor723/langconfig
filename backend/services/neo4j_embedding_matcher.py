"""
Embedding-based document matcher, parallel to choose_best_document_match.

The string scorer in neo4j_document_index.py scans every Document node's
metadata with substring checks (O(N) per query). This module adds a fast
alternative: each Document node gets one `embedding` property (an embedding
of its compact "routing blob"), backed by a Neo4j HNSW vector index
(cosine). Queries are embedded and resolved with `db.index.vector.queryNodes`
(ANN, O(log N)) instead of a full scan.

Design notes:
- Uses the Ollama nomic-embed-text model (768 dims), which is already the
  project's DEFAULT_EMBEDDING_MODEL in .env.
- Applies nomic's recommended retrieval prefixes: `search_document: ` for
  stored docs, `search_query: ` for incoming queries.
- Keeps the legacy string scorer untouched: find_best() returns None when
  the index/embeddings are unavailable or the best score is below the
  threshold, so callers can fall back.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

# Single source of truth: OLLAMA_BASE_URL / OLLAMA_EMBED_MODEL in .env.
# No hardcoded URL or model literal.
from langgraph.connection import OLLAMA_BASE_URL
import os
OLLAMA_DEFAULT_URL = os.getenv("OLLAMA_BASE_URL") or OLLAMA_BASE_URL
OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
EMBED_DIM = 768  # nomic-embed-text dimension

# nomic-embed-text retrieval prefixes (docs vs queries).
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

_VECTOR_INDEX_NAME = "doc_embedding"
_ENTITY_VECTOR_INDEX = "entity_embedding"


def embed_texts(
    texts: list[str],
    model: str = OLLAMA_DEFAULT_MODEL,
    base_url: str = OLLAMA_DEFAULT_URL,
) -> list[list[float]]:
    """Embed a list of strings via Ollama's /api/embeddings.

    Ollama's endpoint is single-prompt, so we reuse one client and POST
    sequentially. Raises on HTTP error so callers can fall back.
    """
    vectors: list[list[float]] = []
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        for text in texts:
            resp = client.post("/api/embeddings", json={"model": model, "prompt": text})
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
    return vectors


class Neo4jEmbeddingMatcher:
    """Embedding matching over Neo4j Document nodes via a vector index."""

    def __init__(
        self,
        index,
        model: str = OLLAMA_DEFAULT_MODEL,
        base_url: str = OLLAMA_DEFAULT_URL,
        dim: int = EMBED_DIM,
        min_score: float = 0.60,
        min_margin: float = 0.035,
        min_entity_margin: float = 0.012,
        use_prefixes: bool = True,
    ):
        self.index = index
        self.model = model
        self.base_url = base_url
        self.dim = dim
        self.min_score = min_score
        self.min_margin = min_margin
        self.min_entity_margin = min_entity_margin
        self.use_prefixes = use_prefixes

    # --- index lifecycle ---------------------------------------------------

    def ensure_index(self) -> None:
        """Create the HNSW vector index if it does not exist yet."""
        self.index._run_cypher(
            (
                "CREATE VECTOR INDEX doc_embedding IF NOT EXISTS "
                "FOR (d:Document) ON (d.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: $dim, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
            {"dim": self.dim},
        )

    def ensure_entity_index(self) -> None:
        """Create the HNSW vector index for Entity embeddings if missing."""
        self.index._run_cypher(
            (
                "CREATE VECTOR INDEX entity_embedding IF NOT EXISTS "
                "FOR (e:Entity) ON (e.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: $dim, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
            {"dim": self.dim},
        )

    # --- embedding build ---------------------------------------------------

    @staticmethod
    def routing_blob(record) -> str:
        """Compact text capturing everything the string scorer uses.

        Keep it metadata-only (name / description / about / supported
        queries / tags) — embedding the full document body would cost a
        lot more for marginal routing gain.
        """
        parts = [
            record.name,
            record.description,
            record.what_this_document_is_about,
            *(record.supported_queries or []),
            *(record.tags or []),
        ]
        return "\n".join(str(p) for p in parts if p)

    def build_embeddings(self, project_id: int, records: Optional[list] = None) -> dict[str, Any]:
        """Embed every Document node's routing blob and store it on the node."""
        records = records if records is not None else self.index.list_documents(project_id=project_id)
        if not records:
            return {"embedded": 0, "dim": self.dim}

        texts = [
            (DOC_PREFIX if self.use_prefixes else "") + self.routing_blob(r)
            for r in records
        ]
        vectors = embed_texts(texts, model=self.model, base_url=self.base_url)

        # Batch-write in one transaction instead of one roundtrip per doc.
        rows = [{"name": r.name, "vec": vec} for r, vec in zip(records, vectors)]
        self.index._run_cypher(
            (
                "UNWIND $rows AS row "
                "MATCH (d:Document {project_id: $pid, name: row.name}) "
                "SET d.embedding = row.vec"
            ),
            {"pid": project_id, "rows": rows},
        )
        return {"embedded": len(records), "dim": self.dim}

    @staticmethod
    def entity_blob(name: str, entity_type: Optional[str], roles) -> str:
        """Compact routing blob for an Entity node (name + type + roles)."""
        parts = [name, entity_type]
        roles_str = ", ".join(str(r) for r in (roles or []))
        if roles_str:
            parts.append(f"roles: {roles_str}")
        return " ".join(str(p) for p in parts if p)

    def build_entity_embeddings(self, project_id: int) -> dict[str, Any]:
        """Embed every Entity node's routing blob and store it on the node."""
        rows = self.index._run_cypher(
            (
                "MATCH (e:Entity {project_id: $pid}) "
                "RETURN e.name AS name, e.entity_type AS entity_type, "
                "e.roles AS roles, e.doc_count AS doc_count"
            ),
            {"pid": project_id},
        )
        if not rows:
            return {"embedded": 0, "dim": self.dim}

        texts = [
            (DOC_PREFIX if self.use_prefixes else "") + self.entity_blob(
                row["name"], row.get("entity_type"), row.get("roles")
            )
            for row in rows
        ]
        vectors = embed_texts(texts, model=self.model, base_url=self.base_url)

        # Batch-write in one transaction.
        data = [{"name": row["name"], "vec": vec} for row, vec in zip(rows, vectors)]
        self.index._run_cypher(
            (
                "UNWIND $rows AS row "
                "MATCH (e:Entity {project_id: $pid, name: row.name}) "
                "SET e.embedding = row.vec"
            ),
            {"pid": project_id, "rows": data},
        )
        return {"embedded": len(rows), "dim": self.dim}

    # --- query -------------------------------------------------------------

    def find_best(
        self,
        project_id: int,
        query: str,
        top_k: int = 5,
        scope: Optional[list[str]] = None,
    ):
        """ANN vector search over the document embeddings.

        Returns the best matching Neo4jDocumentRecord, or None when the
        vector index is missing, no node has an embedding yet, the top
        hit fails the confidence gate (absolute floor + top1-top2 margin),
        or an embed/index error occurs.
        """
        vec = embed_texts(
            [(QUERY_PREFIX if self.use_prefixes else "") + query],
            model=self.model,
            base_url=self.base_url,
        )[0]

        try:
            rows = self.index._run_cypher(
                (
                    # Neo4j 2025.x expects (index, k, query); toFloatList() casts
                    # the JSON list so the HTTP tx endpoint binds LIST<FLOAT>.
                    "CALL db.index.vector.queryNodes($index, $k, toFloatList($vec)) "
                    "YIELD node, score "
                    "WHERE node.project_id = $pid "
                    "RETURN node.name AS name, score "
                    "ORDER BY score DESC"
                ),
                {"index": _VECTOR_INDEX_NAME, "vec": vec, "k": top_k, "pid": project_id},
            )
        except Exception:
            # Index does not exist yet (or embed step failed) -> caller falls back.
            return None
        if not rows:
            return None

        scope_set = set(scope) if scope else None
        candidates = [
            (row["score"], row["name"])
            for row in rows
            if (scope_set is None or row["name"] in scope_set)
        ]
        if not candidates:
            return None

        # Reject weak hits. nomic cosine scores are compressed (0.7-0.9 for any
        # query), so an absolute floor alone cannot separate "best of a bad set"
        # from a real match: a relevant query clears top1-top2 by ~0.06 while an
        # unrelated query's top hits sit in a tight band (~0.01). Use the margin.
        top_score = candidates[0][0]
        if top_score < self.min_score:
            return None
        if len(candidates) >= 2 and (top_score - candidates[1][0]) < self.min_margin:
            return None

        # Map hit names back to full records with one metadata read.
        by_name = {d.name: d for d in self.index.list_documents(project_id=project_id)}
        record = by_name.get(candidates[0][1])
        if record is None:
            return None
        setattr(record, "match_score", top_score)
        return record

    def find_best_entity(
        self,
        project_id: int,
        query: str,
        top_k: int = 5,
    ) -> Optional[dict[str, Any]]:
        """ANN vector search over Entity node embeddings.

        Returns a dict {name, entity_type, roles, doc_count, score} for the
        best entity, or None when the entity vector index is missing, no
        entity has an embedding yet, or the top hit fails the confidence
        gate (same absolute floor + top1-top2 margin as find_best).
        """
        vec = embed_texts(
            [(QUERY_PREFIX if self.use_prefixes else "") + query],
            model=self.model,
            base_url=self.base_url,
        )[0]

        try:
            rows = self.index._run_cypher(
                (
                    # Same (index, k, query) order + toFloatList() cast as find_best.
                    "CALL db.index.vector.queryNodes($index, $k, toFloatList($vec)) "
                    "YIELD node, score "
                    "WHERE node.project_id = $pid "
                    "RETURN node.name AS name, node.entity_type AS entity_type, "
                    "node.roles AS roles, node.doc_count AS doc_count, score "
                    "ORDER BY score DESC"
                ),
                {"index": _ENTITY_VECTOR_INDEX, "vec": vec, "k": top_k, "pid": project_id},
            )
        except Exception:
            # Index does not exist yet (or embed step failed) -> caller falls back.
            return None
        if not rows:
            return None

        top = rows[0]
        top_score = top["score"]
        if top_score < self.min_score:
            return None
        # Entity blobs are short (name + type + roles), so relevant top1-top2
        # margins are tighter than document margins (~0.02 vs ~0.06). Use the
        # dedicated entity margin; unrelated queries still sit in a tight band.
        if len(rows) >= 2 and (top_score - rows[1]["score"]) < self.min_entity_margin:
            return None

        return {
            "name": top["name"],
            "entity_type": top.get("entity_type"),
            "roles": top.get("roles") or [],
            "doc_count": int(top.get("doc_count") or 0),
            "score": top_score,
        }
