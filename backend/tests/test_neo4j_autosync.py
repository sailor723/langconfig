from api.knowledge import rag
from models.core import ContextDocument, DocumentType, IndexingStatus


class DummyDocIndexClient:
    def get_document(self, doc_index_id: str):
        return {
            "doc_name": "department survey",
            "page_count": 3,
            "content_preview": "survey preview",
            "search_terms": ["department", "survey"],
        }


class DummyNeo4jIndex:
    def __init__(self):
        self.upserts: list[dict] = []

    def ensure_constraints(self) -> None:
        return

    def upsert_document(self, project_id: int, name: str, file_path: str, properties: dict | None = None) -> None:
        self.upserts.append(
            {
                "project_id": project_id,
                "name": name,
                "file_path": file_path,
                "properties": properties or {},
            }
        )


def test_try_sync_context_document_to_neo4j_upserts_pointer_metadata(monkeypatch):
    dummy = DummyNeo4jIndex()
    monkeypatch.setattr(rag, "_get_neo4j_document_index", lambda: dummy)

    context_doc = ContextDocument(
        id=123,
        filename="department survey.pdf",
        original_filename="department survey.pdf",
        file_path="/tmp/department_survey.pdf",
        file_size=1,
        mime_type="application/pdf",
        document_type=DocumentType.PDF,
        indexing_status=IndexingStatus.READY,
        project_id=1,
        doc_index_id="doc-123",
        description="Survey results",
        tags=["hr"],
    )
    client = DummyDocIndexClient()

    rag._try_sync_context_document_to_neo4j(context_doc, client)

    assert len(dummy.upserts) == 1
    payload = dummy.upserts[0]["properties"]
    assert payload["project_id"] == 1
    assert payload["context_doc_id"] == 123
    assert payload["doc_index_id"] == "doc-123"
    assert payload["name"] == "department survey.pdf"
    assert payload["file_path"] == "/tmp/department_survey.pdf"
    assert payload["doc_name"] == "department survey"
    assert payload["page_count"] == 3
    assert payload["content_preview"] == "survey preview"
    assert payload["search_terms"] == ["department", "survey"]
    assert "content" not in payload
