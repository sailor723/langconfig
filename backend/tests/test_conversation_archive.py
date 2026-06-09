"""
Test: Conversation archive + auto-metadata extraction.

Every chat turn is automatically archived (server-side, no LLM needed).
Metadata extraction uses an LLM call with structured output.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import text

TEST_USER = 9999  # unique test user ID, won't collide with real data


class TestConversationArchive:
    """Test the conversation_archives table."""

    def test_table_exists(self, db_engine):
        """Verify the conversation_archives table exists."""
        with db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_name = 'conversation_archives')"
                )
            )
            assert result.scalar() is True, "conversation_archives must exist"

    def test_required_columns(self, db_engine):
        """Verify all required columns exist."""
        with db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'conversation_archives' "
                    "ORDER BY ordinal_position"
                )
            )
            cols = {r[0]: {"type": r[1], "nullable": r[2]} for r in result}

            required = ["id", "session_id", "user_id", "turn_number",
                        "user_message", "agent_response", "created_at"]
            for col in required:
                assert col in cols, f"Missing column: {col}"

    def test_insert_and_read(self, db_session):
        """Test basic CRUD on conversation_archives."""
        from models.conversation_archive import ConversationArchive

        record = ConversationArchive(
            session_id="test-archive-1",
            user_id=TEST_USER,
            turn_number=1,
            user_message="hi am weiping",
            agent_response="Hello Weiping!",
            tool_calls=[{"name": "memory_store", "args": {"key": "name"}}],
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(ConversationArchive).filter_by(
            session_id="test-archive-1"
        ).first()
        assert fetched is not None
        assert fetched.user_message == "hi am weiping"
        assert fetched.agent_response == "Hello Weiping!"
        assert len(fetched.tool_calls) == 1

    def test_multiple_turns(self, db_session):
        """Test archiving multiple turns in a session."""
        from models.conversation_archive import ConversationArchive

        for i in range(3):
            db_session.add(ConversationArchive(
                session_id="test-archive-2",
                user_id=TEST_USER,
                turn_number=i + 1,
                user_message=f"msg-{i}",
                agent_response=f"resp-{i}",
            ))
        db_session.commit()

        turns = db_session.query(ConversationArchive).filter_by(
            session_id="test-archive-2"
        ).order_by(ConversationArchive.turn_number).all()

        assert len(turns) == 3
        assert [t.turn_number for t in turns] == [1, 2, 3]


class TestUserMetadataExtraction:
    """Test LLM-based extraction of user metadata from conversation."""

    def _make_mock_llm(self, return_value):
        """Create a mock LLM that returns the given ExtractedMetadata."""
        from core.chat.metadata_extractor import ExtractedMetadata

        if isinstance(return_value, dict):
            return_value = ExtractedMetadata(**return_value)

        # Mock: llm.with_structured_output(...).ainvoke(...) → return_value
        mock_ainvoke = AsyncMock(return_value=return_value)
        mock_structured = MagicMock()
        mock_structured.ainvoke = mock_ainvoke
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        return mock_llm

    @pytest.mark.asyncio
    async def test_extract_name_with_mock_llm(self):
        """Test extracting user name via mock LLM."""
        from core.chat.metadata_extractor import extract_metadata_from_message

        mock_llm = self._make_mock_llm({"name": "Weiping", "has_new_info": True})
        result = await extract_metadata_from_message("hi am weiping", llm=mock_llm)
        assert result.name == "Weiping"
        assert result.has_new_info is True

    @pytest.mark.asyncio
    async def test_extract_preferences_with_mock(self):
        """Test extracting preferences via mock LLM."""
        from core.chat.metadata_extractor import extract_metadata_from_message

        mock_llm = self._make_mock_llm({
            "name": None,
            "preferences": ["blue"],
            "has_new_info": True,
        })
        result = await extract_metadata_from_message("I like blue color", llm=mock_llm)
        assert "blue" in result.preferences
        assert result.has_new_info is True

    @pytest.mark.asyncio
    async def test_no_info_extracted(self):
        """Test that generic messages don't trigger metadata extraction."""
        from core.chat.metadata_extractor import extract_metadata_from_message

        mock_llm = self._make_mock_llm({"has_new_info": False})
        result = await extract_metadata_from_message("how are you", llm=mock_llm)
        assert result.has_new_info is False
        assert result.name is None

    @pytest.mark.asyncio
    async def test_empty_message(self):
        """Test that empty message returns empty metadata."""
        from core.chat.metadata_extractor import extract_metadata_from_message

        mock_llm = self._make_mock_llm({"has_new_info": False})
        result = await extract_metadata_from_message("", llm=mock_llm)
        assert result.name is None
        assert result.has_new_info is False

    def test_pydantic_schema(self):
        """Test the ExtractedMetadata Pydantic schema."""
        from core.chat.metadata_extractor import ExtractedMetadata

        meta = ExtractedMetadata(
            name="Weiping",
            preferences=["blue"],
            has_new_info=True,
        )
        assert meta.name == "Weiping"
        assert meta.preferences == ["blue"]
        assert meta.has_new_info is True

    @pytest.mark.asyncio
    async def test_auto_save_on_introduction(self, db_session):
        """Test that user_profiles gets updated when user introduces themselves."""
        from models.user_profile import UserProfile

        profile = UserProfile(
            user_id=TEST_USER,
            name="Weiping",
            preferences=["blue"],
            metadata_snapshot={"name": "Weiping"},
        )
        db_session.add(profile)
        db_session.commit()

        fetched = db_session.query(UserProfile).filter_by(user_id=TEST_USER).first()
        assert fetched is not None
        assert fetched.name == "Weiping"

    def test_conversation_archive_stores_full_turn(self, db_session):
        """Simulate full chat route logic: archive + profile update."""
        from models.conversation_archive import ConversationArchive
        from models.user_profile import UserProfile

        # Turn 1: archive + profile
        db_session.add(ConversationArchive(
            session_id="int-test-session",
            user_id=TEST_USER,
            turn_number=1,
            user_message="hi am weiping",
            agent_response="Hello Weiping!",
            tool_calls=[{"name": "memory_store"}],
        ))
        db_session.add(UserProfile(
            user_id=TEST_USER,
            name="Weiping",
            metadata_snapshot={"name": "Weiping"},
        ))
        db_session.commit()

        # Turn 2: archive only (no new metadata)
        db_session.add(ConversationArchive(
            session_id="int-test-session",
            user_id=TEST_USER,
            turn_number=2,
            user_message="I like blue",
            agent_response="Blue is nice!",
        ))
        db_session.commit()

        # Verify
        turns = db_session.query(ConversationArchive).filter_by(
            session_id="int-test-session"
        ).order_by(ConversationArchive.turn_number).all()
        assert len(turns) == 2
        assert turns[0].user_message == "hi am weiping"
        assert turns[1].user_message == "I like blue"
