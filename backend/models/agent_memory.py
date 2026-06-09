# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Agent Memory Model — PostgreSQL-backed persistent memory for agents."""

from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, ARRAY
from sqlalchemy.sql import func
from db.database import Base


class AgentMemory(Base):
    """Persistent memory entries for agents, backed by PostgreSQL."""

    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Agent identifier, e.g. 'task_42'",
    )
    memory_type = Column(
        String(50),
        nullable=False,
        default="fact",
        comment="fact/decision/pattern/learning/context/relationship",
    )
    importance = Column(
        Integer,
        nullable=False,
        default=5,
        comment="1-10 importance score",
    )
    tags = Column(ARRAY(String), default=list, comment="Optional tags for categorization")
    content = Column(Text, nullable=False, comment="The memory content")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<AgentMemory id={self.id} agent={self.agent_id} type={self.memory_type}>"