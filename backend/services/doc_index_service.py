"""
DocIndex Service — Vectorless, GraphIndex-style Document Indexing & Retrieval

Inspired by GraphIndex (https://github.com/VectifyAI/GraphIndex).

Core idea: progressive disclosure via TOC tree navigation.
  L1: _meta.json       — all docs with summaries
  L2: {doc_id}.json    — TOC tree (headings/pages only, no body text)
  L3: get_page_content — actual body text for selected pages

No embeddings, no chunking, no vector database needed.
"""

import os
import json
import uuid
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

DOC_INDEX_DIR = "doc_index"
META_FILE = "_meta.json"


def _normalize_text(value: Optional[str]) -> str:
    """Normalize text for vector-free matching."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _build_content_preview(pages: List[dict], max_length: int = 240) -> str:
    """Build a short preview from the first non-empty pages."""
    parts: List[str] = []
    for page in pages:
        text = (page.get("content") or "").strip()
        if text:
            parts.append(text)
        if sum(len(part) for part in parts) >= max_length:
            break

    preview = " ".join(parts)
    preview = re.sub(r"\s+", " ", preview).strip()
    return preview[:max_length]


def _build_search_terms(doc_name: str, structure: List[dict], pages: List[dict], preview: str) -> List[str]:
    """Build lightweight searchable terms for metadata-first GraphIndex routing."""
    terms: List[str] = [doc_name, preview]

    def _walk(nodes: List[dict]):
        for node in nodes:
            title = (node.get("title") or "").strip()
            if title:
                terms.append(title)
            children = node.get("children") or []
            if children:
                _walk(children)

    _walk(structure[:20])

    for page in pages[:5]:
        content = (page.get("content") or "").strip()
        if content:
            terms.append(content[:200])

    seen = set()
    normalized_terms: List[str] = []
    for term in terms:
        normalized = _normalize_text(term)
        if normalized and normalized not in seen:
            seen.add(normalized)
            normalized_terms.append(normalized)
    return normalized_terms


# ═════════════════════════════════════════════════════════════════════════════
# PDF Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _extract_pdf_toc_and_pages(file_path: str) -> dict:
    """
    Extract TOC structure and page text from a PDF using PyMuPDF (fitz).
    Returns:
    {
        "doc_name": str,
        "page_count": int,
        "toc": [{ "title": str, "page": int, "level": int, "children": [...] }],
        "pages": [{ "page": int, "content": str }]
    }
    """
    import fitz

    doc = fitz.open(file_path)

    # Extract page text
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text("text")
        pages.append({"page": i + 1, "content": text.strip()})

    # Extract TOC — PyMuPDF's get_toc() returns [(level, title, page), ...]
    raw_toc = doc.get_toc()

    doc_name = os.path.splitext(os.path.basename(file_path))[0]

    # If no TOC, create a simple structure with pages
    if not raw_toc:
        structure = []
        for i in range(len(doc)):
            structure.append({
                "title": f"Page {i + 1}",
                "page": i + 1,
                "children": []
            })
    else:
        # Build tree structure from flat TOC
        structure = _toc_list_to_tree(raw_toc)

    doc.close()

    preview = _build_content_preview(pages)
    return {
        "doc_name": doc_name,
        "page_count": len(pages),
        "structure": structure,
        "pages": pages,
        "content_preview": preview,
        "search_terms": _build_search_terms(doc_name, structure, pages, preview),
    }


def _toc_list_to_tree(toc_list: list) -> list:
    """Convert flat TOC list [(level, title, page)] into nested tree."""
    if not toc_list:
        return []

    root = []
    stack = [{"children": root}]

    # Validate: some PDFs have page=0 or -1 for non-printable items
    for level, title, page in toc_list:
        node = {
            "title": title,
            "page": page if page > 0 else None,
        }

        # Pop stack until we find the right parent level
        while len(stack) > level:
            stack.pop()

        # Ensure stack has enough levels
        while len(stack) <= level:
            # Create an intermediate container if levels jump
            container = {"title": "", "page": None, "children": []}
            if stack:
                stack[-1]["children"].append(container)
            else:
                root.append(container)
            stack.append(container)

        node["children"] = []
        stack[-1]["children"].append(node)
        stack.append(node)

    # Remove empty titles from intermediate containers
    def _clean(nodes):
        for n in nodes:
            _clean(n.get("children", []))
            if not n["title"] and not n.get("page") and not n.get("children"):
                nodes.remove(n)

    _clean(root)
    return root


def _extract_md_structure(file_path: str) -> dict:
    """Parse markdown headings into a TOC tree structure."""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    doc_name = os.path.splitext(os.path.basename(file_path))[0]

    root = []
    stack = [{"children": root}]
    line_count = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Count heading level
            level = 0
            for ch in stripped:
                if ch == "#":
                    level += 1
                else:
                    break
            title = stripped[level:].strip()
            line_num = i + 1

            node = {"title": title, "line": line_num}

            while len(stack) > level:
                stack.pop()
            while len(stack) <= level:
                container = {"title": "", "line": None, "children": []}
                if stack:
                    stack[-1]["children"].append(container)
                else:
                    root.append(container)
                stack.append(container)

            node["children"] = []
            stack[-1]["children"].append(node)
            stack.append(node)
            line_count += 1

    pages = [{"page": i + 1, "content": lines[i].strip()}
             for i in range(len(lines)) if lines[i].strip()]
    preview = _build_content_preview(pages)
    return {
        "doc_name": doc_name,
        "line_count": line_count,
        "structure": root,
        "pages": pages,
        "content_preview": preview,
        "search_terms": _build_search_terms(doc_name, root, pages, preview),
    }


# ═════════════════════════════════════════════════════════════════════════════
# DocIndex Client
# ═════════════════════════════════════════════════════════════════════════════

class DocIndexClient:
    """
    Vectorless document index for progressive-disclosure retrieval.

    Usage:
        client = DocIndexClient(workspace_path)
        doc_id = client.index("/path/to/doc.pdf")
        meta = client.get_document(doc_id)
        structure = client.get_document_structure(doc_id)
        content = client.get_page_content(doc_id, "3-5")
    """

    def __init__(self, workspace: str):
        self.workspace = Path(workspace) / DOC_INDEX_DIR
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._meta_cache: Optional[dict] = None
        self._load_meta()

    # ── Index ────────────────────────────────────────────────────────────────

    def index(self, file_path: str) -> str:
        """Index a PDF or Markdown document. Returns a doc_id."""
        file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        doc_id = str(uuid.uuid4())

        if ext == ".pdf":
            result = _extract_pdf_toc_and_pages(file_path)
        elif ext in (".md", ".markdown", ".txt"):
            result = _extract_md_structure(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        doc_entry = {
            "id": doc_id,
            "type": "pdf" if ext == ".pdf" else "md",
            "path": file_path,
            "doc_name": result["doc_name"],
            "page_count": result.get("page_count", 0),
            "content_preview": result.get("content_preview", ""),
            "search_terms": result.get("search_terms", []),
        }

        # Save full document (L2: structure + pages)
        full_doc = dict(doc_entry)
        full_doc["structure"] = result["structure"]
        full_doc["pages"] = result["pages"]
        self._save_doc(doc_id, full_doc)

        # Update meta (L1: lightweight)
        self._update_meta(doc_id, doc_entry)

        logger.info(f"DocIndex: Indexed {result['doc_name']} ({doc_id})")
        return doc_id

    def index_directory(self, dir_path: str) -> List[str]:
        """Index all supported documents in a directory. Returns list of doc_ids."""
        doc_ids = []
        supported = {".pdf", ".md", ".markdown", ".txt"}
        dir_path = os.path.abspath(dir_path)

        for fname in sorted(os.listdir(dir_path)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in supported:
                fpath = os.path.join(dir_path, fname)
                try:
                    doc_id = self.index(fpath)
                    doc_ids.append(doc_id)
                except Exception as e:
                    logger.error(f"DocIndex: Failed to index {fname}: {e}")

        return doc_ids

    # ── Storage ──────────────────────────────────────────────────────────────

    def _meta_path(self) -> Path:
        return self.workspace / META_FILE

    def _doc_path(self, doc_id: str) -> Path:
        return self.workspace / f"{doc_id}.json"

    def _load_meta(self):
        meta_path = self._meta_path()
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    self._meta_cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._meta_cache = {}
        else:
            self._meta_cache = {}

    def _save_meta(self):
        with open(self._meta_path(), "w", encoding="utf-8") as f:
            json.dump(self._meta_cache or {}, f, ensure_ascii=False, indent=2)

    def _update_meta(self, doc_id: str, entry: dict):
        if self._meta_cache is None:
            self._meta_cache = {}
        self._meta_cache[doc_id] = entry
        self._save_meta()

    def _save_doc(self, doc_id: str, doc_data: dict):
        path = self._doc_path(doc_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc_data, f, ensure_ascii=False, indent=2)

    def _load_doc(self, doc_id: str) -> Optional[dict]:
        path = self._doc_path(doc_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"DocIndex: Corrupt doc {doc_id}: {e}")
            return None

    def delete(self, doc_id: str) -> bool:
        """Delete a document from the index."""
        doc_path = self._doc_path(doc_id)
        if doc_path.exists():
            doc_path.unlink()
        if self._meta_cache and doc_id in self._meta_cache:
            del self._meta_cache[doc_id]
            self._save_meta()
        return True

    def list_all(self) -> dict:
        """L1: Return lightweight metadata for all documents (no page content)."""
        if self._meta_cache is None:
            self._load_meta()
        return self._meta_cache or {}

    # ── Retrieval ────────────────────────────────────────────────────────────

    def get_document(self, doc_id: str) -> dict:
        """L2a: Return basic document metadata."""
        if self._meta_cache and doc_id in self._meta_cache:
            return dict(self._meta_cache[doc_id])
        return {"error": f"Document {doc_id} not found"}

    def get_document_structure(self, doc_id: str) -> list:
        """L2b: Return TOC tree structure (no body text)."""
        doc = self._load_doc(doc_id)
        if not doc:
            return {"error": f"Document {doc_id} not found"}
        return doc.get("structure", [])

    def get_page_content(self, doc_id: str, pages: str) -> List[dict]:
        """
        L3: Return actual page content for specified pages.

        pages format: '5-7', '3,8', or '12' (1-indexed).
        Returns list of {"page": int, "content": str}.
        """
        doc = self._load_doc(doc_id)
        if not doc:
            return [{"error": f"Document {doc_id} not found"}]

        page_nums = _parse_pages(pages)
        all_pages = doc.get("pages", [])

        results = []
        for p in page_nums:
            for page in all_pages:
                if page.get("page") == p:
                    results.append(page)
                    break
        return results

    def get_full_content(self, doc_id: str) -> dict:
        """
        Return full content of a document, including all pages.
        
        Returns:
            {
                "doc_id": str,
                "doc_name": str,
                "type": str,
                "page_count": int,
                "structure": list,
                "pages": list of {"page": int, "content": str}
            }
        """
        doc = self._load_doc(doc_id)
        if not doc:
            return {"error": f"Document {doc_id} not found"}
        return doc

    def search(self, query: str, doc_ids: Optional[List[str]] = None) -> List[dict]:
        """
        LLM-guided search across documents.

        This returns the structure + summaries for all matching docs so the LLM
        can decide which pages to read next. No vector similarity involved.
        """
        results = []
        meta = self.list_all()

        for doc_id, entry in meta.items():
            if doc_ids and doc_id not in doc_ids:
                continue
            doc = self._load_doc(doc_id)
            if not doc:
                continue

            # Return structure without heavy page content — LLM navigates further
            results.append({
                "doc_id": doc_id,
                "doc_name": entry.get("doc_name", ""),
                "type": entry.get("type", ""),
                "page_count": entry.get("page_count", 0),
                "structure": doc.get("structure", []),
            })

        return results


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _parse_pages(pages_str: str) -> List[int]:
    """Parse a pages string like '5-7', '3,8', or '12' into sorted int list."""
    result = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.extend(range(int(start.strip()), int(end.strip()) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_doc_index_clients: dict = {}


def get_doc_index(workspace: str) -> DocIndexClient:
    """Get or create a DocIndexClient for the given workspace."""
    if workspace not in _doc_index_clients:
        _doc_index_clients[workspace] = DocIndexClient(workspace)
    return _doc_index_clients[workspace]
