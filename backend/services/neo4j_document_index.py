"""
Minimal Neo4j-backed document index for whole-document KV loading.

This service intentionally stays simple:
- one Document node per uploaded document
- key = document name
- value = full document content

No entity extraction, no relation extraction, no chunking.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

import httpx


@dataclass
class Neo4jDocumentRecord:
    project_id: int
    name: str
    content: str


def normalize_lookup_terms(query: str) -> list[str]:
    """Build a small set of query terms for name-based lookup."""
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    if not normalized:
        return []

    terms: list[str] = [normalized]
    words = [word for word in re.split(r"[^a-z0-9\u4e00-\u9fff]+", normalized) if word]

    # Keep longer phrases first so name matching stays focused.
    if len(words) >= 2:
        for size in range(len(words), 1, -1):
            for start in range(0, len(words) - size + 1):
                phrase = " ".join(words[start : start + size])
                if phrase and phrase not in terms:
                    terms.append(phrase)

    for word in words:
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

    def upsert_document(self, project_id: int, name: str, content: str) -> None:
        """Store one whole document as a simple Neo4j node."""
        self._run_cypher(
            (
                "MERGE (d:Document {project_id: $project_id, name: $name}) "
                "SET d.content = $content"
            ),
            {"project_id": project_id, "name": name, "content": content},
        )

    def get_document(self, project_id: int, name: str) -> Optional[Neo4jDocumentRecord]:
        """Load one document by exact name."""
        rows = self._run_cypher(
            (
                "MATCH (d:Document {project_id: $project_id, name: $name}) "
                "RETURN d.project_id AS project_id, d.name AS name, d.content AS content "
                "LIMIT 1"
            ),
            {"project_id": project_id, "name": name},
        )
        if not rows:
            return None
        row = rows[0]
        return Neo4jDocumentRecord(
            project_id=int(row["project_id"]),
            name=str(row["name"]),
            content=str(row["content"]),
        )

    def list_documents(self, project_id: int) -> list[Neo4jDocumentRecord]:
        """List all indexed documents for a project."""
        rows = self._run_cypher(
            (
                "MATCH (d:Document {project_id: $project_id}) "
                "RETURN d.project_id AS project_id, d.name AS name, d.content AS content "
                "ORDER BY d.name"
            ),
            {"project_id": project_id},
        )
        return [
            Neo4jDocumentRecord(
                project_id=int(row["project_id"]),
                name=str(row["name"]),
                content=str(row["content"]),
            )
            for row in rows
        ]

    def find_best_document(self, project_id: int, query: str) -> Optional[Neo4jDocumentRecord]:
        """Find the best document using simple name-based matching."""
        documents = self.list_documents(project_id)
        return choose_best_name_match(query, documents)
