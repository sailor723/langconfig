# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Index and retrieve — the loop the tutorial builds, per account.

    docs = load_file(path)                  # step 1
    splits = split_documents(docs)          # step 3
    store.add_documents(splits)             # step 4
    store.as_retriever(...).invoke(query)   # step 5

Everything here is bound to one account. There is no function that takes a query
without a `user_id`, which is the point: the isolation decision is made once, at
the store, and callers cannot opt out of it by forgetting an argument.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from .documents import load_file, split_documents
from .store import (
    collection_exists,
    collection_name,
    drop_collection,
    get_vector_store,
)

logger = logging.getLogger(__name__)

#: How many chunks a query returns. 4 is the tutorial's neighbourhood and a sane
#: default for prose: enough to hold the answer, few enough that the model still
#: sees the question. Raising it is the first thing to try when an answer is
#: "wrong", and the first thing to lower when it is "vague".
DEFAULT_K = 4


def _chunk_ids(splits: List) -> List[str]:
    """Deterministic ids: the same chunk always lands on the same row.

    `PGVector` writes with `ON CONFLICT DO UPDATE`, so a repeated upload of the same
    PDF *updates* its chunks instead of appending a second copy. Without this,
    re-uploading a contract produced the same passage twice with different scores —
    which reads as a retrieval bug and is really a storage one, and it doubles every
    citation.

    The hash covers the source, the page and the text: edit the PDF and the changed
    chunks get new ids (the old ones remain, which is why `reset=True` still exists
    for the "replace the whole document" case).
    """
    import hashlib

    ids = []
    for s in splits:
        md = s.metadata or {}
        key = "|".join(
            [
                str(md.get("source") or ""),
                str(md.get("page") or ""),
                str(md.get("start_index") or ""),
                s.page_content or "",
            ]
        )
        ids.append(hashlib.sha256(key.encode("utf-8")).hexdigest()[:32])
    return ids


def index_file(
    user_id: int,
    file_path: str,
    source_label: Optional[str] = None,
    extra_metadata: Optional[Dict] = None,
    *,
    url: Optional[str] = None,
    reset: bool = False,
) -> Dict:
    """Index one file into the account's collection. Returns a small report.

    `reset=True` drops the collection first: re-indexing over old chunks leaves
    duplicates, and duplicates surface as the same passage cited twice with
    different scores — which reads like a retrieval bug and isn't.
    """
    if reset:
        drop_collection(user_id, url=url)

    docs = load_file(file_path, source_label)
    if extra_metadata:
        for d in docs:
            d.metadata.update(extra_metadata)
    splits = split_documents(docs)
    for s in splits:
        s.metadata.setdefault("source", source_label or file_path)

    store = get_vector_store(user_id, url=url)
    ids = store.add_documents(documents=splits, ids=_chunk_ids(splits))

    logger.info(
        "indexed %s into %s: %d pages → %d chunks",
        source_label or file_path, collection_name(user_id), len(docs), len(splits),
    )
    return {
        "collection": collection_name(user_id),
        "documents": len(docs),
        "chunks": len(splits),
        "ids": len(ids),
        "source": source_label or file_path,
    }


def index_documents(
    user_id: int,
    docs: Iterable,
    *,
    url: Optional[str] = None,
    reset: bool = False,
) -> Dict:
    """Index already-built `Document` objects (what the tests and the API use)."""
    if reset:
        drop_collection(user_id, url=url)
    splits = split_documents(list(docs))
    store = get_vector_store(user_id, url=url)
    ids = store.add_documents(documents=splits, ids=_chunk_ids(splits))
    return {
        "collection": collection_name(user_id),
        "chunks": len(splits),
        "ids": len(ids),
    }


def get_retriever(user_id: int, k: int = DEFAULT_K, *, url: Optional[str] = None, **search_kwargs):
    """A `VectorStoreRetriever` scoped to one account — step 5.

    `search_type="similarity"` is the tutorial's default. `mmr` (maximum marginal
    relevance) is the alternative worth showing in a lesson: it trades a little
    similarity for diversity, which matters when the top 4 chunks are the same
    paragraph four times.
    """
    store = get_vector_store(user_id, url=url)
    kwargs = {"k": k, **search_kwargs}
    return store.as_retriever(search_type="similarity", search_kwargs=kwargs)


def search(user_id: int, query: str, k: int = DEFAULT_K, *, url: Optional[str] = None) -> List:
    """Nearest chunks for a query, as `Document`s with their metadata intact."""
    return get_vector_store(user_id, url=url).similarity_search(query, k=k)


def search_with_scores(
    user_id: int, query: str, k: int = DEFAULT_K, *, url: Optional[str] = None
) -> List:
    """As `search`, plus the score — which is what makes a citation arguable.

    `PGVector` returns a *distance* under the cosine metric, so a smaller number
    means a closer match. Do not present the raw number to a user as a
    "relevance %"; it is a distance in a space only the model understands.
    """
    return get_vector_store(user_id, url=url).similarity_search_with_score(query, k=k)


def has_index(user_id: int, *, url: Optional[str] = None) -> bool:
    return collection_exists(user_id, url=url)
