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
from typing import List, Dict, Optional, TYPE_CHECKING
from enum import Enum

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
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
    """Schema for saving information to memory."""
    memory_content: str = Field(
        ...,
        description="The specific information to remember. Be detailed, include context and rationale."
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


class MemoryRecallArgs(BaseModel):
    """Schema for recalling information from memory."""
    query: str = Field(
        default="",
        description="What you are trying to recall. Leave empty to see all memories."
    )
    memory_type: Optional[str] = Field(
        None,
        description="Optional: Filter by memory type (fact, decision, pattern, learning, context, relationship)."
    )


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
        memory_content: str,
        memory_type: MemoryType = MemoryType.FACT,
        importance: int = 5,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Save to PostgreSQL if available, otherwise to in-memory dict."""
        try:
            tags = tags or []
            type_str = memory_type if isinstance(memory_type, str) else memory_type.value

            if self._db is not None:
                return await self._save_to_db(memory_content, type_str, importance, tags)
            else:
                return self._save_to_inmem(memory_content, type_str, importance, tags)

        except Exception as e:
            logger.error(f"Failed to save memory: {e}", exc_info=True)
            return f"Error: Failed to save memory — {e}"

    async def recall_memory(
        self,
        query: str = "",
        memory_type: Optional[str] = None,
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
# Convenience Function
# =============================================================================

def create_memory_tools(project_id: int, agent_id: str) -> List[BaseTool]:
    """
    Create memory tools for an agent using SimpleMemory (text-based).

    Args:
        project_id: Project ID for scoping
        agent_id: Agent identifier (e.g., "task_42")

    Returns:
        List of memory tool instances (memory_store, memory_recall)
    """
    memory = get_or_create_memory(project_id=project_id, agent_id=agent_id)
    return memory.create_memory_tools()


# =============================================================================
# System Prompt for Memory-Aware Agent
# =============================================================================

MEMORY_AWARE_AGENT_PROMPT = """You are an intelligent coding agent with memory capabilities.

MEMORY TOOLS AVAILABLE:
You have access to two memory management tools:

1. **memory_store(memory_content, memory_type, importance, tags)**
   - Save important facts, decisions, patterns, or learnings
   - Use when you discover something valuable for future reference
   - Types: fact, decision, pattern, learning, context, relationship
   - Importance: 1-10 scale (higher = more important)

2. **memory_recall(query, memory_type)**
   - Recall ALL stored memories (the full text is returned)
   - Optionally filter by query or memory type
   - Use BEFORE starting work to check for existing patterns/decisions
   - Read through the returned memories carefully for relevant context

WHEN TO USE MEMORY TOOLS:

- After fixing a bug: Save the bug + solution as learning
- When discovering patterns: Save code patterns you notice
- After architectural decisions: Save decisions with rationale
- Before implementing: ALWAYS recall memories to check for relevant past work
- When refactoring: Recall memories for similar refactoring patterns
- After learning conventions: Save project-specific conventions

MEMORY BEST PRACTICES:

1. Be specific: "We use JWT tokens in httpOnly cookies for auth" not "auth setup"
2. Include context: Why was this decision made? What problem does it solve?
3. Add tags: Make memories easily findable later
4. Set importance: Critical decisions = 9-10, minor facts = 3-5
5. Always recall first: Before starting work, check memory for existing context

EXAMPLE WORKFLOW:

```
Task: "Add user registration endpoint"

1. memory_recall(query="authentication patterns")
   - Reads all stored memories about auth patterns

2. Implement registration following past decisions

3. memory_store(
     memory_content="Added /api/auth/register endpoint. Uses bcrypt (12 rounds) for password hashing, returns JWT in httpOnly cookie with 24h expiry.",
     memory_type="fact",
     importance=7,
     tags=["auth", "registration", "api"]
   )
```

Your goal: Build up comprehensive project knowledge over time, making you more consistent and context-aware with each task.
"""


# =============================================================================
# Legacy compatibility (kept for existing code that imports AgentMemorySystem)
# =============================================================================

class AgentMemorySystem:
    """
    DEPRECATED: Use SimpleMemory instead for text-based memory.
    
    Kept for backward compatibility with existing code that references
    AgentMemorySystem by name. Internally wraps SimpleMemory.
    """
    
    def __init__(self, vector_store=None, project_id=0, agent_id=""):
        self._memory = get_or_create_memory(project_id=project_id, agent_id=agent_id)
        self.project_id = project_id
        self.agent_id = agent_id

    def create_memory_tools(self) -> List[BaseTool]:
        return self._memory.create_memory_tools()