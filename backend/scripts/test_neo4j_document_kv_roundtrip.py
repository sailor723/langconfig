"""
Minimal live round-trip for a Neo4j-backed whole-document KV flow.

Flow:
1. Read project documents from PostgreSQL
2. Store each document in Neo4j as a simple Document node:
   - name
   - file_path
   - routing metadata
3. Find one document by name-based lookup
4. Load the full content from filesystem or DocIndex
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
    """Load full content from file or existing DocIndex/GraphIndex storage."""
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


def _load_graphindex_metadata(document) -> dict:
    """Load lightweight GraphIndex metadata for one document."""
    if not document.doc_index_id:
        return {}

    client = _get_doc_index_client()
    meta = client.get_document(document.doc_index_id)
    if not isinstance(meta, dict) or "error" in meta:
        return {}
    return meta


def main() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage
    from pydantic import BaseModel, Field

    from api.models.routes import _create_llm_for_playground, _resolve_model_name
    from db.database import SessionLocal
    from models.core import ContextDocument, IndexingStatus
    from services.neo4j_document_index import (
        Neo4jDocumentEnrichment,
        Neo4jDocumentIndex,
        build_document_node_properties,
        build_project_scope_names,
    )

    class FewShotExample(BaseModel):
        query: str = Field(default="")
        answer_hint: str = Field(default="")

    class DocumentEnrichmentOutput(BaseModel):
        what_this_document_is_about: str = Field(default="")
        supported_queries: list[str] = Field(default_factory=list)
        out_of_scope: list[str] = Field(default_factory=list)
        few_shot: list[FewShotExample] = Field(default_factory=list)

    def extract_document_enrichment(
        llm,
        document_name: str,
        description: str,
        tags: list[str],
        graphindex_meta: dict,
        content: str,
        other_document_names: list[str],
    ) -> Neo4jDocumentEnrichment:
        """Use the LLM to create compact routing metadata for one document."""
        structured_llm = llm.with_structured_output(DocumentEnrichmentOutput)
        content_excerpt = content[:6000]
        message = (
            "Create compact routing metadata for one document.\n"
            "We use this metadata only to choose the best document before loading full content.\n\n"
            f"Document name: {document_name}\n"
            f"Description: {description or 'N/A'}\n"
            f"Tags: {tags or []}\n"
            f"GraphIndex doc_name: {graphindex_meta.get('doc_name', '')}\n"
            f"GraphIndex page_count: {graphindex_meta.get('page_count', 0)}\n"
            f"GraphIndex content_preview: {graphindex_meta.get('content_preview', '')}\n"
            f"GraphIndex search_terms: {graphindex_meta.get('search_terms', [])[:20]}\n"
            f"Other documents in same project: {other_document_names}\n\n"
            "Return:\n"
            "1. what_this_document_is_about\n"
            "2. supported_queries\n"
            "3. out_of_scope\n"
            "4. few_shot\n\n"
            "Rules:\n"
            "- Keep it concise and routing-oriented\n"
            "- out_of_scope must be definitive where possible, using the other project documents as contrast\n"
            "- few_shot should be short examples of the kinds of questions this document can answer\n"
            "- Do not invent unsupported topics\n\n"
            f"Document excerpt:\n{content_excerpt}"
        )
        result = structured_llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You generate document routing metadata for a whole-document KV system. "
                        "Be precise, compact, and conservative."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        return Neo4jDocumentEnrichment(
            what_this_document_is_about=result.what_this_document_is_about,
            supported_queries=result.supported_queries,
            out_of_scope=result.out_of_scope,
            few_shot=[example.model_dump() for example in result.few_shot],
        )

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

        model_name = _resolve_model_name(args.model, db)
        llm = _create_llm_for_playground(
            model_name=model_name,
            temperature=0.2,
            max_tokens=1024,
            db=db,
        )
        all_document_names = [document.filename for document in documents]

        print(f"Rebuilding {len(documents)} document node(s) in Neo4j...")
        index.delete_project_documents(args.project_id)
        for document in documents:
            content = _load_document_content(document).strip()
            if not content:
                print(f"  - skipped (no content): {document.filename}")
                continue
            graphindex_meta = _load_graphindex_metadata(document)
            enrichment = extract_document_enrichment(
                llm=llm,
                document_name=document.filename,
                description=document.description or "",
                tags=list(document.tags or []),
                graphindex_meta=graphindex_meta,
                content=content,
                other_document_names=build_project_scope_names(document.filename, all_document_names),
            )
            properties = build_document_node_properties(
                project_id=args.project_id,
                context_doc_id=document.id,
                doc_index_id=document.doc_index_id,
                name=document.filename,
                file_path=document.file_path,
                description=document.description or "",
                tags=list(document.tags or []),
                graphindex_meta=graphindex_meta,
                enrichment=enrichment,
            )
            index.upsert_document(
                project_id=args.project_id,
                name=document.filename,
                file_path=document.file_path,
                properties=properties,
            )
            print(f"  - indexed: {document.filename} -> {document.file_path}")
            print(f"    about: {enrichment.what_this_document_is_about[:120]}")
            print(f"    supports: {enrichment.supported_queries[:3]}")

        matched = index.find_best_document(args.project_id, args.lookup)
        if not matched:
            raise RuntimeError(f"No document matched lookup '{args.lookup}'")

        matched_document = (
            db.query(ContextDocument)
            .filter(
                ContextDocument.project_id == args.project_id,
                ContextDocument.id == matched.context_doc_id,
            )
            .first()
        )
        if not matched_document:
            raise RuntimeError(f"Matched Neo4j node points to missing ContextDocument {matched.context_doc_id}")
        full_content = _load_document_content(matched_document).strip()
        if not full_content:
            raise RuntimeError(f"Matched document {matched.name} has no loadable content")

        print(f"\nMatched document: {matched.name}")
        print(f"File path: {matched.file_path}")
        print(f"Loaded chars: {len(full_content)}")
        if matched.what_this_document_is_about:
            print(f"About: {matched.what_this_document_is_about}")
        if matched.supported_queries:
            print(f"Supported queries: {matched.supported_queries[:3]}")
        if matched.out_of_scope:
            print(f"Out of scope: {matched.out_of_scope[:3]}")
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
                        f"Document value:\n{full_content}"
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
