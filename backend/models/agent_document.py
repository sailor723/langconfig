# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
AgentDocument Model - Dedicated persistence for formal documents in DB mode.

When STORAGE_MODE=db, agents persist their final deliverables through the
``save_document`` built-in tool into this table (instead of writing loose
files to disk). Each row is one formal document with its own version chain,
so documents stay queryable, listable and versioned without touching the
filesystem.

FS mode keeps the legacy behaviour: final documents are written to disk and
tracked by WorkspaceFile metadata only (see models/workspace_file.py).
"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Index
from sqlalchemy.orm import relationship
from db.database import Base
import datetime


class AgentDocument(Base):
    """A formal document persisted by an agent into the DB (DB mode only)."""
    __tablename__ = "agent_documents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("deep_agent_templates.id"), nullable=True, index=True)
    execution_id = Column(String(100), nullable=True, index=True)  # Unique execution run ID

    # Document identity
    title = Column(String(255), nullable=False)
    doc_type = Column(String(50), nullable=True, default="report")  # report, notes, data, ...
    version = Column(Integer, nullable=False, default=1)            # bump on each save with same title

    # Content
    content = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    project = relationship("Project", foreign_keys=[project_id])
    agent = relationship("DeepAgentTemplate", foreign_keys=[agent_id])

    __table_args__ = (
        # Fast "latest doc by (project, agent, title)" lookups
        Index("ix_agent_documents_project_title", "project_id", "title"),
        Index("ix_agent_documents_agent_title", "agent_id", "title"),
    )

    def __repr__(self):
        return f"<AgentDocument(id={self.id}, title='{self.title}', version={self.version})>"
