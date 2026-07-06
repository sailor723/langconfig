"""
Minimal Neo4j-backed document index for whole-document KV loading.

This service intentionally stays simple:
- one Document node per uploaded document
- key = document name
- value = document pointer + routing metadata

No entity extraction, no relation extraction, no chunking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Optional

import httpx

COMMON_QUERY_STOPWORDS = {
    "a",
    "an",
    "about",
    "are",
    "can",
    "does",
    "for",
    "how",
    "in",
    "is",
    "me",
    "of",
    "show",
    "tell",
    "the",
    "this",
    "what",
    "which",
    "who",
}


@dataclass
class Neo4jDocumentRecord:
    project_id: int
    name: str
    file_path: str
    context_doc_id: int = 0
    doc_index_id: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    doc_name: str = ""
    page_count: int = 0
    content_preview: str = ""
    search_terms: list[str] = field(default_factory=list)
    what_this_document_is_about: str = ""
    supported_queries: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    few_shot: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Neo4jDocumentEnrichment:
    what_this_document_is_about: str = ""
    supported_queries: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    few_shot: list[dict[str, str]] = field(default_factory=list)


def build_project_scope_names(
    current_name: str,
    all_document_names: list[str],
    max_n: int = 30,
) -> list[str]:
    """Return other project document names for reflection-style prompts.

    Capped at ``max_n`` to keep the enrichment prompt bounded
    regardless of project size. Without this cap the LLM prompt
    grows O(N) per file: a 1000-doc project sends a 50 KB
    "other documents" header on every enrichment call, which is
    both costly (high token spend across N calls) and risky
    (LLM API may hang on very large payloads).

    The cap is set high enough (30) that the LLM still has a
    useful sample of peer doc names for ``out_of_scope`` routing;
    if a project genuinely has more than 30 docs the routing
    signal is diluted enough that ``out_of_scope`` exact-name
    matching is already not the dominant factor — instead the
    stronger ``about`` / ``supported_queries`` fields (read from
    the current doc only) carry the load.
    """
    others = sorted(name for name in all_document_names if name != current_name)
    if len(others) <= max_n:
        return others
    # Cap to max_n. We keep the prefix because in alphabetical
    # order the LLM gets a stable, predictable slice — the LLM
    # doesn't need every name, just *some* peer names for
    # `out_of_scope` cross-referencing.
    truncated = others[:max_n]
    overflow = len(others) - max_n
    # Add a synthetic marker so the LLM knows there are more
    # than it sees, but cannot use the marker as an out_of_scope
    # target (it won't exist as a real doc).
    truncated.append(f"…and {overflow} more project documents not shown")
    return truncated


def build_document_node_properties(
    project_id: int,
    context_doc_id: int,
    doc_index_id: Optional[str],
    name: str,
    file_path: str,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
    graphindex_meta: Optional[dict[str, Any]] = None,
    enrichment: Optional[Neo4jDocumentEnrichment] = None,
) -> dict[str, Any]:
    """Build a flat Neo4j property map for one document node."""
    graphindex_meta = graphindex_meta or {}
    enrichment = enrichment or Neo4jDocumentEnrichment()

    return {
        "project_id": project_id,
        "context_doc_id": context_doc_id,
        "doc_index_id": doc_index_id or "",
        "name": name,
        "file_path": file_path,
        "description": description or "",
        "tags": tags or [],
        "doc_name": graphindex_meta.get("doc_name") or name,
        "page_count": int(graphindex_meta.get("page_count") or 0),
        "content_preview": graphindex_meta.get("content_preview") or "",
        "search_terms": graphindex_meta.get("search_terms") or [],
        "what_this_document_is_about": enrichment.what_this_document_is_about,
        "supported_queries": enrichment.supported_queries,
        "out_of_scope": enrichment.out_of_scope,
        "few_shot_json": json.dumps(enrichment.few_shot, ensure_ascii=False),
        # Step N+1: hierarchy metadata. Pass-through from context_doc
        # when present (set by bulk ingest); empty string for single
        # uploads. Used by folder-scope filters in Neo4j-side queries.
        "industry": getattr(enrichment, "industry", None) or "",
        "player": getattr(enrichment, "player", None) or "",
        "sub_category": getattr(enrichment, "sub_category", None) or "",
        "sub_department": getattr(enrichment, "sub_department", None) or "",
    }


def normalize_lookup_terms(query: str) -> list[str]:
    """Build a small set of routing terms and filter generic question filler."""
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    if not normalized:
        return []

    terms: list[str] = []
    words = [word for word in re.split(r"[^a-z0-9\u4e00-\u9fff]+", normalized) if word]
    content_words = [word for word in words if word not in COMMON_QUERY_STOPWORDS]

    if content_words:
        terms.append(" ".join(content_words))
    else:
        terms.append(normalized)

    # Keep longer phrases first so routing stays focused on meaningful tokens.
    if len(content_words) >= 2:
        for size in range(len(content_words), 1, -1):
            for start in range(0, len(content_words) - size + 1):
                phrase = " ".join(content_words[start : start + size])
                if phrase and phrase not in terms:
                    terms.append(phrase)
    elif len(words) >= 2:
        for size in range(len(words), 1, -1):
            for start in range(0, len(words) - size + 1):
                phrase = " ".join(words[start : start + size])
                if phrase and phrase not in terms:
                    terms.append(phrase)

    for word in content_words or words:
        if word not in terms:
            terms.append(word)

    return terms


def choose_best_name_match(
    query: str,
    documents: list[Neo4jDocumentRecord],
) -> Optional[Neo4jDocumentRecord]:
    """Choose the best document using only document names."""
    lookup_terms = normalize_lookup_terms(query)
    if not lookup_terms:
        return None

    best_match: Optional[tuple[int, int, Neo4jDocumentRecord]] = None
    for document in documents:
        doc_name = document.name.lower()
        matched_term_length = 0
        matched_token_count = 0

        for term in lookup_terms:
            if term in doc_name:
                matched_term_length = max(matched_term_length, len(term))
                matched_token_count += 1

        if matched_term_length == 0:
            continue

        candidate = (matched_term_length, matched_token_count, document)
        if best_match is None or candidate[:2] > best_match[:2]:
            best_match = candidate

    return best_match[2] if best_match else None


def choose_best_document_match(
    query: str,
    documents: list[Neo4jDocumentRecord],
) -> Optional[Neo4jDocumentRecord]:
    """Choose the best document using enriched document node metadata."""
    lookup_terms = normalize_lookup_terms(query)
    if not lookup_terms:
        return None

    best_match: Optional[tuple[float, Neo4jDocumentRecord]] = None
    for document in documents:
        score = 0.0
        doc_name = document.name.lower()
        doc_name_alt = document.doc_name.lower()
        description = document.description.lower()
        preview = document.content_preview.lower()
        about = document.what_this_document_is_about.lower()
        tags = [str(tag).lower() for tag in document.tags]
        search_terms = [str(term).lower() for term in document.search_terms]
        supported_queries = [str(item).lower() for item in document.supported_queries]
        out_of_scope = [str(item).lower() for item in document.out_of_scope]

        for term in lookup_terms:
            if len(term) < 2:
                continue

            if term in doc_name or term in doc_name_alt:
                score += 3.0
            if description and term in description:
                score += 2.0
            if preview and term in preview:
                score += 2.0
            if about and term in about:
                score += 2.5
            if any(term in tag for tag in tags):
                score += 2.0
            if any(term in candidate for candidate in search_terms):
                score += 1.5
            if any(term in candidate for candidate in supported_queries):
                score += 3.0
            if any(term in candidate for candidate in out_of_scope):
                score -= 3.0

        if score <= 0:
            continue

        candidate = (score, document)
        if best_match is None or candidate[0] > best_match[0]:
            best_match = candidate

    if best_match is not None:
        return best_match[1]

    # No doc scored above 0 — return None rather than falling back to
    # name matching, which would happily return the first in-scope doc
    # even when the query is unrelated to any of them.
    return None


class Neo4jDocumentIndex:
    """Small HTTP-based Neo4j client for document KV indexing."""

    def __init__(
        self,
        base_url: str = "http://localhost:7474",
        username: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.database = database
        self.timeout_seconds = timeout_seconds

    @property
    def transaction_url(self) -> str:
        return f"{self.base_url}/db/{self.database}/tx/commit"

    def _run_cypher(self, statement: str, parameters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        payload = {
            "statements": [
                {
                    "statement": statement,
                    "parameters": parameters or {},
                }
            ]
        }
        response = httpx.post(
            self.transaction_url,
            auth=(self.username, self.password),
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        errors = data.get("errors", [])
        if errors:
            message = "; ".join(error.get("message", "Unknown Neo4j error") for error in errors)
            raise RuntimeError(message)

        results = data.get("results", [])
        if not results:
            return []

        columns = results[0].get("columns", [])
        rows = []
        for row in results[0].get("data", []):
            values = row.get("row", [])
            rows.append(dict(zip(columns, values)))
        return rows

    def ensure_constraints(self) -> None:
        """Create the minimal index constraint for project_id + name."""
        self._run_cypher(
            (
                "CREATE CONSTRAINT document_name_per_project IF NOT EXISTS "
                "FOR (d:Document) REQUIRE (d.project_id, d.name) IS UNIQUE"
            )
        )

    def upsert_document(self, project_id: int, name: str, file_path: str, properties: Optional[dict[str, Any]] = None) -> None:
        """Store one document pointer plus routing metadata as a Neo4j node."""
        properties = properties or build_document_node_properties(
            project_id=project_id,
            context_doc_id=0,
            doc_index_id=None,
            name=name,
            file_path=file_path,
        )
        self._run_cypher(
            (
                "MERGE (d:Document {project_id: $project_id, name: $name}) "
                "SET d += $properties "
                "REMOVE d.content"
            ),
            {"project_id": project_id, "name": name, "properties": properties},
        )

    def delete_project_documents(self, project_id: int) -> None:
        """Delete all Document nodes for one project before a clean rebuild."""
        self._run_cypher(
            "MATCH (d:Document {project_id: $project_id}) DETACH DELETE d",
            {"project_id": project_id},
        )

    def delete_document(self, project_id: int, name: str) -> bool:
        """Delete one Document node (and its relationships) by project+name.

        Step N+1: paired with the Postgres delete endpoint so the
        Knowledge Base UI's "remove doc" action also clears the
        graphindex catalog. Without this, the deleted file would
        still appear in the chat agent's `list_docs` results and
        the user would hit "doc not found" errors.

        Important: the Neo4j node's `name` field is the file's
        POST-RENAME name (after `file_storage.save_file` prefixes
        an 8-char content hash, e.g. `cfd711e3_01_tesla_q3_strategy.pdf`).
        The Postgres `ContextDocument.filename` is the ORIGINAL name
        (e.g. `01_tesla_q3_strategy.pdf`) and won't match. So callers
        should pass either the `file_path` basename OR the rename-
        prefixed name. The single-doc DELETE endpoint in rag.py tries
        `original_filename` first, then `filename`; for orphan cleanup,
        use `delete_project_documents()` (project-wide DETACH DELETE)
        which is more reliable.

        Returns True if a node was deleted, False if no matching node
        existed (e.g. doc was never indexed into Neo4j).
        """
        rows = self._run_cypher(
            (
                "MATCH (d:Document {project_id: $project_id, name: $name}) "
                "DETACH DELETE d RETURN count(d) AS deleted_count"
            ),
            {"project_id": project_id, "name": name},
        )
        return bool(rows and rows[0].get("deleted_count", 0) > 0)

    def get_document(self, project_id: int, name: str) -> Optional[Neo4jDocumentRecord]:
        """Load one document by exact name."""
        rows = self._run_cypher(
            (
                "MATCH (d:Document {project_id: $project_id, name: $name}) "
                "RETURN d.project_id AS project_id, d.context_doc_id AS context_doc_id, "
                "d.doc_index_id AS doc_index_id, d.name AS name, d.file_path AS file_path, "
                "d.description AS description, d.tags AS tags, d.doc_name AS doc_name, "
                "d.page_count AS page_count, d.content_preview AS content_preview, "
                "d.search_terms AS search_terms, d.what_this_document_is_about AS what_this_document_is_about, "
                "d.supported_queries AS supported_queries, d.out_of_scope AS out_of_scope, d.few_shot_json AS few_shot_json "
                "LIMIT 1"
            ),
            {"project_id": project_id, "name": name},
        )
        if not rows:
            return None
        row = rows[0]
        return Neo4jDocumentRecord(
            project_id=int(row["project_id"]),
            context_doc_id=int(row.get("context_doc_id") or 0),
            doc_index_id=str(row.get("doc_index_id") or ""),
            name=str(row["name"]),
            file_path=str(row.get("file_path") or ""),
            description=str(row.get("description") or ""),
            tags=list(row.get("tags") or []),
            doc_name=str(row.get("doc_name") or row["name"]),
            page_count=int(row.get("page_count") or 0),
            content_preview=str(row.get("content_preview") or ""),
            search_terms=list(row.get("search_terms") or []),
            what_this_document_is_about=str(row.get("what_this_document_is_about") or ""),
            supported_queries=list(row.get("supported_queries") or []),
            out_of_scope=list(row.get("out_of_scope") or []),
            few_shot=json.loads(row.get("few_shot_json") or "[]"),
        )

    def list_documents(
        self,
        project_id: int,
        name_only: bool = False,
    ) -> list[Neo4jDocumentRecord]:
        """List all indexed documents for a project.

        Args:
            project_id: Project identifier.
            name_only: When True, only the document names are
                returned (via `RETURN d.name`); the other fields
                on each record are left at their defaults. Use
                this when callers only need the name list (e.g.
                `build_project_scope_names` to assemble the
                "other documents" prompt header) — it avoids
                pulling 13 fields × N rows over the Neo4j HTTP
                API, which becomes painful at 1000+ docs.
        """
        if name_only:
            rows = self._run_cypher(
                "MATCH (d:Document {project_id: $project_id}) "
                "RETURN d.name AS name, d.project_id AS project_id "
                "ORDER BY d.name",
                {"project_id": project_id},
            )
            return [
                Neo4jDocumentRecord(
                    project_id=int(row["project_id"]),
                    name=str(row["name"]),
                    file_path="",
                )
                for row in rows
            ]
        rows = self._run_cypher(
            (
                "MATCH (d:Document {project_id: $project_id}) "
                "RETURN d.project_id AS project_id, d.context_doc_id AS context_doc_id, "
                "d.doc_index_id AS doc_index_id, d.name AS name, d.file_path AS file_path, "
                "d.description AS description, d.tags AS tags, d.doc_name AS doc_name, "
                "d.page_count AS page_count, d.content_preview AS content_preview, "
                "d.search_terms AS search_terms, d.what_this_document_is_about AS what_this_document_is_about, "
                "d.supported_queries AS supported_queries, d.out_of_scope AS out_of_scope, d.few_shot_json AS few_shot_json "
                "ORDER BY d.name"
            ),
            {"project_id": project_id},
        )
        return [
            Neo4jDocumentRecord(
                project_id=int(row["project_id"]),
                context_doc_id=int(row.get("context_doc_id") or 0),
                doc_index_id=str(row.get("doc_index_id") or ""),
                name=str(row["name"]),
                file_path=str(row.get("file_path") or ""),
                description=str(row.get("description") or ""),
                tags=list(row.get("tags") or []),
                doc_name=str(row.get("doc_name") or ""),
                page_count=int(row.get("page_count") or 0),
                content_preview=str(row.get("content_preview") or ""),
                search_terms=list(row.get("search_terms") or []),
                what_this_document_is_about=str(row.get("what_this_document_is_about") or ""),
                supported_queries=list(row.get("supported_queries") or []),
                out_of_scope=list(row.get("out_of_scope") or []),
                few_shot=json.loads(row.get("few_shot_json") or "[]"),
            )
            for row in rows
        ]

    def find_best_document(self, project_id: int, query: str,
                           scope: Optional[list[str]] = None) -> Optional[Neo4jDocumentRecord]:
        """Find the best document using enriched node metadata first.

        Args:
            project_id: Neo4j project id.
            query: Natural-language query to match against document metadata.
            scope: Optional list of document names to restrict search to.
                   If None or empty, searches all documents in the project.
        """
        documents = self.list_documents(project_id)
        if scope:
            scope_set = set(scope)
            documents = [d for d in documents if d.name in scope_set]
        return choose_best_document_match(query, documents)
