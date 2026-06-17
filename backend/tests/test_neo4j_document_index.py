"""
Mock tests for a minimal Neo4j-style document index.

Goal:
- keep PageIndex in place
- add a tiny document index prototype beside it
- use document name as the key and full content as the value
- prove the minimal routing behavior before touching backend code
"""

from services.neo4j_document_index import (
    Neo4jDocumentRecord,
    choose_best_name_match,
    normalize_lookup_terms,
)


def test_normalize_lookup_terms_prefers_longer_terms():
    terms = normalize_lookup_terms("what is nike revenue")

    assert "what is nike revenue" in terms
    assert "nike revenue" in terms
    assert "nike" in terms
    assert "revenue" in terms


def test_choose_best_name_match_finds_partial_name_match():
    documents = [
        Neo4jDocumentRecord(project_id=1, name="人物库", content="people content"),
        Neo4jDocumentRecord(project_id=1, name="nike-10k-2023", content="nike content"),
    ]

    matched = choose_best_name_match("what is nike revenue", documents)

    assert matched is not None
    assert matched.name == "nike-10k-2023"


def test_choose_best_name_match_returns_none_when_name_has_no_overlap():
    documents = [
        Neo4jDocumentRecord(project_id=1, name="人物库", content="people content"),
        Neo4jDocumentRecord(project_id=1, name="huawei cloud deployment", content="cloud content"),
    ]

    matched = choose_best_name_match("what is nike revenue", documents)

    assert matched is None
