# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Skills API - CRUD, discovery, and invocation endpoints.

Provides REST endpoints for managing modular, context-aware skills
that agents can automatically invoke or users can trigger explicitly.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, AliasChoices
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import json
import os

from db.database import get_db
from core.skills.registry import get_skill_registry
from models.skill import Skill, SkillSourceType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================

class SkillResponse(BaseModel):
    """Skill data for API responses.

    Per the Agent Skills Specification (https://agentskills.io/specification),
    the SKILL.md frontmatter uses kebab-case `allowed-tools`. We accept both
    snake_case (DB native) and kebab-case (spec-native) on input via
    `validation_alias=AliasChoices(...)`. The kebab-case mirror on output
    is added by `_skill_to_response_dict()` which post-processes the dict.

    All fields are optional except `skill_id` to tolerate legacy DB records
    that may have NULL in some columns.
    """
    skill_id: str
    name: Optional[str] = ""
    description: Optional[str] = ""
    version: Optional[str] = ""
    source_type: Optional[str] = ""
    tags: Optional[List[str]] = Field(default_factory=list)
    triggers: Optional[List[str]] = Field(default_factory=list)
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("allowed_tools", "allowed-tools"),
        description="Accepts both `allowed_tools` (snake) and `allowed-tools` (kebab).",
    )
    usage_count: Optional[int] = 0
    last_used_at: Optional[datetime] = None
    avg_success_rate: Optional[float] = 0.0

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class SkillDetailResponse(SkillResponse):
    """Detailed skill with instructions and examples."""
    instructions: Optional[str] = ""
    examples: Optional[str] = None
    source_path: Optional[str] = ""
    author: Optional[str] = None
    required_context: Optional[List[str]] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillMatchRequest(BaseModel):
    """Request to find matching skills."""
    query: str = Field(..., description="User query to match against skills")
    file_path: Optional[str] = Field(None, description="Current file path for context")
    project_type: Optional[str] = Field(None, description="Project type (e.g., python, nodejs)")
    tags: Optional[List[str]] = Field(None, description="Explicit tags to match")
    max_results: int = Field(5, ge=1, le=20, description="Maximum results to return")
    skill_ids: Optional[List[str]] = Field(None, description="Optional allowlist — only consider these skills")


class SkillMatchResponse(BaseModel):
    """Skill match result with relevance info."""
    skill: SkillResponse
    score: float
    match_reason: str


# =============================================================================
# Helper Functions
# =============================================================================

# Stop words for trigger matching — words too common to be meaningful signals.
_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "i", "you", "he", "she", "it", "we", "they", "them", "their", "my",
    "your", "his", "her", "its", "our", "this", "that", "these", "those",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "from", "up", "down", "out", "off", "over", "under", "again",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "s", "t", "d", "m", "re", "ve",
    "ll", "user", "users", "ask", "asks", "asking", "want", "wants",
    "wanting", "need", "needs", "needing", "use", "uses", "using",
})

import re as _re


def _tokenize(text: str) -> list[str]:
    """Lowercase + split into alphanumeric tokens (length >= 2)."""
    if not text:
        return []
    return [t for t in _re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 2]


def _extract_trigger_keywords(trigger: str) -> list[str]:
    """Extract a list of meaningful phrase-level keywords from a trigger string.

    Examples:
      "when user asks about recent events or current news"
      → ["recent events", "current news"]

      "if user wants to search the web"
      → ["search", "web"]

    Strategy: keep 2-gram phrases (skip stop-word-only phrases) and unique tokens.
    """
    if not trigger:
        return []
    tokens = _tokenize(trigger)
    if not tokens:
        return []
    keywords: list[str] = []
    # 1) Bigrams (consecutive 2-word phrases) — meaningful signals like "recent events"
    for i in range(len(tokens) - 1):
        phrase = f"{tokens[i]} {tokens[i+1]}"
        if any(w not in _STOP_WORDS for w in (tokens[i], tokens[i+1])):
            keywords.append(phrase)
    # 2) Single meaningful tokens (no duplicates)
    seen: set[str] = set()
    for t in tokens:
        if t not in _STOP_WORDS and t not in seen:
            keywords.append(t)
            seen.add(t)
    return keywords

def _db_skill_to_match_obj(dbs):
    """Build a duck-typed Skill-like object from a DB Skill row.

    We need this because `match_skills` iterates over skills and reads
    .description / .name / .tags / .triggers — and DB-only skills aren't in
    the in-memory registry. Return a plain object that has those attributes.
    """
    from types import SimpleNamespace
    return SimpleNamespace(
        skill_id=dbs.skill_id,
        name=dbs.name or "",
        description=dbs.description or "",
        version=dbs.version or "1.0.0",
        author=dbs.author or "",
        source_type=dbs.source_type or "personal",
        source_path=dbs.source_path or "",
        tags=list(dbs.tags or []),
        triggers=list(dbs.triggers or []),
        allowed_tools=_normalize_allowed_tools(dbs.allowed_tools) or [],
        instructions=dbs.instructions or "",
        examples=dbs.examples or "",
        avg_success_rate=dbs.avg_success_rate or 1.0,
        usage_count=dbs.usage_count or 0,
        last_used_at=dbs.last_used_at,
        created_at=dbs.created_at,
        updated_at=dbs.updated_at,
        required_context=list(dbs.required_context or []),
    )


def _normalize_allowed_tools(value):
    """Coerce allowed_tools from any of {list, JSON-string, None} to List[str] or None.

    Legacy DB records may store allowed_tools as a JSON-encoded string (e.g.
    '["web_search", "web_fetch"]') instead of a native JSON list. The DB
    column is JSON-typed but historical inserts via SQL might have stringified
    the value. Accept both forms so older rows don't break Pydantic validation.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Try JSON first (handles '["a","b"]' and 'null')
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
            if parsed is None:
                return None
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to Python literal (handles "['a','b']" from repr())
        try:
            import ast
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
        # Last resort: treat as single tool name
        return [s]
    return list(value) if value else None


def _skill_to_response(skill: Skill) -> SkillResponse:
    """Convert Skill model to SkillResponse."""
    return SkillResponse(
        skill_id=skill.skill_id,
        name=skill.name or "",
        description=skill.description or "",
        version=skill.version or "",
        source_type=skill.source_type.value if hasattr(skill.source_type, 'value') else (skill.source_type or ""),
        tags=skill.tags or [],
        triggers=skill.triggers or [],
        allowed_tools=_normalize_allowed_tools(skill.allowed_tools),
        usage_count=skill.usage_count or 0,
        last_used_at=skill.last_used_at,
        avg_success_rate=skill.avg_success_rate or 0.0
    )


def _skill_to_detail_response(skill: Skill) -> SkillDetailResponse:
    """Convert Skill model to SkillDetailResponse."""
    return SkillDetailResponse(
        skill_id=skill.skill_id,
        name=skill.name or "",
        description=skill.description or "",
        version=skill.version or "",
        source_type=skill.source_type.value if hasattr(skill.source_type, 'value') else (skill.source_type or ""),
        tags=skill.tags or [],
        triggers=skill.triggers or [],
        allowed_tools=_normalize_allowed_tools(skill.allowed_tools),
        usage_count=skill.usage_count or 0,
        last_used_at=skill.last_used_at,
        avg_success_rate=skill.avg_success_rate or 0.0,
        instructions=skill.instructions or "",
        examples=skill.examples,
        source_path=skill.source_path or "",
        author=skill.author,
        required_context=skill.required_context or [],
        created_at=skill.created_at,
        updated_at=skill.updated_at
    )


def _kebabify_skill_dict(d: dict) -> dict:
    """Add the `allowed-tools` kebab-case mirror to a serialized skill dict.

    Per the Agent Skills Specification, frontmatter uses kebab-case. We emit
    BOTH `allowed_tools` (snake, legacy) and `allowed-tools` (kebab, spec).
    """
    if not isinstance(d, dict):
        return d
    tools = d.get("allowed_tools")
    if tools is not None and "allowed-tools" not in d:
        d["allowed-tools"] = tools
    return d


def _skill_to_response_dict(skill: Skill) -> dict:
    """Serialize a Skill to dict with both `allowed_tools` AND `allowed-tools`."""
    return _kebabify_skill_dict(_skill_to_response(skill).model_dump())


def _skill_to_detail_response_dict(skill: Skill) -> dict:
    """Serialize a Skill to dict with full detail + both `allowed_tools` AND `allowed-tools`."""
    return _kebabify_skill_dict(_skill_to_detail_response(skill).model_dump())


# =============================================================================
# Skill Endpoints
# =============================================================================

@router.get("", response_model=List[SkillResponse])
async def list_skills(
    source_type: Optional[str] = Query(None, description="Filter by source: builtin, personal, project"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search by name/description")
):
    """
    List all available skills with optional filtering.

    Query parameters:
    - source_type: Filter by builtin, personal, or project
    - tag: Filter by a specific tag
    - search: Text search across names and descriptions
    """
    # Query DB directly (includes both filesystem-loaded and tool-created skills)
    from sqlalchemy import or_
    from db.database import SessionLocal
    from models.skill import Skill

    db = SessionLocal()
    try:
        query = db.query(Skill)

        if source_type:
            query = query.filter(Skill.source_type == source_type)
        if tag:
            query = query.filter(Skill.tags.any(tag))
        if search:
            term = f"%{search}%"
            query = query.filter(
                or_(Skill.name.ilike(term), Skill.description.ilike(term))
            )

        skills = query.order_by(Skill.skill_id).all()
    finally:
        db.close()

    # Tolerate per-skill validation errors — legacy DB rows may have NULL
    # fields that fail Pydantic. Log and emit a minimal placeholder instead
    # of failing the whole list (which would break the frontend via CORS).
    result = []
    for s in skills:
        try:
            result.append(_skill_to_response_dict(s))
        except Exception as exc:
            logger.warning(
                f"Failed to serialize skill {s.skill_id!r} for list response: {exc}. "
                f"Emitting minimal placeholder."
            )
            result.append({
                "skill_id": s.skill_id,
                "name": s.skill_id,
                "description": "(serialization error — DB record has unexpected fields)",
                "version": "",
                "source_type": "",
                "tags": [],
                "triggers": [],
                "allowed_tools": None,
                "allowed-tools": None,
                "usage_count": 0,
                "last_used_at": None,
                "avg_success_rate": 0.0,
                "_serialization_error": True,
            })
    return result


@router.get("/summary")
async def get_skills_summary():
    """
    Get a summary of available skills.

    Returns counts by source type and tag statistics.
    """
    from db.database import SessionLocal
    from models.skill import Skill

    db = SessionLocal()
    try:
        skills = db.query(Skill).all()
        by_source = {}
        tag_counts = {}
        for skill in skills:
            source = skill.source_type.value if hasattr(skill.source_type, 'value') else skill.source_type
            by_source[source] = by_source.get(source, 0) + 1
            for tag in (skill.tags or []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    finally:
        db.close()

    return {
        "total": len(skills),
        "by_source": by_source,
        "top_tags": sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    }


@router.get("/{skill_id}")
async def get_skill(skill_id: str):
    """Get detailed information for a specific skill."""
    from db.database import SessionLocal
    from models.skill import Skill

    db = SessionLocal()
    try:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
    finally:
        db.close()

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    return _skill_to_detail_response_dict(skill)


class SkillCreateRequest(BaseModel):
    """Request to create a new skill.

    Accepts both `allowed_tools` (snake) and `allowed-tools` (kebab, per
    Agent Skills spec) on input.
    """
    name: str = Field(..., description="Skill name")
    description: str = Field(..., description="Brief description of the skill")
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    triggers: List[str] = Field(default_factory=list, description="Auto-trigger conditions")
    instructions: str = Field("", description="Detailed instructions for the skill")
    examples: Optional[str] = Field(None, description="Optional example dialogs (markdown)")
    author: Optional[str] = Field(None, description="Skill author")
    version: Optional[str] = Field(None, description="Initial version (defaults to 1.0.0)")
    required_context: Optional[List[str]] = Field(default=None, description="Required context entries")
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("allowed_tools", "allowed-tools"),
        description="Tools this skill may use (accepts both snake and kebab case).",
    )


class SkillUpdateRequest(BaseModel):
    """Request to update a skill.

    Accepts both `allowed_tools` (snake) and `allowed-tools` (kebab, per
    Agent Skills spec) on input. All fields are optional — only fields
    that are provided will be updated.
    """
    model_config = {"populate_by_name": True}

    name: Optional[str] = Field(None, description="Updated skill name")
    description: Optional[str] = Field(None, description="Updated description")
    tags: Optional[List[str]] = Field(None, description="Updated tags list")
    triggers: Optional[List[str]] = Field(None, description="Updated trigger conditions")
    instructions: Optional[str] = Field(None, description="Updated instructions")
    examples: Optional[str] = Field(None, description="Updated examples (markdown)")
    author: Optional[str] = Field(None, description="Updated author")
    version: Optional[str] = Field(None, description="Updated version")
    required_context: Optional[List[str]] = Field(None, description="Updated required context")
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("allowed_tools", "allowed-tools"),
        description="Updated tools list (accepts both snake and kebab case).",
    )


@router.post("")
async def create_skill(request: SkillCreateRequest):
    """
    Create a new personal skill.

    Creates a skill that is stored in the database (not filesystem).
    """
    registry = get_skill_registry()

    if not registry._initialized:
        await registry.initialize()

    # Generate skill_id from name
    skill_id = request.name.lower().replace(" ", "-").replace("_", "-")

    # Check if skill already exists
    if registry.get_skill(skill_id):
        raise HTTPException(status_code=409, detail=f"Skill '{skill_id}' already exists")

    try:
        skill = await registry.create_skill(
            skill_id=skill_id,
            name=request.name,
            description=request.description,
            tags=request.tags,
            triggers=request.triggers,
            instructions=request.instructions,
            allowed_tools=request.allowed_tools,
            examples=request.examples,
            author=request.author,
            version=request.version,
            required_context=request.required_context,
        )
    except Exception as e:
        logger.error(f"Failed to create skill: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {str(e)}")

    # Sync to filesystem (Option A: DB primary, FS git-tracked materialized view)
    try:
        from core.skills.sync import db_row_to_fs
        from db.database import SessionLocal
        from models.skill import Skill as SkillModel
        with SessionLocal() as db:
            db_row = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
            if db_row:
                db_row_to_fs(db_row)
                logger.debug(f"Created {skill_id} on FS")
    except Exception as fs_err:
        logger.warning(f"FS sync failed for {skill_id} (DB was updated): {fs_err}")

    return _skill_to_detail_response_dict(skill)


@router.put("/{skill_id}")
async def update_skill(skill_id: str, request: SkillUpdateRequest):
    """
    Update a skill's properties.

    Only updates fields that are provided in the request.
    Works for both registry (builtin) and DB (personal) skills.
    """
    from db.database import SessionLocal
    from models.skill import Skill as SkillModel

    registry = get_skill_registry()

    if not registry._initialized:
        await registry.initialize()

    skill = registry.get_skill(skill_id)

    # If not in registry, try DB (personal skills)
    if not skill:
        db = SessionLocal()
        try:
            db_skill = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
            if not db_skill:
                raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

            # Update fields if provided
            if request.name is not None:
                db_skill.name = request.name
            if request.description is not None:
                db_skill.description = request.description
            if request.tags is not None:
                db_skill.tags = list(request.tags)
            if request.triggers is not None:
                db_skill.triggers = list(request.triggers)
            if request.instructions is not None:
                db_skill.instructions = request.instructions
            if request.examples is not None:
                db_skill.examples = request.examples
            if request.author is not None:
                db_skill.author = request.author
            if request.version is not None:
                db_skill.version = request.version
            if request.required_context is not None:
                db_skill.required_context = list(request.required_context)
            if request.allowed_tools is not None:
                # Persist as snake_case for DB (frontmatter will emit kebab-case)
                import json as _json
                if isinstance(request.allowed_tools, list):
                    db_skill.allowed_tools = _json.dumps(request.allowed_tools)

            db_skill.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(db_skill)
            return _skill_to_detail_response_dict(db_skill)
        finally:
            db.close()

    # Registry skill (builtin)
    if request.name is not None:
        skill.name = request.name
    if request.description is not None:
        skill.description = request.description
    if request.tags is not None:
        skill.tags = list(request.tags)
    if request.triggers is not None:
        skill.triggers = list(request.triggers)
    if request.instructions is not None:
        skill.instructions = request.instructions
    if request.examples is not None:
        skill.examples = request.examples
    if request.author is not None:
        skill.author = request.author
    if request.version is not None:
        skill.version = request.version
    if request.required_context is not None:
        skill.required_context = list(request.required_context)
    if request.allowed_tools is not None:
        skill.allowed_tools = list(request.allowed_tools or [])

    skill.updated_at = datetime.utcnow()

    try:
        await registry.update_skill(skill)
    except Exception as e:
        logger.error(f"Failed to update skill {skill_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")

    # Sync to filesystem (Option A: DB primary, FS git-tracked materialized view)
    try:
        from core.skills.sync import db_row_to_fs
        # Re-fetch from DB to get persisted state
        from db.database import SessionLocal
        from models.skill import Skill as SkillModel
        with SessionLocal() as db:
            db_row = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
            if db_row:
                db_row_to_fs(db_row)
                logger.debug(f"Synced {skill_id} → FS")
    except Exception as fs_err:
        # Don't fail the request if FS sync fails — DB is primary
        logger.warning(f"FS sync failed for {skill_id} (DB was updated): {fs_err}")

    return _skill_to_detail_response_dict(skill)


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """
    Delete a skill.

    Only personal/project skills can be deleted.
    Builtin skills cannot be deleted.

    Looks up the skill in BOTH the in-memory registry AND the database,
    since DB-only personal skills may not be loaded into the registry yet.
    """
    from db.database import SessionLocal
    from models.skill import Skill

    registry = get_skill_registry()
    if not registry._initialized:
        await registry.initialize()

    # Check in-memory registry first (faster path for known skills)
    skill = registry.get_skill(skill_id)
    source_type = None

    if skill:
        source_type = skill.source_type
        if hasattr(source_type, 'value'):
            source_type = source_type.value
    else:
        # Fall back to DB lookup (for DB-only personal skills not in registry)
        db = SessionLocal()
        try:
            db_skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
            if not db_skill:
                raise HTTPException(
                    status_code=404,
                    detail=f"Skill '{skill_id}' not found"
                )
            source_type = (
                db_skill.source_type.value
                if hasattr(db_skill.source_type, 'value')
                else db_skill.source_type
            )
        finally:
            db.close()

    # Prevent deletion of builtin skills
    if source_type == "builtin" or source_type == SkillSourceType.BUILTIN:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete builtin skills"
        )

    # For personal skills, also remove FS directory (Option A: DB primary, FS git-tracked)
    fs_skill_dir = None
    try:
        from db.database import SessionLocal
        from models.skill import Skill as SkillModel
        with SessionLocal() as db:
            db_skill = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
            if db_skill and db_skill.source_path:
                from pathlib import Path
                fs_skill_dir = Path(db_skill.source_path)
    except Exception as e:
        logger.warning(f"Could not get source_path for delete cleanup: {e}")

    try:
        # Use registry.delete_skill which handles both in-memory and DB cleanup
        await registry.delete_skill(skill_id)

        # Remove FS directory if it exists (Option A: keep DB and FS in sync)
        if fs_skill_dir and fs_skill_dir.exists():
            import shutil
            shutil.rmtree(fs_skill_dir)
            logger.info(f"Removed FS skill dir: {fs_skill_dir}")

        return {"status": "deleted", "skill_id": skill_id}
    except Exception as e:
        logger.error(f"Failed to delete skill {skill_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete skill: {str(e)}"
        )


@router.post("/match", response_model=List[SkillMatchResponse])
async def match_skills(request: SkillMatchRequest):
    """
    Find skills matching the given context.

    Uses the production SkillMatcher (LLM-based semantic + trigger + tag).
    Falls back to keyword matching if embeddings are unavailable.
    """
    registry = get_skill_registry()

    if not registry._initialized:
        await registry.initialize()

    # Build context for the matcher
    context = {
        "query": request.query,
        "file_path": request.file_path,
        "project_type": request.project_type,
        "tags": request.tags or [],
    }
    if request.skill_ids:
        context["skill_ids"] = request.skill_ids

    # Try the production SkillMatcher first (LLM embeddings + trigger eval)
    try:
        from core.skills.matcher import get_skill_matcher
        matcher = get_skill_matcher()
        matches = await matcher.find_relevant_skills(
            context=context,
            max_results=request.max_results,
            min_score=0.0,  # don't filter too aggressively; let caller decide
        )
        return [
            SkillMatchResponse(
                skill=_skill_to_response(m.skill),
                score=m.score,
                match_reason=m.match_reason,
            )
            for m in matches
        ]
    except Exception as e:
        logger.warning(f"SkillMatcher failed, falling back to keyword matching: {e}")

    # === Fallback: keyword-based matching ===
    results = []

    skills = registry.list_all()

    # Also pull in DB-only personal skills
    try:
        from db.database import SessionLocal
        from models.skill import Skill as SkillModel
        db = SessionLocal()
        try:
            in_memory_ids = {s.skill_id for s in skills}
            db_skills = (
                db.query(SkillModel)
                .filter(SkillModel.source_type != "builtin")
                .all()
            )
            for dbs in db_skills:
                if dbs.skill_id not in in_memory_ids:
                    skills.append(_db_skill_to_match_obj(dbs))
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to load DB-only skills for matching: {e}")

    query_lower = request.query.lower()

    for skill in skills:
        score = 0.0
        match_reason = []

        # === Description / name matching ===
        desc_lower = (skill.description or "").lower()
        if query_lower and query_lower in desc_lower:
            score += 0.4
            match_reason.append("description contains query")
        # Multi-word overlap with description (stronger signal)
        query_tokens = set(_tokenize(query_lower))
        desc_tokens = set(_tokenize(desc_lower))
        desc_overlap = (query_tokens & desc_tokens) - _STOP_WORDS
        if desc_overlap:
            score += min(0.15 * len(desc_overlap), 0.5)
            match_reason.append(f"description: {', '.join(sorted(desc_overlap))}")

        if query_lower and query_lower in (skill.name or "").lower():
            score += 0.3
            match_reason.append("name match")

        # === Tag matching (when caller provides tags) ===
        if request.tags:
            skill_tags_lower = [t.lower() for t in (skill.tags or [])]
            matching_tags = set(t.lower() for t in request.tags) & set(skill_tags_lower)
            if matching_tags:
                score += 0.3 * len(matching_tags)
                match_reason.append(f"tags: {', '.join(matching_tags)}")

        # === Skill's own tags count too (lightweight semantic signal) ===
        skill_tags = set(t.lower() for t in (skill.tags or []))
        if skill_tags:
            tag_overlap = query_tokens & skill_tags - _STOP_WORDS
            if tag_overlap:
                # Each matching tag adds a strong boost (tags are intentional keywords)
                score += min(0.25 * len(tag_overlap), 0.6)
                match_reason.append(f"skill tags: {', '.join(sorted(tag_overlap))}")

        # === Trigger matching — best trigger wins ===
        for trigger in (skill.triggers or []):
            trigger_lower = trigger.lower()
            keywords = _extract_trigger_keywords(trigger_lower)
            trigger_tokens = set(_tokenize(trigger_lower))

            # 1) "mentions X" style (legacy)
            if "mentions" in trigger_lower:
                after_mentions = trigger_lower.split("mentions", 1)[1].strip()
                if after_mentions and any(k in query_lower for k in after_mentions.split()):
                    score = max(score, 0.6)
                    match_reason = [f"trigger: {trigger} (mentions: {after_mentions})"]
                    continue

            # 2) Overlap-based scoring — count meaningful shared words
            overlap = query_tokens & trigger_tokens
            meaningful_overlap = overlap - _STOP_WORDS
            if meaningful_overlap:
                # Stronger than before — multi-word overlap is more specific
                trigger_score = min(0.5 + 0.15 * len(meaningful_overlap), 0.95)
                if trigger_score > score:
                    score = trigger_score
                    match_reason = [
                        f"trigger: {trigger} (matched {len(meaningful_overlap)}: "
                        f"{', '.join(sorted(meaningful_overlap))})"
                    ]
                continue

            # 3) Phrase-level keyword presence (single fuzzy keyword)
            for kw in keywords:
                if kw and kw in query_lower:
                    # Cap keyword-only matches lower than multi-word overlap
                    # so a specific 2-word match beats a single fuzzy keyword
                    if 0.55 > score:
                        score = 0.55
                        match_reason = [f"trigger: {trigger} (keyword: {kw})"]
                    break

        if score > 0:
            results.append(SkillMatchResponse(
                skill=_skill_to_response(skill),
                score=min(score, 1.0),
                match_reason="; ".join(match_reason) if match_reason else "partial match"
            ))

    # Sort by score and limit results
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:request.max_results]


class PlaygroundRunRequest(BaseModel):
    """Request to run a skill in the playground."""
    skill_id: str = Field(..., description="Which skill to test")
    query: str = Field(..., description="User query to test the skill against")
    model: Optional[str] = Field(None, description="LLM model (defaults to DEFAULT_MODEL)")
    overrides: Optional[Dict[str, Any]] = Field(None, description="In-memory overrides (not saved)")
    skill_ids: Optional[List[str]] = Field(None, description="Optional allowlist — only match against these skills (simulates real agent config). None = use all skills.")


@router.post("/playground/run")
async def playground_run_skill(request: PlaygroundRunRequest):
    """
    Skill Playground — run a skill against a user query.

    Phase 1 (direct LLM test): builds a system prompt from the skill's
    instructions and calls DeepSeek chat directly. No agent framework,
    no tool execution — just verifies the skill's instructions produce
    a sensible answer.

    Phase 2 (future): will use AgentFactory for real tool execution.

    Args:
        request: {skill_id, query, model?, overrides?}

    Returns:
        {
          "matched": [...],          # skills that matched this query
          "agent_output": "...",      # the LLM response
          "system_prompt": "...",     # the prompt we built (for debugging)
          "skill": {...},             # the skill used
          "model": "...",             # model used
          "elapsed_ms": 1234
        }
    """
    import time
    t0 = time.time()

    # 1. Load skill (registry cache + DB fallback)
    registry = get_skill_registry()
    if not registry._initialized:
        await registry.initialize()

    skill = registry.get_skill(request.skill_id)
    if not skill:
        # Try DB
        try:
            from db.database import SessionLocal
            from models.skill import Skill as SkillModel
            db = SessionLocal()
            try:
                dbs = db.query(SkillModel).filter(SkillModel.skill_id == request.skill_id).first()
                if dbs:
                    skill = dbs
            finally:
                db.close()
        except Exception:
            pass

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.skill_id}' not found")

    # 2. Apply overrides (in-memory only, don't save)
    overrides = request.overrides or {}
    skill_name = overrides.get("name", skill.name)
    skill_description = overrides.get("description", skill.description or "")
    skill_instructions = overrides.get("instructions", skill.instructions or "")
    skill_triggers = overrides.get("triggers", list(skill.triggers or []))
    skill_tags = overrides.get("tags", list(skill.tags or []))
    skill_allowed_tools = overrides.get("allowed_tools", list(skill.allowed_tools or []))

    # 3. Match query against skills (to see which would activate)
    try:
        from core.skills.matcher import get_skill_matcher
        matcher = get_skill_matcher()
        match_context = {"query": request.query}
        if request.skill_ids:
            match_context["skill_ids"] = request.skill_ids
        matched = await matcher.find_relevant_skills(
            context=match_context,
            max_results=5,
        )
        matched_serializable = [
            {
                "skill_id": m.skill.skill_id,
                "name": m.skill.name,
                "score": m.score,
                "match_reason": m.match_reason,
            }
            for m in matched
        ]
    except Exception as e:
        logger.warning(f"Playground: skill matching failed: {e}")
        matched_serializable = []

    # 4. Build system prompt from skill
    system_prompt_parts = [
        f"You are an AI assistant running a skill named '{skill_name}'.",
        "",
    ]
    if skill_description:
        system_prompt_parts.append(f"## Skill Purpose\n{skill_description}\n")
    if skill_instructions:
        system_prompt_parts.append(f"## Skill Instructions\n{skill_instructions}\n")
    if skill_allowed_tools:
        tools_list = ", ".join(skill_allowed_tools)
        system_prompt_parts.append(
            f"## Available Tools\nYou may use these tools if appropriate: {tools_list}\n"
        )
    if skill_triggers:
        triggers_list = "\n".join(f"- {t}" for t in skill_triggers[:8])
        system_prompt_parts.append(
            f"## Activation Triggers\nThis skill is active when:\n{triggers_list}\n"
        )
    system_prompt = "\n".join(system_prompt_parts)

    # 5. Call LLM
    model_name = request.model or os.environ.get("DEFAULT_MODEL", "deepseek-chat")
    try:
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = init_chat_model(
            model=model_name,
            temperature=0.3,
            model_provider="deepseek",
        )
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=request.query),
        ])
        agent_output = response.content or ""
    except Exception as e:
        logger.error(f"Playground: LLM call failed: {e}")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "matched": matched_serializable,
        "agent_output": agent_output,
        "system_prompt": system_prompt,
        "skill": {
            "skill_id": skill.skill_id,
            "name": skill_name,
            "description": skill_description,
            "triggers": skill_triggers,
            "tags": skill_tags,
            "allowed_tools": skill_allowed_tools,
        },
        "skill_pool": request.skill_ids,  # None = all skills, list = filtered
        "skill_pool_size": len(request.skill_ids) if request.skill_ids else "all",
        "model": model_name,
        "elapsed_ms": elapsed_ms,
    }


@router.post("/reload-all")
async def reload_all_skills(project_paths: Optional[List[str]] = None):
    """
    Reload all skills from filesystem.

    Scans all skill directories and updates the registry.
    """
    registry = get_skill_registry()
    count = await registry.reload_all(project_paths)

    return {"status": "reloaded", "skill_count": count}


@router.get("/{skill_id}/files")
async def list_skill_files(skill_id: str):
    """
    List files in a skill's source directory.

    Used by the skill editor's Files section to show actual files
    (SKILL.md, data_analysis.py, etc.) instead of hardcoded folder names.

    Returns: { files: [{name, path, type, size}], source_path: str }
    """
    from db.database import SessionLocal
    from models.skill import Skill as SkillModel
    from pathlib import Path

    db = SessionLocal()
    try:
        skill = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
        source_path = skill.source_path
    finally:
        db.close()

    if not source_path or not Path(source_path).exists():
        return {"files": [], "source_path": source_path, "exists": False}

    files = []
    for p in sorted(Path(source_path).rglob("*")):
        if p.is_file():
            rel = p.relative_to(source_path).as_posix()
            files.append({
                "name": p.name,
                "path": rel,
                "full_path": str(p),
                "type": "file",
                "size": p.stat().st_size,
                "modified": p.stat().st_mtime,
            })
        elif p.is_dir() and p != Path(source_path):
            rel = p.relative_to(source_path).as_posix()
            files.append({
                "name": p.name + "/",
                "path": rel,
                "full_path": str(p),
                "type": "dir",
                "size": 0,
            })

    return {"files": files, "source_path": source_path, "exists": True}


@router.get("/{skill_id}/files/{file_path:path}")
async def read_skill_file(skill_id: str, file_path: str):
    """
    Read a single file's content from a skill's source directory.

    Used by the code editor to display script content.
    """
    from db.database import SessionLocal
    from models.skill import Skill as SkillModel
    from pathlib import Path

    db = SessionLocal()
    try:
        skill = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
        source_root = skill.source_path
    finally:
        db.close()

    if not source_root:
        raise HTTPException(status_code=404, detail="No source path for this skill")

    target = (Path(source_root) / file_path).resolve()
    root_resolved = Path(source_root).resolve()

    # Security: ensure target is within source_root
    if not str(target).startswith(str(root_resolved)):
        raise HTTPException(status_code=403, detail="Path escapes skill directory")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Binary file cannot be displayed as text")

    return {
        "file_path": file_path,
        "content": content,
        "size": target.stat().st_size,
        "modified": target.stat().st_mtime,
    }


@router.put("/{skill_id}/files/{file_path:path}")
async def write_skill_file(skill_id: str, file_path: str, payload: dict):
    """
    Write a file's content to a skill's source directory.

    Used by the code editor to save script edits back to FS.
    """
    from db.database import SessionLocal
    from models.skill import Skill as SkillModel
    from pathlib import Path

    content = payload.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="Missing 'content' field")

    db = SessionLocal()
    try:
        skill = db.query(SkillModel).filter(SkillModel.skill_id == skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
        source_root = skill.source_path
    finally:
        db.close()

    if not source_root:
        raise HTTPException(status_code=404, detail="No source path for this skill")

    target = (Path(source_root) / file_path).resolve()
    root_resolved = Path(source_root).resolve()

    if not str(target).startswith(str(root_resolved)):
        raise HTTPException(status_code=403, detail="Path escapes skill directory")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {
        "status": "saved",
        "file_path": file_path,
        "size": target.stat().st_size,
        "modified": target.stat().st_mtime,
    }


# =============================================================================
# Dead code removed 2026-06-24 (verified by static analysis - 0 callers):
#   - POST /{skill_id}/invoke          (replaced by subagent delegation)
#   - POST /{skill_id}/reload          (superseded by POST /reload-all)
#   - 4 debug endpoints (paths, registry-state, init, reload-verbose)
#   - GET /{skill_id}/stats            (analytics, no UI consumer)
#   - POST /{skill_id}/record-execution (analytics, no UI consumer)
#   - GET /{skill_id}/agents           (no UI consumer)
#   - InvokeSkillRequest, InvokeSkillResponse, SkillStatsResponse schemas
# See git history before commit `Phase 5 P1.5` to restore.
# =============================================================================
