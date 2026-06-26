#!/usr/bin/env python3
"""
Phase 9 / Step D — Clean Python build CLI (recommended entry point).

Why this exists:
  The legacy build_graphindex.py mixes raw llm.invoke with manual
  orchestration. The deepagent version (build_graphindex_deep.py) adds
  state-graph overhead that is unnecessary for build-side work.

  This file is the **recommended entry point** for ingestion: each step
  is a pure Python function, except for one LLM call that generates
  enrichment metadata.

Flow per --ingest:
  1. sha256_of_file(file_path)            — pure Python
  2. scan_filesystem_for_dupe(hash)        — pure Python (reuses base)
  3. scan_neo4j_for_dupe(hash)             — pure Python (Neo4j query)
  4. (if dupe) skip steps 5-7
  5. copy_with_hash_prefix(file, hash)     — pure Python
  6. extract_document_enrichment(...)      — ONE LLM call (reuses base)
  7. upsert_to_neo4j(target, enrichment)   — pure Python

Per rules.md: no truncation, no chunking, no embeddings; MiniMax M3 only.

Compare:
  build_graphindex.py          legacy: same flow, but orchestration mixed
                               into main(), less reusable
  build_graphindex_deep.py     parallel deepagent path (state-graph demo)
  build_graphindex_clean.py    THIS FILE — recommended, clean Python
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402

from services.neo4j_document_index import (  # noqa: E402
    Neo4jDocumentIndex,
    Neo4jDocumentEnrichment,
    build_document_node_properties,
)

# Reuse pure-Python primitives from the legacy script (no LLM calls in them)
from legacy.build_graphindex import (  # noqa: E402
    DOCS_BASE,
    SUPPORTED_EXTS,
    extract_document_enrichment,
    load_document_content,
    load_graphindex_metadata,
    make_llm,
)

PROJECT_ID = 1
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MODEL = "minimax-m3"


# --- Pure-Python primitives (no LLM) -----------------------------------

def sha256_of_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_filesystem_duplicate(content_hash: str,
                              source_path: str) -> Optional[str]:
    """Walk backend/data/documents/project_* (excluding project_chat_sessions)
    and return the matching path if any file has the same sha256."""
    if not DOCS_BASE.exists():
        return None
    src = Path(source_path).resolve()
    for p in DOCS_BASE.rglob("*"):
        if not p.is_file():
            continue
        if p.resolve() == src:
            continue
        try:
            rel = p.relative_to(DOCS_BASE)
            top = rel.parts[0] if rel.parts else ""
        except ValueError:
            continue
        if not top.startswith("project_") or top == "project_chat_sessions":
            continue
        if sha256_of_file(str(p)) == content_hash:
            return str(p)
    return None


def is_neo4j_duplicate(idx: Neo4jDocumentIndex,
                        content_hash: str,
                        project_id: int = PROJECT_ID) -> Optional[str]:
    """Return existing Document node name if any has this content_sha256."""
    rows = idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, content_sha256: $h}) "
        "RETURN d.name AS name LIMIT 1",
        {"pid": project_id, "h": content_hash},
    )
    return rows[0]["name"] if rows else None


def copy_with_hash_prefix(source_path: str,
                            target_dir: str,
                            short_hash: str) -> str:
    """Copy file to target_dir with {short_hash}_{filename} naming."""
    src = Path(source_path).resolve()
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    new_name = f"{short_hash}_{src.name}"
    target_path = target / new_name
    if not target_path.exists():
        shutil.copy2(src, target_path)
    return str(target_path)


def upsert_to_neo4j(idx: Neo4jDocumentIndex,
                     name: str,
                     file_path: str,
                     enrichment: Neo4jDocumentEnrichment,
                     description: str = "",
                     tags: Optional[List[str]] = None,
                     project_id: int = PROJECT_ID) -> None:
    """Upsert Document node with enrichment + set content_sha256."""
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
    idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "SET d.content_sha256 = $h",
        {"pid": project_id, "name": name, "h": sha256_of_file(file_path)},
    )


def set_content_sha256(idx: Neo4jDocumentIndex,
                        name: str,
                        content_hash: str,
                        project_id: int = PROJECT_ID) -> None:
    """Set content_sha256 on an existing Document node (used by rebuild)."""
    idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "SET d.content_sha256 = $h",
        {"pid": project_id, "name": name, "h": content_hash},
    )


# --- The single LLM call (reuses base's enrichment function) ------------

def enrich_document(idx: Neo4jDocumentIndex,
                     llm: BaseChatModel,
                     file_path: str) -> Neo4jDocumentEnrichment:
    """Run ONE LLM call to generate enrichment metadata for one document.

    Reuses build_graphindex.extract_document_enrichment, which handles
    the structured-output + plain-text fallback dance.
    """
    file_path_obj = Path(file_path)
    document_name = file_path_obj.name
    description = ""  # no separate description for ad-hoc ingests
    tags: List[str] = []
    graphindex_meta = load_graphindex_metadata(file_path) or {}
    content = load_document_content(file_path)
    other_names = [d.name for d in idx.list_documents(project_id=PROJECT_ID)]
    return extract_document_enrichment(
        llm=llm,
        document_name=document_name,
        description=description,
        tags=tags,
        graphindex_meta=graphindex_meta,
        content=content,
        other_document_names=other_names,
    )


# --- CLI subcommands ------------------------------------------------------

def cmd_ingest(file_path: str,
                target_dir: Optional[str] = None,
                llm: BaseChatModel = None) -> int:
    """Ingest a new file: hash → dedup → copy → enrich (1 LLM call) → upsert."""
    src = Path(file_path)
    if not src.exists():
        print(f"  ✗ file not found: {file_path}")
        return 1
    if src.suffix.lower() not in SUPPORTED_EXTS:
        print(f"  ✗ unsupported extension: {src.suffix}")
        return 1

    print(f"📥 Ingesting {file_path}")
    print(f"   target: {target_dir or str(DOCS_BASE / 'project_1')}")

    idx = Neo4jDocumentIndex()
    target_dir = target_dir or str(DOCS_BASE / "project_1")

    # 1. Hash
    content_hash = sha256_of_file(str(src))
    short_hash = content_hash[:8]
    print(f"   hash: {short_hash}…  ({src.stat().st_size:,} bytes)")

    # 2. Filesystem dedup
    fs_match = is_filesystem_duplicate(content_hash, str(src))
    if fs_match:
        print(f"   ✗ fs dupe: {fs_match}")
        return 0

    # 3. Neo4j dedup
    neo_match = is_neo4j_duplicate(idx, content_hash)
    if neo_match:
        print(f"   ✗ neo4j dupe: {neo_match}")
        return 0

    # 4. Copy
    target_path = copy_with_hash_prefix(str(src), target_dir, short_hash)
    print(f"   copied: {target_path}")

    # 5. Enrich (one LLM call)
    print(f"   enriching via LLM…", end=" ", flush=True)
    t0 = time.time()
    if llm is None:
        llm = make_llm()
    enrichment = enrich_document(idx, llm, target_path)
    enrich_time = time.time() - t0
    print(f"done ({enrich_time:.1f}s)")
    print(f"      about: {enrichment.what_this_document_is_about[:100]}…")
    print(f"      supports: {len(enrichment.supported_queries)} queries")
    print(f"      out_of_scope: {len(enrichment.out_of_scope)} docs")

    # 6. Upsert Neo4j
    upsert_to_neo4j(idx, name=src.name, file_path=target_path,
                    enrichment=enrichment)
    print(f"   neo4j: upserted as {src.name}")

    print(f"\n✅ Done in {enrich_time:.1f}s")
    return 0


def cmd_rebuild_one(name: str,
                     llm: BaseChatModel = None) -> int:
    """Rebuild enrichment for one existing doc."""
    idx = Neo4jDocumentIndex()
    node = idx.get_document(project_id=PROJECT_ID, name=name)
    if not node:
        print(f"  ✗ no doc named {name!r}")
        return 1

    print(f"🔄 Rebuilding {name}")
    print(f"   file: {node.file_path}")

    print(f"   enriching…", end=" ", flush=True)
    t0 = time.time()
    if llm is None:
        llm = make_llm()
    enrichment = enrich_document(idx, llm, node.file_path)
    enrich_time = time.time() - t0
    print(f"done ({enrich_time:.1f}s)")

    upsert_to_neo4j(idx, name=name, file_path=node.file_path,
                    enrichment=enrichment)
    print(f"   neo4j: upserted")

    print(f"\n✅ Done in {enrich_time:.1f}s")
    return 0


def cmd_rebuild_project(llm: BaseChatModel = None) -> int:
    """Rebuild enrichment for every doc in project 1."""
    idx = Neo4jDocumentIndex()
    docs = idx.list_documents(project_id=PROJECT_ID)
    print(f"🔄 Rebuilding {len(docs)} docs in project {PROJECT_ID}")
    if llm is None:
        llm = make_llm()

    total = 0.0
    for i, d in enumerate(docs, 1):
        t0 = time.time()
        try:
            enrichment = enrich_document(idx, llm, d.file_path)
            upsert_to_neo4j(idx, name=d.name, file_path=d.file_path,
                            enrichment=enrichment)
            elapsed = time.time() - t0
            total += elapsed
            print(f"  [{i:2d}/{len(docs)}] {d.name}  ✓ {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            total += elapsed
            print(f"  [{i:2d}/{len(docs)}] {d.name}  ✗ {elapsed:.1f}s  ({e})")

    print(f"\n✅ Done in {total:.1f}s ({total/len(docs):.1f}s/doc)")
    return 0


def cmd_show(name: str) -> int:
    """Print one Document node's key fields."""
    idx = Neo4jDocumentIndex()
    node = idx.get_document(project_id=PROJECT_ID, name=name)
    if not node:
        print(f"  ✗ no doc named {name!r}")
        return 1
    print(f"📄 {node.name}")
    print(f"   file_path: {node.file_path}")
    print(f"   about: {node.what_this_document_is_about or '(none)'}")
    print(f"   supports ({len(node.supported_queries)}):")
    for q in node.supported_queries[:5]:
        print(f"     - {q}")
    print(f"   out_of_scope ({len(node.out_of_scope)}):")
    for n in node.out_of_scope[:5]:
        print(f"     - {n}")
    rows = idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "RETURN d.content_sha256 AS h",
        {"pid": PROJECT_ID, "name": name},
    )
    if rows and rows[0].get("h"):
        print(f"   content_sha256: {rows[0]['h'][:16]}…")
    return 0


# --- Main -----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / Clean Python build CLI (recommended)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ingest", metavar="FILE",
                       help="ingest a new file")
    group.add_argument("--rebuild-one", metavar="NAME",
                       help="rebuild enrichment for one doc")
    group.add_argument("--rebuild-project", action="store_true",
                       help="rebuild enrichment for all docs")
    group.add_argument("--show", metavar="NAME", help="show a document node")
    parser.add_argument("--ingest-target", metavar="DIR", default=None,
                        help="target directory for the ingested file")
    args = parser.parse_args()

    if not MINIMAX_API_KEY:
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        return 1

    if args.ingest:
        return cmd_ingest(args.ingest, args.ingest_target)
    if args.rebuild_one:
        return cmd_rebuild_one(args.rebuild_one)
    if args.rebuild_project:
        return cmd_rebuild_project()
    if args.show:
        return cmd_show(args.show)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())