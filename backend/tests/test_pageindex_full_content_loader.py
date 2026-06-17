from pathlib import Path

from api.knowledge.rag import _load_full_content_for_kv
from models.core import ContextDocument, DocumentType


class DummyDocIndexClient:
    def __init__(self, full_doc: dict | None):
        self._full_doc = full_doc

    def get_full_content(self, doc_index_id: str):
        return self._full_doc


def test_load_full_content_for_kv_prefers_docindex_when_available(tmp_path: Path):
    context_doc = ContextDocument(
        id=1,
        filename="nke-10k-2023.pdf",
        original_filename="nke-10k-2023.pdf",
        file_path=str(tmp_path / "nke-10k-2023.pdf"),
        file_size=1,
        mime_type="application/pdf",
        document_type=DocumentType.PDF,
        doc_index_id="doc-1",
    )
    client = DummyDocIndexClient(
        {
            "id": "doc-1",
            "doc_name": "nke-10k-2023",
            "pages": [
                {"page": 1, "content": "Revenue was $51,217 million."},
                {"page": 2, "content": "More details."},
            ],
        }
    )

    doc_id, doc_name, pages_loaded, full_content = _load_full_content_for_kv(context_doc, client)

    assert doc_id == "doc-1"
    assert doc_name == "nke-10k-2023"
    assert pages_loaded == 2
    assert "Revenue was $51,217 million." in full_content


def test_load_full_content_for_kv_falls_back_to_text_file(tmp_path: Path):
    fp = tmp_path / "test_doc.txt"
    fp.write_text("hello world\n", encoding="utf-8")
    context_doc = ContextDocument(
        id=2,
        filename="test_doc.txt",
        original_filename="test_doc.txt",
        file_path=str(fp),
        file_size=11,
        mime_type="text/plain",
        document_type=DocumentType.TEXT,
        doc_index_id=None,
    )
    client = DummyDocIndexClient(None)

    doc_id, doc_name, pages_loaded, full_content = _load_full_content_for_kv(context_doc, client)

    assert doc_id == "context:2"
    assert doc_name == "test_doc.txt"
    assert pages_loaded == 0
    assert full_content.strip() == "hello world"
