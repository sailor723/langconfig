# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Vector store for retrieval — step 4 of the semantic-search tutorial.

`node 1` of the tutorial is `vector_store = PGVector(embeddings=…, collection_name=…)`,
`node 2` is `vector_store.add_documents(splits)`. This module owns both, plus the
one decision the tutorial does not have to make: **whose** vectors these are.

## Two document chats, deliberately

This platform now has two answers to "chat with a document" and they are not
versions of each other:

* **KV chat** (`api/knowledge/doc_chat.py`) — read the whole file, put it in the
  prompt, answer. No chunks, no scores. Fast and exact for a 5-page contract; it
  dies on a 200-page filing because the file does not fit in the context window.
* **Embedding chat** (this package) — split, embed, store, retrieve the nearest
  chunks. Works on any size, can cite *page 4*, and can miss a passage that the
  KV path would have read verbatim.

Neither wins outright, so both stay. Teaching them side by side is the point:
"which kind of document problem do I have" is a real decision, and picking the
KV path for a 300-page PDF is the mistake this comparison makes visible.

## Per-account collections, not a metadata filter

One collection per account (`lc_kb_u<user_id>`), because the alternative fails in
the one way this codebase has already been bitten by: a shared collection plus a
`user_id` metadata filter is correct only while every query remembers the filter.
Forget it once and user A retrieves user B's contract, with no error and an answer
that looks fine.

A per-account collection cannot leak, because there is nothing to leak into: the
collection's UUID is resolved from the account id, and `langchain_pg_embedding`
rows belong to exactly one collection. Wrong account → empty result, not somebody
else's text.

The cost is honest and small: cross-account sharing means re-indexing (a copy),
and the collection list grows with the accounts that actually upload documents.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .embeddings import get_embeddings

logger = logging.getLogger(__name__)

#: Prefix for a per-account collection. `PGVector`'s own default is `langchain`,
#: so a prefix keeps these distinguishable in a psql session that also shows other
#: collections.
COLLECTION_PREFIX = "lc_kb_u"


def collection_name(user_id: int) -> str:
    """The collection that holds one account's chunks.

    Deterministic from the account id — no registry to keep in sync, and a
    restored database resolves the same collection without any bookkeeping.
    """
    if user_id is None:
        raise ValueError("collection_name() needs a user_id: a shared collection is the bug")
    return f"{COLLECTION_PREFIX}{int(user_id)}"


def connection_string(url: Optional[str] = None) -> str:
    """psycopg-v3 form of the app database URL.

    `PGVector` speaks psycopg 3 (`postgresql+psycopg://`), while the rest of the
    app uses psycopg2 (`postgresql://`). Converting here instead of adding a second
    environment variable keeps one source of truth: vectors are always written to
    the same database as the documents they describe. A separate URL is how an
    install ends up with an empty index and a full documents table.
    """
    raw = url or os.getenv("DATABASE_URL")
    if not raw:
        from db.database import DATABASE_URL

        raw = DATABASE_URL
    raw = str(raw).strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def get_vector_store(user_id: int, url: Optional[str] = None, embeddings=None):
    """The `VectorStore` for one account.

    Same signature as the tutorial's `PGVector(embeddings=…, collection_name=…)`,
    with `collection_name` derived from the account and the connection derived
    from the app's own database URL. The collection (and the extension) are created
    on first write — step 4 of the tutorial is `add_documents`, and it is allowed
    to be the thing that creates them.
    """
    from langchain_postgres import PGVector

    return PGVector(
        embeddings=embeddings or get_embeddings(),
        collection_name=collection_name(user_id),
        connection=connection_string(url),
        # jsonb metadata: filters and payloads then use Postgres' own operators
        # rather than a text column that has to be parsed on every query.
        use_jsonb=True,
        create_extension=True,
        # `distance_strategy` is left at PGVector's default (COSINE), which is the
        # metric nomic-embed-text is trained for and what the tutorial assumes.
        # Changing it later silently invalidates every stored vector without
        # altering a byte of them, so it is not parameterised on purpose.
    )


def drop_collection(user_id: int, url: Optional[str] = None) -> None:
    """Delete one account's collection and its chunks.

    Exists because "re-index" is the normal repair for bad chunks, and re-indexing
    into a collection that still holds the old chunks is how duplicates — and
    duplicate *citations* — appear.
    """
    from langchain_postgres import PGVector

    store = PGVector(
        embeddings=get_embeddings(),
        collection_name=collection_name(user_id),
        connection=connection_string(url),
        use_jsonb=True,
        create_extension=True,
        pre_delete_collection=True,
    )
    # Construction with pre_delete_collection drops it; nothing else to do.
    del store


def collection_exists(user_id: int, url: Optional[str] = None) -> bool:
    """Whether this account has indexed anything yet (used by the UI's empty state)."""
    import psycopg

    try:
        with psycopg.connect(plain_dsn(url)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM langchain_pg_collection WHERE name = %s",
                    (collection_name(user_id),),
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001 — no table yet means "not indexed", not an error
        return False


def plain_dsn(url: Optional[str] = None) -> str:
    """`connection_string` without the SQLAlchemy driver suffix, for raw psycopg."""
    return connection_string(url).replace("postgresql+psycopg://", "postgresql://", 1)
