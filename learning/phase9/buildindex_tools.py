#!/usr/bin/env python3
"""
Phase 9 / Step C — Build-side LangChain tool wrappers.

These wrap the existing build_graphindex.py primitives (sha256, fs scan,
Neo4j scan, upsert, doc read) as LangChain @tool so the build_agent.py
DeepAgent can call them through its subagent tool-use mechanism.

Per rules.md: stateless tools, no in-memory mutable state. Safe to call
from multiple subagents.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

from langchain_core.tools import tool  # noqa: E402

from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    Neo4jDocumentEnrichment,
    Neo4jDocumentRecord,
    build_document_node_properties,
)

import fitz  # noqa: E402

# Reuse the original graphindex module (raw llm.invoke path)
from legacy.build_graphindex import (  # noqa: E402
    DOCS_BASE,
    SUPPORTED_EXTS,
    load_document_content,
    load_graphindex_metadata,
)

_PROJECT_ID = 1

# Module-level singletons
_IDX: Optional[Neo4jDocumentIndex] = None


def _idx() -> Neo4jDocumentIndex:
    global _IDX
    if _IDX is None:
        _IDX = Neo4jDocumentIndex(
            base_url=os.getenv("NEO4J_URL", "http://localhost:7474"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
        )
    return _IDX


# --- Tool 1: sha256_of_file_tool ----------------------------------------

@tool
def sha256_of_file_tool(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file's bytes.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        64-character hex digest, or an error string if the file is missing.
    """
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"ERROR: {e}"


# --- Tool 2: scan_filesystem_for_dupe_tool -------------------------------

@tool
def scan_filesystem_for_dupe_tool(content_hash: str,
                                    root_dir: Optional[str] = None,
                                    exclude_self: str = "") -> List[str]:
    """Find files under backend/data/documents/project_* with matching SHA-256.

    Skips project_chat_sessions/ (per-session clones, not source docs).

    Args:
        content_hash: SHA-256 hex string to look for.
        root_dir: Override the docs root (defaults to backend/data/documents).
        exclude_self: Optional path to exclude from results (e.g. the source
                      file itself, if it's already in the project tree).

    Returns:
        List of existing file paths that match. Empty list = no dupe.
    """
    base = Path(root_dir) if root_dir else DOCS_BASE
    if not base.exists():
        return []
    matches: List[str] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if exclude_self and Path(p).resolve() == Path(exclude_self).resolve():
            continue
        try:
            rel = p.relative_to(base)
            top = rel.parts[0] if rel.parts else ""
        except ValueError:
            continue
        if not top.startswith("project_") or top == "project_chat_sessions":
            continue
        # Cheap: only sha256 files that are not already in matches
        if sha256_of_file_tool.invoke({"file_path": str(p)}) == content_hash:
            matches.append(str(p))
    return matches


# --- Tool 3: scan_neo4j_for_dupe_tool -----------------------------------

@tool
def scan_neo4j_for_dupe_tool(content_hash: str,
                              project_id: int = 1) -> List[str]:
    """Find Neo4j Document nodes whose content_sha256 matches.

    Args:
        content_hash: SHA-256 hex to look up.
        project_id: Neo4j project id (default 1).

    Returns:
        List of existing doc names. Empty list = no dupe.
    """
    idx = _idx()
    rows = idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, content_sha256: $h}) "
        "RETURN d.name AS name",
        {"pid": project_id, "h": content_hash},
    )
    return [r["name"] for r in rows]


# --- Tool 4: read_doc_tool -----------------------------------------------

@tool
def read_doc_tool(file_path: str, max_chars: int = 6000) -> str:
    """Read a document's content (PDF/MD/TXT) for LLM enrichment.

    Args:
        file_path: Path to the document.
        max_chars: Hard cap on returned characters (default 6000 to fit
                   in a single LLM enrichment prompt).

    Returns:
        Document text, truncated to max_chars.
    """
    try:
        content = load_document_content(file_path)
    except Exception as e:
        return f"ERROR reading: {e}"
    if len(content) > max_chars:
        return content[:max_chars] + f"\n... [truncated at {max_chars:,} chars]"
    return content


# --- Tool 5: get_graphindex_metadata_tool --------------------------------

@tool
def get_graphindex_metadata_tool(file_path: str) -> dict:
    """Read GraphIndex metadata (TOC, page_count, search_terms, content_preview)
    for a given document, if a DocIndex JSON exists for it.

    Args:
        file_path: Path to the document on disk.

    Returns:
        Dict with keys: doc_name, page_count, content_preview, search_terms, toc.
        Returns {} if no metadata is found.
    """
    try:
        return load_graphindex_metadata(file_path)
    except Exception:
        return {}


# --- Tool 6: list_other_doc_names_tool -----------------------------------

@tool
def list_other_doc_names_tool(project_id: int = 1) -> List[str]:
    """List all other document names in the project (used for enrichment
    prompts so the LLM can pick out_of_scope names).

    Args:
        project_id: Neo4j project id (default 1).

    Returns:
        List of document names.
    """
    idx = _idx()
    return [d.name for d in idx.list_documents(project_id=project_id)]


# --- Tool 7: copy_to_project_dir_tool -----------------------------------

@tool
def copy_to_project_dir_tool(source_path: str,
                               target_dir: Optional[str] = None,
                               short_hash: str = "") -> str:
    """Copy a file into backend/data/documents/project_1/ with a
    hash-prefixed name ({short_hash}_{filename}). Returns the new path.

    Args:
        source_path: Absolute path to the source file.
        target_dir: Override target directory.
        short_hash: 8-char hash prefix for the filename. Required.

    Returns:
        New file path on success, or error string.
    """
    if not short_hash:
        return "ERROR: short_hash required"
    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        return f"ERROR: source not found {src}"
    target = Path(target_dir) if target_dir else DOCS_BASE / "project_1"
    target.mkdir(parents=True, exist_ok=True)
    new_name = f"{short_hash}_{src.name}"
    target_path = target / new_name
    if target_path.exists():
        return str(target_path)  # already there
    shutil.copy2(src, target_path)
    return str(target_path)


# --- Tool 8: upsert_doc_to_neo4j_tool -----------------------------------

@tool
def upsert_doc_to_neo4j_tool(name: str, file_path: str,
                              about: str, supports: List[str],
                              out_of_scope: List[str], few_shot: List[dict],
                              description: str = "", tags: Optional[List[str]] = None,
                              project_id: int = 1) -> str:
    """Upsert a Document node in Neo4j with LLM-enriched routing metadata.

    Uses base's build_document_node_properties to construct the properties
    dict, then sets content_sha256 separately.

    Args:
        name: Exact document name.
        file_path: Path to the file on disk.
        about: LLM-generated "what this document is about" (150-300 chars).
        supports: LLM-generated list of supported query strings.
        out_of_scope: LLM-generated list of exact other-doc names.
        few_shot: LLM-generated list of {query, answer_hint} dicts.
        description: Optional description.
        tags: Optional list of tags.
        project_id: Neo4j project id (default 1).

    Returns:
        "OK" on success, or error string.
    """
    try:
        idx = _idx()
        # Reuse base's properties builder with enrichment payload
        enrichment = Neo4jDocumentEnrichment(
            what_this_document_is_about=about,
            supported_queries=supports,
            out_of_scope=out_of_scope,
            few_shot=few_shot,
        )
        properties = build_document_node_properties(
            file_path=file_path,
            name=name,
            enrichment=enrichment,
            description=description,
            tags=tags or [],
            context_doc_id=0,
            doc_index_id=None,
            project_id=project_id,
        )
        idx.upsert_document(project_id=project_id, name=name,
                            file_path=file_path, properties=properties)

        # Set content_sha256 separately (not in base's properties builder)
        content_hash = sha256_of_file_tool.invoke({"file_path": file_path})
        idx._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) "
            "SET d.content_sha256 = $h",
            {"pid": project_id, "name": name, "h": content_hash},
        )
        return "OK"
    except Exception as e:
        return f"ERROR: {e}"


# --- Tool 9: set_content_sha256_tool -------------------------------------

@tool
def set_content_sha256_tool(name: str, content_hash: str,
                              project_id: int = 1) -> str:
    """Set content_sha256 on an existing Document node.

    Args:
        name: Document name.
        content_hash: SHA-256 hex string.
        project_id: Neo4j project id (default 1).

    Returns:
        "OK" or error string.
    """
    try:
        idx = _idx()
        idx._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) "
            "SET d.content_sha256 = $h",
            {"pid": project_id, "name": name, "h": content_hash},
        )
        return "OK"
    except Exception as e:
        return f"ERROR: {e}"


# --- Tool registry -------------------------------------------------------

ALL_TOOLS = [
    sha256_of_file_tool,
    scan_filesystem_for_dupe_tool,
    scan_neo4j_for_dupe_tool,
    read_doc_tool,
    get_graphindex_metadata_tool,
    list_other_doc_names_tool,
    copy_to_project_dir_tool,
    upsert_doc_to_neo4j_tool,
    set_content_sha256_tool,
]


if __name__ == "__main__":
    # Quick smoke test
    print("sha256:", sha256_of_file_tool.invoke({"file_path":
        "/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/data/documents/project_1/31042021_nke-10k-2023.pdf"
    })[:16], "...")
    print("fs scan:", scan_filesystem_for_dupe_tool.invoke(
        {"content_hash": "deadbeef"}))