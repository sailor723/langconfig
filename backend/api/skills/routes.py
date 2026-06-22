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

from db.database import get_db
from core.skills.registry import get_skill_registry
from models.skill import Skill, SkillExecution, SkillSourceType

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


class SkillMatchResponse(BaseModel):
    """Skill match result with relevance info."""
    skill: SkillResponse
    score: float
    match_reason: str


class InvokeSkillRequest(BaseModel):
    """Request to explicitly invoke a skill."""
    context: Dict[str, Any] = Field(default_factory=dict, description="Execution context")
    agent_id: Optional[str] = Field(None, description="Agent ID using the skill")
    workflow_id: Optional[int] = Field(None, description="Workflow context")
    task_id: Optional[int] = Field(None, description="Task context")


class InvokeSkillResponse(BaseModel):
    """Response with skill details for invocation."""
    skill_id: str
    name: str
    instructions: str
    allowed_tools: Optional[List[str]]
    examples: Optional[str]
    status: str


class SkillStatsResponse(BaseModel):
    """Usage statistics for a skill."""
    skill_id: str
    usage_count: int
    last_used_at: Optional[datetime]
    avg_success_rate: float
    recent_executions: List[Dict[str, Any]]


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

    if not registry.is_initialized:
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
        return _skill_to_detail_response_dict(skill)
    except Exception as e:
        logger.error(f"Failed to create skill: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {str(e)}")


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

    if not registry.is_initialized:
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
    if not registry.is_initialized:
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

    try:
        # Use registry.delete_skill which handles both in-memory and DB cleanup
        await registry.delete_skill(skill_id)
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

    if not registry.is_initialized:
        await registry.initialize()

    # Build context for the matcher
    context = {
        "query": request.query,
        "file_path": request.file_path,
        "project_type": request.project_type,
        "tags": request.tags or [],
    }

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


@router.post("/{skill_id}/invoke", response_model=InvokeSkillResponse)
async def invoke_skill(skill_id: str, request: InvokeSkillRequest):
    """
    Explicitly invoke a skill.

    Returns the skill's instructions and configuration for use by an agent.
    Records the invocation for analytics.
    """
    registry = get_skill_registry()

    if not registry.is_initialized:
        await registry.initialize()

    skill = registry.get_skill(skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    # Record invocation start
    await registry.record_execution(
        skill_id=skill_id,
        invocation_type="explicit",
        status="started",
        context=request.context,
        agent_id=request.agent_id,
        workflow_id=request.workflow_id,
        task_id=request.task_id
    )

    return InvokeSkillResponse(
        skill_id=skill.skill_id,
        name=skill.name,
        instructions=skill.instructions,
        allowed_tools=skill.allowed_tools,
        examples=skill.examples,
        status="ready"
    )


@router.post("/{skill_id}/reload")
async def reload_skill(skill_id: str):
    """
    Reload a skill from filesystem.

    Use this after modifying a SKILL.md file to pick up changes.
    """
    registry = get_skill_registry()

    if not registry.is_initialized:
        await registry.initialize()

    if not registry.get_skill(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    success = await registry.reload_skill(skill_id)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_id}'")

    return {"status": "reloaded", "skill_id": skill_id}


@router.post("/reload-all")
async def reload_all_skills(project_paths: Optional[List[str]] = None):
    """
    Reload all skills from filesystem.

    Scans all skill directories and updates the registry.
    """
    registry = get_skill_registry()
    count = await registry.reload_all(project_paths)

    return {"status": "reloaded", "skill_count": count}


@router.get("/debug/paths")
async def debug_skill_paths():
    """Debug endpoint to check skill loader paths."""
    import os
    from core.skills.loader import SkillLoader

    loader = SkillLoader()

    # Check paths
    builtin_exists = os.path.exists(loader.builtin_path)
    personal_exists = os.path.exists(loader.personal_path)

    # Try to discover
    discovered = loader.discover_all()

    # Try to load each
    loaded = []
    for d in discovered:
        skill = loader.load_skill(d.skill_path)
        loaded.append({
            "path": d.skill_path,
            "source_type": d.source_type,
            "loaded": skill is not None,
            "skill_id": skill.skill_id if skill else None,
            "error": None if skill else "Failed to parse"
        })

    return {
        "builtin_path": loader.builtin_path,
        "builtin_exists": builtin_exists,
        "personal_path": loader.personal_path,
        "personal_exists": personal_exists,
        "discovered_count": len(discovered),
        "loaded_skills": loaded
    }


@router.get("/debug/registry-state")
async def debug_registry_state():
    """Debug endpoint to check registry state."""
    registry = get_skill_registry()
    return {
        "is_initialized": registry.is_initialized,
        "skill_count": registry.skill_count,
        "skills_in_memory": list(registry._skills.keys()),
        "tags_indexed": list(registry._by_tag.keys())
    }


@router.post("/debug/init")
async def debug_init():
    """Debug endpoint to force registry initialization."""
    import traceback
    registry = get_skill_registry()

    try:
        count = await registry.initialize()
        return {
            "status": "success",
            "skill_count": count,
            "is_initialized": registry.is_initialized,
            "skills_in_memory": list(registry._skills.keys())
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@router.post("/debug/reload-verbose")
async def debug_reload_verbose():
    """Debug endpoint to reload skills with verbose error output."""
    import os
    import traceback
    from core.skills.loader import SkillLoader
    from db.database import AsyncSessionLocal
    from models.skill import Skill, SkillSourceType
    from sqlalchemy import select
    from datetime import datetime

    loader = SkillLoader()
    discovered = loader.discover_all()
    results = []

    async with AsyncSessionLocal() as session:
        for d in discovered:
            result = {"path": d.skill_path, "source_type": d.source_type}
            try:
                parsed = loader.load_skill(d.skill_path)
                if not parsed:
                    result["status"] = "parse_failed"
                    results.append(result)
                    continue

                result["skill_id"] = parsed.skill_id

                # Try to check if exists
                db_result = await session.execute(
                    select(Skill).where(Skill.skill_id == parsed.skill_id)
                )
                existing = db_result.scalar_one_or_none()

                if existing:
                    result["status"] = "exists_in_db"
                    result["db_id"] = existing.id
                else:
                    # Try to create
                    skill = Skill(
                        skill_id=parsed.skill_id,
                        name=parsed.name,
                        description=parsed.description,
                        version=parsed.version,
                        author=parsed.author,
                        source_type=SkillSourceType(d.source_type),
                        source_path=parsed.source_path,
                        tags=parsed.tags,
                        triggers=parsed.triggers,
                        allowed_tools=parsed.allowed_tools,
                        required_context=parsed.required_context,
                        instructions=parsed.instructions,
                        examples=parsed.examples,
                        file_modified_at=parsed.file_modified_at
                    )
                    session.add(skill)
                    result["status"] = "created"

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                result["traceback"] = traceback.format_exc()

            results.append(result)

        try:
            await session.commit()
        except Exception as e:
            return {
                "commit_error": str(e),
                "commit_traceback": traceback.format_exc(),
                "results": results
            }

    return {"results": results}


@router.get("/{skill_id}/stats", response_model=SkillStatsResponse)
async def get_skill_stats(skill_id: str, db: Session = Depends(get_db)):
    """Get usage statistics for a skill."""
    registry = get_skill_registry()

    if not registry.is_initialized:
        await registry.initialize()

    skill = registry.get_skill(skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    # Get recent executions from database
    recent = db.query(SkillExecution).filter(
        SkillExecution.skill_id == skill.id
    ).order_by(
        SkillExecution.created_at.desc()
    ).limit(10).all()

    recent_executions = [
        {
            "id": ex.id,
            "invocation_type": ex.invocation_type.value if hasattr(ex.invocation_type, 'value') else ex.invocation_type,
            "status": ex.status,
            "execution_time_ms": ex.execution_time_ms,
            "created_at": ex.created_at.isoformat() if ex.created_at else None
        }
        for ex in recent
    ]

    return SkillStatsResponse(
        skill_id=skill_id,
        usage_count=skill.usage_count,
        last_used_at=skill.last_used_at,
        avg_success_rate=skill.avg_success_rate,
        recent_executions=recent_executions
    )


@router.post("/{skill_id}/record-execution")
async def record_skill_execution(
    skill_id: str,
    status: str = Query(..., description="Execution status: success, failed, partial"),
    execution_time_ms: Optional[int] = Query(None, description="Execution time in milliseconds"),
    error_message: Optional[str] = Query(None, description="Error message if failed"),
    invocation_type: str = Query("explicit", description="How skill was invoked: automatic, explicit")
):
    """
    Record a skill execution result.

    Call this after a skill has finished executing to track metrics.
    """
    registry = get_skill_registry()

    if not registry.is_initialized:
        await registry.initialize()

    if not registry.get_skill(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    await registry.record_execution(
        skill_id=skill_id,
        invocation_type=invocation_type,
        status=status,
        execution_time_ms=execution_time_ms,
        error_message=error_message
    )

    return {"status": "recorded", "skill_id": skill_id}


@router.get("/{skill_id}/agents")
async def get_skill_agents(skill_id: str, db: Session = Depends(get_db)):
    """
    List all DeepAgents that reference this skill (by id) in their config.

    Searches both `config.skills` (top-level explicit list) and `subagents_config[*].skills`
    (per-subagent skills). Returns agent id, name, and which section referenced the skill.
    """
    from models.deep_agent import DeepAgentTemplate

    agents = db.query(DeepAgentTemplate).all()
    matches: list[dict] = []

    for agent in agents:
        cfg = agent.config or {}
        referenced_in: list[str] = []

        # 1. Top-level config.skills list
        top_skills = cfg.get("skills") or []
        if isinstance(top_skills, list) and skill_id in top_skills:
            referenced_in.append("config.skills")

        # 2. Subagents that list this skill
        sub_cfg = agent.subagents_config or []
        if isinstance(sub_cfg, list):
            for sub in sub_cfg:
                if not isinstance(sub, dict):
                    continue
                sub_skills = sub.get("skills") or []
                if isinstance(sub_skills, list) and skill_id in sub_skills:
                    referenced_in.append(f"subagent:{sub.get('name', '?')}")

        if referenced_in:
            matches.append({
                "id": agent.id,
                "name": agent.name,
                "category": agent.category,
                "referenced_in": referenced_in,
            })

    return {
        "skill_id": skill_id,
        "agent_count": len(matches),
        "agents": matches,
    }
