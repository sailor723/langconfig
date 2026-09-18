# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent Documents API (DB mode document library).

Formal documents agents persist via the ``save_document`` built-in tool
(STORAGE_MODE=db) land in the ``agent_documents`` table. These endpoints
let the Workbench list and retrieve them, including version history.

Endpoints:
    GET /api/agent-documents           -> list latest version per document
    GET /api/agent-documents/{doc_id}  -> full content of one version
    GET /api/agent-documents/{doc_id}/versions -> all versions of a doc
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.database import get_db
from models.agent_document import AgentDocument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-documents", tags=["agent-documents"])


def _doc_to_dict(doc: AgentDocument) -> dict:
    """Serialize one document row (content included for single-get)."""
    return {
        "id": doc.id,
        "project_id": doc.project_id,
        "agent_id": doc.agent_id,
        "execution_id": doc.execution_id,
        "title": doc.title,
        "doc_type": doc.doc_type,
        "version": doc.version,
        "content": doc.content,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.get("")
def list_documents(
    project_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    doc_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List documents (latest version per project+title) with version counts.

    Each returned row is the newest version of a document; ``version_count``
    reports how many versions exist for that title.
    """
    # Latest id per (project_id, title) group via window-function subquery.
    count_sq = (
        db.query(
            AgentDocument.project_id,
            AgentDocument.title,
            func.count(AgentDocument.id).label("version_count"),
        )
        .group_by(AgentDocument.project_id, AgentDocument.title)
        .subquery()
    )
    window = (
        db.query(
            AgentDocument.id,
            func.row_number().over(
                partition_by=[AgentDocument.project_id, AgentDocument.title],
                order_by=AgentDocument.version.desc(),
            ).label("rn"),
        ).subquery()
    )

    query = (
        db.query(AgentDocument, count_sq.c.version_count)
        .join(window, AgentDocument.id == window.c.id)
        .join(count_sq, (count_sq.c.project_id == AgentDocument.project_id) & (count_sq.c.title == AgentDocument.title))
        .filter(window.c.rn == 1)
    )
    if project_id is not None:
        query = query.filter(AgentDocument.project_id == project_id)
    if agent_id is not None:
        query = query.filter(AgentDocument.agent_id == agent_id)
    if doc_type:
        query = query.filter(AgentDocument.doc_type == doc_type)

    rows = query.order_by(AgentDocument.updated_at.desc()).all()
    return [
        {
            **_doc_to_dict(doc),
            "version_count": version_count,
            "content": None,  # list view: omit the heavy content
        }
        for doc, version_count in rows
    ]


@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    """Get the full content of a single document version."""
    doc = db.query(AgentDocument).filter(AgentDocument.id == doc_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_to_dict(doc)


@router.get("/{doc_id}/versions")
def list_document_versions(
    doc_id: int,
    project_id: Optional[int] = None,
    title: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all versions of a document (identified by id, or project+title)."""
    if title:
        query = db.query(AgentDocument).filter(AgentDocument.title == title)
        if project_id is not None:
            query = query.filter(AgentDocument.project_id == project_id)
        rows = query.order_by(AgentDocument.version.asc()).all()
        if not rows:
            raise HTTPException(status_code=404, detail="Document not found")
    else:
        doc = db.query(AgentDocument).filter(AgentDocument.id == doc_id).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        rows = (
            db.query(AgentDocument)
            .filter(
                AgentDocument.title == doc.title,
                AgentDocument.project_id == doc.project_id,
            )
            .order_by(AgentDocument.version.asc())
            .all()
        )
    return [_doc_to_dict(d) for d in rows]
