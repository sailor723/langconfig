from api.knowledge import rag
from services.neo4j_document_index import Neo4jDocumentRecord


class DummyDocIndexClient:
    def get_document_structure(self, doc_index_id: str):
        return [{"title": "Section 1"}]


class DummyNeo4jIndex:
    def ensure_constraints(self) -> None:
        return

    def find_best_document(self, project_id: int, query: str):
        return Neo4jDocumentRecord(
            project_id=project_id,
            context_doc_id=7,
            doc_index_id="doc-7",
            name="Departmental Survey for Biz Strategy.pdf",
            doc_name="Departmental Survey for Biz Strategy",
            file_path="/tmp/department.pdf",
            page_count=12,
            content_preview="department survey preview",
            search_terms=["department", "survey"],
        )


def test_try_graphindex_search_via_neo4j_returns_one_document(monkeypatch):
    monkeypatch.setattr(rag, "_get_neo4j_document_index", lambda: DummyNeo4jIndex())
    result = rag._try_graphindex_search_via_neo4j(
        project_id=1,
        query="please show me department survey",
        top_k=10,
        client=DummyDocIndexClient(),
    )

    assert result is not None
    assert result.search_mode == "graphindex"
    assert result.total_documents == 1
    assert result.documents[0].doc_id == "doc-7"
    assert result.documents[0].doc_name == "Departmental Survey for Biz Strategy"
    assert result.documents[0].type == "pdf"
    assert result.documents[0].page_count == 12
    assert result.documents[0].structure == [{"title": "Section 1"}]
