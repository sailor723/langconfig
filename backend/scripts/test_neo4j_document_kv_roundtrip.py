"""
Minimal live round-trip for a Neo4j-backed whole-document KV flow.

Flow:
1. Read project documents from PostgreSQL
2. Store each document in Neo4j as a simple Document node:
   - name
   - content
3. Find one document by name-based lookup
4. Load the full content
5. Ask the configured LLM using that single document as KV context

Usage examples:
    ./.venv/bin/python3 scripts/test_neo4j_document_kv_roundtrip.py --project-id 1 --lookup "nke-10k" --question "what is nike revenue"
    ./.venv/bin/python3 scripts/test_neo4j_document_kv_roundtrip.py --project-id 1 --lookup "人物库" --question "这份文档主要讲什么"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

def _get_doc_index_client():
    from services.doc_index_service import DocIndexClient

    outputs_dir = Path(__file__).resolve().parents[1] / "outputs"
    return DocIndexClient(str(outputs_dir))


def _load_document_content(document) -> str:
    """Load full content from file or existing DocIndex/PageIndex storage."""
    from models.core import DocumentType
    from pypdf import PdfReader

    if document.document_type in {DocumentType.TEXT, DocumentType.MARKDOWN, DocumentType.JSON, DocumentType.YAML}:
        return Path(document.file_path).read_text(encoding="utf-8", errors="ignore")

    if document.doc_index_id:
        client = _get_doc_index_client()
        full_doc = client.get_full_content(document.doc_index_id)
        pages = full_doc.get("pages", [])
        return "\n\n".join(
            f"[Page {page.get('page', '?')}]\n{page.get('content', '')}"
            for page in pages
            if page.get("content")
        )

    if document.document_type == DocumentType.PDF:
        # Fallback for documents that are vector-indexed but not available in DocIndex.
        reader = PdfReader(document.file_path)
        page_texts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                page_texts.append(text)
        return "\n\n".join(page_texts)

    return document.content_preview or ""


def main() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from api.models.routes import _create_llm_for_playground, _resolve_model_name
    from db.database import SessionLocal
    from models.core import ContextDocument, IndexingStatus
    from services.neo4j_document_index import Neo4jDocumentIndex

    parser = argparse.ArgumentParser(description="Simple Neo4j document KV round-trip")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--lookup", type=str, required=True, help="Document-name lookup text")
    parser.add_argument("--question", type=str, required=True, help="Question to ask after loading the matched document")
    parser.add_argument("--model", type=str, default=None, help="Optional explicit model name")
    parser.add_argument("--neo4j-url", type=str, default="http://localhost:7474")
    parser.add_argument("--neo4j-user", type=str, default="neo4j")
    parser.add_argument("--neo4j-password", type=str, default="password")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        index = Neo4jDocumentIndex(
            base_url=args.neo4j_url,
            username=args.neo4j_user,
            password=args.neo4j_password,
        )
        index.ensure_constraints()

        documents = (
            db.query(ContextDocument)
            .filter(
                ContextDocument.project_id == args.project_id,
                ContextDocument.indexing_status == IndexingStatus.READY,
            )
            .all()
        )
        if not documents:
            raise RuntimeError(f"No ready documents found for project {args.project_id}")

        print(f"Indexing {len(documents)} document(s) into Neo4j...")
        for document in documents:
            content = _load_document_content(document).strip()
            if not content:
                print(f"  - skipped (no content): {document.filename}")
                continue
            index.upsert_document(
                project_id=args.project_id,
                name=document.filename,
                content=content,
            )
            print(f"  - indexed: {document.filename} ({len(content)} chars)")

        matched = index.find_best_document(args.project_id, args.lookup)
        if not matched:
            raise RuntimeError(f"No document matched lookup '{args.lookup}'")

        print(f"\nMatched document: {matched.name}")
        print(f"Loaded chars: {len(matched.content)}")

        model_name = _resolve_model_name(args.model, db)
        llm = _create_llm_for_playground(
            model_name=model_name,
            temperature=0.2,
            max_tokens=1024,
            db=db,
        )
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You answer using one selected document only.\n"
                        "Treat the document as a key-value source.\n"
                        "Key: document name.\n"
                        "Value: full document content.\n"
                        "Do not use outside knowledge."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Document key: {matched.name}\n"
                        f"User question: {args.question}\n\n"
                        f"Document value:\n{matched.content}"
                    )
                ),
            ]
        )
        print("\nAnswer:\n")
        print(response.content if isinstance(response.content, str) else str(response.content))
    finally:
        db.close()


if __name__ == "__main__":
    main()
