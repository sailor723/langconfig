"""Conversation Archive model — every chat turn is auto-saved."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from db.database import Base


class ConversationArchive(Base):
    """Auto-archived conversation turn. Append-only, never deleted."""
    __tablename__ = "conversation_archives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    user_message = Column(Text, nullable=False)
    agent_response = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True, default=list)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
