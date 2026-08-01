# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Cross-cutting helpers for the api.knowledge.rag package.

Split out of api/knowledge/rag.py; moved verbatim.
"""
import os as _os
from datetime import datetime
from pathlib import Path
from typing import List

from models.core import ContextDocument, IndexingStatus

from .schemas import DocumentContentResponse
from .shared import logger

SUPPORTED_GRAPHINDEX_EXTS: set[str] = {
    ".pdf", ".txt", ".md", ".html", ".csv", ".json",
    ".xml", ".yaml", ".yml", ".py", ".js", ".ts",
    ".java", ".cpp", ".hpp", ".c", ".h", ".rb", ".go",
    ".rs", ".swift", ".kt", ".scala",
}


def _is_graphindexable(filename: str) -> bool:
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_GRAPHINDEX_EXTS

def _queue_graphindex_ingest(file_path: str, project_id: int = 1) -> None:
    """Run cmd_ingest on the uploaded file to create a Neo4j Document node.

    This is called as a background task after a file has been uploaded and
    saved to disk. It runs the same Phase 9 ingestion pipeline as the CLI:
    hash → dedup (FS + Neo4j) → copy → LLM enrichment → upsert to Neo4j.
    """
    try:
        from learning.phase9.graphindex.index_build import (
            make_llm, cmd_ingest, Neo4jDocumentIndex,
        )
        index = Neo4jDocumentIndex(
            base_url=_os.environ.get("NEO4J_URL", "http://localhost:7474"),
            username=_os.environ.get("NEO4J_USER", "neo4j"),
            password=_os.environ.get("NEO4J_PASSWORD", "password"),
        )
        index.ensure_constraints()
        llm = make_llm()
        cmd_ingest(index, llm, file_path, project_id=project_id)
    except Exception as e:
        logger.error(f"graphindex ingest failed for {file_path}: {e}")

async def index_document_background(document_id: int):
    """Background task to index a document for both vector RAG and GraphIndex."""
    from db.database import SessionLocal
    from services.context_document_indexer import context_document_indexer

    db = SessionLocal()
    try:
        doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found for indexing")
            return

        if not doc.file_path:
            logger.error(f"Document {document_id} has no file_path")
            doc.indexing_status = IndexingStatus.FAILED
            db.commit()
            return

        # Update status to indexing
        doc.indexing_status = IndexingStatus.INDEXING
        file_path = doc.file_path  # Save for later use
        db.commit()
        db.close()

        vector_result = None
        vector_error = None

        # Index the document for vector RAG.
        try:
            vector_result = await context_document_indexer.index_document(
                document_id=document_id,
                file_path=file_path
            )
        except Exception as ve:
            vector_error = ve
            logger.warning(f"Vector indexing failed for {document_id}: {ve}")

        # Update status with new session
        db = SessionLocal()
        doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
        if doc:
            if vector_result:
                doc.indexed_chunks_count = vector_result.get("embeddings_stored", 0)
                doc.indexing_status = IndexingStatus.READY
                doc.indexed_at = datetime.utcnow()
            else:
                doc.indexing_status = IndexingStatus.FAILED
            db.commit()
        db.close()

        if vector_result:
            logger.info(f"Document {document_id} indexed successfully")
        else:
            logger.warning(f"Vector indexing failed for {document_id} — document available via GraphIndex only.")

    except Exception as e:
        logger.error(f"Failed to index document {document_id}: {e}", exc_info=True)
        # Create fresh session for error handling
        try:
            db.close()
        except Exception:
            pass

        db = SessionLocal()
        try:
            doc = db.query(ContextDocument).filter(ContextDocument.id == document_id).first()
            if doc:
                doc.indexing_status = IndexingStatus.FAILED
                db.commit()
        finally:
            db.close()

def _extract_text_for_viewer(file_path: Path, ext: str, max_chars: int = 500_000) -> DocumentContentResponse:
    """Extract the text/markdown/csv/structured content for inline viewing.

    Mirrors the extraction logic in `_load_full_content_for_kv` so the
    Knowledge panel viewer shows the same content that search/answer uses.
    """
    ext = ext.lower()

    # Markdown
    if ext == ".md" or ext == ".markdown":
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # CSV — render as a 2D table
    if ext == ".csv":
        import csv as _csv
        rows: List[List[str]] = []
        with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = _csv.reader(f)
            for i, row in enumerate(reader):
                if i >= 5000:  # cap rows to keep payload reasonable
                    break
                rows.append(row)
        return DocumentContentResponse(
            kind="csv",
            content="",
            rows=rows,
            truncated=len(rows) >= 5000,
        )

    # HTML — wrap in a sandboxed iframe on the client
    if ext in (".html", ".htm"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="html",
            content=text[:max_chars],
            truncated=truncated,
        )

    # JSON
    if ext == ".json":
        try:
            import json as _json
            data = _json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
            formatted = _json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            formatted = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(formatted) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=formatted[:max_chars],
            truncated=truncated,
        )

    # YAML — treat as plain code (no parser dependency)
    if ext in (".yaml", ".yml"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=text[:max_chars],
            truncated=truncated,
        )

    # DOCX (Word)
    if ext == ".docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(file_path))
            parts: list[str] = []
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            # Also pull table cells
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
            text = "\n\n".join(parts)
        except Exception as e:
            logger.warning(f"docx parse failed for {file_path}: {e}")
            text = f"[Failed to parse .docx: {e}]"
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # PPTX (PowerPoint)
    if ext == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(str(file_path))
            parts: list[str] = []
            for slide_idx, slide in enumerate(prs.slides, start=1):
                parts.append(f"## Slide {slide_idx}")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            text = "".join(run.text for run in para.runs).strip()
                            if text:
                                parts.append(text)
                parts.append("")
            text = "\n\n".join(parts).strip()
        except Exception as e:
            logger.warning(f"pptx parse failed for {file_path}: {e}")
            text = f"[Failed to parse .pptx: {e}]"
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="markdown",
            content=text[:max_chars],
            truncated=truncated,
        )

    # XLSX (Excel) — return all sheets as rows
    if ext == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
            sheet_names = wb.sheetnames
            all_rows: list[list[list[str]]] = []
            for sheet_name in sheet_names:
                ws = wb[sheet_name]
                rows: list[list[str]] = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 5000:
                        break
                    rows.append(["" if v is None else str(v) for v in row])
                all_rows.append(rows)
            # Also build a flat markdown view of the first sheet
            text = ""
            if sheet_names:
                text = f"# {sheet_names[0]}\n\n"
                if all_rows and all_rows[0]:
                    header = all_rows[0][0]
                    text += "| " + " | ".join(header) + " |\n"
                    text += "| " + " | ".join(["---"] * len(header)) + " |\n"
                    for row in all_rows[0][1:50]:
                        text += "| " + " | ".join(row) + " |\n"
            return DocumentContentResponse(
                kind="csv",  # frontend uses 'csv' to render as a table; sheet_names makes it multi-sheet
                content=text,
                rows=all_rows[0] if all_rows else [],
                sheet_names=sheet_names,
                sheet_rows=all_rows,
                truncated=any(len(r) >= 5000 for r in all_rows),
            )
        except Exception as e:
            logger.warning(f"xlsx parse failed for {file_path}: {e}")
            return DocumentContentResponse(
                kind="plain",
                content=f"[Failed to parse .xlsx: {e}]",
                truncated=False,
            )

    # Plain text + code files
    if ext in (".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp",
               ".c", ".h", ".hpp", ".rb", ".go", ".rs", ".swift", ".kt",
               ".scala", ".sh", ".bash", ".sql", ".xml", ".log"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(text) > max_chars
        return DocumentContentResponse(
            kind="code",
            content=text[:max_chars],
            truncated=truncated,
        )

    # Fallback — try to decode as UTF-8 text, else surface a hint
    try:
        text = file_path.read_text(encoding="utf-8")
        return DocumentContentResponse(kind="plain", content=text, truncated=False)
    except Exception:
        return DocumentContentResponse(
            kind="plain",
            content=f"[Binary file: {file_path.name} — open in new tab to download]",
            truncated=False,
        )
