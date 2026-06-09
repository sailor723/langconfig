"""UserProfile model — auto-extracted metadata from conversations."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from db.database import Base


class UserProfile(Base):
    """Auto-extracted user profile from conversation history."""
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    preferences = Column(JSON, nullable=True, default=list)
    metadata_snapshot = Column(JSON, nullable=True, default=dict)
    first_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
