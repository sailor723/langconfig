"""Ontology workbench routes.

The workbench is one process per ontology profile, and nobody should have to start them by
hand: these endpoints report what is running and start whatever is not. The supervisor lives
in `services/ontology_workbench.py` (lazy start, one child per profile, health = the
workbench's own answer).
"""
from __future__ import annotations

import logging

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import ontology_publish, ontology_workbench

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/workbenches")
async def list_workbenches(ensure: bool = True):
    """Every configured ontology, with its live state. Starts what is not running."""
    return await ontology_workbench.status(ensure=ensure)


@router.post("/workbenches/{key}/stop")
async def stop_workbench(key: str):
    return ontology_workbench.stop(key)


# ── publishing declarations ────────────────────────────────────────────────
# Stage validates and changes nothing; apply needs confirmation and an editor. An agent can
# only reach `stage` — that is the difference between "the agent did the work" and "the agent
# changed production on its own".

class StageRequest(BaseModel):
    key: str
    files: dict[str, str]
    note: Optional[str] = ""
    profile_name: Optional[str] = None


class ApplyRequest(BaseModel):
    confirmed: bool = False
    git_commit: bool = True


def _require_editor() -> str:
    """Who may publish. `ontology_editor` (or admin) — a role, because a publish changes what
    a number MEANS for everyone."""
    try:
        from services.user_roots import subject_user_id
        from db.database import SessionLocal
        from services.user_service import get_user

        uid = subject_user_id()
        if uid is None:
            return "owner"                     # single-user install: the owner publishes
        db = SessionLocal()
        try:
            user = get_user(db, uid)
            role = getattr(user, "role", None)
            role = getattr(role, "value", role)
            name = getattr(user, "username", str(uid))
        finally:
            db.close()
    except Exception as exc:                                    # noqa: BLE001
        raise HTTPException(500, f"could not verify your role ({exc})") from exc
    if role not in ("admin", "ontology_editor"):
        raise HTTPException(
            403,
            f"publishing an ontology needs the ontology_editor role (you are role={role!r}); "
            "ask an admin to grant it, or keep the change as a proposal",
        )
    return name


@router.post("/publish/stage")
async def publish_stage(req: StageRequest):
    """Validate a candidate ontology without touching the installed one."""
    actor = _require_editor()
    return ontology_publish.stage(req.key, req.files, actor=actor, note=req.note or "",
                                  profile_name=req.profile_name)


@router.post("/publish/{staged_id}/apply")
async def publish_apply(staged_id: str, req: ApplyRequest):
    """Install a staged publish. Needs `confirmed` from a human (agents cannot confirm)."""
    actor = _require_editor()
    if not req.confirmed:
        raise HTTPException(400, "confirmed=false: a publish lands only after a human says so")
    res = ontology_publish.apply(staged_id, actor=actor, confirmed=True,
                                 git_commit=req.git_commit)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error") or "publish failed")
    return res


@router.get("/publish/history")
async def publish_history(key: Optional[str] = None, limit: int = 50,
                          status: Optional[str] = None):
    """The publish ledger, newest first. `status=staged` is what a human has to decide on."""
    rows = ontology_publish.history(key=key, limit=limit)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return {"ok": True, "publishes": rows}


@router.post("/publish/{staged_id}/discard")
async def publish_discard(staged_id: str):
    """Drop a staged candidate (an editor decision, same role as apply)."""
    actor = _require_editor()
    res = ontology_publish.discard(staged_id, actor=actor)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error") or "discard failed")
    return res


@router.get("/publish/{staged_id}")
async def publish_one(staged_id: str):
    rows = ontology_publish._audit_list(staged_id)
    if not rows:
        raise HTTPException(404, f"no publish {staged_id!r}")
    return {"ok": True, "publish": rows[0]}
