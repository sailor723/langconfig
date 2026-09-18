# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DSH-style settings wire API (docs/settings-refactor.md §6).

Two generic endpoints replace the ~26 bespoke legacy endpoints:

- ``GET  /api/settings/describe`` — every namespace with its JSON Schema,
  resolved value, raw user section, revision, writable flag, and redacted
  secret positions. The Settings UI renders all sections from this one call.
- ``POST /api/settings/mutate`` — path ops (set/unset) against one namespace
  with an optimistic ``expectedRevision`` (409 on stale), mirroring DSH's
  ``settings.mutate``.

Secrets never cross the wire: secret fields are stripped from ``value``/``user``
and enumerated in ``secrets`` (``{path, set}``) so the UI can render write-only
inputs with set/missing dots.

The legacy endpoints in ``api/system/settings.py`` are intentionally left
untouched for now — they back the current UI. Once the frontend migrates to
this surface, the legacy router is deleted (Phase 4/5).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from core import settings as core_settings
from db.database import get_db

router = APIRouter(prefix="/api/settings", tags=["settings-documents"])


class MutateOp(BaseModel):
    op: Literal["set", "unset"]
    path: list[str]
    value: Any = None


class MutateRequest(BaseModel):
    ns: str
    ops: list[MutateOp]
    expected_revision: Optional[int] = None


class MutateResponse(BaseModel):
    ns: str
    value: dict
    revision: int
    secrets: list[dict]


@router.get("/describe")
def describe(db: Session = Depends(get_db)):
    """All registered namespaces: schema + resolved value + user section +
    revision + redacted secret positions (the UI's single render source)."""
    try:
        resolved = core_settings.resolve_all(db)
    except Exception as exc:  # noqa: BLE001 — surface a clear 500 for DB issues
        raise HTTPException(status_code=500, detail=f"settings describe failed: {exc}") from exc
    return {"namespaces": [r.wire() for r in resolved], "writable": True}


# ── runtime side-effects on mutate ───────────────────────────────────────────
# A workspace-path change must take effect immediately: drop the cached
# WorkspaceManager so the next access builds from the new root.

def _apply_runtime_side_effects(db: Session, ns: str) -> None:
    if ns == "workspace":
        try:
            from services.workspace_manager import reset_workspace_manager
            reset_workspace_manager()
        except Exception:  # noqa: BLE001 — never fail a write for a cache reset
            pass


@router.post("/mutate", response_model=MutateResponse)
def mutate(req: MutateRequest, db: Session = Depends(get_db)):
    """Apply path ops to one namespace's user section (optimistic revision)."""
    if not core_settings.is_registered(req.ns):
        raise HTTPException(status_code=404, detail=f"unknown settings namespace {req.ns!r}")
    ops = [op.model_dump() for op in req.ops]
    try:
        doc, revision = core_settings.mutate(db, req.ns, ops, req.expected_revision)
    except core_settings.SettingsConflict as exc:
        # Stale write — the client holds an older revision; retry after re-read.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        # The resulting document violates the namespace schema.
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        # Malformed op (empty path, missing value, …).
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _apply_runtime_side_effects(db, req.ns)

    spec = core_settings.get(req.ns)
    redacted, secrets = core_settings.redact(doc, spec.schema)
    return MutateResponse(ns=req.ns, value=redacted, revision=revision, secrets=secrets)
