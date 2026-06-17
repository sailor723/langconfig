"""
Tests for enriching Neo4j document nodes with GraphIndex metadata plus
LLM-generated routing metadata.
"""

from services.neo4j_document_index import (
    Neo4jDocumentEnrichment,
    build_document_node_properties,
    build_project_scope_names,
)


def test_build_project_scope_names_excludes_current_document():
    names = build_project_scope_names(
        current_name="nke-10k-2023.pdf",
        all_document_names=["人物库.pdf", "nke-10k-2023.pdf", "pricing-policy.md"],
    )

    assert names == ["pricing-policy.md", "人物库.pdf"]


def test_build_document_node_properties_keeps_graphindex_and_llm_metadata():
    enrichment = Neo4jDocumentEnrichment(
        what_this_document_is_about="Nike annual report focused on company financials.",
        supported_queries=[
            "what is nike revenue",
            "summarize nike revenue recognition",
        ],
        out_of_scope=[
            "executive biography details",
            "people profiles covered by 人物库.pdf",
        ],
        few_shot=[
            {
                "query": "what is nike revenue",
                "answer_hint": "Look for the annual revenue figure in the financial summary.",
            }
        ],
    )

    properties = build_document_node_properties(
        project_id=1,
        context_doc_id=6,
        doc_index_id="doc-6",
        name="nke-10k-2023.pdf",
        file_path="/tmp/nke-10k-2023.pdf",
        description="Nike annual report",
        tags=["finance", "annual-report"],
        graphindex_meta={
            "doc_name": "nke-10k-2023",
            "page_count": 108,
            "content_preview": "Nike annual report preview",
            "search_terms": ["nike", "revenue", "annual report"],
        },
        enrichment=enrichment,
    )

    assert properties["project_id"] == 1
    assert properties["context_doc_id"] == 6
    assert properties["doc_index_id"] == "doc-6"
    assert properties["name"] == "nke-10k-2023.pdf"
    assert properties["file_path"] == "/tmp/nke-10k-2023.pdf"
    assert "content" not in properties
    assert properties["description"] == "Nike annual report"
    assert properties["tags"] == ["finance", "annual-report"]
    assert properties["doc_name"] == "nke-10k-2023"
    assert properties["page_count"] == 108
    assert properties["content_preview"] == "Nike annual report preview"
    assert properties["search_terms"] == ["nike", "revenue", "annual report"]
    assert properties["what_this_document_is_about"].startswith("Nike annual report")
    assert "what is nike revenue" in properties["supported_queries"]
    assert "executive biography details" in properties["out_of_scope"]
    assert '"query": "what is nike revenue"' in properties["few_shot_json"]
