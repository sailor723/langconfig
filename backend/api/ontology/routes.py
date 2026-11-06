"""Ontology workbench routes.

The workbench is one process per ontology profile, and nobody should have to start them by
hand: these endpoints report what is running and start whatever is not. The supervisor lives
in `services/ontology_workbench.py` (lazy start, one child per profile, health = the
workbench's own answer).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from services import ontology_workbench

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/workbenches")
async def list_workbenches(ensure: bool = True):
    """Every configured ontology, with its live state. Starts what is not running."""
    return await ontology_workbench.status(ensure=ensure)


@router.post("/workbenches/{key}/stop")
async def stop_workbench(key: str):
    return ontology_workbench.stop(key)
