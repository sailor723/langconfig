# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent Memory System for LangConfig.

Provides agents with explicit memory control through tools, enabling them to:
1. Decide what information is important enough to save
2. Recall their memories when needed
3. Build up project knowledge across conversation turns

Uses simple text-based storage (dict) — no vector store or embeddings required.
The LLM reads all stored memories directly in its context window.
"""

import logging
from typing import Any, List, Dict, Optional, TYPE_CHECKING
from enum import Enum

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from models.agent_memory import AgentMemory

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """Types of memories agents can store."""
    FACT = "fact"
    DECISION = "decision"
    PATTERN = "pattern"
    LEARNING = "learning"
    CONTEXT = "context"
    RELATIONSHIP = "relationship"


# =============================================================================
# Pydantic Schemas for Tool Arguments
# =============================================================================

class MemorySaveArgs(BaseModel):
    """Schema for saving information to memory.

    Accepts both legacy (key/value/context) and modern (memory_content/...)
    parameter names for backward compatibility with existing agents/stubs.
    """
    # Legacy params (what LLM/stubs generate)
    key: Optional[str] = Field(
        None,
        description="[Legacy] Unique identifier for this memory."
    )
    value: Optional[str] = Field(
        None,
        description="[Legacy] The specific information to remember."
    )
    context: Optional[str] = Field(
        None,
        description="[Legacy] Context/category (e.g., 'conversation', 'user_pref')."
    )
    # Modern params (canonical)
    memory_content: Optional[str] = Field(
        None,
        description="[Modern] The specific information to remember."
    )
    memory_type: MemoryType = Field(
        MemoryType.FACT,
        description="Category of the memory (e.g., FACT, DECISION, LEARNING)."
    )
    importance: int = Field(
        5,
        description="Importance score (1-10). Higher is more critical.",
        ge=1,
        le=10
    )
    tags: Optional[List[str]] = Field(
        None,
        description="Optional tags for categorization (e.g., ['auth', 'security'])."
    )

    @model_validator(mode='before')
    @classmethod
    def normalize_legacy_params(cls, data: Any) -> Any:
        """Merge legacy (key/value/context) params into canonical (memory_content)."""
        if not isinstance(data, dict):
            return data
        # value → memory_content
        if data.get('value') and not data.get('memory_content'):
            data['memory_content'] = data['value']
        # key (when no value) → memory_content as "[key]"
        if data.get('key') and not data.get('memory_content') and not data.get('value'):
            data['memory_content'] = f"[{data['key']}]"
        return data


class MemoryRecallArgs(BaseModel):
    """Schema for recalling information from memory.

    Accepts both legacy (key/context) and modern (query/memory_type)
    parameter names for backward compatibility.
    """
    # Legacy params
    key: Optional[str] = Field(
        None,
        description="[Legacy] The key to look up."
    )
    context: Optional[str] = Field(
        None,
        description="[Legacy] Context/category filter."
    )
    # Modern params (canonical)
    query: str = Field(
        default="",
        description="What you are trying to recall. Leave empty to see all memories."
    )
    memory_type: Optional[str] = Field(
        None,
        description="Optional: Filter by memory type (fact, decision, pattern, learning, context, relationship)."
    )

    @model_validator(mode='before')
    @classmethod
    def normalize_legacy_params(cls, data: Any) -> Any:
        """Merge legacy (key/context) params into canonical fields."""
        if not isinstance(data, dict):
            return data
        # key → query
        if data.get('key') and not data.get('query'):
            data['query'] = str(data['key'])
        # context → memory_type (only if it's a known MemoryType to avoid false matches)
        if data.get('context') and not data.get('memory_type'):
            ctx_lower = str(data['context']).lower()
            try:
                MemoryType(ctx_lower)
                data['memory_type'] = ctx_lower
            except ValueError:
                pass  # ignore generic context like "conversation"
        return data


# =============================================================================
# Simple Text-Based Memory System
# =============================================================================

# Module-level cache — persists memory instances across agent calls
_memory_cache: Dict[str, "SimpleMemory"] = {}


def get_or_create_memory(
    project_id: int, agent_id: str, db_session: Optional[AsyncSession] = None
) -> "SimpleMemory":
    """Return an existing SimpleMemory for this agent, or create and cache a new one."""
    key = f"{project_id}:{agent_id}"
    if key not in _memory_cache:
        _memory_cache[key] = SimpleMemory(project_id, agent_id)
    instance = _memory_cache[key]
    # Always update the DB session (reconnect after server restart)
    if db_session is not None:
        instance._db = db_session
    return instance


class SimpleMemory:
    """
    Text-based memory with optional PostgreSQL persistence.

    Supports two backends:
    - In-memory (dict): fast, no deps, lost on restart — always available
    - PostgreSQL (via AsyncSession): persistent across restarts — used when available

    Usage:
        # In-memory only
        >>> mem = SimpleMemory(project_id=1, agent_id="task_42")
        >>> tools = mem.create_memory_tools()

        # With PostgreSQL
        >>> from db.database import AsyncSessionLocal
        >>> mem = SimpleMemory(project_id=1, agent_id="task_42", db_session=AsyncSessionLocal())
        >>> tools = mem.create_memory_tools()
    """

    def __init__(
        self,
        project_id: int,
        agent_id: str,
        db_session: Optional[AsyncSession] = None,
    ):
        self.project_id = project_id
        self.agent_id = agent_id
        self._db = db_session
        self._store: List[Dict] = []  # in-memory fallback / local cache

    def create_memory_tools(self) -> List[BaseTool]:
        """Create memory_store and memory_recall tools (async-compatible)."""
        return [
            StructuredTool.from_function(
                coroutine=self.save_to_memory,
                name="memory_store",
                description=(
                    "Save critical information (facts, decisions, patterns, or learnings) "
                    "to memory. Use this immediately when you discover something vital "
                    "for future reference."
                ),
                args_schema=MemorySaveArgs,
                return_direct=False,
            ),
            StructuredTool.from_function(
                coroutine=self.recall_memory,
                name="memory_recall",
                description=(
                    "Recall previously stored information from memory. "
                    "Use this BEFORE starting a task to check for existing "
                    "patterns, decisions, or conventions. Leave query empty to see all memories."
                ),
                args_schema=MemoryRecallArgs,
                return_direct=False,
            ),
        ]

    # =========================================================================
    # Async Tool Implementations (works with both backends)
    # =========================================================================

    async def save_to_memory(
        self,
        memory_content: Optional[str] = None,
        memory_type: MemoryType = MemoryType.FACT,
        importance: int = 5,
        tags: Optional[List[str]] = None,
        **kwargs: Any,  # absorb legacy params (key, value, context)
    ) -> str:
        """Save to PostgreSQL if available, otherwise to in-memory dict."""
        try:
            # Guard: must have content (pydantic validator should normalize legacy -> modern)
            content = memory_content or ""
            if not content:
                return "Error: No memory content provided."

            tags = tags or []
            type_str = memory_type if isinstance(memory_type, str) else memory_type.value

            if self._db is not None:
                return await self._save_to_db(content, type_str, importance, tags)
            else:
                return self._save_to_inmem(content, type_str, importance, tags)

        except Exception as e:
            logger.error(f"Failed to save memory: {e}", exc_info=True)
            return f"Error: Failed to save memory — {e}"

    async def recall_memory(
        self,
        query: str = "",
        memory_type: Optional[str] = None,
        **kwargs: Any,  # absorb legacy params (key, context)
    ) -> str:
        """Recall from PostgreSQL if available, otherwise from in-memory dict."""
        try:
            if self._db is not None:
                return await self._recall_from_db(query, memory_type)
            else:
                return self._recall_from_inmem(query, memory_type)

        except Exception as e:
            logger.error(f"Memory recall failed: {e}", exc_info=True)
            return f"Error recalling memories: {e}"

    # =========================================================================
    # PostgreSQL Backend
    # =========================================================================

    async def _save_to_db(
        self,
        content: str,
        memory_type: str,
        importance: int,
        tags: List[str],
    ) -> str:
        """Persist a memory entry to PostgreSQL."""
        from models.agent_memory import AgentMemory

        entry = AgentMemory(
            project_id=self.project_id,
            agent_id=self.agent_id,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            content=content,
        )
        self._db.add(entry)
        await self._db.commit()
        await self._db.refresh(entry)

        logger.info(
            f"Agent {self.agent_id} saved memory to DB "
            f"(id={entry.id}, type={memory_type}, importance={importance}): "
            f"{content[:100]}..."
        )
        return (
            f"Memory stored (DB id={entry.id}). "
            f"Type: {memory_type}, Importance: {importance}/10."
        )

    async def _recall_from_db(
        self,
        query: str = "",
        memory_type: Optional[str] = None,
    ) -> str:
        """Recall memories from PostgreSQL, ordered by most recent first."""
        from models.agent_memory import AgentMemory

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.project_id == self.project_id,
                AgentMemory.agent_id == self.agent_id,
            )
            .order_by(AgentMemory.created_at.desc())
        )

        result = await self._db.execute(stmt)
        entries = result.scalars().all()

        if not entries:
            return (
                "No memories stored yet. You are starting fresh — "
                "use memory_store to save important information for future turns."
            )

        # Filter by type if specified
        if memory_type:
            entries = [e for e in entries if e.memory_type == memory_type]

        if not entries:
            return f"No memories found with type '{memory_type}'."

        lines = [f"=== AGENT MEMORY ({len(entries)} entries) ===\n"]
        for i, e in enumerate(entries, 1):
            tags_str = f" [{', '.join(e.tags)}]" if e.tags else ""
            lines.append(
                f"[{i}] {e.memory_type.upper()} "
                f"(importance: {e.importance}/10){tags_str}\n"
                f"    {e.content}\n"
            )

        if query:
            lines.insert(1, f'Query: "{query}"\n')

        return "".join(lines)

    # =========================================================================
    # In-Memory Backend
    # =========================================================================

    def _save_to_inmem(
        self,
        content: str,
        memory_type: str,
        importance: int,
        tags: List[str],
    ) -> str:
        """Save to in-memory list (synchronous, no I/O)."""
        entry = {
            "content": content,
            "type": memory_type,
            "importance": importance,
            "tags": tags,
            "index": len(self._store) + 1,
        }
        self._store.append(entry)

        logger.info(
            f"Agent {self.agent_id} saved memory "
            f"(#{entry['index']}, type={memory_type}, importance={importance}): "
            f"{content[:100]}..."
        )
        return (
            f"Memory stored (#{entry['index']}). "
            f"Type: {memory_type}, Importance: {importance}/10."
        )

    def _recall_from_inmem(
        self,
        query: str = "",
        memory_type: Optional[str] = None,
    ) -> str:
        """Recall from in-memory list (synchronous, no I/O)."""
        entries = self._store
        if memory_type:
            entries = [e for e in entries if e["type"] == memory_type]

        if not entries:
            return (
                "No memories stored yet. You are starting fresh — "
                "use memory_store to save important information for future turns."
            )

        lines = [f"=== AGENT MEMORY ({len(entries)} entries) ===\n"]
        for e in entries:
            type_str = e["type"].upper()
            tags_str = f" [{', '.join(e['tags'])}]" if e["tags"] else ""
            lines.append(
                f"[{e['index']}] {type_str} "
                f"(importance: {e['importance']}/10){tags_str}\n"
                f"    {e['content']}\n"
            )

        if query:
            lines.insert(1, f'Query: "{query}"\n')

        return "".join(lines)

    # =========================================================================
    # Properties & Utilities
    # =========================================================================

    @property
    def memory_count(self) -> int:
        """Number of stored memories (from in-memory cache)."""
        return len(self._store)

    def get_memory_text(self) -> str:
        """
        Get all memories as a single text block for injection into system prompt.
        Returns empty string if no memories.
        """
        return self._recall_from_inmem() if self._store else ""


# =============================================================================
# Dead code removed 2026-06-24:
#   - AgentMemorySystem class (deprecated wrapper around SimpleMemory)
#   - module-level create_memory_tools() function (unused)
#   - MEMORY_AWARE_AGENT_PROMPT constant (unused)
#
# If you need a memory tools factory, use:
#   from core.agents.memory import get_or_create_memory
#   mem = get_or_create_memory(project_id, agent_id, db_session)
#   tools = mem.create_memory_tools()  # instance method
# =============================================================================
