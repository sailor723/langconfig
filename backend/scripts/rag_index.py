#!/usr/bin/env python
"""Index documents for retrieval — the step between uploading and asking.

    cd backend
    .venv/bin/python scripts/rag_index.py ~/Downloads/contract.pdf --user 1
    .venv/bin/python scripts/rag_index.py data/knowledge/knowledge-4242 --user 1 --reset
    .venv/bin/python scripts/rag_index.py --status --user 1

Why this is a script and not a tool the agent calls:

* **It is not idempotent.** Indexing the same file twice produces duplicate chunks
  with different ids, which surface as the same passage cited twice — a retrieval
  bug that isn't one. `--reset` is the explicit way to re-index.
* **It is slow and expensive**: every chunk becomes a local embedding call. An agent
  deciding to re-index mid-conversation stalls the turn.
* **It is where retrieval quality is decided** — chunk size, overlap, how many
  chunks a 20-page PDF becomes. That is the lesson of the case, and it should be
  visible in a terminal rather than hidden behind a tool call.

The report it prints is the point:

    1 file · 18 pages · 214 chunks · 1h2m3s → lc_kb_u1

214 chunks for 18 pages is the number that explains a vague answer later.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown", ".csv", ".log", ".html", ".htm"}


def _collect(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)


def main() -> int:
    ap = argparse.ArgumentParser(description="Index documents into an account's retrieval collection.")
    ap.add_argument("path", nargs="?", help="A file or a folder to index")
    ap.add_argument("--user", type=int, help="Account id whose collection to write (required)")
    ap.add_argument("--reset", action="store_true", help="Drop the collection first (re-index from scratch)")
    ap.add_argument("--status", action="store_true", help="Only report what is indexed")
    ap.add_argument("--chunk-size", type=int, default=None, help="Override the 1000-char default")
    ap.add_argument("--chunk-overlap", type=int, default=None, help="Override the 200-char default")
    args = ap.parse_args()

    if args.user is None:
        ap.error("--user is required: a collection belongs to one account")

    from core.rag import collection_name, drop_collection, has_index
    from core.rag.documents import load_file, split_documents
    from core.rag.store import get_vector_store

    uid = args.user
    name = collection_name(uid)

    if args.status or not args.path:
        if not has_index(uid):
            print(f"{name}: not indexed")
            return 0
        import psycopg

        from core.rag.store import plain_dsn

        with psycopg.connect(plain_dsn()) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), count(DISTINCT e.document)
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                WHERE c.name = %s
                """,
                (name,),
            )
            chunks, docs = cur.fetchone()
        print(f"{name}: {chunks} chunk(s) from {docs} indexed document(s)")
        return 0

    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        sys.exit(f"✗ not found: {target}")

    files = _collect(target)
    if not files:
        sys.exit(f"✗ no supported files in {target} (supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})")

    if args.reset:
        drop_collection(uid)
        print(f"· dropped {name}")

    splitter_kwargs = {}
    if args.chunk_size:
        splitter_kwargs["chunk_size"] = args.chunk_size
    if args.chunk_overlap is not None:
        splitter_kwargs["chunk_overlap"] = args.chunk_overlap

    started = time.time()
    docs = []
    pages = 0
    for f in files:
        try:
            loaded = load_file(f, source_label=f.name)
        except ValueError as exc:  # unsupported suffix, or a loader we do not have
            print(f"· skipped {f.name}: {exc}")
            continue
        docs.extend(loaded)
        pages += len(loaded)
        print(f"· read {f.name}: {len(loaded)} page(s)")

    if not docs:
        sys.exit("✗ nothing readable")

    splits = split_documents(docs, **splitter_kwargs)
    store = get_vector_store(uid)
    ids = store.add_documents(documents=splits)
    elapsed = time.time() - started

    print(
        f"\n{len(files)} file(s) · {pages} page(s) · {len(splits)} chunk(s) · "
        f"{elapsed:.1f}s → {name}"
    )
    if splits:
        avg = sum(len(s.page_content) for s in splits) // len(splits)
        print(f"average chunk: {avg} chars (target {splitter_kwargs.get('chunk_size', 1000)})")
    print(f"ids written: {len(ids)}")
    print(
        "\nNow ask a question in a chat whose agent has the `rag_search` tool.\n"
        "If the answer is vague, that chunk count is the first thing to look at —\n"
        "smaller chunks sharpen a specific question, larger ones keep context."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
