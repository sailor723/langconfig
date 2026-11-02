# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
User accounts API.

Two surfaces, deliberately separated by role:

* **self-service** — ``/me`` reads and edits your own profile and password. No
  role required; the caller is whoever the LAN gate authenticated (or the local
  owner on loopback).
* **administration** — list/create/disable/promote/reset, guarded by
  ``require_admin``. These return 404 for unknown ids and 403 for members, so a
  member cannot enumerate accounts.

There is no email, no signup and no token reset: an admin sets a password and
tells the person, because this is a LAN app with no outbound mail dependency.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.context.current_user import require_admin, require_user
from db.database import get_db
from models.user import UserRole
from services import user_service
from services.user_service import UserError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


# ── schemas ──────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    username: str
    #: Optional alias that also works at the login prompt (case-insensitive).
    nickname: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None
    #: Configured workspace root, or None when the account uses the default
    #: convention (``<install root>/users/<id>``).
    workspace_path: Optional[str] = None


class MeOut(UserOut):
    """Your own profile — plus *how* you are signed in.

    ``via`` is "session" (the sign-in page), "loopback" (this machine's owner) or
    "lan" (a Basic credential from a script). It is only ever about the caller, so
    it belongs on /me and not on the account list.
    """

    via: str


class UpdateMeRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=128)
    #: Alias you can sign in with. Send "" to remove it, omit to leave it alone.
    nickname: Optional[str] = Field(None, max_length=32)
    #: Absolute path for this account's files. Omit to leave it alone, send ""
    #: (or null) to fall back to ``<install root>/users/<id>``.
    workspace_path: Optional[str] = Field(None, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str = Field(..., description="2-64 chars: letters, digits, . _ -")
    password: str = Field(..., description="At least 8 characters")
    nickname: Optional[str] = Field(None, description="2-32 chars: an extra login alias")
    display_name: Optional[str] = None
    role: str = Field("member", description="admin or member")


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    #: "" removes the alias; omit the field to leave it alone.
    nickname: Optional[str] = Field(None, max_length=32)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    workspace_path: Optional[str] = Field(None, max_length=1024)


class AdminSetPasswordRequest(BaseModel):
    new_password: str


# ── helpers ──────────────────────────────────────────────────────────────────

def _out(user) -> UserOut:
    return UserOut(**user.to_public())


def _apply_workspace_path(db: Session, user, value: Optional[str]):
    """Validate and store a workspace-root override, then drop the cached root.

    One place for both call paths (self and admin) so the checks cannot drift:
    the value must be absolute, must not sit inside another account's tree, and
    two accounts must not resolve to the same directory.
    """
    from services import user_roots

    try:
        normalized = user_roots.validate_workspace_path(db, user.id, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if (user.workspace_path or None) != normalized:
        user.workspace_path = normalized
        db.commit()
        db.refresh(user)
        # The resolver caches one entry per account; a stale entry would keep
        # serving the old tree until the process restarted.
        user_roots.invalidate_root_override(user.id)
        logger.info("User %s workspace_path -> %s", user.username, normalized or "(default)")


def _require_target(db: Session, user_id: int):
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


# ── self-service ─────────────────────────────────────────────────────────────

@router.get("/me", response_model=MeOut)
def get_me(db: Session = Depends(get_db), me=Depends(require_user)):
    """The caller's own profile, and how they got in."""
    user = user_service.get_user(db, me.id)
    if user is None:  # deleted between auth and this call
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return MeOut(**user.to_public(), via=getattr(me, "via", "unknown"))


@router.patch("/me", response_model=UserOut)
def update_me(
    request: UpdateMeRequest,
    db: Session = Depends(get_db),
    me=Depends(require_user),
):
    """Rename yourself and choose where your own files live.

    Role and active state are admin-only fields. ``workspace_path`` is allowed
    here because it only ever moves **your own** tree — the validation still
    rejects another account's directory.
    """
    user = _require_target(db, me.id)
    try:
        user_service.update_user(
            db, user, display_name=request.display_name, nickname=request.nickname
        )
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "workspace_path" in getattr(request, "model_fields_set", set()):
        _apply_workspace_path(db, user, request.workspace_path)
    return _out(user)


@router.post("/me/password")
def change_my_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    me=Depends(require_user),
):
    """Change your own password, proving the current one first.

    The current password is required even though the caller is already
    authenticated: this blocks a walk-up attack on an unlocked browser.
    """
    user = _require_target(db, me.id)
    if not user_service.check_password(db, user, request.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        user_service.set_password(db, user, request.new_password)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("User %s changed their own password", user.username)
    return {"status": "ok"}


# ── administration ───────────────────────────────────────────────────────────

@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Every account (admin only)."""
    return [_out(u) for u in user_service.list_users(db)]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    request: CreateUserRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Create an account. The password is set here; there is no email."""
    try:
        user = user_service.create_user(
            db,
            request.username,
            request.password,
            display_name=request.display_name,
            nickname=request.nickname,
            role=request.role,
        )
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Admin %s created user %s (%s)", admin.username, user.username, user.role)
    return _out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    request: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Change a role or disable an account.

    Refuses to demote or disable the acting admin, or the last active admin —
    locking everyone out of a LAN app with no recovery path is not a feature.
    """
    user = _require_target(db, user_id)
    try:
        user_service.update_user(
            db,
            user,
            display_name=request.display_name,
            nickname=request.nickname,
            role=request.role,
            is_active=request.is_active,
            acting_user_id=admin.id,
        )
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "workspace_path" in getattr(request, "model_fields_set", set()):
        _apply_workspace_path(db, user, request.workspace_path)
    logger.info(
        "Admin %s updated user %s (role=%s active=%s nickname=%s)",
        admin.username,
        user.username,
        user.role,
        user.is_active,
        user.nickname or "-",
    )
    return _out(user)


@router.post("/{user_id}/password")
def admin_set_password(
    user_id: int,
    request: AdminSetPasswordRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Reset someone else's password (admin only). No current password needed."""
    user = _require_target(db, user_id)
    try:
        user_service.set_password(db, user, request.new_password)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Admin %s reset the password for %s", admin.username, user.username)
    return {"status": "ok"}


@router.get("/roles")
def list_roles(admin=Depends(require_admin)):
    """The role vocabulary, so the UI does not hard-code it."""
    return {"roles": [r.value for r in UserRole]}
