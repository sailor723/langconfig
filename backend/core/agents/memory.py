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
from typing import List, Dict, Optional
from enum import Enum

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

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

class SimpleMemory:
    """
    Text-based memory using a simple dict — no vector store or embeddings.

    Each entry is stored as a plain text record. memory_recall returns
    the full text of all stored memories for the LLM to read directly.
    Modern LLMs with large context windows handle this efficiently.

    Usage:
        >>> memory = SimpleMemory(project_id=1, agent_id="task_42")
        >>> tools = memory.create_memory_tools()
        >>> await tools[0].ainvoke({"memory_content": "We use JWT auth", "memory_type": "fact"})
    """

    def __init__(self, project_id: int, agent_id: str):
        self.project_id = project_id
        self.agent_id = agent_id
        self._store: List[Dict] = []  # list of memory dicts

    def create_memory_tools(self) -> List[BaseTool]:
        """Create memory_store and memory_recall tools."""
        return [
            StructuredTool.from_function(
                func=self.save_to_memory,
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
                func=self.recall_memory,
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
    # Tool Implementations (synchronous - no async needed for dict access)
    # =========================================================================

    def save_to_memory(
        self,
        memory_content: str,
        memory_type: MemoryType = MemoryType.FACT,
        importance: int = 5,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Save important information to memory.

        Use this when you learn something important that you'll need later.
        Examples:
        - Architectural decisions made
        - Code patterns discovered
        - Bugs fixed and their solutions
        - Important project conventions
        """
        try:
            entry = {
                "content": memory_content,
                "type": memory_type if isinstance(memory_type, str) else memory_type.value,
                "importance": importance,
                "tags": tags or [],
                "index": len(self._store) + 1,
            }
            self._store.append(entry)

            logger.info(
                f"Agent {self.agent_id} saved memory "
                f"(#{entry['index']}, type={entry['type']}, "
                f"importance={importance}): {memory_content[:100]}..."
            )

            return (
                f"Memory stored (#{entry['index']}). "
                f"Type: {entry['type']}, Importance: {importance}/10."
            )

        except Exception as e:
            logger.error(f"Failed to save memory: {e}", exc_info=True)
            return f"Error: Failed to save memory — {e}"

    def recall_memory(
        self,
        query: str = "",
        memory_type: Optional[str] = None
    ) -> str:
        """
        Recall stored memories. Returns all memories as formatted text.

        The LLM reads all returned memories in its context window and
        determines relevance by itself — no vector search needed.
        """
        try:
            # Filter by type if specified
            entries = self._store
            if memory_type:
                entries = [e for e in entries if e["type"] == memory_type]

            if not entries:
                return (
                    "No memories stored yet. You are starting fresh — "
                    "use memory_store to save important information for future turns."
                )

            # Format all memories as a readable text block
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
                lines.insert(1, f"Query: \"{query}\"\n")

            return "".join(lines)

        except Exception as e:
            logger.error(f"Memory recall failed: {e}", exc_info=True)
            return f"Error recalling memories: {e}"

    @property
    def memory_count(self) -> int:
        """Number of stored memories."""
        return len(self._store)

    def get_memory_text(self) -> str:
        """
        Get all memories as a single text block for injection into system prompt.
        Returns empty string if no memories.
        """
        return self.recall_memory() if self._store else ""


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
    memory = SimpleMemory(project_id=project_id, agent_id=agent_id)
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
        self._memory = SimpleMemory(project_id=project_id, agent_id=agent_id)
        self.project_id = project_id
        self.agent_id = agent_id

    def create_memory_tools(self) -> List[BaseTool]:
        return self._memory.create_memory_tools()