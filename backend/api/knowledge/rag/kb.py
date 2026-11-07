# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""The RAG agent's own index + search API (`/api/rag/kb/*`).

There are two retrieval systems in this app and they are easy to confuse:

  * **Project documents** — `context_documents` rows, one pgvector table per
    project (`data_project_index_<id>`). That is what `/api/rag/search` and
    `/api/rag/index/{document_id}` talk to, and what a chat attachment used to be
    embedded into.
  * **The account collection** — `lc_kb_u<user id>`, written by
    `scripts/rag_index.py`, read by the `rag_search` native tool. This is the one
    the document-QA agent (`doc-chat-embed`, id 278) uses, and until now it had
    **no API at all**: indexing meant running a script in a terminal.

That gap is what this module closes. The agent gets both halves over HTTP with the
same identity rule the tool uses — the collection comes from the caller, never
from an argument, so one account cannot search or overwrite another's.

Why indexing is still an explicit request (not a side effect of uploading):
indexing is slow (one local embedding per chunk) and *not* idempotent in spirit —
`reset=true` is the honest way to re-index, and a turn that silently re-indexes a
20-page PDF would stall the conversation. See `scripts/rag_index.py` for the
report format this returns.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.context.current_user import require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rag"])


class KBIndexRequest(BaseModel):
    """Index a file or a folder into the caller's collection."""

    path: str
    reset: bool = False
    source_label: Optional[str] = None


class KBSearchRequest(BaseModel):
    query: str
    k: int = 4


@router.post("/kb/index")
def kb_index(req: KBIndexRequest, user=Depends(require_user)) -> dict:
    """Split, embed and store `path` under the CALLER's collection.

    `reset=true` drops the collection first. Without it, re-indexing an edited file
    leaves the old chunks behind — the same passage then cites twice with two
    scores, which reads as a retrieval bug and is really a storage one.
    """
    from core.rag import index_file

    path = Path(req.path).expanduser()
    if not path.is_absolute():
        # Relative paths are resolved against the backend directory, which is where
        # the CLI puts itself (os.chdir(BACKEND)) — same answer as the script.
        from services import user_roots

        try:
            backend_dir = Path(user_roots.install_root()).parent
        except Exception:  # noqa: BLE001
            backend_dir = Path.cwd()
        path = (backend_dir / path).resolve()
    if not path.exists():
        raise HTTPException(404, f"not found: {path}")

    try:
        report = index_file(user.id, str(path), source_label=req.source_label, reset=req.reset)
    except Exception as exc:  # noqa: BLE001 — surface the reason, do not 200 an empty index
        logger.error("kb_index failed for %s: %s", path, exc, exc_info=True)
        raise HTTPException(500, f"indexing failed: {exc}") from exc

    logger.info("indexed %s into %s: %s chunks", path.name, report.get("collection"), report.get("chunks"))
    return report


@router.post("/kb/search")
def kb_search(req: KBSearchRequest, user=Depends(require_user)) -> dict:
    """Nearest passages from the caller's collection, with source and score.

    Same shape the `rag_search` tool prints, so a UI can show citations without
    parsing prose: passages are returned as data, never as a pre-formatted answer.
    """
    from core.rag import has_index, search_with_scores

    if not req.query.strip():
        raise HTTPException(400, "query is required")
    if not has_index(user.id):
        return {"collection": None, "results": [], "indexed": False}
    k = max(1, min(int(req.k or 4), 20))
    pairs = search_with_scores(user.id, req.query, k=k)
    results = []
    for doc, score in pairs:
        md = doc.metadata or {}
        results.append(
            {
                "text": doc.page_content,
                "source": md.get("source"),
                "page": md.get("page"),
                "score": score,
            }
        )
    return {"collection": f"lc_kb_u{user.id}", "results": results, "indexed": True}


@router.get("/kb/status")
def kb_status(user=Depends(require_user)) -> dict:
    """Whether this account has an index, and how big it is."""
    from core.rag import has_index
    from core.rag.store import collection_name

    try:
        exists = has_index(user.id)
    except Exception as exc:  # noqa: BLE001 — a missing table means "no index yet"
        logger.warning("kb_status failed: %s", exc)
        return {"collection": collection_name(user.id), "indexed": False, "error": str(exc)}
    return {"collection": collection_name(user.id), "indexed": exists}
