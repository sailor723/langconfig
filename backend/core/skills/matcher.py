# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Skill Matcher — LLM-based skill selection using langchain init_chat_model.

Given a user query and the list of available skills, ask a chat LLM
(DeepSeek by default) to score each skill's relevance and return the top N.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from core.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


@dataclass
class SkillMatch:
    """A skill match with relevance score and explanation."""
    skill: Any  # Skill model (duck-typed OK)
    score: float
    match_reason: str


# Module-level singleton
_matcher_instance: Optional["SkillMatcher"] = None


def get_skill_matcher() -> "SkillMatcher":
    """Get the singleton SkillMatcher instance."""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = SkillMatcher()
    return _matcher_instance


class SkillMatcher:
    """
    Match a user query to relevant skills using an LLM.

    The LLM (DeepSeek chat by default — configured via .env) is asked to
    score each skill's metadata against the query and return JSON with
    skill_id + score + reason. The top N are returned.
    """

    def __init__(self, model_name: Optional[str] = None):
        # Default model — read from .env / set in init_chat_model
        self._model_name = model_name or os.environ.get("DEFAULT_MODEL", "deepseek-chat")
        self._registry = get_skill_registry()
        self._llm = None  # Lazy init

    def _get_llm(self):
        """Lazy-init the chat model via langchain's init_chat_model."""
        if self._llm is None:
            try:
                from langchain.chat_models import init_chat_model
                # init_chat_model reads provider/model from env vars:
                #   DEEPSEEK_API_KEY, DEEPSEEK_API_BASE → provider=deepseek
                #   AZURE_OPENAI_* → provider=azure_openai
                #   OPENAI_API_KEY → provider=openai
                self._llm = init_chat_model(
                    model=self._model_name,
                    temperature=0.0,
                    model_provider="deepseek",
                )
                logger.info(f"SkillMatcher initialized with model: {self._model_name}")
            except Exception as e:
                logger.warning(f"Could not init chat model '{self._model_name}': {e}")
                self._llm = False
        return self._llm if self._llm else None

    async def find_relevant_skills(
        self,
        context: Dict[str, Any],
        max_results: int = 5,
        min_score: float = 0.0,
        strategies: Optional[List[str]] = None,
    ) -> List[SkillMatch]:
        """
        Find skills relevant to the given context.

        Args:
            context: {"query": "...", "file_path": "...", "tags": [...]}
            max_results: Max skills to return
            min_score: Drop matches below this score
            strategies: For backward compatibility — ignored, we always use LLM

        Returns:
            List[SkillMatch] sorted by score descending
        """
        query = context.get("query", "").strip()
        if not query:
            return []

        # Load skills (registry cache + DB-only personal skills)
        skills = list(self._registry.list_all())
        skills.extend(self._load_db_only_skills(skills))

        if not skills:
            return []

        # Build compact metadata block for the prompt
        metadata_block = self._build_metadata_block(skills)

        # Ask the LLM to score each skill
        prompt = f"""You are a skill router. Given a user query and a list of skills,
score each skill's relevance from 0 to 1 (0=irrelevant, 1=perfect match).

Skills (id | name | description | triggers | tags):
{metadata_block}

User query: "{query}"

Return ONLY a JSON array, no markdown, no commentary:
[
  {{"skill_id": "skill-id", "score": 0.85, "reason": "matches because..."}},
  ...
]

Rules:
- Be strict: only score >= 0.5 if the skill should clearly activate for this query
- Sort by score descending
- Include all skills you scored > 0 (omit those with 0)
- Keep each "reason" to one short sentence"""

        try:
            llm = self._get_llm()
            if not llm:
                logger.warning("No LLM available; returning empty matches")
                return []

            response = await llm.ainvoke([
                SystemMessage(content="You are a precise skill router. Output strict JSON only."),
                HumanMessage(content=prompt),
            ])
            content = (response.content or "").strip()

            # Strip markdown code fence if present
            if content.startswith("```"):
                lines = content.split("\n")
                # drop first ```json line and last ``` line
                content = "\n".join(lines[1:])
                if content.rstrip().endswith("```"):
                    content = content.rstrip()[:-3]

            data = json.loads(content)
            if not isinstance(data, list):
                logger.warning(f"LLM returned non-list: {type(data)}")
                return []

            # Build lookup
            skills_by_id = {s.skill_id: s for s in skills}

            results = []
            for item in data:
                sid = item.get("skill_id")
                try:
                    score = float(item.get("score", 0.0))
                except (TypeError, ValueError):
                    continue
                reason = item.get("reason", "llm semantic match")
                if sid in skills_by_id and score > 0:
                    results.append(SkillMatch(
                        skill=skills_by_id[sid],
                        score=min(score, 1.0),
                        match_reason=f"llm: {reason}",
                    ))

            results.sort(key=lambda m: m.score, reverse=True)
            return [m for m in results if m.score >= min_score][:max_results]

        except Exception as e:
            logger.warning(f"LLM skill match failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_metadata_block(self, skills: List[Any]) -> str:
        """Build a compact text representation of all skills for the prompt."""
        lines = []
        for s in skills:
            desc = (s.description or "").replace("\n", " ").strip()
            if len(desc) > 200:
                desc = desc[:197] + "..."
            triggers = (s.triggers or [])[:5]
            tags = s.tags or []
            lines.append(
                f"- {s.skill_id} | {s.name} | {desc} | triggers: {triggers} | tags: {tags}"
            )
        return "\n".join(lines)

    def _load_db_only_skills(self, in_memory_skills: List[Any]) -> List[Any]:
        """Load DB-only personal skills not yet in the registry cache."""
        from types import SimpleNamespace
        try:
            from db.database import SessionLocal
            from models.skill import Skill as SkillModel

            db = SessionLocal()
            try:
                in_memory_ids = {s.skill_id for s in in_memory_skills}
                db_skills = (
                    db.query(SkillModel)
                    .filter(SkillModel.source_type != "builtin")
                    .all()
                )
                results = []
                for dbs in db_skills:
                    if dbs.skill_id not in in_memory_ids:
                        # Build a Skill-like duck-typed object with ALL fields
                        # that _skill_to_response might read.
                        results.append(SimpleNamespace(
                            skill_id=dbs.skill_id,
                            name=dbs.name or "",
                            description=dbs.description or "",
                            version=dbs.version or "1.0.0",
                            author=dbs.author or "User",
                            source_type=dbs.source_type or "personal",
                            source_path=dbs.source_path or "",
                            tags=list(dbs.tags or []),
                            triggers=list(dbs.triggers or []),
                            allowed_tools=_normalize_allowed_tools_local(dbs.allowed_tools),
                            instructions=dbs.instructions or "",
                            examples=dbs.examples or "",
                            avg_success_rate=dbs.avg_success_rate or 1.0,
                            usage_count=dbs.usage_count or 0,
                            last_used_at=dbs.last_used_at,
                            created_at=dbs.created_at,
                            updated_at=dbs.updated_at,
                            required_context=list(dbs.required_context or []),
                        ))
                return results
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to load DB-only skills: {e}")
            return []


def _normalize_allowed_tools_local(value):
    """Coerce allowed_tools from any of {list, JSON-string, None} to List[str] or []."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []