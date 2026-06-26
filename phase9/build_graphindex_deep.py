#!/usr/bin/env python3
"""
Phase 9 / Step C — DeepAgent-based CLI for build-side operations.

This is a parallel entry point to build_graphindex.py (which uses raw
llm.invoke). The legacy script is left untouched.

Subcommands:
  --ingest <file>      ingest a new file with SHA-256 dedup
  --rebuild-one <name> rebuild enrichment for one existing doc
  --rebuild-project    rebuild enrichment for all docs
  --show <name>        show a document node
  --show-agent         print agent topology
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Repo + backend path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))

from langchain_core.messages import HumanMessage  # noqa: E402

from services.neo4j_document_index import Neo4jDocumentIndex  # noqa: E402
from build_agent import get_build_agent  # noqa: E402

PROJECT_ID = 1


def _strip_think(answer: str) -> str:
    if "<think>" in answer and "</think>" in answer:
        return answer.split("</think>", 1)[1].strip()
    return answer


def _print_turn_footer(elapsed: float, in_tok: int = 0, out_tok: int = 0,
                        cache_read: int = 0) -> None:
    cache_pct = 100 * cache_read / in_tok if in_tok else 0
    print(f"\n   ├─ tokens: in={in_tok:>7,}  out={out_tok:>5,}")
    print(f"   │          cache_read={cache_read:>6,}  ({cache_pct:.1f}% cached)")
    print(f"   └─ latency: {elapsed:5.1f}s")


def cmd_ingest(file_path: str, target_dir: str = None) -> int:
    """Ingest a new file: hash, dedup, copy, enrich, upsert — via DeepAgent."""
    if not Path(file_path).exists():
        print(f"  ✗ file not found: {file_path}")
        return 1

    agent = get_build_agent()
    msg = (
        f"Ingest this file: {file_path}\n"
        f"Target directory: {target_dir or 'default (backend/data/documents/project_1)'}\n\n"
        "Workflow: ingest_checker (hash + dedup) → enricher (LLM metadata) → "
        "writer (copy + upsert Neo4j). If a dupe is found, skip the rest."
    )
    cfg = {"configurable": {"thread_id": "phase9-build-ingest"}}
    t0 = time.time()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": msg}]},
        config=cfg,
    )
    elapsed = time.time() - t0
    answer = _strip_think(result["messages"][-1].content)
    last = result["messages"][-1]
    usage = getattr(last, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))

    print(f"\n🤖 {answer}")
    _print_turn_footer(elapsed, in_tok, out_tok, cache_read)
    return 0


def cmd_rebuild_one(name: str) -> int:
    """Rebuild enrichment for one existing doc."""
    idx = Neo4jDocumentIndex()
    node = idx.get_document(project_id=PROJECT_ID, name=name)
    if not node:
        print(f"  ✗ no doc named {name!r}")
        return 1

    agent = get_build_agent()
    msg = (
        f"Rebuild enrichment for the existing document: {name}\n"
        f"File path: {node.file_path}\n\n"
        "Workflow: skip ingest_checker (already indexed). "
        "Run enricher to regenerate metadata, then writer to upsert Neo4j."
    )
    cfg = {"configurable": {"thread_id": f"phase9-rebuild-{name}"}}
    t0 = time.time()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": msg}]},
        config=cfg,
    )
    elapsed = time.time() - t0
    answer = _strip_think(result["messages"][-1].content)
    last = result["messages"][-1]
    usage = getattr(last, "usage_metadata", None) or {}
    details = usage.get("input_token_details", {}) or {}
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    cache_read = int(details.get("cache_read", 0) or details.get("cached_tokens", 0))

    print(f"\n🤖 {answer}")
    _print_turn_footer(elapsed, in_tok, out_tok, cache_read)
    return 0


def cmd_rebuild_project() -> int:
    """Rebuild enrichment for every doc in project 1."""
    idx = Neo4jDocumentIndex()
    docs = idx.list_documents(project_id=PROJECT_ID)
    print(f"  rebuilding {len(docs)} docs...")
    agent = get_build_agent()
    for i, d in enumerate(docs, 1):
        print(f"\n[{i}/{len(docs)}] {d.name}")
        cfg = {"configurable": {"thread_id": f"phase9-rebuild-all-{i}"}}
        msg = f"Rebuild enrichment for: {d.name} (file: {d.file_path})"
        t0 = time.time()
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": msg}]},
                config=cfg,
            )
            elapsed = time.time() - t0
            answer = _strip_think(result["messages"][-1].content)
            print(f"   ✓ {elapsed:.1f}s — {answer[:200]}")
        except Exception as e:
            print(f"   ✗ error: {e}")
    return 0


def cmd_show(name: str) -> int:
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
    # Try to read content_sha256
    rows = idx._run_cypher(
        "MATCH (d:Document {project_id: $pid, name: $name}) "
        "RETURN d.content_sha256 AS h",
        {"pid": PROJECT_ID, "name": name},
    )
    if rows and rows[0].get("h"):
        print(f"   content_sha256: {rows[0]['h'][:16]}…")
    return 0


def cmd_show_agent() -> int:
    agent = get_build_agent()
    print("Build-side DeepAgent topology:")
    try:
        for node in agent.get_graph().nodes:
            print(f"  - {node}")
    except Exception as e:
        print(f"  (could not introspect: {e})")
    print(f"\nTools: 9 (sha256, scan_fs, scan_neo4j, read_doc, get_metadata,")
    print(f"        list_other_docs, copy, upsert, set_sha256)")
    print(f"Subagents: 3 (ingest_checker, enricher, writer)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 9 / DeepAgent-based build CLI",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ingest", metavar="FILE",
                       help="ingest a new file with SHA-256 dedup")
    group.add_argument("--rebuild-one", metavar="NAME",
                       help="rebuild enrichment for one doc")
    group.add_argument("--rebuild-project", action="store_true",
                       help="rebuild enrichment for all docs")
    group.add_argument("--show", metavar="NAME", help="show a document node")
    group.add_argument("--show-agent", action="store_true",
                       help="print agent topology and exit")
    parser.add_argument("--ingest-target", metavar="DIR", default=None,
                        help="target directory for the ingested file")
    args = parser.parse_args()

    if not os.getenv("MINIMAX_API_KEY"):
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
    if args.show_agent:
        return cmd_show_agent()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())