#!/usr/bin/env python3
"""
Phase 9 / Step 2.5 — complete GraphIndex builder.

Reuses the base project's Neo4j types and helpers (services/neo4j_document_index.py)
but adds an actual enrichment pipeline that the production sync in
backend/api/knowledge/rag.py never runs (it passes enrichment=None).

The enrichment generator (`extract_document_enrichment`) was lifted from
backend/scripts/test_neo4j_document_kv_roundtrip.py — it lived as a nested
function inside a script and was effectively dead code. We extract it to
module level so we can call it from anywhere, and we swap the LLM to
MiniMax M3 (consistent with dv_chat.py).

Commands:
  --show <name>           Dump the current node + enrichment for one doc
  --rebuild-one <name>    Rebuild enrichment for one doc (LLM call)
  --rebuild-project       Rebuild enrichment for every Document node (LLM call)
  --query <text>          Run choose_best_document_match on a query
  --no-llm                Skip enrichment, only show / query
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# .env resolution (works as script AND in REPL)
try:
    _env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
except NameError:
    _env_path = Path(os.getcwd()) / ".env"
if not _env_path.exists():
    _alt = Path(os.getcwd()).parent / ".env"
    if _alt.exists():
        _env_path = _alt
load_dotenv(_env_path)

# Reuse base's Neo4j types + helpers
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentEnrichment,
    Neo4jDocumentIndex,
    build_document_node_properties,
    build_project_scope_names,
    choose_best_document_match,
)

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

# --- Local defaults (domain logic, not configuration) ----------------------
_DOCS_BASE = REPO_ROOT / "backend/data/documents"
_SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt"}
_PROJECT_ID = int(os.getenv("GRAPHINDEX_DEFAULT_PROJECT_ID", "1"))


# --- Document loading (lifted from scripts/test_neo4j_document_kv_roundtrip.py) -

def _read_pdf_text(file_path: Path) -> str:
    """Read a PDF with PyMuPDF (preferred; already used by dv_chat.py)."""
    import fitz
    doc = fitz.open(str(file_path))
    parts: List[str] = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        if text:
            parts.append(f"--- Page {i+1}/{len(doc)} ---\n{text}")
    doc.close()
    return "\n\n".join(parts)


def _read_text_file(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="ignore")


def load_document_content(file_path: str) -> str:
    """Read the full text of a document based on its file extension."""
    p = Path(file_path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _read_pdf_text(p)
    if ext in {".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}:
        return _read_text_file(p)
    return _read_text_file(p)


def load_graphindex_metadata(file_path: str) -> dict:
    """For now we don't have a DocIndex client here; the full content is
    enough for the LLM to derive everything it needs. Returned as {} for
    compatibility with the build_document_node_properties signature."""
    return {}


# --- Enrichment schema (lifted from scripts/test_neo4j_document_kv_roundtrip.py) ---

class FewShotExample(BaseModel):
    query: str = Field(default="")
    answer_hint: str = Field(default="")


class DocumentEnrichmentOutput(BaseModel):
    what_this_document_is_about: str = Field(
        default="",
        description="One-sentence description of what this document covers.",
    )
    supported_queries: List[str] = Field(
        default_factory=list,
        description="Natural-language questions this document can answer.",
    )
    out_of_scope: List[str] = Field(
        default_factory=list,
        description="Topics this document does NOT cover (include names of other "
                    "project documents that handle those topics).",
    )
    few_shot: List[FewShotExample] = Field(default_factory=list)


# --- LLM + enrichment (lifted from scripts/test_neo4j_document_kv_roundtrip.py) --

def make_llm() -> BaseChatModel:
    if not os.getenv("MINIMAX_API_KEY"):
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        sys.exit(1)
    return init_chat_model(
        model=os.getenv("GRAPHINDEX_MODEL", "minimax-m3"),
        model_provider="openai",
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0.2,
        max_tokens=2048,
    )


def extract_document_enrichment(
    llm: BaseChatModel,
    document_name: str,
    description: str,
    tags: List[str],
    graphindex_meta: dict,
    content: str,
    other_document_names: List[str],
) -> Neo4jDocumentEnrichment:
    """Use the LLM to create compact routing metadata for one document.

    Lifted from backend/scripts/test_neo4j_document_kv_roundtrip.py:103-160
    and adapted to use MiniMax M3 via init_chat_model.
    """
    structured_llm = llm.with_structured_output(DocumentEnrichmentOutput)
    content_excerpt = content[:6000]  # keep prompt bounded
    message = (
        "Create compact routing metadata for one document.\n"
        "We use this metadata only to choose the best document before "
        "loading full content.\n\n"
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
        "CRITICAL — out_of_scope format rules:\n"
        "- Each entry MUST be a single, exact document name from the list above\n"
        "- Do NOT group multiple documents into one string\n"
        "- Do NOT add phrases like 'see X' or 'and Y' — just the bare name\n"
        "- Example (correct): ['6 人物库.pdf', 'Deep Learning in Healthcare.pdf']\n"
        "- Example (WRONG): ['Biographical profiles (see 6 人物库.pdf)']\n"
        "- The scoring algorithm does exact substring match against these names,\n"
        "  so any extra text breaks routing.\n\n"
        "Other rules:\n"
        "- Keep it concise and routing-oriented\n"
        "- supported_queries are the natural questions this doc can answer\n"
        "- few_shot should be short examples of the kinds of questions "
        "this document can answer\n"
        "- Do not invent unsupported topics\n\n"
        f"Document excerpt:\n{content_excerpt}"
    )
    try:
        result = structured_llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Be precise, compact, and conservative. "
                "Do NOT include any <think> blocks or commentary in your output — "
                "return only the JSON object matching the schema."
            )),
            HumanMessage(content=message),
        ])
    except Exception as e:
        # MiniMax sometimes wraps its answer in <think>...</think> despite instructions.
        # Fall back to a plain text call and strip the reasoning block.
        print(f"    (structured output failed, retrying plain: {e})")
        resp = llm.invoke([
            SystemMessage(content=(
                "You generate document routing metadata for a whole-document "
                "KV system. Reply with ONLY a JSON object matching this schema:\n"
                '{"what_this_document_is_about": str, '
                '"supported_queries": [str], '
                '"out_of_scope": [str], '
                '"few_shot": [{"query": str, "answer_hint": str}]}\n'
                "CRITICAL: each out_of_scope entry MUST be a single, exact "
                "document name (e.g. '6 人物库.pdf'). Do NOT group names. "
                "Do NOT include <think> blocks or commentary."
            )),
            HumanMessage(content=message),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        # Strip <think>...</think> block if present
        if "<think>" in text and "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        # Find a balanced { ... } JSON object using brace matching (the LLM
        # sometimes appends trailing text after the JSON).
        start = text.find("{")
        if start < 0:
            raise ValueError(f"no JSON object in response: {text[:200]}")
        depth = 0
        in_string = False
        escape = False
        end = -1
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            raise ValueError(f"unbalanced JSON braces in: {text[:200]}")
        text = text[start:end + 1]
        # Sanitize common LLM JSON issues
        text = text.replace("\\n", " ").replace("\\t", " ")
        text = re.sub(r"[\x00-\x1f]+", " ", text)
        data = json.loads(text)
        result = DocumentEnrichmentOutput(**data)
    return Neo4jDocumentEnrichment(
        what_this_document_is_about=result.what_this_document_is_about,
        supported_queries=list(result.supported_queries),
        out_of_scope=list(result.out_of_scope),
        few_shot=[ex.model_dump() for ex in result.few_shot],
    )


# --- File → property builder -------------------------------------------------

def build_properties(
    file_path: str,
    name: str,
    enrichment: Neo4jDocumentEnrichment,
    graphindex_meta: Optional[dict] = None,
    description: str = "",
    tags: Optional[List[str]] = None,
    context_doc_id: int = 0,
    project_id: int = _PROJECT_ID,
) -> Dict[str, Any]:
    """Build a flat Neo4j property map for one document node."""
    return build_document_node_properties(
        project_id=project_id,
        context_doc_id=context_doc_id,
        doc_index_id=(graphindex_meta or {}).get("doc_index_id") or None,
        name=name,
        file_path=file_path,
        description=description,
        tags=tags or [],
        graphindex_meta=graphindex_meta or {},
        enrichment=enrichment,
    )


# --- Commands ----------------------------------------------------------------

def cmd_show(index: Neo4jDocumentIndex, name: str, project_id: int = _PROJECT_ID) -> int:
    """Show one node's full content."""
    node = index.get_document(project_id=project_id, name=name)
    if node is None:
        print(f"  ✗ no Document node with name={name!r}")
        return 1
    print(f"\n{'='*70}\nDocument: {node.name}\n{'='*70}")
    print(f"  context_doc_id  = {node.context_doc_id}")
    print(f"  doc_index_id    = {node.doc_index_id!r}")
    print(f"  file_path       = {node.file_path}")
    print(f"  page_count      = {node.page_count}")
    print(f"  description     = {node.description!r}")
    print(f"  tags            = {node.tags}")
    print(f"  search_terms    = {node.search_terms}")
    print(f"  about ({len(node.what_this_document_is_about)} chars):")
    if node.what_this_document_is_about:
        print(f"    {node.what_this_document_is_about}")
    print(f"  supported_queries ({len(node.supported_queries)}):")
    for q in node.supported_queries:
        print(f"    - {q}")
    print(f"  out_of_scope ({len(node.out_of_scope)}):")
    for q in node.out_of_scope:
        print(f"    - {q}")
    print(f"  few_shot ({len(node.few_shot)}):")
    for ex in node.few_shot:
        print(f"    - Q: {ex.get('query')}  A: {ex.get('answer_hint')}")
    return 0


# --- sha256 helpers + dedup ---------------------------------------------------

def sha256_of_file(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_filesystem_for_dupe(file_path: str, content_hash: str,
                              docs_base: Path = _DOCS_BASE) -> List[Path]:
    """Find any file under docs_base whose name ends with the same hash prefix
    or whose full sha256 matches the candidate. Returns existing files."""
    matches: List[Path] = []
    if not docs_base.exists():
        return matches
    for p in docs_base.rglob("*"):
        if not p.is_file() or p.resolve() == Path(file_path).resolve():
            continue
        # Skip chat-session copies and files outside the scan root.
        rel = p.relative_to(docs_base)
        top = rel.parts[0] if rel.parts else ""
        # When scanning from _DOCS_BASE (full root), skip non-project dirs.
        # When scanning from a project folder, all files are in-scope.
        if docs_base == _DOCS_BASE and (not top.startswith("project_")
                                         or top == "project_chat_sessions"):
            continue
        if sha256_of_file(str(p)) == content_hash:
            matches.append(p)
    return matches


def scan_neo4j_for_dupe(index: Neo4jDocumentIndex, content_hash: str,
                         project_id: int = _PROJECT_ID) -> List[str]:
    """Find any Document node whose content_sha256 matches. Returns names."""
    rows = index._run_cypher(
        "MATCH (d:Document {project_id: $pid, content_sha256: $h}) "
        "RETURN d.name AS name",
        {"pid": project_id, "h": content_hash},
    )
    return [r["name"] for r in rows]


def cmd_ingest(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    source_path: str,
    target_project_dir: str = None,
    project_id: int = _PROJECT_ID,
) -> int:
    """Ingest a new file: hash it, dedup against fs + Neo4j, copy if new,
    then run rebuild-one to add the graphindex node."""
    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        # Search project docs folder by filename
        candidates = list(_DOCS_BASE.rglob(src.name))
        if candidates:
            src = candidates[0]
            print(f"  → found: {src}")
        else:
            print(f"  ✗ source not found: {src}")
            return 1
    if src.suffix.lower() not in _SUPPORTED_EXTS:
        print(f"  ✗ unsupported extension: {src.suffix}")
        return 1

    # 1. Hash source
    content_hash = sha256_of_file(str(src))
    print(f"  hash:  {content_hash[:8]}…  ({src.stat().st_size:,} bytes)")

    # 2. Dedup against Neo4j (primary — content hash is source of truth)
    neo_dupes = scan_neo4j_for_dupe(index, content_hash)
    if neo_dupes:
        print(f"  ✗ already indexed (Neo4j): {neo_dupes[0]}")
        return 0

    # 3. Check target folder for same-name collision
    target_dir = (Path(target_project_dir) if target_project_dir
                  else _DOCS_BASE / f"project_{project_id}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / src.name
    if target_path.resolve() == src.resolve():
        # Already at the target path — skip copy, just re-index.
        print(f"  → already at target path: {target_path}")
    elif target_path.exists():
        old_hash = sha256_of_file(str(target_path))
        if old_hash == content_hash:
            print(f"  → already on disk: {target_path.name}")
        else:
            print(f"  ✗ file exists with different content: {target_path.name}")
            return 1
    else:
        shutil.copy2(src, target_path)
        print(f"  ✓ copied: {target_path}")

    # 4. Add Neo4j node via rebuild-one (which also sets content_sha256)
    docs = index.list_documents(project_id=project_id)
    all_names = [d.name for d in docs]
    return cmd_rebuild_one(index, llm, src.name, all_names, project_id=project_id)


def cmd_ingest_folder(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    folder_path: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Ingest all supported files in a directory."""
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        print(f"  ✗ folder not found: {folder}")
        return 1
    files = sorted([
        p for p in folder.rglob("*")
        if p.suffix.lower() in _SUPPORTED_EXTS
    ])
    if not files:
        print(f"  ✗ no supported files in {folder}")
        return 1
    print(f"\nIngesting {len(files)} file(s) from {folder}...\n")
    failed = 0
    for f in files:
        print(f"── {f.name} ──")
        ok = cmd_ingest(index, llm, str(f), project_id=project_id)
        if ok != 0:
            failed += 1
        print()
    print(f"Done: {len(files) - failed}/{len(files)} ingested")
    return 0 if failed == 0 else 1


def cmd_rebuild_one(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    name: str,
    all_names: List[str],
    project_id: int = _PROJECT_ID,
) -> int:
    """Rebuild enrichment for one doc and upsert it.

    If the node doesn't exist yet (e.g. after a delete), we locate the file
    under backend/data/documents/ and create a fresh node.
    """
    node = index.get_document(project_id=project_id, name=name)
    file_path: Optional[str] = None
    context_doc_id = 0
    description = ""
    tags: List[str] = []
    if node is not None:
        file_path = node.file_path
        context_doc_id = node.context_doc_id
        description = node.description or ""
        tags = list(node.tags or [])
        print(f"  → found existing node (context_doc_id={context_doc_id})")
    else:
        # Find the file under any project_*/ folder.
        # Filenames often have a hash prefix (e.g. "31042021_nke-10k-2023.pdf")
        # but the node name is just the suffix. Strip .pdf and search.
        base = name[:-4] if name.lower().endswith(".pdf") else name
        candidates = [p for p in _DOCS_BASE.rglob("*.pdf")
                      if p.stem.endswith(base) or base in p.stem]
        if not candidates:
            # Fall back to exact-name match (for non-PDF files)
            candidates = list(_DOCS_BASE.rglob(name))
        if not candidates:
            print(f"  ✗ no Document node with name={name!r} "
                  f"and no matching file under {_DOCS_BASE}")
            return 1
        file_path = str(candidates[0].resolve())
        print(f"  → node missing; will recreate from file {file_path}")

    content = load_document_content(file_path)
    if not content:
        print(f"  ✗ no content extracted from {file_path}")
        return 1
    graphindex_meta = load_graphindex_metadata(file_path)
    other_names = build_project_scope_names(name, all_names)

    print(f"  → generating enrichment for {name!r} "
          f"({len(content):,} chars)...")
    t0 = time.time()
    enrichment = extract_document_enrichment(
        llm=llm,
        document_name=name,
        description=description,
        tags=tags,
        graphindex_meta=graphindex_meta,
        content=content,
        other_document_names=other_names,
    )
    elapsed = time.time() - t0

    properties = build_properties(
        file_path=file_path,
        name=name,
        enrichment=enrichment,
        graphindex_meta=graphindex_meta,
        description=description,
        tags=tags,
        context_doc_id=context_doc_id,
        project_id=project_id,
    )
    index.upsert_document(project_id=project_id, name=name,
                          file_path=file_path, properties=properties)

    # Also set content_sha256 (not in base properties builder)
    content_hash = sha256_of_file(file_path)
    index._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "SET d.content_sha256 = $h",
        {"pid": project_id, "name": name, "h": content_hash},
    )

    print(f"  ✓ upserted in {elapsed:.1f}s")
    print(f"    about: {enrichment.what_this_document_is_about[:120]}")
    print(f"    supports ({len(enrichment.supported_queries)}): "
          f"{enrichment.supported_queries[:3]}")
    print(f"    out_of_scope ({len(enrichment.out_of_scope)}): "
          f"{enrichment.out_of_scope[:3]}")
    return 0


def cmd_list(
    index: Neo4jDocumentIndex,
    project_id: int = _PROJECT_ID,
) -> int:
    """Scan files on disk and cross-check against Neo4j index."""
    project_folder = _DOCS_BASE / f"project_{project_id}"
    indexed = {d.name for d in index.list_documents(project_id=project_id)}
    print(f"\nFiles on disk — {project_folder}\n")
    files = sorted([
        p for p in project_folder.rglob("*")
        if p.suffix.lower() in _SUPPORTED_EXTS
    ])
    if not files:
        print("  (no supported files found)")
        return 0
    indexed_count = 0
    for i, f in enumerate(files, 1):
        name = f.name
        in_neo4j = any(name.endswith(d) or d.endswith(name)
                       for d in indexed)
        status = "✓" if in_neo4j else "✗ NOT INDEXED"
        if in_neo4j:
            indexed_count += 1
        size = f.stat().st_size
        print(f"  {i}. [{status}] {name}  ({size:,} bytes)")
    print(f"\n  {indexed_count}/{len(files)} indexed")
    return 0


def cmd_remove(
    index: Neo4jDocumentIndex,
    name: str,
    project_id: int = _PROJECT_ID,
) -> int:
    """Remove a doc from Neo4j and delete the file from disk."""
    # Check if it exists in Neo4j
    doc = index.get_document(project_id=project_id, name=name)
    if doc:
        file_path = doc.file_path
        index._run_cypher(
            "MATCH (d:Document {project_id: $pid, name: $name}) DELETE d",
            {"pid": project_id, "name": name},
        )
        print(f"  ✓ removed from Neo4j: {name}")
    else:
        print(f"  ✗ not found in Neo4j (project {project_id}): {name}")
        file_path = None

    # Try to find and delete the file on disk
    project_folder = _DOCS_BASE / f"project_{project_id}"
    candidates = list(project_folder.rglob(name))
    if not candidates:
        # Try matching by suffix (e.g. name="a34de781_01..." → file="2c406458_a34de781_01...")
        candidates = [p for p in project_folder.rglob(name.split("_", 1)[-1])
                      if p.stem.endswith(name)]
    if not candidates and file_path:
        candidates = [Path(file_path)]
    if candidates:
        for p in candidates:
            p.unlink()
            print(f"  ✓ removed from disk: {p.name}")
    else:
        print(f"  (no matching file found on disk)")
    return 0


def cmd_rebuild_project(
    index: Neo4jDocumentIndex,
    llm: BaseChatModel,
    project_id: int = _PROJECT_ID,
) -> int:
    """Rebuild enrichment for every Document node in the project."""
    docs = index.list_documents(project_id=project_id)
    all_names = [d.name for d in docs]
    print(f"\n{'='*70}\nRebuilding enrichment for {len(docs)} doc(s) "
          f"(project {project_id})\n{'='*70}\n")
    failed = 0
    for d in docs:
        ok = cmd_rebuild_one(index, llm, d.name, all_names, project_id=project_id)
        if ok != 0:
            failed += 1
        print()
    print(f"{'='*70}\n{len(docs) - failed}/{len(docs)} rebuilt successfully\n{'='*70}")
    return 0 if failed == 0 else 1


def cmd_query(index: Neo4jDocumentIndex, query_text: str,
              project_id: int = _PROJECT_ID) -> int:
    """Route a query using the current enrichment state and print top candidates."""
    docs = index.list_documents(project_id=project_id)
    print(f"\nQuery ({query_text!r}) — project {project_id}\n")
    if not docs:
        print(f"  ✗ no documents in project {project_id}")
        return 1
    best = index.find_best_document(project_id=project_id, query=query_text)
    if best is None:
        print("  ✗ no match")
        return 1
    print(f"  ✓ best match: {best.name}  (context_doc_id={best.context_doc_id})")
    print(f"    about: {best.what_this_document_is_about[:200]}")
    print(f"    file: {best.file_path}")
    return 0


# --- Entry point -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 — complete GraphIndex builder.",
    )
    parser.add_argument("--project-id", type=int, default=_PROJECT_ID,
                        help=f"Neo4j project id (default: {_PROJECT_ID}, "
                             "from GRAPHINDEX_DEFAULT_PROJECT_ID env var)")
    parser.add_argument("--list", action="store_true",
                        help="List files on disk, cross-checked against Neo4j")
    parser.add_argument("--show", metavar="NAME", help="Show a document node")
    parser.add_argument("--remove", metavar="NAME",
                        help="Remove a doc from Neo4j and delete file from disk")
    parser.add_argument("--rebuild-one", metavar="NAME",
                        help="Rebuild enrichment for one doc")
    parser.add_argument("--rebuild-project", action="store_true",
                        help="Rebuild enrichment for every doc in the project")
    parser.add_argument("--query", metavar="TEXT",
                        help="Route a query and print best match")
    parser.add_argument("--ingest", metavar="FILE",
                        help="Ingest a single file: hash, dedup, copy, build graphindex")
    parser.add_argument("--ingest-folder", metavar="DIR",
                        help="Ingest all supported files in a directory")
    parser.add_argument("--ingest-target", metavar="DIR", default=None,
                        help="Target directory for the ingested file "
                             "(default: backend/data/documents/project_{ID})")
    args = parser.parse_args()
    project_id = args.project_id

    if not any([args.list, args.show, args.remove, args.rebuild_one, args.rebuild_project,
                args.query, args.ingest, args.ingest_folder]):
        parser.print_help()
        return 1

    # Connect to Neo4j
    _neo4j_url = os.getenv("NEO4J_URL", "http://localhost:7474")
    print(f"🔌 Neo4j: {_neo4j_url}")
    index = Neo4jDocumentIndex(
        base_url=_neo4j_url,
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    index.ensure_constraints()
    print(f"   constraints ensured")

    # Build LLM (lazy — only when we need enrichment)
    llm: Optional[BaseChatModel] = None
    if args.rebuild_one or args.rebuild_project or args.ingest or args.ingest_folder:
        llm = make_llm()
        print(f"🔌 LLM: {os.getenv('GRAPHINDEX_MODEL', 'minimax-m3')}\n")

    if args.list:
        return cmd_list(index, project_id=project_id)
    if args.show:
        return cmd_show(index, args.show, project_id=project_id)
    if args.remove:
        return cmd_remove(index, args.remove, project_id=project_id)
    if args.rebuild_one:
        all_names = [d.name for d in index.list_documents(project_id=project_id)]
        return cmd_rebuild_one(index, llm, args.rebuild_one, all_names,
                               project_id=project_id)
    if args.rebuild_project:
        return cmd_rebuild_project(index, llm, project_id=project_id)
    if args.query:
        return cmd_query(index, args.query, project_id=project_id)
    if args.ingest:
        return cmd_ingest(index, llm, args.ingest, args.ingest_target,
                          project_id=project_id)
    if args.ingest_folder:
        return cmd_ingest_folder(index, llm, args.ingest_folder,
                                 project_id=project_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
