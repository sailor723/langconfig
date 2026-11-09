# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent Memory Management API

Provides endpoints to view, search, and manage agent memories stored in the vector database.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from db.database import get_db
from services.llama_config import get_vector_store
from core.agents.memory import MemoryType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# Response Models
class MemoryItem(BaseModel):
    """A single memory item"""
    memory_id: str
    content: str
    memory_type: str
    importance: int
    tags: List[str]
    agent_id: str
    created_at: str

    class Config:
        from_attributes = True


class MemorySearchResponse(BaseModel):
    """Response for memory search"""
    memories: List[MemoryItem]
    total: int
    query: Optional[str] = None


class MemoryStatsResponse(BaseModel):
    """Memory statistics for a project"""
    total_memories: int
    by_type: dict
    by_agent: dict
    avg_importance: float


# Request Models
class MemorySearchRequest(BaseModel):
    """Request to search memories"""
    query: str = Field(..., description="Search query")
    k: int = Field(5, ge=1, le=50, description="Number of results")
    min_importance: Optional[int] = Field(None, ge=1, le=10)
    memory_types: Optional[List[str]] = None
    tags: Optional[List[str]] = None





