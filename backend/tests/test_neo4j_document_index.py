"""
Mock tests for a minimal Neo4j-style document index.

Goal:
- keep GraphIndex in place
- add a tiny document index prototype beside it
- use document name as the key and full content as the value
- prove the minimal routing behavior before touching backend code
"""

from services.neo4j_document_index import (
    Neo4jDocumentRecord,
    choose_best_document_match,
    choose_best_name_match,
    normalize_lookup_terms,
)


def test_normalize_lookup_terms_prefers_longer_terms():
    terms = normalize_lookup_terms("what is nike revenue")

    assert "nike revenue" in terms
    assert "nike" in terms
    assert "revenue" in terms


def test_choose_best_name_match_finds_partial_name_match():
    documents = [
        Neo4jDocumentRecord(project_id=1, name="人物库", file_path="/tmp/people.pdf"),
        Neo4jDocumentRecord(project_id=1, name="nike-10k-2023", file_path="/tmp/nike.pdf"),
    ]

    matched = choose_best_name_match("what is nike revenue", documents)

    assert matched is not None
    assert matched.name == "nike-10k-2023"


def test_choose_best_name_match_returns_none_when_name_has_no_overlap():
    documents = [
        Neo4jDocumentRecord(project_id=1, name="人物库", file_path="/tmp/people.pdf"),
        Neo4jDocumentRecord(project_id=1, name="huawei cloud deployment", file_path="/tmp/cloud.pdf"),
    ]

    matched = choose_best_name_match("what is nike revenue", documents)

    assert matched is None


def test_choose_best_document_match_uses_supported_queries_and_preview():
    documents = [
        Neo4jDocumentRecord(
            project_id=1,
            name="人物库.pdf",
            file_path="/tmp/people.pdf",
            what_this_document_is_about="Profiles of entrepreneurs and philosopher pairings.",
            supported_queries=["which entrepreneur matches nietzsche"],
            content_preview="Jobs Musk Confucius Nietzsche pairings",
            search_terms=["jobs", "musk", "nietzsche", "pairings"],
        ),
        Neo4jDocumentRecord(
            project_id=1,
            name="nke-10k-2023.pdf",
            file_path="/tmp/nike.pdf",
            what_this_document_is_about="Nike annual report and financial statements.",
            supported_queries=["what is nike revenue", "nike annual report 2023 financials"],
            content_preview="Nike revenue recognition and total annual revenues",
            search_terms=["nike", "revenue", "annual report"],
        ),
    ]

    matched = choose_best_document_match("what is nike revenue", documents)

    assert matched is not None
    assert matched.name == "nke-10k-2023.pdf"


def test_choose_best_document_match_ignores_generic_question_words():
    documents = [
        Neo4jDocumentRecord(
            project_id=1,
            name="test_doc.txt",
            file_path="/tmp/test.txt",
            what_this_document_is_about="Placeholder test content.",
            supported_queries=["what is in the test document"],
            search_terms=["test", "placeholder"],
        ),
        Neo4jDocumentRecord(
            project_id=1,
            name="nke-10k-2023.pdf",
            file_path="/tmp/nike.pdf",
            what_this_document_is_about="Nike annual report and financial statements.",
            supported_queries=["what is nike revenue"],
            search_terms=["nike", "revenue", "annual report"],
        ),
    ]

    matched = choose_best_document_match("what is nike revenue", documents)

    assert matched is not None
    assert matched.name == "nke-10k-2023.pdf"
