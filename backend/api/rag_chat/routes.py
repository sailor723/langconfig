# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Embedding-based document chat — the retrieval half of `/api/doc-chat`, kept separate.

Two endpoints families answer "chat with a document" on this platform and they are
not versions of each other:

    POST /api/doc-chat                    KV: read the whole file, inline it, answer.
                                          Exact, unbounded recall on the documents
                                          that fit; useless past the context window.

    POST /api/rag-chat/index              Embed: split → embed → store (steps 1-4 of
    POST /api/rag-chat/ask                the LangChain semantic-search tutorial).
    GET  /api/rag-chat/status             Retrieves the nearest chunks and answers with
    DELETE /api/rag-chat/index            page-level citations (step 5).

This router is the embed side only. It reuses none of the KV chat's prompt assembly,
because the two are meant to be compared: same question, two mechanisms, visible
difference in what each can cite and what each gets wrong.

Scoping: every call resolves the caller's account and uses that account's own
collection (`lc_kb_u<id>`). There is no request field for "whose documents" — the
identity comes from the session, which is the same rule the rest of the app follows.

Answering is **retrieve-then-answer**, the tutorial's minimal RAG: search, put the
chunks in the prompt with their source labels, ask the model to answer only from
them. The agent-with-a-retrieval-tool version is a later case; this one exists to
make the retrieval step observable without an agent deciding anything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.context.current_user import require_user
from core.rag import (
    DEFAULT_K,
    collection_name,
    drop_collection,
    has_index,
    search_with_scores,
)
from db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag-chat", tags=["rag-chat"])


# ── schemas ─────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    """Index documents the account already owns.

    `session_documents` / `context_documents` rows are referenced by id rather than
    by path: a path would let a caller index a file outside their own tree, and the
    file's location is already recorded by the row that owns it.
    """

    document_ids: List[int] = Field(default_factory=list, description="session_documents ids")
    knowledge: str = Field("", description="Knowledge-base folder name, if indexing a folder")
    folder_path: str = Field("", description="Folder inside that knowledge base")
    reset: bool = Field(False, description="Drop this account's collection before indexing")


class IndexResponse(BaseModel):
    collection: str
    chunks: int
    documents: int
    sources: List[str]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    k: int = Field(DEFAULT_K, ge=1, le=20, description="How many chunks to retrieve")
    model: Optional[str] = Field(None, description="Defaults to the account's default model")
    temperature: float = Field(0.0, ge=0.0, le=2.0)


class Citation(BaseModel):
    source: str
    page: Optional[int] = None
    distance: float
    preview: str


class AskResponse(BaseModel):
    answer: str
    citations: List[Citation]
    retrieved: int
    model: str
    collection: str


class StatusResponse(BaseModel):
    collection: str
    indexed: bool
    chunks: int


# ── helpers ─────────────────────────────────────────────────────────────────

def _resolve_user(me) -> int:
    """The account whose collection this call touches. Never a request field."""
    uid = getattr(me, "id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return int(uid)


def _citation(doc, distance: float) -> Citation:
    md = doc.metadata or {}
    text = " ".join((doc.page_content or "").split())
    return Citation(
        source=str(md.get("source") or "unknown"),
        page=md.get("page"),
        distance=round(float(distance), 4),
        preview=text[:240],
    )


def _context_block(citations: List[Citation], docs: List[Any]) -> str:
    """The retrieved passages, numbered and labelled, as the answer prompt sees them.

    Numbered + labelled because the model is asked to cite by number: a citation
    that points at a passage the model never saw is indistinguishable from a
    fabricated one, so the numbers have to come from here.
    """
    lines = []
    for i, (doc, cit) in enumerate(zip(docs, citations), start=1):
        page = f" p.{cit.page}" if cit.page else ""
        lines.append(f"[{i}] {cit.source}{page}\n{doc.page_content}")
    return "\n\n".join(lines)


SYSTEM_PROMPT = """You answer questions using only the numbered passages provided.

Rules:
- Every factual claim ends with the passage number it came from, like [1] or [2][3].
- If the passages do not contain the answer, say so plainly: "The provided passages
  do not answer this." Do not fill the gap from your own knowledge.
- If the passages conflict, say they conflict and cite both.
- Do not cite a number that is not in the list."""


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db), me=Depends(require_user)):
    """Whether this account has an index yet, and how big it is."""
    uid = _resolve_user(me)
    name = collection_name(uid)
    if not has_index(uid):
        return StatusResponse(collection=name, indexed=False, chunks=0)
    # Count only; the store is created lazily by PGVector, so ask the collection row.
    import psycopg

    from core.rag.store import plain_dsn

    try:
        with psycopg.connect(plain_dsn()) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                WHERE c.name = %s
                """,
                (name,),
            )
            chunks = int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001 — an unreadable count must not fail the status
        chunks = 0
    return StatusResponse(collection=name, indexed=chunks > 0, chunks=chunks)


@router.post("/index", response_model=IndexResponse)
def index_documents(
    req: IndexRequest,
    db: Session = Depends(get_db),
    me=Depends(require_user),
):
    """Index this account's documents into its own collection."""
    uid = _resolve_user(me)

    from models.deep_agent import ChatSession, SessionDocument

    from core.rag import index_documents as run_index

    docs: List[Any] = []
    sources: List[str] = []

    if req.document_ids:
        # Ownership is resolved through the conversation, not assumed: a session
        # document has no owner column of its own — it belongs to whoever owns the
        # chat it was uploaded to. Filtering in SQL (not in Python) means a document
        # belonging to another account is simply absent, so it cannot be indexed and
        # its text cannot reach this account's collection.
        rows = (
            db.query(SessionDocument)
            .join(ChatSession, ChatSession.session_id == SessionDocument.session_id)
            .filter(
                SessionDocument.id.in_(req.document_ids),
                ChatSession.user_id == uid,
            )
            .all()
        )
        if len(rows) != len(set(req.document_ids)):
            raise HTTPException(
                status_code=404,
                detail="One or more documents were not found for this account",
            )
        from core.rag.documents import load_file

        for row in rows:
            path = getattr(row, "file_path", None) or getattr(row, "path", None)
            if not path:
                continue
            docs.extend(load_file(path, source_label=getattr(row, "filename", None)))
            sources.append(str(getattr(row, "filename", None) or path))

    if req.knowledge:
        from services.kb_discovery import documents_dir

        root = documents_dir(req.knowledge)
        target = (root / req.folder_path).resolve() if req.folder_path else root.resolve()
        if not str(target).startswith(str(root.resolve())):
            raise HTTPException(status_code=400, detail="folder_path escapes the knowledge base")
        from core.rag.documents import load_file

        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            try:
                docs.extend(load_file(path))
                sources.append(path.name)
            except ValueError:
                continue  # unsupported suffix: skip rather than index binary noise

    if not docs:
        raise HTTPException(
            status_code=400,
            detail="Nothing to index: pass document_ids, or a knowledge folder with supported files",
        )

    report = run_index(uid, docs, reset=req.reset)
    logger.info("rag-chat index user=%s %s", uid, report)
    return IndexResponse(
        collection=report["collection"],
        chunks=report.get("chunks", 0),
        documents=len(docs),
        sources=sources,
    )


@router.delete("/index")
def delete_index(me=Depends(require_user)):
    """Drop this account's collection (re-index from scratch, or start over)."""
    uid = _resolve_user(me)
    drop_collection(uid)
    return {"collection": collection_name(uid), "dropped": True}


@router.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    db: Session = Depends(get_db),
    me=Depends(require_user),
):
    """Retrieve this account's nearest chunks, then answer from them only."""
    uid = _resolve_user(me)

    if not has_index(uid):
        raise HTTPException(
            status_code=409,
            detail="No index for this account yet — index some documents first",
        )

    pairs = search_with_scores(uid, req.question, k=req.k)
    docs = [d for d, _ in pairs]
    citations = [_citation(d, s) for d, s in pairs]
    if not docs:
        return AskResponse(
            answer="The provided passages do not answer this.",
            citations=[],
            retrieved=0,
            model="",
            collection=collection_name(uid),
        )

    from core.settings import resolve_value
    from services.agent_utils import resolve_model

    model_name = req.model or resolve_value(db, "models").get("default_model")
    llm = await resolve_model(model_name, req.temperature, 2000, {})

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(
            content=SYSTEM_PROMPT
            + "\n\nPassages:\n\n"
            + _context_block(citations, docs)
        ),
        HumanMessage(content=req.question),
    ]
    result = await llm.ainvoke(messages)
    answer = result.content if isinstance(result.content, str) else str(result.content)

    return AskResponse(
        answer=answer,
        citations=citations,
        retrieved=len(docs),
        model=str(model_name),
        collection=collection_name(uid),
    )
